#!/usr/bin/env python3
"""Build loop and mask-registration proofs for every vibration selection."""

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
DETAIL_OUTPUT = OUTPUT / "vibration-registration"
FRAME_COUNT = 24
SCALE = 7


def crop_box(spec: dict, source: Image.Image) -> tuple[int, int, int, int]:
    amplitude = spec.get("amplitude", [0.75, 1.0])
    margin = math.ceil(max(abs(float(amplitude[0])), abs(float(amplitude[1]))) + 7)
    polygon = spec["polygon"]
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
        draw.ellipse((x - 1.1, y - 1.1, x + 1.1, y + 1.1), fill=(255, 247, 218, 255))
    pivot = spec.get(
        "pivot",
        [sum(point[0] for point in polygon) / len(polygon), sum(point[1] for point in polygon) / len(polygon)],
    )
    amplitude = spec.get("amplitude", [0.75, 1.0])
    draw.line(
        (pivot[0], pivot[1], pivot[0] + amplitude[0], pivot[1] + amplitude[1]),
        fill=(101, 193, 235, 255),
        width=1,
    )
    draw.ellipse((pivot[0] - 1.2, pivot[1] - 1.2, pivot[0] + 1.2, pivot[1] + 1.2), fill=(101, 193, 235, 255))
    return result


def main() -> None:
    assets = asset_store.load_all_assets()
    DETAIL_OUTPUT.mkdir(parents=True, exist_ok=True)
    entries = []
    verification = {}
    for asset in assets:
        source = ga.load_rgba(ROOT / asset["source"])
        vibration_index = 0
        for motion_index, spec in enumerate(asset["motions"]):
            if spec["type"] != "vibration":
                continue
            vibration_index += 1
            # Only layers up through this vibration feed its captured piece.
            # Later lights/effects are irrelevant to selection registration.
            motions = asset["motions"][: motion_index + 1]
            frames = [ga.animate_frame(source, motions, index / FRAME_COUNT) for index in range(FRAME_COUNT)]
            box = crop_box(spec, source)
            crops = [enlarged(frame.crop(box)) for frame in frames]
            stem = f"{asset['name']}-vibration-{vibration_index}"
            crops[0].save(
                DETAIL_OUTPUT / f"{stem}.gif",
                save_all=True,
                append_images=crops[1:],
                duration=70,
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

            closure = ga.animate_frame(source, motions, 1.0)
            start_values = np.asarray(frames[0].convert("RGB"), dtype=np.int16)
            closure_values = np.asarray(closure.convert("RGB"), dtype=np.int16)
            consecutive = []
            for index in range(FRAME_COUNT):
                a = np.asarray(frames[index].convert("RGB"), dtype=np.int16)
                b = np.asarray(frames[(index + 1) % FRAME_COUNT].convert("RGB"), dtype=np.int16)
                consecutive.append(float(np.mean(np.abs(a - b))))
            verification[stem] = {
                "exact_loop_closure_max_channel_delta": int(np.max(np.abs(start_values - closure_values))),
                "mean_consecutive_frame_delta": float(np.mean(consecutive)),
                "loop_delta_over_median_delta": consecutive[-1] / max(1e-9, float(np.median(consecutive))),
                "polygon_vertex_count": len(spec["polygon"]),
                "amplitude": spec["amplitude"],
                "waveform": spec["waveform"],
                "cycles_per_loop": spec["cycles_per_loop"],
            }
            entries.append((source, motions, box))

    if not entries:
        raise SystemExit("No vibration layers found in any asset file")

    panel_width = max((box[2] - box[0]) * SCALE for _, _, box in entries)
    panel_height = max((box[3] - box[1]) * SCALE for _, _, box in entries)
    gallery_frames = []
    for frame_index in range(FRAME_COUNT):
        gallery = Image.new("RGBA", (panel_width * len(entries), panel_height), (22, 21, 19, 255))
        for column, (source, motions, box) in enumerate(entries):
            frame = ga.animate_frame(source, motions, frame_index / FRAME_COUNT)
            panel = enlarged(frame.crop(box))
            gallery.alpha_composite(panel, (column * panel_width, (panel_height - panel.height) // 2))
        gallery_frames.append(gallery)
    gallery_frames[0].save(
        OUTPUT / "vibration-motion-gallery.gif",
        save_all=True,
        append_images=gallery_frames[1:],
        duration=70,
        loop=0,
        disposal=2,
    )
    (DETAIL_OUTPUT / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(OUTPUT / "vibration-motion-gallery.gif")
    print(DETAIL_OUTPUT / "verification.json")


if __name__ == "__main__":
    main()
