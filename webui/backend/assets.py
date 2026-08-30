from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import asset_store
import generate_animations as ga

from .config import AppConfig
from .errors import ApiError
from .validation import require_asset_name, validate_asset

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}


class AssetService:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def resolve_source(self, asset: dict[str, Any]) -> Path:
        return (self.config.asset_root / asset["source"]).expanduser().resolve()

    def load(self, path: Path) -> dict[str, Any]:
        target = path.expanduser().resolve()
        if target.suffix.lower() != ".json":
            raise ApiError("Asset files must use the .json extension", code="invalid_asset_file")
        if not target.is_file():
            raise ApiError(f"Asset file does not exist: {target}", 404, "asset_not_found")
        try:
            payload = json.loads(target.read_text())
        except json.JSONDecodeError as exc:
            raise ApiError(f"Invalid JSON in {target.name}: {exc.msg}", code="invalid_json") from exc
        return validate_asset(payload)

    def save(self, asset: dict[str, Any], path: Path) -> None:
        validated = validate_asset(asset)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(validated, indent=2) + "\n")

    def find_by_source(self, source_path: Path) -> tuple[dict[str, Any], Path] | None:
        if not self.config.assets_dir.exists():
            return None
        for path in sorted(self.config.assets_dir.glob("*.json")):
            try:
                asset = self.load(path)
            except (ApiError, OSError):
                continue
            if self.resolve_source(asset) == source_path:
                return asset, path
        return None

    def create(self, name: str, source_path: Path, output_path: Path) -> tuple[dict[str, Any], Path]:
        name = require_asset_name(name)
        source_path = source_path.expanduser().resolve()
        if source_path.suffix.lower() not in IMAGE_SUFFIXES or not source_path.is_file():
            raise ApiError(f"Unsupported or missing source image: {source_path}", code="invalid_source")
        target = (self.config.assets_dir / f"{name}.json").resolve()
        if target.exists():
            raise ApiError(f"An asset named {name!r} already exists", 409, "asset_exists")
        image = ga.load_rgba(source_path)
        asset = asset_store.new_asset(
            name=name,
            source=str(source_path),
            output=str(output_path.expanduser().resolve()),
            size=(image.width, image.height),
        )
        return validate_asset(asset), target

    def browse(self, requested: str, kind: str) -> dict[str, Any]:
        if kind not in {"image", "json"}:
            raise ApiError("Browse kind must be 'image' or 'json'", code="invalid_browse_kind")
        suffixes = IMAGE_SUFFIXES if kind == "image" else {".json"}
        default_root = self.config.asset_root if kind == "image" else self.config.assets_dir
        base = Path(requested).expanduser() if requested else default_root
        if base.is_file():
            base = base.parent
        base = base.resolve()
        if not base.is_dir():
            base = default_root.resolve()
        base.mkdir(parents=True, exist_ok=True)

        directories: list[Path] = []
        files: list[Path] = []
        try:
            candidates = list(base.iterdir())
        except OSError as exc:
            raise ApiError(f"Cannot read {base}: {exc}", code="browse_failed") from exc
        for entry in candidates:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    directories.append(entry)
                elif entry.suffix.lower() in suffixes:
                    files.append(entry)
            except OSError:
                continue
        directories.sort(key=lambda item: item.name.lower())
        files.sort(key=lambda item: item.name.lower())
        entries = [{"name": p.name, "path": str(p), "is_dir": True} for p in directories]
        entries += [{"name": p.name, "path": str(p), "is_dir": False} for p in files]
        return {
            "path": str(base),
            "parent": str(base.parent) if base.parent != base else None,
            "entries": entries,
        }
