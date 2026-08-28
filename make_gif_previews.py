#!/usr/bin/env python3
"""Render human-friendly looping GIF previews from the production atlases."""

from __future__ import annotations

import argparse
import math
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import asset_store

PIPELINE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("ANIMATORIO_ASSET_ROOT", os.environ.get("ANIMATORIO_ROOT", PIPELINE)))
BACKGROUND = (49, 48, 43)
PANEL = (66, 64, 57)
TEXT = (242, 235, 220)


def load_frames(asset: dict) -> list[Image.Image]:
    source_path = ROOT / asset["source"]
    sheet_path = ROOT / asset["output"]
    with Image.open(source_path) as source, Image.open(sheet_path) as sheet:
        width, height = source.size
        frame_count = int(asset.get("frame_count", asset_store.FRAME_COUNT))
        line_length = int(asset.get("line_length", asset_store.LINE_LENGTH))
        return [
            sheet.crop(
                (
                    (index % line_length) * width,
                    (index // line_length) * height,
                    (index % line_length + 1) * width,
                    (index // line_length + 1) * height,
                )
            ).convert("RGBA")
            for index in range(frame_count)
        ]


def contain(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    result = image.copy()
    result.thumbnail(size, Image.Resampling.LANCZOS)
    return result


def panel(frame: Image.Image, name: str, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGB", size, BACKGROUND)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((4, 4, size[0] - 5, size[1] - 5), radius=10, fill=PANEL)
    draw.text((12, 10), name, font=ImageFont.load_default(), fill=TEXT)
    sprite = contain(frame, (size[0] - 20, size[1] - 42))
    x = (size[0] - sprite.width) // 2
    y = 32 + (size[1] - 36 - sprite.height) // 2
    canvas.paste(sprite, (x, y), sprite)
    return canvas


def gif_frame(image: Image.Image) -> Image.Image:
    return image.quantize(
        colors=192,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.FLOYDSTEINBERG,
    )


def save_gif(frames: list[Image.Image], path: Path, duration: int) -> None:
    encoded = [gif_frame(frame) for frame in frames]
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded[0].save(
        path,
        save_all=True,
        append_images=encoded[1:],
        duration=duration,
        loop=0,
        optimize=True,
        disposal=2,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=PIPELINE / "output" / "gifs")
    parser.add_argument("--duration", type=int, default=70, help="Milliseconds per frame (GIF-safe approximation of 15 fps)")
    args = parser.parse_args()

    assets = asset_store.load_all_assets()
    animations = [(asset["name"], load_frames(asset)) for asset in assets]

    for name, frames in animations:
        largest = max(max(frame.size) for frame in frames)
        scale = min(1.0, 420 / largest)
        size = (
            max(220, math.ceil(frames[0].width * scale) + 28),
            max(220, math.ceil(frames[0].height * scale) + 52),
        )
        save_gif([panel(frame, name, size) for frame in frames], args.output_dir / f"{name}.gif", args.duration)

    if not animations:
        print("No assets found in animations/")
        return
    columns = 4
    cell_size = (230, 200)
    rows = math.ceil(len(animations) / columns)
    gallery_frames: list[Image.Image] = []
    for frame_index in range(len(animations[0][1])):
        gallery = Image.new("RGB", (columns * cell_size[0], rows * cell_size[1]), BACKGROUND)
        for index, (name, frames) in enumerate(animations):
            tile = panel(frames[frame_index], name, cell_size)
            gallery.paste(tile, ((index % columns) * cell_size[0], (index // columns) * cell_size[1]))
        gallery_frames.append(gallery)
    gallery_path = args.output_dir.parent / "animation-gallery.gif"
    save_gif(gallery_frames, gallery_path, args.duration)

    print(f"Rendered {len(animations)} individual previews and {gallery_path}")


if __name__ == "__main__":
    main()
