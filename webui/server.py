#!/usr/bin/env python3
"""Local live-preview editor for a single asset's rotor/gear motions.

Serves a small webUI (index.html/app.js/style.css) that renders motions with
the *real* generate_animations.py handlers, so position, scale and
perspective (the plane_basis matrix) can be tuned against the actual pixels
and saved straight back into that asset's own JSON file.

The editor starts empty: use "Open..." in the webUI to pick one asset file
under animations/ (or "New from image..." to start a fresh asset), edit it,
save it, and come back to it later. There is no shared manifest and nothing
is opened automatically on startup.

Stdlib-only on top of what generate_animations.py already needs (PIL, numpy).
"""

from __future__ import annotations

import base64
import copy
import io
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

WEBUI_DIR = Path(__file__).resolve().parent
PIPELINE_DIR = WEBUI_DIR.parent
# Allow overriding the root so assets can live outside the repo checkout.
ROOT = Path(os.environ.get("ANIMATORIO_ASSET_ROOT", os.environ.get("ANIMATORIO_ROOT", PIPELINE_DIR)))

sys.path.insert(0, str(PIPELINE_DIR))
import asset_store  # noqa: E402
import generate_animations as ga  # noqa: E402
from PIL import Image  # noqa: E402

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}

_lock = threading.Lock()
_source_cache: dict[str, Any] = {}
# asset: the currently open asset's data, or None if nothing is open yet.
# asset_path: where it will be saved -- may not exist on disk yet for a
# brand-new asset (nothing is written until the first Save).
_state: dict[str, Any] = {"asset": None, "asset_path": None}


def resolve_source(asset: dict[str, Any]) -> Path:
    # Older asset files keep paths relative to ROOT; assets picked through
    # "Open image..." are stored absolute, and an absolute right-hand side
    # makes `/` just return itself, so this handles both.
    return (ROOT / asset["source"]).expanduser().resolve()


def get_source(asset: dict[str, Any]):
    path = str(resolve_source(asset))
    image = _source_cache.get(path)
    if image is None:
        image = ga.load_rgba(Path(path))
        _source_cache[path] = image
    return image


def clear_render_caches() -> None:
    _source_cache.clear()
    ga.GEAR_MATERIAL_CACHE.clear()
    ga.VERTICAL_GEAR_DETAIL_CACHE.clear()


def find_asset_by_source(source_path: Path) -> tuple[dict[str, Any], Path] | None:
    for path in sorted(asset_store.ASSETS_DIR.glob("*.json")):
        asset = asset_store.load_asset_file(path)
        if resolve_source(asset) == source_path:
            return asset, path
    return None


def browse_directory(requested: str, kind: str) -> dict[str, Any]:
    suffixes = IMAGE_SUFFIXES if kind == "image" else {".json"}
    default_root = ROOT if kind == "image" else asset_store.ASSETS_DIR
    base = Path(requested).expanduser() if requested else default_root
    if base.is_file():
        base = base.parent
    base = base.resolve()
    if not base.is_dir():
        base = default_root.resolve()
    base.mkdir(parents=True, exist_ok=True)

    dirs = []
    files = []
    for entry in base.iterdir():
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_dir():
                dirs.append(entry)
            elif entry.suffix.lower() in suffixes:
                files.append(entry)
        except OSError:
            continue
    dirs.sort(key=lambda p: p.name.lower())
    files.sort(key=lambda p: p.name.lower())

    entries = [{"name": p.name, "path": str(p), "is_dir": True} for p in dirs]
    entries += [{"name": p.name, "path": str(p), "is_dir": False} for p in files]

    parent = str(base.parent) if base.parent != base else None
    return {"path": str(base), "parent": parent, "entries": entries}


def render_phase(
    asset: dict[str, Any],
    motions: list[dict[str, Any]],
    selected_index: int,
    phase_value: float,
    isolate: bool,
):
    """Render one frame from the browser's current working set of layers.

    `motions` is the client's full in-progress layer list for this sprite --
    not the last-saved copy on disk -- so unsaved edits to other layers
    still show up in a "show all layers" preview, and added/removed layers
    are reflected immediately without a save round-trip.
    """
    source = get_source(asset)
    if isolate:
        frame = source.copy()
        motion = motions[selected_index]
        handler = ga.MOTION_HANDLERS[motion["type"]]
        handler(frame, source, motion, phase_value)
        return frame
    return ga.animate_frame(source, motions, phase_value)


def encode_png(image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def encode_gif(images, duration_ms: int = 70) -> str:
    """Encode a list of PIL Images as a looping GIF, returned as base64.

    Uses a single global adaptive palette derived from all frames together
    to avoid per-frame palette shifts (the “weird artifacts” caused by
    quantizing each frame independently). No dithering is used to keep
    flat mechanical colors clean; compression relies on optimize=True and
    a shared 255-color table, matching the web preview’s crisp look.
    """
    buffer = io.BytesIO()
    if not images:
        raise ValueError("no frames to encode")
    # Build a global palette from a mosaic of all frames — this gives one
    # shared table instead of per-frame palettes that flicker.
    w, h = images[0].size
    # Only sample up to 8 frames for palette to keep it fast; 24-frame mosaics are large.
    sample = images[:: max(1, len(images) // 8)]
    mosaic_w = w * len(sample)
    mosaic = Image.new("RGB", (mosaic_w, h), (255, 255, 255))
    for idx, frame in enumerate(sample):
        # Composite RGBA onto white to avoid alpha quantize issues (MEDIANCUT only supports RGB)
        rgba = frame.convert("RGBA")
        bg = Image.new("RGB", (w, h), (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        mosaic.paste(bg, (idx * w, 0))
    # No dither, median-cut, 255 colors — matches the clean flat shading of the preview.
    global_palette = mosaic.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    quantized = []
    for frame in images:
        rgba = frame.convert("RGBA")
        bg = Image.new("RGB", (w, h), (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        quantized.append(bg.quantize(palette=global_palette, dither=Image.Dither.NONE))
    quantized[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=quantized[1:],
        duration=duration_ms,
        loop=0,
        disposal=2,
        optimize=True,
    )
    return base64.b64encode(buffer.getvalue()).decode("ascii")


class Handler(BaseHTTPRequestHandler):
    server_version = "AnimationEditor/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # quieter console
        sys.stderr.write("[webui] " + (format % args) + "\n")

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw or b"{}")

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in STATIC_FILES:
            filename, content_type = STATIC_FILES[path]
            data = (WEBUI_DIR / filename).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/api/asset":
            with _lock:
                asset = _state["asset"]
                asset_path = _state["asset_path"]
                self._send_json({"asset": asset, "path": str(asset_path) if asset_path else None})
            return
        if path == "/api/browse":
            from urllib.parse import parse_qs, urlparse

            query = parse_qs(urlparse(self.path).query)
            kind = (query.get("kind") or ["json"])[0]
            requested = (query.get("path") or [""])[0]
            try:
                payload = browse_directory(requested, kind)
            except Exception as exc:
                self._send_json({"error": str(exc)}, status=400)
                return
            self._send_json(payload)
            return
        if path == "/api/source_image":
            with _lock:
                asset = _state["asset"]
                if asset is None:
                    self._send_json({"error": "no asset open"}, status=400)
                    return
            source = get_source(asset)
            buffer = io.BytesIO()
            source.save(buffer, format="PNG")
            data = buffer.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        self._send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/preview":
                self._handle_preview()
            elif path == "/api/export_gif":
                self._handle_export_gif()
            elif path == "/api/save":
                self._handle_save()
            elif path == "/api/regenerate":
                self._handle_regenerate()
            elif path == "/api/reload":
                self._handle_reload()
            elif path == "/api/open_asset_file":
                self._handle_open_asset_file()
            elif path == "/api/open_asset_from_image":
                self._handle_open_asset_from_image()
            else:
                self._send_json({"error": "not found"}, status=404)
        except Exception as exc:  # surfaced to the UI instead of a dead connection
            self._send_json({"error": str(exc)}, status=400)

    def _require_open_asset(self) -> dict[str, Any]:
        asset = _state["asset"]
        if asset is None:
            raise ValueError("No asset open -- click \"Open...\" first")
        return asset

    def _handle_preview(self) -> None:
        body = self._read_json()
        with _lock:
            asset = self._require_open_asset()
        motions = body["motions"]
        selected_index = int(body["selected_index"])
        phases = body.get("phases", [0.0])
        isolate = bool(body.get("isolate", True))

        if len(ga.GEAR_MATERIAL_CACHE) > 40:
            ga.GEAR_MATERIAL_CACHE.clear()
        if len(ga.VERTICAL_GEAR_DETAIL_CACHE) > 40:
            ga.VERTICAL_GEAR_DETAIL_CACHE.clear()

        frames = [
            encode_png(render_phase(asset, motions, selected_index, float(p), isolate))
            for p in phases
        ]
        self._send_json({"frames": frames})

    def _handle_export_gif(self) -> None:
        body = self._read_json()
        with _lock:
            asset = self._require_open_asset()
            asset_name = asset.get("name", "animation")
        motions = body.get("motions")
        if motions is None:
            with _lock:
                motions = copy.deepcopy(asset.get("motions", []))
        selected_index = int(body.get("selected_index", 0)) if motions else 0
        isolate = bool(body.get("isolate", False))
        # Use current working animation speed if provided, else asset's
        animation_speed = float(body.get("animation_speed", asset.get("animation_speed", asset_store.NEW_ASSET_ANIMATION_SPEED)))
        frame_count = int(body.get("frame_count", asset.get("frame_count", asset_store.FRAME_COUNT)))
        frame_count = max(1, min(64, frame_count))

        if len(ga.GEAR_MATERIAL_CACHE) > 40:
            ga.GEAR_MATERIAL_CACHE.clear()
        if len(ga.VERTICAL_GEAR_DETAIL_CACHE) > 40:
            ga.VERTICAL_GEAR_DETAIL_CACHE.clear()

        # Duration per frame derived from animation speed (60 ticks/sec).
        # The web preview samples PHASE_COUNT=10 phases at this interval, so its
        # apparent phase speed is (1/10)/interval. To make the 24-frame GIF feel
        # identical, scale the interval by 10/frame_count so phase per ms matches.
        PREVIEW_PHASE_COUNT = 10
        try:
            base_interval = 1000 / (60 * animation_speed)
            # Scale to match preview's perceived speed (phase per ms)
            duration_ms = max(20, min(500, int(round(base_interval * PREVIEW_PHASE_COUNT / frame_count))))
        except Exception:
            duration_ms = 70

        images = []
        if not motions:
            # No motions — just export the source as a single-frame gif
            source = get_source(asset)
            images = [source]
            duration_ms = 500
        elif isolate and 0 <= selected_index < len(motions):
            for i in range(frame_count):
                phase = i / frame_count
                images.append(render_phase(asset, motions, selected_index, phase, True))
        else:
            source = get_source(asset)
            for i in range(frame_count):
                phase = i / frame_count
                images.append(ga.animate_frame(source, motions, phase))

        gif_b64 = encode_gif(images, duration_ms)
        filename = f"{asset_name}.gif"
        self._send_json({"gif": gif_b64, "filename": filename, "duration_ms": duration_ms, "frame_count": len(images)})

    def _handle_save(self) -> None:
        body = self._read_json()
        motions = body["motions"]
        with _lock:
            asset = self._require_open_asset()
            asset["motions"] = motions
            if "animation_speed" in body:
                asset["animation_speed"] = float(body["animation_speed"])
            asset_store.save_asset(asset, _state["asset_path"])
            # Optional: sync generated speeds to downstream consumers if
            # sync_lua_animation_speed is available and configured.
            try:
                import sync_lua_animation_speed as sync_lua  # type: ignore

                sync_lua.sync()
            except Exception:
                pass
        self._send_json({"ok": True})

    def _handle_regenerate(self) -> None:
        with _lock:
            asset = self._require_open_asset()
            name = asset["name"]
            asset_copy = copy.deepcopy(asset)
            record = ga.generate_asset(asset_copy)

            metadata_path = PIPELINE_DIR / "generated-metadata.json"
            metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {"assets": []}
            by_name = {entry["name"]: entry for entry in metadata["assets"]}
            by_name[name] = record
            metadata["assets"] = list(by_name.values())
            metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
        self._send_json({"ok": True, "record": record})

    def _handle_reload(self) -> None:
        with _lock:
            asset_path = _state["asset_path"]
            if asset_path is None:
                raise ValueError("No asset open")
            if not asset_path.exists():
                raise ValueError("Nothing saved yet -- nothing to reload")
            _state["asset"] = asset_store.load_asset_file(asset_path)
            clear_render_caches()
            asset = _state["asset"]
        self._send_json({"asset": asset, "path": str(asset_path)})

    def _handle_open_asset_file(self) -> None:
        body = self._read_json()
        target = Path(body["path"]).expanduser()
        if not target.is_absolute():
            raise ValueError("path must be absolute")
        if not target.exists():
            raise ValueError(f"{target} does not exist")
        with _lock:
            _state["asset"] = asset_store.load_asset_file(target)
            _state["asset_path"] = target
            clear_render_caches()
            asset = _state["asset"]
        self._send_json({"asset": asset, "path": str(target)})

    def _handle_open_asset_from_image(self) -> None:
        body = self._read_json()
        source_path = Path(body["source_path"]).expanduser().resolve()
        name = body.get("name")
        output_path = body.get("output_path")
        with _lock:
            found = find_asset_by_source(source_path)
            if found is not None:
                asset, path = found
                _state["asset"] = asset
                _state["asset_path"] = path
                clear_render_caches()
                self._send_json({"ok": True, "created": False, "asset": asset, "path": str(path)})
                return
            if not name or not output_path:
                # Not tracked yet -- the client prompts for a name and
                # output path, then calls back in with both filled in.
                self._send_json({"needs_details": True})
                return
            target = asset_store.asset_path(name)
            if target.exists():
                raise ValueError(f"an asset named {name!r} already exists")
            image = ga.load_rgba(source_path)
            asset = asset_store.new_asset(
                name=name,
                source=str(source_path),
                output=str(Path(output_path).expanduser().resolve()),
                size=(image.width, image.height),
            )
            # Not written to disk until the first Save -- browsing to a
            # not-yet-existing asset name shouldn't leave a stray file
            # behind if the user just backs out.
            _state["asset"] = asset
            _state["asset_path"] = target
            clear_render_caches()
        self._send_json({"ok": True, "created": True, "asset": asset, "path": str(target)})


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--open", type=Path, default=None, help="asset JSON to open on startup (optional)")
    args = parser.parse_args()

    if args.open is not None:
        asset_path = args.open.expanduser().resolve()
        if not asset_path.exists():
            raise SystemExit(f"{asset_path} does not exist")
        _state["asset"] = asset_store.load_asset_file(asset_path)
        _state["asset_path"] = asset_path

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Animation motion editor running at {url}")
    print('Ctrl+C to stop. Use "Open..." in the header to pick an asset; Regenerate re-bakes the sheet PNG.')

    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
