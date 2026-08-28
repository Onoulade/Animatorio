#!/usr/bin/env python3
"""Build enlarged loop/registration proofs for every projective vertical gear."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import asset_store
import generate_animations as ga

PIPELINE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("ANIMATORIO_ASSET_ROOT", os.environ.get("ANIMATORIO_ROOT", PIPELINE)))
OUTPUT = PIPELINE / "output"
DETAIL_OUTPUT = OUTPUT / "vertical-gear-registration"
FRAME_COUNT = 24
SCALE = 7


def crop_box(spec: dict, source: Image.Image) -> tuple[int, int, int, int]:
    polygon = spec.get("mask_polygon", spec["polygon"])
    margin = 7
    return (
        max(0, math.floor(min(point[0] for point in polygon) - margin)),
        max(0, math.floor(min(point[1] for point in polygon) - margin)),
        min(source.width, math.ceil(max(point[0] for point in polygon) + margin)),
        min(source.height, math.ceil(max(point[1] for point in polygon) + margin)),
    )


def enlarged(image: Image.Image) -> Image.Image:
    return image.resize((image.width * SCALE, image.height * SCALE), Image.Resampling.NEAREST)


def overlay(source: Image.Image, spec: dict) -> Image.Image:
    result = source.copy()
    draw = ImageDraw.Draw(result)
    polygon = [tuple(point) for point in spec["polygon"]]
    draw.line(polygon + [polygon[0]], fill=(255, 176, 54, 255), width=1)
    for x, y in polygon:
        draw.ellipse((x - 1.2, y - 1.2, x + 1.2, y + 1.2), fill=(255, 247, 218, 255))
    middle = spec.get(
        "middle",
        [sum(point[0] for point in polygon) / 4, sum(point[1] for point in polygon) / 4],
    )
    across = (
        ((polygon[1][0] - polygon[0][0]) + (polygon[2][0] - polygon[3][0])) / 2,
        ((polygon[1][1] - polygon[0][1]) + (polygon[2][1] - polygon[3][1])) / 2,
    )
    draw.line(
        (
            middle[0] - across[0] * 0.55,
            middle[1] - across[1] * 0.55,
            middle[0] + across[0] * 0.55,
            middle[1] + across[1] * 0.55,
        ),
        fill=(101, 193, 235, 255),
        width=1,
    )
    draw.ellipse(
        (middle[0] - 1.2, middle[1] - 1.2, middle[0] + 1.2, middle[1] + 1.2),
        fill=(101, 193, 235, 255),
    )
    if spec.get("axis", "y") == "y":
        outer_indices = (0, 3) if spec.get("outer_edge", "start") == "start" else (1, 2)
    else:
        outer_indices = (0, 1) if spec.get("outer_edge", "start") == "start" else (3, 2)
    draw.line(
        (polygon[outer_indices[0]], polygon[outer_indices[1]]),
        fill=(121, 238, 153, 255),
        width=1,
    )
    if spec.get("mask_polygon"):
        mask_polygon = [tuple(point) for point in spec["mask_polygon"]]
        draw.line(mask_polygon + [mask_polygon[0]], fill=(199, 108, 255, 255), width=1)
    return result


def main() -> None:
    assets = asset_store.load_all_assets()
    DETAIL_OUTPUT.mkdir(parents=True, exist_ok=True)
    gallery_frames: list[Image.Image] = []
    verification: dict[str, dict] = {}

    for asset in assets:
        source = ga.load_rgba(ROOT / asset["source"])
        vertical_gears = [motion for motion in asset["motions"] if motion["type"] == "vertical_gear"]
        for index, spec in enumerate(vertical_gears, 1):
            frames = []
            for frame_index in range(FRAME_COUNT):
                frame = source.copy()
                ga.add_vertical_gear(frame, source, spec, frame_index / FRAME_COUNT)
                frames.append(frame)

            box = crop_box(spec, source)
            crops = [enlarged(frame.crop(box)) for frame in frames]
            stem = f"{asset['name']}-vertical-gear-{index}"
            crops[0].save(
                DETAIL_OUTPUT / f"{stem}.gif",
                save_all=True,
                append_images=crops[1:],
                duration=75,
                loop=0,
                disposal=2,
            )
            enlarged(source.crop(box)).save(DETAIL_OUTPUT / f"{stem}-source.png")
            enlarged(overlay(source, spec).crop(box)).save(DETAIL_OUTPUT / f"{stem}-overlay.png")

            phase_indices = [0, 3, 6, 9, 12, 15, 18, 21]
            strip = Image.new("RGBA", (crops[0].width * len(phase_indices), crops[0].height), (22, 21, 19, 255))
            for column, phase_index in enumerate(phase_indices):
                strip.alpha_composite(crops[phase_index], (column * crops[0].width, 0))
            strip.save(DETAIL_OUTPUT / f"{stem}-eight-phase.png")

            close = source.copy()
            ga.add_vertical_gear(close, source, spec, 1.0)
            closure_delta = np.asarray(frames[0].convert("RGB"), dtype=np.int16) - np.asarray(
                close.convert("RGB"), dtype=np.int16
            )
            consecutive_deltas = []
            for frame_index in range(FRAME_COUNT):
                a = np.asarray(frames[frame_index].convert("RGB"), dtype=np.int16)
                b = np.asarray(frames[(frame_index + 1) % FRAME_COUNT].convert("RGB"), dtype=np.int16)
                consecutive_deltas.append(float(np.mean(np.abs(a - b))))
            verification[stem] = {
                "exact_pitch_closure_max_channel_delta": int(np.max(np.abs(closure_delta))),
                "mean_consecutive_frame_delta": float(np.mean(consecutive_deltas)),
                "loop_delta_over_median_delta": consecutive_deltas[-1]
                / max(1e-9, float(np.median(consecutive_deltas))),
                "polygon": spec["polygon"],
                "middle": spec.get("middle"),
                "arc_start_degrees": spec.get("arc_start_degrees", 90),
                "arc_end_degrees": spec.get("arc_end_degrees", 90),
                "relative_speed_at_start_limb": math.cos(
                    math.radians(spec.get("arc_start_degrees", 90))
                ),
                "relative_speed_at_tangent": 1.0,
                "relative_speed_at_end_limb": math.cos(
                    math.radians(spec.get("arc_end_degrees", 90))
                ),
                "direction": spec.get("direction", 1),
                "tooth_count": spec["tooth_count"],
                "outer_edge": spec.get("outer_edge", "start"),
                "tooth_depth_fraction": spec.get("tooth_depth_fraction", 0.42),
                "side_depth_fraction": spec.get("side_depth_fraction", 0.20),
                "root_face_brightness": spec.get("root_face_brightness", 0.64),
                "cavity_brightness": spec.get("cavity_brightness", 0.28),
            }
            gallery_frames.append(crops[0])

    if not gallery_frames:
        raise SystemExit("No vertical_gear layers found in any asset file")

    # All layers animate in lockstep; compose one gallery frame per phase.
    gallery_animation = []
    entries = []
    for asset in assets:
        source = ga.load_rgba(ROOT / asset["source"])
        for spec in (motion for motion in asset["motions"] if motion["type"] == "vertical_gear"):
            entries.append((source, spec, crop_box(spec, source)))
    panel_width = max((box[2] - box[0]) * SCALE for _, _, box in entries)
    for frame_index in range(FRAME_COUNT):
        panels = []
        for source, spec, box in entries:
            frame = source.copy()
            ga.add_vertical_gear(frame, source, spec, frame_index / FRAME_COUNT)
            panels.append(enlarged(frame.crop(box)))
        panel_height = max(panel.height for panel in panels)
        gallery = Image.new("RGBA", (panel_width * len(panels), panel_height), (22, 21, 19, 255))
        for column, panel in enumerate(panels):
            gallery.alpha_composite(panel, (column * panel_width, (panel_height - panel.height) // 2))
        gallery_animation.append(gallery)
    gallery_animation[0].save(
        OUTPUT / "vertical-gear-motion-gallery.gif",
        save_all=True,
        append_images=gallery_animation[1:],
        duration=75,
        loop=0,
        disposal=2,
    )
    (DETAIL_OUTPUT / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(OUTPUT / "vertical-gear-motion-gallery.gif")
    print(DETAIL_OUTPUT / "verification.json")


if __name__ == "__main__":
    main()
