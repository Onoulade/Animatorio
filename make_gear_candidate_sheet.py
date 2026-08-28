#!/usr/bin/env python3
"""Render enlarged source crops for exposed-gear animation triage."""

import os
from pathlib import Path

from PIL import Image, ImageDraw


PIPELINE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("ANIMATORIO_ASSET_ROOT", os.environ.get("ANIMATORIO_ROOT", PIPELINE)))
OUTPUT = Path(__file__).with_name("output") / "gear-candidate-sheet.png"
CROP_OUTPUT = Path(__file__).with_name("output") / "gear-candidates"

# No hardcoded assets — populate with your own (label, path, cropBox, scale).
# Historical examples are in examples/archive/.
CANDIDATES: list[tuple] = []


def main() -> None:
    panels = []
    CROP_OUTPUT.mkdir(parents=True, exist_ok=True)
    for candidate_index, (label, path, crop_box, scale) in enumerate(CANDIDATES, 1):
        src = ROOT / path
        if not src.exists():
            print(f"skip {label}: {src} not found")
            continue
        crop = Image.open(src).convert("RGBA").crop(crop_box)
        crop = crop.resize((crop.width * scale, crop.height * scale), Image.Resampling.NEAREST)
        crop.save(CROP_OUTPUT / f"{candidate_index:02d}-{label.split(' / ')[0]}-source.png")
        panel = Image.new("RGBA", (crop.width, crop.height + 24), (23, 22, 21, 255))
        panel.alpha_composite(crop, (0, 24))
        ImageDraw.Draw(panel).text((6, 6), label, fill=(244, 237, 219, 255))
        panels.append(panel)
    if not panels:
        print("No candidate crops found -- update CANDIDATES for your sprites.")
        return

    width = max(panel.width for panel in panels)
    height = sum(panel.height for panel in panels) + 12 * (len(panels) - 1)
    sheet = Image.new("RGBA", (width, height), (31, 30, 28, 255))
    y = 0
    for panel in panels:
        sheet.alpha_composite(panel, (0, y))
        y += panel.height + 12
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
