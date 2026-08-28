#!/usr/bin/env python3
"""Build enlarged source/generated overlays for mechanical registration review."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

import asset_store

PIPELINE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("ANIMATORIO_ASSET_ROOT", os.environ.get("ANIMATORIO_ROOT", PIPELINE)))
OUTPUT = PIPELINE / "output" / "rotor-registration-diagnostics.png"
CROP_OUTPUT = PIPELINE / "output" / "registration-crops"
LINE_LENGTH = 6
SCALE = 10
LABEL_HEIGHT = 34
GUTTER = 12


def frame_zero(sheet: Image.Image, size: tuple[int, int]) -> Image.Image:
    return sheet.crop((0, 0, size[0], size[1]))


def sheet_frame(sheet: Image.Image, size: tuple[int, int], index: int) -> Image.Image:
    x = index % LINE_LENGTH * size[0]
    y = index // LINE_LENGTH * size[1]
    return sheet.crop((x, y, x + size[0], y + size[1]))


def edge_mask(image: Image.Image) -> Image.Image:
    gray = image.convert("L")
    edges = gray.filter(ImageFilter.FIND_EDGES)
    values = np.asarray(edges, dtype=np.uint8)
    values = np.where(values >= 26, 255, 0).astype(np.uint8)
    return Image.fromarray(values)


def annotated_overlay(source: Image.Image, generated: Image.Image, motion: dict) -> Image.Image:
    canvas = source.convert("RGBA")
    red = Image.new("RGBA", source.size, (255, 44, 35, 0))
    red.putalpha(edge_mask(source).point(lambda value: int(value * 0.72)))
    cyan = Image.new("RGBA", source.size, (0, 229, 255, 0))
    cyan.putalpha(edge_mask(generated).point(lambda value: int(value * 0.72)))
    canvas.alpha_composite(red)
    canvas.alpha_composite(cyan)

    draw = ImageDraw.Draw(canvas)
    center_x, center_y = (float(value) for value in motion["center"])
    if "plane_basis" in motion:
        basis_x, basis_y = motion["plane_basis"]
        points = []
        for index in range(97):
            angle = index * 2 * np.pi / 96
            points.append(
                (
                    center_x + basis_x[0] * np.cos(angle) + basis_y[0] * np.sin(angle),
                    center_y + basis_x[1] * np.cos(angle) + basis_y[1] * np.sin(angle),
                )
            )
        draw.line(points, fill=(96, 255, 92, 255), width=1, joint="curve")
    else:
        radius_x, radius_y = (float(value) for value in motion["aperture_radius"])
        draw.ellipse(
            (center_x - radius_x, center_y - radius_y, center_x + radius_x, center_y + radius_y),
            outline=(96, 255, 92, 255),
            width=1,
        )
    draw.line((center_x - 3, center_y, center_x + 3, center_y), fill=(255, 242, 73, 255), width=1)
    draw.line((center_x, center_y - 3, center_x, center_y + 3), fill=(255, 242, 73, 255), width=1)
    return canvas


def crop_for_motion(size: tuple[int, int], motion: dict) -> tuple[int, int, int, int]:
    center_x, center_y = (float(value) for value in motion["center"])
    if "plane_basis" in motion:
        basis_x, basis_y = motion["plane_basis"]
        radius_x = abs(float(basis_x[0])) + abs(float(basis_y[0]))
        radius_y = abs(float(basis_x[1])) + abs(float(basis_y[1]))
    else:
        radius_x, radius_y = (float(value) for value in motion["aperture_radius"])
    padding = max(5, int(round(max(radius_x, radius_y) * 0.30)))
    return (
        max(0, int(np.floor(center_x - radius_x - padding))),
        max(0, int(np.floor(center_y - radius_y - padding))),
        min(size[0], int(np.ceil(center_x + radius_x + padding + 1))),
        min(size[1], int(np.ceil(center_y + radius_y + padding + 1))),
    )


def title_strip(width: int, text: str) -> Image.Image:
    strip = Image.new("RGBA", (width, LABEL_HEIGHT), (18, 18, 17, 255))
    draw = ImageDraw.Draw(strip)
    draw.text((8, 5), text, fill=(244, 237, 219, 255), font=ImageFont.load_default())
    draw.text((8, 18), "source | generated | 50% | red source / cyan generated / green fit", fill=(185, 180, 166, 255), font=ImageFont.load_default())
    return strip


def main() -> None:
    assets = asset_store.load_all_assets()
    rows: list[Image.Image] = []
    for asset in assets:
        motions = [motion for motion in asset["motions"] if motion["type"] == "mechanical_rotor"]
        if not motions:
            continue
        size = tuple(asset["size"])
        source = Image.open(ROOT / asset["source"]).convert("RGBA")
        generated_sheet = Image.open(ROOT / asset["output"]).convert("RGBA")
        generated = frame_zero(generated_sheet, size)
        for motion_index, motion in enumerate(motions, 1):
            crop_box = crop_for_motion(size, motion)
            source_crop = source.crop(crop_box)
            generated_crop = generated.crop(crop_box)
            blend = Image.blend(source_crop, generated_crop, 0.5)
            overlay = annotated_overlay(source, generated, motion).crop(crop_box)
            CROP_OUTPUT.mkdir(parents=True, exist_ok=True)
            stem = f"{asset['name']}-rotor-{motion_index}"
            source_crop.resize(
                (source_crop.width * SCALE, source_crop.height * SCALE), Image.Resampling.NEAREST
            ).save(CROP_OUTPUT / f"{stem}-source.png")
            generated_crop.resize(
                (generated_crop.width * SCALE, generated_crop.height * SCALE), Image.Resampling.NEAREST
            ).save(CROP_OUTPUT / f"{stem}-generated.png")
            overlay.resize(
                (overlay.width * SCALE, overlay.height * SCALE), Image.Resampling.NEAREST
            ).save(CROP_OUTPUT / f"{stem}-overlay.png")
            phase_frames = []
            for frame_index in range(0, 24, 3):
                phase_crop = sheet_frame(generated_sheet, size, frame_index).crop(crop_box)
                phase_frames.append(
                    phase_crop.resize(
                        (phase_crop.width * SCALE, phase_crop.height * SCALE),
                        Image.Resampling.NEAREST,
                    )
                )
            phase_width = phase_frames[0].width * 4
            phase_height = phase_frames[0].height * 2
            phase_sheet = Image.new("RGBA", (phase_width, phase_height), (24, 23, 22, 255))
            for phase_index, phase_frame in enumerate(phase_frames):
                phase_sheet.alpha_composite(
                    phase_frame,
                    (
                        phase_index % 4 * phase_frame.width,
                        phase_index // 4 * phase_frame.height,
                    ),
                )
            phase_sheet.convert("RGB").save(CROP_OUTPUT / f"{stem}-eight-phase.png")
            cells = [source_crop, generated_crop, blend, overlay]
            scaled = [cell.resize((cell.width * SCALE, cell.height * SCALE), Image.Resampling.NEAREST) for cell in cells]
            panel_width = sum(cell.width for cell in scaled) + GUTTER * (len(scaled) - 1)
            panel_height = max(cell.height for cell in scaled) + LABEL_HEIGHT
            panel = Image.new("RGBA", (panel_width, panel_height), (31, 30, 28, 255))
            panel.alpha_composite(title_strip(panel_width, f"{asset['name']} / rotor {motion_index}"), (0, 0))
            x = 0
            for cell in scaled:
                panel.alpha_composite(cell, (x, LABEL_HEIGHT))
                x += cell.width + GUTTER
            rows.append(panel)

    width = max(row.width for row in rows)
    height = sum(row.height for row in rows) + GUTTER * (len(rows) - 1)
    sheet = Image.new("RGBA", (width, height), (24, 23, 22, 255))
    y = 0
    for row in rows:
        sheet.alpha_composite(row, (0, y))
        y += row.height + GUTTER
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.convert("RGB").save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
