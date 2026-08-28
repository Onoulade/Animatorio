#!/usr/bin/env python3
"""Fit projected rotor apertures and source hubs to sprite luminance boundaries."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import asset_store

PIPELINE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("ANIMATORIO_ASSET_ROOT", os.environ.get("ANIMATORIO_ROOT", PIPELINE)))
OUTPUT_JSON = PIPELINE / "output" / "rotor-registration-fit.json"
OUTPUT_IMAGE = PIPELINE / "output" / "rotor-registration-fit.png"


def luminance(image: Image.Image) -> np.ndarray:
    rgb = np.asarray(image.convert("RGB"), dtype=np.float32)
    return rgb[:, :, 0] * 0.2126 + rgb[:, :, 1] * 0.7152 + rgb[:, :, 2] * 0.0722


def sample_bilinear(values: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0, values.shape[1] - 1.001)
    y = np.clip(y, 0, values.shape[0] - 1.001)
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    x1 = x0 + 1
    y1 = y0 + 1
    fx = x - x0
    fy = y - y0
    return (
        values[y0, x0] * (1 - fx) * (1 - fy)
        + values[y0, x1] * fx * (1 - fy)
        + values[y1, x0] * (1 - fx) * fy
        + values[y1, x1] * fx * fy
    )


def ellipse_points(
    center: tuple[float, float], radius: tuple[float, float], angle_degrees: float, scale: float
) -> tuple[np.ndarray, np.ndarray]:
    phase = np.linspace(0, 2 * math.pi, 192, endpoint=False)
    cosine = np.cos(phase)
    sine = np.sin(phase)
    angle = math.radians(angle_degrees)
    ca = math.cos(angle)
    sa = math.sin(angle)
    x = center[0] + scale * (radius[0] * ca * cosine - radius[1] * sa * sine)
    y = center[1] + scale * (radius[0] * sa * cosine + radius[1] * ca * sine)
    return x, y


def boundary_score(
    values: np.ndarray,
    center: tuple[float, float],
    radius: tuple[float, float],
    angle: float,
    bright_inside: bool,
) -> float:
    inner_scale, outer_scale = (0.76, 1.16) if bright_inside else (0.84, 1.09)
    inner_x, inner_y = ellipse_points(center, radius, angle, inner_scale)
    outer_x, outer_y = ellipse_points(center, radius, angle, outer_scale)
    inside = sample_bilinear(values, inner_x, inner_y)
    outside = sample_bilinear(values, outer_x, outer_y)
    contrast = inside - outside if bright_inside else outside - inside
    ordered = np.sort(contrast)
    trimmed = ordered[len(ordered) // 7 : -len(ordered) // 7]
    return float(np.mean(trimmed) + np.percentile(contrast, 65) * 0.22)


def search_ellipse(
    values: np.ndarray,
    center: tuple[float, float],
    radius: tuple[float, float],
    bright_inside: bool,
    radius_scale_range: tuple[float, float],
) -> tuple[float, float, float, float, float, float]:
    best = (-1e9, center[0], center[1], radius[0], radius[1], 0.0)

    def search(
        anchor: tuple[float, float, float, float, float],
        center_offsets: list[float],
        radius_offsets: list[float],
        angles: list[float],
    ) -> None:
        nonlocal best
        anchor_x, anchor_y, anchor_rx, anchor_ry, _ = anchor
        for dx in center_offsets:
            for dy in center_offsets:
                candidate_center = (anchor_x + dx, anchor_y + dy)
                for drx in radius_offsets:
                    candidate_rx = anchor_rx + drx
                    if candidate_rx <= 2:
                        continue
                    for dry in radius_offsets:
                        candidate_ry = anchor_ry + dry
                        if candidate_ry <= 2:
                            continue
                        for angle in angles:
                            score = boundary_score(
                                values,
                                candidate_center,
                                (candidate_rx, candidate_ry),
                                angle,
                                bright_inside,
                            )
                            if score > best[0]:
                                best = (score, *candidate_center, candidate_rx, candidate_ry, angle)

    minimum_scale, maximum_scale = radius_scale_range
    scaled_rx = np.arange(radius[0] * minimum_scale, radius[0] * maximum_scale + 0.01, 1.0)
    scaled_ry = np.arange(radius[1] * minimum_scale, radius[1] * maximum_scale + 0.01, 1.0)
    for candidate_rx in scaled_rx:
        for candidate_ry in scaled_ry:
            anchor = (center[0], center[1], float(candidate_rx), float(candidate_ry), 0.0)
            search(anchor, [-2.0, -1.0, 0.0, 1.0, 2.0], [0.0], list(np.arange(-8, 8.1, 2.0)))

    _, best_x, best_y, best_rx, best_ry, best_angle = best
    search(
        (best_x, best_y, best_rx, best_ry, best_angle),
        [-0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75],
        [-0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 0.75],
        list(np.arange(best_angle - 1.5, best_angle + 1.51, 0.5)),
    )
    return best


def basis_from_fit(radius_x: float, radius_y: float, angle_degrees: float) -> list[list[float]]:
    angle = math.radians(angle_degrees)
    ca = math.cos(angle)
    sa = math.sin(angle)
    return [
        [round(radius_x * ca, 3), round(radius_x * sa, 3)],
        [round(-radius_y * sa, 3), round(radius_y * ca, 3)],
    ]


def draw_fit(image: Image.Image, fit: dict, color: tuple[int, int, int, int]) -> None:
    draw = ImageDraw.Draw(image)
    points = []
    basis_x, basis_y = fit["basis"]
    for index in range(97):
        angle = index * 2 * math.pi / 96
        points.append(
            (
                fit["center"][0] + basis_x[0] * math.cos(angle) + basis_y[0] * math.sin(angle),
                fit["center"][1] + basis_x[1] * math.cos(angle) + basis_y[1] * math.sin(angle),
            )
        )
    draw.line(points, fill=color, width=1, joint="curve")


def main() -> None:
    assets = asset_store.load_all_assets()
    results = []
    review_panels = []
    for asset in assets:
        source = Image.open(ROOT / asset["source"]).convert("RGBA")
        values = luminance(source)
        for motion_index, motion in enumerate(asset["motions"]):
            if motion["type"] != "mechanical_rotor":
                continue
            center = tuple(float(value) for value in motion["center"])
            radius = tuple(float(value) for value in motion["aperture_radius"])
            aperture_raw = search_ellipse(values, center, radius, False, (0.72, 1.02))
            _, aperture_x, aperture_y, aperture_rx, aperture_ry, aperture_angle = aperture_raw

            hub_bbox = tuple(float(value) for value in motion["hub_bbox"])
            hub_center = ((hub_bbox[0] + hub_bbox[2]) / 2, (hub_bbox[1] + hub_bbox[3]) / 2)
            hub_radius = ((hub_bbox[2] - hub_bbox[0]) / 2, (hub_bbox[3] - hub_bbox[1]) / 2)
            hub_raw = search_ellipse(values, hub_center, hub_radius, True, (0.75, 1.70))
            hub_score, hub_x, hub_y, hub_rx, hub_ry, hub_angle = hub_raw

            fit = {
                "asset": asset["name"],
                "motion_index": motion_index,
                "aperture": {
                    "score": round(aperture_raw[0], 3),
                    "center": [round(aperture_x, 3), round(aperture_y, 3)],
                    "basis": basis_from_fit(aperture_rx, aperture_ry, aperture_angle),
                },
                "hub": {
                    "score": round(hub_score, 3),
                    "center": [round(hub_x, 3), round(hub_y, 3)],
                    "basis": basis_from_fit(hub_rx, hub_ry, hub_angle),
                },
            }
            results.append(fit)

            annotated = source.copy()
            draw_fit(annotated, fit["aperture"], (82, 255, 93, 255))
            draw_fit(annotated, fit["hub"], (255, 77, 218, 255))
            radius_pad = max(radius) + 6
            crop_box = (
                max(0, int(center[0] - radius_pad)),
                max(0, int(center[1] - radius_pad)),
                min(source.width, int(center[0] + radius_pad + 1)),
                min(source.height, int(center[1] + radius_pad + 1)),
            )
            panel = annotated.crop(crop_box).resize(
                ((crop_box[2] - crop_box[0]) * 8, (crop_box[3] - crop_box[1]) * 8),
                Image.Resampling.NEAREST,
            )
            review_panels.append((asset["name"], panel))

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(json.dumps({"fits": results}, indent=2) + "\n")

    panel_width = max(panel.width for _, panel in review_panels)
    panel_height = max(panel.height for _, panel in review_panels) + 20
    sheet = Image.new("RGBA", (panel_width * 3, panel_height * math.ceil(len(review_panels) / 3)), (23, 22, 21, 255))
    draw = ImageDraw.Draw(sheet)
    for index, (name, panel) in enumerate(review_panels):
        x = index % 3 * panel_width
        y = index // 3 * panel_height
        sheet.alpha_composite(panel, (x, y + 20))
        draw.text((x + 4, y + 4), name, fill=(242, 236, 218, 255))
    sheet.convert("RGB").save(OUTPUT_IMAGE)
    print(OUTPUT_JSON)
    print(OUTPUT_IMAGE)


if __name__ == "__main__":
    main()
