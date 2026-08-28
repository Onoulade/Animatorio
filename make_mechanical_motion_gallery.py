#!/usr/bin/env python3
"""Render a close-up GIF of the verified rotor and gear animations."""

import os
from pathlib import Path

from PIL import Image, ImageDraw


PIPELINE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("ANIMATORIO_ASSET_ROOT", os.environ.get("ANIMATORIO_ROOT", PIPELINE)))
OUTPUT = Path(__file__).with_name("output") / "mechanical-motion-gallery.gif"
FRAME_COUNT = 24
LINE_LENGTH = 6
PANEL_SIZE = (380, 340)

# No hardcoded assets — populate with your own (label, path, size, crop, scale).
# Historical examples are in examples/archive/ and output/archive/.
ASSETS: list[tuple] = []


def sheet_frame(sheet: Image.Image, size: tuple[int, int], index: int) -> Image.Image:
    width, height = size
    x = index % LINE_LENGTH * width
    y = index // LINE_LENGTH * height
    return sheet.crop((x, y, x + width, y + height))


def _load_sheets():
    sheets = []
    for label, path, size, crop, scale in ASSETS:
        full = ROOT / path
        if not full.exists():
            print(f"skip {label}: {full} not found")
            continue
        sheets.append((label, Image.open(full).convert("RGBA"), size, crop, scale))
    return sheets


def main() -> None:
    sheets = _load_sheets()
    if not sheets:
        print("No gallery sheets found -- generate assets first or update ASSETS for your sprites.")
        return
    frames = []
    for frame_index in range(FRAME_COUNT):
        gallery = Image.new("RGBA", (PANEL_SIZE[0] * 3, PANEL_SIZE[1] * 2), (31, 30, 28, 255))
        draw = ImageDraw.Draw(gallery)
        for slot, (label, sheet, size, crop_box, scale) in enumerate(sheets):
            crop = sheet_frame(sheet, size, frame_index).crop(crop_box)
            crop = crop.resize((crop.width * scale, crop.height * scale), Image.Resampling.NEAREST)
            panel_x = slot % 3 * PANEL_SIZE[0]
            panel_y = slot // 3 * PANEL_SIZE[1]
            x = panel_x + (PANEL_SIZE[0] - crop.width) // 2
            y = panel_y + 30 + (PANEL_SIZE[1] - 30 - crop.height) // 2
            gallery.alpha_composite(crop, (x, y))
            draw.rectangle((panel_x, panel_y, panel_x + PANEL_SIZE[0], panel_y + 28), fill=(12, 12, 12, 230))
            draw.text((panel_x + 8, panel_y + 8), label, fill=(244, 236, 216, 255))
        frames.append(gallery.convert("P", palette=Image.Palette.ADAPTIVE, colors=255))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=frames[1:],
        duration=70,
        loop=0,
        disposal=2,
        optimize=False,
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
