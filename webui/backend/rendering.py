from __future__ import annotations

import base64
import io
import json
import threading
from pathlib import Path
from typing import Any

import generate_animations as ga
from PIL import Image

from .assets import AssetService
from .config import AppConfig
from .errors import ApiError


class RenderService:
    def __init__(self, config: AppConfig, assets: AssetService) -> None:
        self.config = config
        self.assets = assets
        self._source_cache: dict[str, Any] = {}
        self._lock = threading.RLock()

    def clear_caches(self) -> None:
        with self._lock:
            self._source_cache.clear()
            ga.GEAR_MATERIAL_CACHE.clear()
            ga.VERTICAL_GEAR_DETAIL_CACHE.clear()

    def trim_motion_caches(self, limit: int = 40) -> None:
        with self._lock:
            if len(ga.GEAR_MATERIAL_CACHE) > limit:
                ga.GEAR_MATERIAL_CACHE.clear()
            if len(ga.VERTICAL_GEAR_DETAIL_CACHE) > limit:
                ga.VERTICAL_GEAR_DETAIL_CACHE.clear()

    def source(self, asset: dict[str, Any]):
        with self._lock:
            path = str(self.assets.resolve_source(asset))
            image = self._source_cache.get(path)
            if image is None:
                image = ga.load_rgba(Path(path))
                self._source_cache[path] = image
            return image

    def render_phase(
        self,
        asset: dict[str, Any],
        motions: list[dict[str, Any]],
        selected_index: int,
        phase: float,
        isolate: bool,
        lighting: dict[str, Any] | None = None,
    ):
        with self._lock:
            source = self.source(asset)
            if isolate:
                if not 0 <= selected_index < len(motions):
                    raise ApiError("Selected layer is out of range", code="invalid_selection")
                frame = source.copy()
                motion = motions[selected_index]
                handler = ga.MOTION_HANDLERS.get(motion["type"])
                if handler is None:
                    raise ApiError(f"Unknown motion type: {motion['type']}", code="unknown_motion")
                render_motion = dict(motion)
                render_motion["_resolved_lighting"] = ga.resolve_lighting(
                    motion, lighting or asset.get("lighting")
                )
                handler(frame, source, render_motion, phase)
                return frame
            return ga.animate_frame(source, motions, phase, lighting or asset.get("lighting"))

    @staticmethod
    def encode_png(image) -> str:
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    @staticmethod
    def encode_gif(images: list[Any], duration_ms: int) -> str:
        if not images:
            raise ApiError("No frames to encode", code="empty_export")
        buffer = io.BytesIO()
        width, height = images[0].size
        sample_indices = list(range(0, len(images), max(1, len(images) // 8)))
        sample = [images[index] for index in sample_indices]
        mosaic = Image.new("RGB", (width * len(sample), height), (255, 255, 255))
        rgb_frames = []
        for index, frame in enumerate(images):
            rgba = frame.convert("RGBA")
            background = Image.new("RGB", (width, height), (255, 255, 255))
            background.paste(rgba, mask=rgba.getchannel("A"))
            rgb_frames.append(background)
            if index in sample_indices:
                mosaic.paste(background, (sample_indices.index(index) * width, 0))
        palette = mosaic.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        quantized = [frame.quantize(palette=palette, dither=Image.Dither.NONE) for frame in rgb_frames]
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

    def regenerate(self, asset: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            record = ga.generate_asset(asset)
            path = self.config.metadata_path
            metadata = json.loads(path.read_text()) if path.exists() else {"assets": []}
            by_name = {entry["name"]: entry for entry in metadata.get("assets", [])}
            by_name[record["name"]] = record
            metadata["assets"] = list(by_name.values())
            path.write_text(json.dumps(metadata, indent=2) + "\n")
            return record
