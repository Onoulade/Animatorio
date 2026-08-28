#!/usr/bin/env python3
"""Render gear registration overlays, phase sheets, and looping GIF reviews."""

from __future__ import annotations

import math
import os
from pathlib import Path

from PIL import Image, ImageDraw

import asset_store

PIPELINE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("ANIMATORIO_ASSET_ROOT", os.environ.get("ANIMATORIO_ROOT", PIPELINE)))
OUTPUT = PIPELINE / "output" / "gear-motion-gallery.gif"
CROP_OUTPUT = PIPELINE / "output" / "gear-registration"
LINE_LENGTH = 6
FRAME_COUNT = 24
SCALE = 8
PANEL_SIZE = (420, 390)


def sheet_frame(sheet: Image.Image, size: tuple[int, int], index: int) -> Image.Image:
    x = index % LINE_LENGTH * size[0]
    y = index // LINE_LENGTH * size[1]
    return sheet.crop((x, y, x + size[0], y + size[1]))


def ellipse_points(center: list[float], basis: list[list[float]], scale: float = 1.0) -> list[tuple[float, float]]:
    points = []
    basis_x, basis_y = basis
    for index in range(97):
        angle = index * 2 * math.pi / 96
        points.append(
            (
                center[0] + scale * (basis_x[0] * math.cos(angle) + basis_y[0] * math.sin(angle)),
                center[1] + scale * (basis_x[1] * math.cos(angle) + basis_y[1] * math.sin(angle)),
            )
        )
    return points


def crop_for_gear(size: tuple[int, int], gear: dict) -> tuple[int, int, int, int]:
    center_x, center_y = gear["center"]
    basis_x, basis_y = gear.get(
        "plane_basis",
        [[gear["outer_radius"][0], 0], [0, gear["outer_radius"][1]]],
    )
    extent_x = abs(basis_x[0]) + abs(basis_y[0]) + 7
    extent_y = abs(basis_x[1]) + abs(basis_y[1]) + 7
    return (
        max(0, int(math.floor(center_x - extent_x))),
        max(0, int(math.floor(center_y - extent_y))),
        min(size[0], int(math.ceil(center_x + extent_x + 1))),
        min(size[1], int(math.ceil(center_y + extent_y + 1))),
    )


def fit_to_panel(crop: Image.Image) -> Image.Image:
    usable_width = PANEL_SIZE[0] - 20
    usable_height = PANEL_SIZE[1] - 48
    scale = min(usable_width / crop.width, usable_height / crop.height)
    width = max(1, int(round(crop.width * scale)))
    height = max(1, int(round(crop.height * scale)))
    return crop.resize((width, height), Image.Resampling.NEAREST)


def main() -> None:
    assets = asset_store.load_all_assets()
    records = []
    CROP_OUTPUT.mkdir(parents=True, exist_ok=True)
    for asset in assets:
        size = tuple(asset["size"])
        source = Image.open(ROOT / asset["source"]).convert("RGBA")
        sheet = Image.open(ROOT / asset["output"]).convert("RGBA")
        gear_number = 0
        for motion in asset["motions"]:
            if motion["type"] != "mechanical_gear":
                continue
            gear_number += 1
            crop_box = crop_for_gear(size, motion)
            stem = f"{asset['name']}-gear-{gear_number}"
            source_crop = source.crop(crop_box)
            source_crop.resize(
                (source_crop.width * SCALE, source_crop.height * SCALE), Image.Resampling.NEAREST
            ).save(CROP_OUTPUT / f"{stem}-source.png")

            overlay = source.copy()
            draw = ImageDraw.Draw(overlay)
            basis = motion.get(
                "plane_basis",
                [[motion["outer_radius"][0], 0], [0, motion["outer_radius"][1]]],
            )
            draw.line(ellipse_points(motion["center"], basis), fill=(91, 255, 83, 255), width=1, joint="curve")
            inner_fraction = motion.get(
                "inner_fraction",
                motion["inner_radius"][0] / motion["outer_radius"][0],
            )
            draw.line(
                ellipse_points(motion["center"], basis, inner_fraction),
                fill=(255, 80, 220, 255),
                width=1,
                joint="curve",
            )
            if "source_center_basis" in motion:
                draw.line(
                    ellipse_points(motion.get("source_center", motion["center"]), motion["source_center_basis"]),
                    fill=(64, 220, 255, 255),
                    width=1,
                    joint="curve",
                )
            center_x, center_y = motion["center"]
            draw.line((center_x - 3, center_y, center_x + 3, center_y), fill=(255, 241, 65, 255), width=1)
            draw.line((center_x, center_y - 3, center_x, center_y + 3), fill=(255, 241, 65, 255), width=1)
            overlay.crop(crop_box).resize(
                (source_crop.width * SCALE, source_crop.height * SCALE), Image.Resampling.NEAREST
            ).save(CROP_OUTPUT / f"{stem}-overlay.png")

            phase_crops = [sheet_frame(sheet, size, index).crop(crop_box) for index in range(0, FRAME_COUNT, 3)]
            phase_sheet = Image.new(
                "RGBA",
                (source_crop.width * SCALE * 4, source_crop.height * SCALE * 2),
                (25, 24, 23, 255),
            )
            for index, crop in enumerate(phase_crops):
                scaled = crop.resize((crop.width * SCALE, crop.height * SCALE), Image.Resampling.NEAREST)
                phase_sheet.alpha_composite(
                    scaled,
                    (index % 4 * scaled.width, index // 4 * scaled.height),
                )
            phase_sheet.convert("RGB").save(CROP_OUTPUT / f"{stem}-eight-phase.png")

            gif_frames = [sheet_frame(sheet, size, index).crop(crop_box) for index in range(FRAME_COUNT)]
            gif_frames[0].save(
                CROP_OUTPUT / f"{stem}.gif",
                save_all=True,
                append_images=gif_frames[1:],
                duration=80,
                loop=0,
                disposal=2,
                optimize=False,
            )
            records.append((asset["name"], gif_frames))

    gallery_frames = []
    for frame_index in range(FRAME_COUNT):
        gallery = Image.new("RGBA", (PANEL_SIZE[0] * len(records), PANEL_SIZE[1]), (30, 29, 27, 255))
        draw = ImageDraw.Draw(gallery)
        for panel_index, (name, frames) in enumerate(records):
            crop = fit_to_panel(frames[frame_index])
            panel_x = panel_index * PANEL_SIZE[0]
            x = panel_x + (PANEL_SIZE[0] - crop.width) // 2
            y = 42 + (PANEL_SIZE[1] - 42 - crop.height) // 2
            gallery.alpha_composite(crop, (x, y))
            draw.rectangle((panel_x, 0, panel_x + PANEL_SIZE[0], 34), fill=(12, 12, 12, 235))
            draw.text((panel_x + 9, 11), name, fill=(244, 237, 219, 255))
        gallery_frames.append(gallery.convert("P", palette=Image.Palette.ADAPTIVE, colors=255))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    gallery_frames[0].save(
        OUTPUT,
        save_all=True,
        append_images=gallery_frames[1:],
        duration=80,
        loop=0,
        disposal=2,
        optimize=False,
    )
    print(OUTPUT)


if __name__ == "__main__":
    main()
