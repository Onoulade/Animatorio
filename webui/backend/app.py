from __future__ import annotations

import copy
import io
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import asset_store

from .assets import AssetService
from .config import AppConfig
from .errors import ApiError
from .rendering import RenderService
from .session import EditorSession
from .validation import require_frame_count, require_number, require_object, validate_motions

JsonHandler = Callable[[dict[str, Any]], dict[str, Any]]

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/api-client.js": ("api-client.js", "application/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/assets/animatorio-gear.png": ("assets/animatorio-gear.png", "image/png"),
}


class EditorApplication:
    api_version = 1

    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.from_environment()
        self.assets = AssetService(self.config)
        self.session = EditorSession(self.assets)
        self.renderer = RenderService(self.config, self.assets)
        self.get_routes: dict[str, JsonHandler] = {
            "/api/health": self.health,
            "/api/asset": self.get_asset,
            "/api/browse": self.browse,
        }
        self.post_routes: dict[str, JsonHandler] = {
            "/api/preview": self.preview,
            "/api/export_gif": self.export_gif,
            "/api/save": self.save,
            "/api/regenerate": self.regenerate,
            "/api/reload": self.reload,
            "/api/open_asset_file": self.open_asset_file,
            "/api/open_asset_from_image": self.open_asset_from_image,
        }

    def make_handler(self) -> type[BaseHTTPRequestHandler]:
        application = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "Animatorio/2"

            def log_message(self, format: str, *args: Any) -> None:
                sys.stderr.write("[webui] " + (format % args) + "\n")

            def _headers(self, content_type: str, length: int, status: int = 200) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(length))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()

            def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
                body = json.dumps(payload).encode("utf-8")
                self._headers("application/json; charset=utf-8", len(body), status)
                self.wfile.write(body)

            def _read_json(self) -> dict[str, Any]:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError as exc:
                    raise ApiError("Invalid Content-Length", code="invalid_request") from exc
                if length > 10 * 1024 * 1024:
                    raise ApiError("Request body is too large", HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body_too_large")
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw or b"{}")
                except json.JSONDecodeError as exc:
                    raise ApiError(f"Invalid JSON: {exc.msg}", code="invalid_json") from exc
                return dict(require_object(payload))

            def _dispatch(self, method: str) -> None:
                parsed = urlparse(self.path)
                try:
                    if method == "GET" and parsed.path in STATIC_FILES:
                        filename, content_type = STATIC_FILES[parsed.path]
                        data = (application.config.webui_dir / filename).read_bytes()
                        self._headers(content_type, len(data))
                        self.wfile.write(data)
                        return
                    if method == "GET" and parsed.path == "/api/source_image":
                        data = application.source_image()
                        self._headers("image/png", len(data))
                        self.wfile.write(data)
                        return
                    routes = application.get_routes if method == "GET" else application.post_routes
                    handler = routes.get(parsed.path)
                    if handler is None:
                        raise ApiError("Route not found", 404, "not_found")
                    payload = (
                        {key: values[0] for key, values in parse_qs(parsed.query).items()}
                        if method == "GET"
                        else self._read_json()
                    )
                    self._send_json(handler(payload))
                except ApiError as exc:
                    self._send_json({"error": str(exc), "code": exc.code}, exc.status)
                except Exception as exc:
                    self._send_json({"error": str(exc), "code": "internal_error"}, 500)

            def do_GET(self) -> None:  # noqa: N802
                self._dispatch("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._dispatch("POST")

        return Handler

    def open_on_startup(self, path: Path) -> None:
        self.session.open(path)
        self.renderer.clear_caches()

    def health(self, _query: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "service": "animatorio", "api_version": self.api_version}

    def get_asset(self, _query: dict[str, Any]) -> dict[str, Any]:
        result = self.session.snapshot()
        result["api_version"] = self.api_version
        return result

    def browse(self, query: dict[str, Any]) -> dict[str, Any]:
        return self.assets.browse(str(query.get("path", "")), str(query.get("kind", "json")))

    def source_image(self) -> bytes:
        asset, _path = self.session.current()
        source = self.renderer.source(asset)
        buffer = io.BytesIO()
        source.save(buffer, format="PNG")
        return buffer.getvalue()

    def preview(self, body: dict[str, Any]) -> dict[str, Any]:
        asset, _path = self.session.current()
        self.renderer.trim_motion_caches()
        motions = validate_motions(body.get("motions"))
        if "frame_count" in body:
            frame_count = require_frame_count(body["frame_count"])
            phases = [index / frame_count for index in range(frame_count)]
        else:
            phases = body.get("phases", [0.0])
            if not isinstance(phases, list) or not 1 <= len(phases) <= asset_store.MAX_FRAME_COUNT:
                raise ApiError(
                    f"phases must contain 1–{asset_store.MAX_FRAME_COUNT} values",
                    code="invalid_phases",
                )
        selected_index = int(require_number(body.get("selected_index", 0), "selected_index", minimum=0))
        isolate = bool(body.get("isolate", True))
        lighting = body.get("lighting", asset.get("lighting"))
        frames = [
            self.renderer.encode_png(
                self.renderer.render_phase(
                    asset,
                    motions,
                    selected_index,
                    require_number(phase, "phase"),
                    isolate,
                    lighting,
                )
            )
            for phase in phases
        ]
        return {"frames": frames}

    def export_gif(self, body: dict[str, Any]) -> dict[str, Any]:
        asset, _path = self.session.current()
        self.renderer.trim_motion_caches()
        motions = validate_motions(body.get("motions", copy.deepcopy(asset.get("motions", []))))
        selected_index = int(require_number(body.get("selected_index", 0), "selected_index", minimum=0))
        isolate = bool(body.get("isolate", False))
        speed = require_number(
            body.get("animation_speed", asset.get("animation_speed", asset_store.NEW_ASSET_ANIMATION_SPEED)),
            "animation_speed",
            minimum=0.01,
        )
        frame_count = require_frame_count(
            body.get("frame_count", asset.get("frame_count", asset_store.FRAME_COUNT))
        )
        lighting = body.get("lighting", asset.get("lighting"))
        duration_ms = max(20, min(500, int(round((1000 / (60 * speed)) * 10 / frame_count))))
        if not motions:
            images = [self.renderer.source(asset)]
            duration_ms = 500
        else:
            images = [
                self.renderer.render_phase(
                    asset, motions, selected_index, index / frame_count, isolate, lighting
                )
                for index in range(frame_count)
            ]
        return {
            "gif": self.renderer.encode_gif(images, duration_ms),
            "filename": f"{asset.get('name', 'animation')}.gif",
            "duration_ms": duration_ms,
            "frame_count": len(images),
        }

    def save(self, body: dict[str, Any]) -> dict[str, Any]:
        result = self.session.save(
            body.get("motions"),
            body.get("animation_speed", 0.25),
            body.get("frame_count"),
            body.get("lighting"),
        )
        try:
            import sync_lua_animation_speed as sync_lua

            sync_lua.sync()
        except Exception:
            pass
        return {"ok": True, **result}

    def regenerate(self, _body: dict[str, Any]) -> dict[str, Any]:
        asset, _path = self.session.current()
        return {"ok": True, "record": self.renderer.regenerate(asset)}

    def reload(self, _body: dict[str, Any]) -> dict[str, Any]:
        result = self.session.reload()
        self.renderer.clear_caches()
        return result

    def open_asset_file(self, body: dict[str, Any]) -> dict[str, Any]:
        raw_path = body.get("path")
        if not isinstance(raw_path, str) or not Path(raw_path).expanduser().is_absolute():
            raise ApiError("path must be absolute", code="invalid_path")
        result = self.session.open(Path(raw_path))
        self.renderer.clear_caches()
        return result

    def open_asset_from_image(self, body: dict[str, Any]) -> dict[str, Any]:
        raw_source = body.get("source_path")
        if not isinstance(raw_source, str):
            raise ApiError("source_path is required", code="invalid_source")
        source_path = Path(raw_source).expanduser().resolve()
        found = self.assets.find_by_source(source_path)
        if found is not None:
            asset, path = found
            result = self.session.set_unsaved(asset, path)
            self.renderer.clear_caches()
            return {"ok": True, "created": False, **result}
        name = body.get("name")
        output_path = body.get("output_path")
        if not name or not output_path:
            return {"needs_details": True}
        asset, path = self.assets.create(str(name), source_path, Path(str(output_path)))
        result = self.session.set_unsaved(asset, path)
        self.renderer.clear_caches()
        return {"ok": True, "created": True, **result}
