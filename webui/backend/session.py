from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any

from .assets import AssetService
from .errors import NoAssetOpenError
from .validation import require_frame_count, require_number, validate_asset, validate_motions


class EditorSession:
    def __init__(self, assets: AssetService) -> None:
        self.assets = assets
        self._lock = threading.RLock()
        self._asset: dict[str, Any] | None = None
        self._path: Path | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "asset": copy.deepcopy(self._asset),
                "path": str(self._path) if self._path else None,
            }

    def current(self) -> tuple[dict[str, Any], Path]:
        with self._lock:
            if self._asset is None or self._path is None:
                raise NoAssetOpenError()
            return copy.deepcopy(self._asset), self._path

    def open(self, path: Path) -> dict[str, Any]:
        asset = self.assets.load(path)
        with self._lock:
            self._asset = asset
            self._path = path.expanduser().resolve()
            return self.snapshot()

    def set_unsaved(self, asset: dict[str, Any], path: Path) -> dict[str, Any]:
        validated = validate_asset(asset)
        with self._lock:
            self._asset = validated
            self._path = path.resolve()
            return self.snapshot()

    def save(self, motions: Any, animation_speed: Any, frame_count: Any = None) -> dict[str, Any]:
        validated_motions = validate_motions(motions)
        speed = require_number(animation_speed, "animation_speed", minimum=0.01)
        with self._lock:
            if self._asset is None or self._path is None:
                raise NoAssetOpenError()
            updated = copy.deepcopy(self._asset)
            updated["motions"] = validated_motions
            updated["animation_speed"] = speed
            if frame_count is not None:
                updated["frame_count"] = require_frame_count(frame_count)
            # Remove the old user-authored layout field when an asset is saved.
            updated.pop("line_length", None)
            self.assets.save(updated, self._path)
            self._asset = updated
            return self.snapshot()

    def reload(self) -> dict[str, Any]:
        with self._lock:
            if self._path is None:
                raise NoAssetOpenError()
            asset = self.assets.load(self._path)
            self._asset = asset
            return self.snapshot()
