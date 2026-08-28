#!/usr/bin/env python3
"""Historical prototype for a blade-separated fan — see examples/archive.

This is intentionally separate from the production manifest.  It exists so a
rotor must pass enlarged phase-by-phase visual review before it can be promoted.
For standalone use, pass --source /path/to/input.png.
"""

from __future__ import annotations

import math
import json
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter


PIPELINE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("ANIMATORIO_ASSET_ROOT", os.environ.get("ANIMATORIO_ROOT", PIPELINE)))
# Standalone default; historical source is archived in examples/archive
DEFAULT_SOURCE = PIPELINE / "examples" / "demo-rotor" / "input.png"
SOURCE = DEFAULT_SOURCE
OUTPUT = Path(__file__).with_name("output") / "prototypes" / "demo-rotor-v1"

FRAME_COUNT = 24
SUPERSAMPLE = 8
CENTER = (299.0, 94.0)
APERTURE_RADIUS = (31.0, 21.0)
APERTURE_BBOX = (268, 73, 330, 115)
HUB_BBOX = (289, 86, 309, 102)
BLADE_COUNT = 11
BASE_ANGLE = 0.147


def polar_point(center: float, radius: float, angle: float) -> tuple[float, float]:
    return center + radius * math.cos(angle), center + radius * math.sin(angle)


def blade_polygon(side: int, angle: float, inset: float = 0.0) -> list[tuple[float, float]]:
    """Return one gently swept trapezoidal blade in an untilted rotor plane."""
    center = (side - 1) / 2
    outer = side * (0.435 - inset)
    inner = side * (0.140 + inset * 0.45)
    # The wide tip and modest sweep reproduce the source's paddle-like blades.
    points = (
        (inner, angle - 0.105),
        (outer, angle - 0.175),
        (outer, angle + 0.205),
        (inner, angle + 0.105),
    )
    return [polar_point(center, radius, theta) for radius, theta in points]


def build_plane(angle: float, side: int) -> Image.Image:
    """Render only moving rotor geometry in a front-facing circular plane."""
    mask = Image.new("L", (side, side), 0)
    mask_draw = ImageDraw.Draw(mask)
    edge = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    edge_draw = ImageDraw.Draw(edge)

    for index in range(BLADE_COUNT):
        theta = angle + 2 * math.pi * index / BLADE_COUNT
        polygon = blade_polygon(side, theta)
        mask_draw.polygon(polygon, fill=255)
        edge_draw.line(
            [polygon[0], polygon[1]],
            fill=(190, 176, 137, 185),
            width=max(1, side // 190),
        )
        edge_draw.line(
            [polygon[2], polygon[3]],
            fill=(22, 21, 18, 210),
            width=max(1, side // 150),
        )

    yy, xx = np.mgrid[0:side, 0:side].astype(np.float32)
    cx = cy = (side - 1) / 2
    radius = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / (side / 2)
    # Stable metal grain lives in object space and therefore rotates with blades.
    theta = np.arctan2(yy - cy, xx - cx)
    pitch = 2 * math.pi / BLADE_COUNT
    local_angle = np.mod(theta - angle + pitch / 2, pitch) - pitch / 2
    local_phase = local_angle / pitch
    native_radius = np.floor(radius * side / (2 * SUPERSAMPLE))
    grain = (
        7.0 * np.sin(native_radius * 1.37 + local_phase * 5.1)
        + 4.0 * np.sin(native_radius * 0.43 - local_phase * 8.3)
        + 2.2 * np.cos(radius * 53.0 + local_phase * 3.2)
    )
    base = np.zeros((side, side, 4), dtype=np.uint8)
    base[:, :, 0] = np.clip(91 + grain, 0, 255).astype(np.uint8)
    base[:, :, 1] = np.clip(85 + grain * 0.88, 0, 255).astype(np.uint8)
    base[:, :, 2] = np.clip(67 + grain * 0.63, 0, 255).astype(np.uint8)
    base[:, :, 3] = np.asarray(mask)
    rotor = Image.fromarray(base)
    rotor.alpha_composite(edge)
    return rotor


def make_aperture_mask(source: Image.Image) -> Image.Image:
    """Select the rotor cavity while leaving the source housing/rim untouched."""
    mask = Image.new("L", source.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse(APERTURE_BBOX, fill=255)

    # Larger apertures may cross behind the front lip; this measured one does not.
    if APERTURE_BBOX[3] > 121:
        draw.rectangle((APERTURE_BBOX[0], 121, APERTURE_BBOX[2], APERTURE_BBOX[3]), fill=0)
    return mask.filter(ImageFilter.GaussianBlur(0.32))


def hub_layer(source: Image.Image) -> Image.Image:
    """Render a small fixed cap from the source palette, without fused blade pixels."""
    x0, y0, x1, y1 = HUB_BBOX
    width = (x1 - x0) * SUPERSAMPLE
    height = (y1 - y0) * SUPERSAMPLE
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = (xx - (width - 1) / 2) / (width / 2)
    ny = (yy - (height - 1) / 2) / (height / 2)
    radius2 = nx * nx + ny * ny
    inside = radius2 <= 1.0
    z = np.sqrt(np.clip(1.0 - radius2, 0.0, 1.0))

    light = np.array([-0.48, -0.58, 0.93], dtype=np.float32)
    light /= np.linalg.norm(light)
    lambert = nx * light[0] + ny * light[1] + z * light[2]
    illumination = np.clip(0.43 + 0.61 * lambert, 0.32, 1.07)
    native_x = np.floor(xx / SUPERSAMPLE)
    native_y = np.floor(yy / SUPERSAMPLE)
    grain = 6.0 * np.sin(native_x * 1.73 + native_y * 0.81) + 3.5 * np.cos(
        native_x * 0.51 - native_y * 1.41
    )
    source_pixels = np.asarray(source.crop(HUB_BBOX).convert("RGB"), dtype=np.float32)
    palette = np.percentile(source_pixels.reshape(-1, 3), 72, axis=0)
    rgb = palette[None, None, :] * illumination[:, :, None] + grain[:, :, None]
    rust = np.exp(-(((nx + 0.18) / 0.22) ** 2 + ((ny + 0.32) / 0.17) ** 2))
    rgb[:, :, 0] += rust * 20
    rgb[:, :, 1] -= rust * 7
    rgb[:, :, 2] -= rust * 10
    alpha = np.where(inside, 255, 0).astype(np.uint8)
    hub = Image.fromarray(np.dstack((np.clip(rgb, 0, 255).astype(np.uint8), alpha)))

    full = Image.new("RGBA", (source.width * SUPERSAMPLE, source.height * SUPERSAMPLE), (0, 0, 0, 0))
    shadow = Image.new("RGBA", full.size, (0, 0, 0, 0))
    shadow_mask = Image.new("L", full.size, 0)
    ImageDraw.Draw(shadow_mask).ellipse(
        ((x0 - 1) * SUPERSAMPLE, (y0 + 1) * SUPERSAMPLE, (x1 + 2) * SUPERSAMPLE, (y1 + 3) * SUPERSAMPLE),
        fill=190,
    )
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(1.1 * SUPERSAMPLE))
    shadow.putalpha(shadow_mask)
    full.alpha_composite(shadow)
    full.alpha_composite(hub, (x0 * SUPERSAMPLE, y0 * SUPERSAMPLE))
    return full.resize(source.size, Image.Resampling.LANCZOS).filter(
        ImageFilter.UnsharpMask(radius=0.55, percent=45, threshold=2)
    )


def cavity_layer(source: Image.Image) -> Image.Image:
    """Create a fixed, dark, source-colored cavity behind the separated blades."""
    width, height = source.size
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = (xx - CENTER[0]) / APERTURE_RADIUS[0]
    ny = (yy - CENTER[1]) / APERTURE_RADIUS[1]
    radius = np.sqrt(nx * nx + ny * ny)

    # Colors come from the source's darkest visible fan gaps, not a foreign asset.
    src = np.asarray(source.convert("RGB"), dtype=np.float32)
    local = (radius > 0.30) & (radius < 0.92)
    values = src[local]
    base = np.percentile(values, 18, axis=0)
    radial = np.clip(0.78 + 0.20 * radius, 0.72, 1.0)
    screen_light = np.clip(0.90 + 0.07 * nx + 0.12 * ny, 0.72, 1.12)
    rgb = base[None, None, :] * radial[:, :, None] * screen_light[:, :, None]
    # A restrained fixed texture prevents the cavity from reading as a flat void.
    texture = 1.7 * np.sin(xx * 0.71 + yy * 0.19) + 1.1 * np.cos(xx * 0.23 - yy * 0.49)
    rgb += texture[:, :, None]
    rgba = np.dstack((np.clip(rgb, 0, 255).astype(np.uint8), np.full((height, width), 255, np.uint8)))
    return Image.fromarray(rgba)


def rotor_layer(source: Image.Image, angle: float) -> Image.Image:
    """Tilt a circular rotor into the source ellipse and apply fixed-world light."""
    plane_side = int(round(APERTURE_RADIUS[0] * 2 * SUPERSAMPLE))
    plane = build_plane(angle, plane_side)
    ellipse_size = (
        int(round(APERTURE_RADIUS[0] * 2 * SUPERSAMPLE)),
        int(round(APERTURE_RADIUS[1] * 2 * SUPERSAMPLE)),
    )
    tilted = plane.resize(ellipse_size, Image.Resampling.LANCZOS)

    array = np.asarray(tilted).astype(np.float32)
    height, width = array.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = (xx - (width - 1) / 2) / max(1.0, width / 2)
    ny = (yy - (height - 1) / 2) / max(1.0, height / 2)
    # Lighting stays in screen/world space instead of spinning with the albedo.
    light = np.clip(0.78 - 0.08 * nx + 0.34 * ny, 0.56, 1.16)
    array[:, :, :3] *= light[:, :, None]
    tilted = Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))

    layer = Image.new("RGBA", (source.width * SUPERSAMPLE, source.height * SUPERSAMPLE), (0, 0, 0, 0))
    x = int(round((CENTER[0] - APERTURE_RADIUS[0]) * SUPERSAMPLE))
    y = int(round((CENTER[1] - APERTURE_RADIUS[1]) * SUPERSAMPLE))
    layer.alpha_composite(tilted, (x, y))
    return layer.resize(source.size, Image.Resampling.LANCZOS)


def render_frame(
    source: Image.Image,
    index: int,
    aperture: Image.Image,
    cavity: Image.Image,
    hub: Image.Image,
) -> Image.Image:
    # One blade pitch is a visually closed loop for an evenly repeated rotor.
    angle = BASE_ANGLE - 2 * math.pi * index / (FRAME_COUNT * BLADE_COUNT)
    frame = source.copy()
    frame.paste(cavity, (0, 0), aperture)
    rotor = rotor_layer(source, angle)
    rotor.putalpha(ImageChops.multiply(rotor.getchannel("A"), aperture))
    shadow_alpha = rotor.getchannel("A").filter(ImageFilter.GaussianBlur(0.65))
    shadow_alpha = ImageChops.offset(shadow_alpha, 1, 1).point(lambda value: int(value * 0.38))
    shadow_alpha = ImageChops.multiply(shadow_alpha, aperture)
    shadow = Image.new("RGBA", source.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)
    frame.alpha_composite(shadow)
    frame.alpha_composite(rotor)
    frame.alpha_composite(hub)
    return frame


def make_sheet(frames: list[Image.Image]) -> Image.Image:
    width, height = frames[0].size
    sheet = Image.new("RGBA", (width * 8, height * 3), (0, 0, 0, 0))
    for index, frame in enumerate(frames):
        sheet.alpha_composite(frame, ((index % 8) * width, (index // 8) * height))
    return sheet


def make_review(frames: list[Image.Image]) -> Image.Image:
    sample_indices = list(range(0, FRAME_COUNT, 3))
    crop_box = (250, 48, 370, 145)
    crops = [frames[index].crop(crop_box).resize((720, 582), Image.Resampling.NEAREST) for index in sample_indices]
    review = Image.new("RGBA", (720 * 4, 582 * 2), (24, 24, 24, 255))
    draw = ImageDraw.Draw(review)
    for slot, (index, crop) in enumerate(zip(sample_indices, crops)):
        x = (slot % 4) * 720
        y = (slot // 4) * 582
        review.alpha_composite(crop, (x, y))
        draw.rectangle((x, y, x + 92, y + 32), fill=(0, 0, 0, 210))
        draw.text((x + 8, y + 8), f"frame {index:02d}", fill=(255, 255, 255, 255))
    return review


def verify(source: Image.Image, frames: list[Image.Image], aperture: Image.Image, cavity: Image.Image, hub: Image.Image) -> dict:
    arrays = [np.asarray(frame.convert("RGB"), dtype=np.int16) for frame in frames]
    consecutive = []
    for index in range(FRAME_COUNT):
        following = (index + 1) % FRAME_COUNT
        consecutive.append(float(np.mean(np.abs(arrays[index] - arrays[following]))))

    closure = render_frame(source, FRAME_COUNT, aperture, cavity, hub)
    closure_delta = np.abs(np.asarray(closure, dtype=np.int16) - np.asarray(frames[0], dtype=np.int16))

    source_array = np.asarray(source, dtype=np.int16)
    safety = (APERTURE_BBOX[0] - 3, APERTURE_BBOX[1] - 3, APERTURE_BBOX[2] + 3, APERTURE_BBOX[3] + 3)
    outside = np.ones((source.height, source.width), dtype=bool)
    outside[safety[1] : safety[3], safety[0] : safety[2]] = False
    outside_changed = 0
    for frame in frames:
        delta = np.any(np.asarray(frame, dtype=np.int16) != source_array, axis=2)
        outside_changed += int(np.count_nonzero(delta & outside))

    identities = [float(np.mean(np.all(array == source_array[:, :, :3], axis=2))) for array in arrays]
    return {
        "blade_count": BLADE_COUNT,
        "center": CENTER,
        "aperture_bbox": APERTURE_BBOX,
        "hub_bbox": HUB_BBOX,
        "exact_pitch_closure_max_channel_delta": int(closure_delta.max()),
        "outside_safety_box_changed_pixels_all_frames": outside_changed,
        "minimum_exact_source_pixel_identity": min(identities),
        "consecutive_mean_absolute_deltas": consecutive,
        "loop_delta_over_median_delta": consecutive[-1] / max(float(np.median(consecutive)), 1e-9),
    }


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Historical rotor prototype — standalone demo available via examples/demo-rotor")
    parser.add_argument("--source", type=Path, default=SOURCE, help="input image path")
    parser.add_argument("--output", type=Path, default=OUTPUT, help="output directory")
    args = parser.parse_args()
    src_path = args.source
    out_dir = args.output
    out_dir.mkdir(parents=True, exist_ok=True)
    if not src_path.exists():
        # fallback to standalone demo input so the script works without archived assets
        demo = PIPELINE / "examples" / "demo-rotor" / "input.png"
        if demo.exists():
            print(f"{src_path} not found, using demo {demo}")
            src_path = demo
        else:
            raise SystemExit(f"source not found: {src_path}")
    source = Image.open(src_path).convert("RGBA")
    # keep OUTPUT in sync for legacy callers that expect the default location
    OUTPUT.mkdir(parents=True, exist_ok=True)
    aperture = make_aperture_mask(source)
    cavity = cavity_layer(source)
    hub = hub_layer(source)
    frames = [render_frame(source, index, aperture, cavity, hub) for index in range(FRAME_COUNT)]
    verification = verify(source, frames, aperture, cavity, hub)
    if verification["exact_pitch_closure_max_channel_delta"] > 1:
        raise ValueError(f"rotor loop does not close: {verification}")
    if verification["outside_safety_box_changed_pixels_all_frames"]:
        raise ValueError(f"rotor changed pixels outside its safety box: {verification}")

    make_sheet(frames).save(out_dir / "rotor-sheet.png")
    make_review(frames).save(out_dir / "rotor-eight-phase-review.png")
    aperture.save(out_dir / "rotor-aperture-mask.png")
    (out_dir / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    frames[0].crop((250, 48, 370, 145)).resize((720, 582), Image.Resampling.NEAREST).save(
        out_dir / "rotor-frame-zero.png"
    )
    gif_frames = [frame.crop((250, 48, 370, 145)).resize((480, 388), Image.Resampling.NEAREST) for frame in frames]
    gif_frames[0].save(
        out_dir / "rotor-preview.gif",
        save_all=True,
        append_images=gif_frames[1:],
        duration=70,
        loop=0,
        disposal=2,
    )
    print(out_dir)


if __name__ == "__main__":
    main()
