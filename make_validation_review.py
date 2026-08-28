#!/usr/bin/env python3
"""Build an A/B/difference contact sheet from validation screenshots."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance

import asset_store


def mean_luma(image: Image.Image) -> float:
    histogram = image.convert("L").histogram()
    pixels = image.width * image.height
    return sum(value * count for value, count in enumerate(histogram)) / pixels


def _discover_entities() -> list[str]:
    # Prefer generated-metadata if available, otherwise scan animations/*.json
    meta = Path(__file__).with_name("generated-metadata.json")
    if meta.exists():
        try:
            return [e["name"] for e in json.loads(meta.read_text()).get("assets", [])]
        except Exception:
            pass
    return asset_store.asset_names()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(os.environ.get("ANIMATORIO_VALIDATION_DIR", "/tmp/animatorio-validation-data/script-output")),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).with_name("output") / "animation-closeups.png",
    )
    parser.add_argument(
        "--entities",
        nargs="*",
        default=None,
        help="Optional explicit entity list; defaults to all assets discovered from animations/",
    )
    args = parser.parse_args()
    entities = args.entities if args.entities else _discover_entities()

    cell_width = 384
    cell_height = 288
    label_height = 24
    review = Image.new("RGB", (cell_width * 3, (cell_height + label_height) * len(entities)), (25, 24, 22))
    draw = ImageDraw.Draw(review)
    records = []

    for row, name in enumerate(entities):
        left = Image.open(args.input_dir / f"animatorio-animation-phase-a-{name}.png").convert("RGB")
        right = Image.open(args.input_dir / f"animatorio-animation-phase-b-{name}.png").convert("RGB")
        diff = ImageChops.difference(left, right)
        center = diff.crop((106, 42, 406, 342))
        edge = diff.crop((0, 0, 96, 96))
        records.append({
            "name": name,
            "center_mean_difference": round(mean_luma(center), 6),
            "background_mean_difference": round(mean_luma(edge), 6),
        })
        diff = ImageEnhance.Contrast(diff).enhance(3.0)
        diff = ImageEnhance.Brightness(diff).enhance(3.0)

        y = row * (cell_height + label_height)
        draw.text((8, y + 5), f"{name} — phase A / phase B / 9x difference", fill=(238, 231, 216))
        for column, image in enumerate((left, right, diff)):
            image.thumbnail((cell_width, cell_height), Image.Resampling.LANCZOS)
            tile = Image.new("RGB", (cell_width, cell_height), (55, 52, 46))
            tile.paste(image, ((cell_width - image.width) // 2, (cell_height - image.height) // 2))
            review.paste(tile, (column * cell_width, y + label_height))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    review.save(args.output, optimize=True)
    args.output.with_suffix(".json").write_text(json.dumps({"entities": records}, indent=2) + "\n")


if __name__ == "__main__":
    main()
