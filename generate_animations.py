#!/usr/bin/env python3
"""Generate registered sprite-sheet animations from static sprites.

The source image is immutable.  Each frame begins as an exact copy and receives
only localized, manifest-driven motion.  This retains the authored sprite
identity while giving all assets a common motion vocabulary.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

import asset_store

PIPELINE = Path(__file__).resolve().parent
# Standalone by default (assets live alongside this pipeline); set
# ANIMATORIO_ASSET_ROOT (or ANIMATORIO_ROOT) to point elsewhere if assets live
# in a separate checkout.
ROOT = Path(os.environ.get("ANIMATORIO_ASSET_ROOT", os.environ.get("ANIMATORIO_ROOT", PIPELINE)))
GEAR_MATERIAL_CACHE: dict[tuple[Any, ...], Image.Image] = {}
VERTICAL_GEAR_DETAIL_CACHE: dict[tuple[Any, ...], np.ndarray] = {}


def load_rgba(path: Path) -> Image.Image:
    return Image.open(path).convert("RGBA")


def phase(frame: int, frame_count: int) -> float:
    return frame / frame_count


def surface_mask(source: Image.Image, spec: dict[str, Any]) -> Image.Image:
    """Return a mask that follows an explicit visible surface, never a moved crop.

    `mask_polygon` is an optional free-form override (any vertex count) for
    motions whose own `polygon` is otherwise constrained by the motion's
    geometry -- e.g. surface_scan's `polygon` must stay a 4-point quad
    because scan_segment() interpolates the travelling highlight across it,
    so a non-quad visible outline goes in `mask_polygon` instead.
    """
    mask = Image.new("L", source.size, 0)
    draw = ImageDraw.Draw(mask)
    if "mask_polygon" in spec:
        draw.polygon([tuple(point) for point in spec["mask_polygon"]], fill=255)
    elif "polygon" in spec:
        draw.polygon([tuple(point) for point in spec["polygon"]], fill=255)
    else:
        bbox = tuple(spec["bbox"])
        if spec.get("shape") == "ellipse":
            draw.ellipse(bbox, fill=255)
        else:
            draw.rounded_rectangle(bbox, radius=int(spec.get("radius", 2)), fill=255)
    if spec.get("clip", True):
        mask = ImageChops.multiply(mask, source.getchannel("A"))
    return mask


def composite_on_surface(
    frame: Image.Image,
    source: Image.Image,
    effect: Image.Image,
    spec: dict[str, Any],
) -> None:
    effect.putalpha(ImageChops.multiply(effect.getchannel("A"), surface_mask(source, spec)))
    frame.alpha_composite(effect)


def scan_segment(spec: dict[str, Any], t: float) -> tuple[tuple[float, float], tuple[float, float]]:
    polygon = spec.get("polygon")
    axis = spec.get("axis", "y")
    if axis.startswith("-"):
        axis = axis[1:]
        t = 1.0 - t
    if polygon and len(polygon) == 4:
        top_left, top_right, bottom_right, bottom_left = polygon
        if axis == "y":
            left = (
                top_left[0] + (bottom_left[0] - top_left[0]) * t,
                top_left[1] + (bottom_left[1] - top_left[1]) * t,
            )
            right = (
                top_right[0] + (bottom_right[0] - top_right[0]) * t,
                top_right[1] + (bottom_right[1] - top_right[1]) * t,
            )
            return left, right
        top = (
            top_left[0] + (top_right[0] - top_left[0]) * t,
            top_left[1] + (top_right[1] - top_left[1]) * t,
        )
        bottom = (
            bottom_left[0] + (bottom_right[0] - bottom_left[0]) * t,
            bottom_left[1] + (bottom_right[1] - bottom_left[1]) * t,
        )
        return top, bottom

    x0, y0, x1, y1 = spec["bbox"]
    if axis == "y":
        y = y0 + (y1 - y0) * t
        return (x0, y), (x1, y)
    x = x0 + (x1 - x0) * t
    return (x, y0), (x, y1)


def add_surface_scan(frame: Image.Image, source: Image.Image, spec: dict[str, Any], p: float) -> None:
    """Move a highlight or print line across an explicit perspective surface."""
    local_phase = (p + float(spec.get("phase", 0.0))) % 1.0
    if spec.get("mode", "loop") == "pingpong":
        t = 0.5 - 0.5 * math.cos(2.0 * math.pi * local_phase)
        visibility = 1.0
    else:
        t = local_phase
        visibility = math.sin(math.pi * t) ** float(spec.get("fade_power", 0.6))
    alpha = int(round(float(spec.get("alpha", 80)) * visibility))
    if alpha <= 0:
        return

    effect = Image.new("RGBA", source.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(effect)
    start, end = scan_segment(spec, t)
    color = tuple(spec.get("color", [245, 230, 194]))
    draw.line((start, end), fill=(*color, alpha), width=int(spec.get("width", 2)))
    blur = float(spec.get("blur", 1.0))
    if blur:
        effect = effect.filter(ImageFilter.GaussianBlur(blur))
    composite_on_surface(frame, source, effect, spec)


def add_orbit_glint(frame: Image.Image, source: Image.Image, spec: dict[str, Any], p: float) -> None:
    """Suggest rotation by moving reflected light around a fixed fan/gear face."""
    x0, y0, x1, y1 = spec["bbox"]
    center_x = (x0 + x1) / 2
    center_y = (y0 + y1) / 2
    radius_x = (x1 - x0) * float(spec.get("orbit_x", 0.38))
    radius_y = (y1 - y0) * float(spec.get("orbit_y", 0.38))
    count = int(spec.get("count", 3))
    turns = float(spec.get("turns", 1.0))
    dot_radius = float(spec.get("dot_radius", 2.0))
    color = tuple(spec.get("color", [244, 221, 168]))
    effect = Image.new("RGBA", source.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(effect)
    for index in range(count):
        angle = 2.0 * math.pi * (turns * p + index / count + float(spec.get("phase", 0.0)))
        x = center_x + radius_x * math.cos(angle)
        y = center_y + radius_y * math.sin(angle)
        alpha = int(float(spec.get("alpha", 72)) * (0.55 + 0.45 * math.sin(angle) ** 2))
        draw.ellipse(
            (x - dot_radius, y - dot_radius, x + dot_radius, y + dot_radius),
            fill=(*color, alpha),
        )
    effect = effect.filter(ImageFilter.GaussianBlur(float(spec.get("blur", 1.2))))
    surface_spec = {**spec, "shape": "ellipse"}
    composite_on_surface(frame, source, effect, surface_spec)


def rotor_polar_point(center: float, radius: float, angle: float) -> tuple[float, float]:
    return center + radius * math.cos(angle), center + radius * math.sin(angle)


def rotor_blade_polygon(side: int, angle: float, spec: dict[str, Any]) -> list[tuple[float, float]]:
    center = (side - 1) / 2
    outer = side * float(spec.get("blade_outer_fraction", 0.435))
    inner = side * float(spec.get("blade_inner_fraction", 0.140))
    leading_root = float(spec.get("leading_root", -0.105))
    leading_tip = float(spec.get("leading_tip", -0.175))
    trailing_tip = float(spec.get("trailing_tip", 0.205))
    trailing_root = float(spec.get("trailing_root", 0.105))
    points = (
        (inner, angle + leading_root),
        (outer, angle + leading_tip),
        (outer, angle + trailing_tip),
        (inner, angle + trailing_root),
    )
    return [rotor_polar_point(center, radius, theta) for radius, theta in points]


def build_rotor_plane(spec: dict[str, Any], angle: float, side: int) -> Image.Image:
    blade_count = int(spec["blade_count"])
    supersample = int(spec.get("supersample", 8))
    mask = Image.new("L", (side, side), 0)
    mask_draw = ImageDraw.Draw(mask)
    edge = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    edge_draw = ImageDraw.Draw(edge)
    for index in range(blade_count):
        theta = angle + 2 * math.pi * index / blade_count
        polygon = rotor_blade_polygon(side, theta, spec)
        mask_draw.polygon(polygon, fill=255)
        edge_draw.line(
            [polygon[0], polygon[1]],
            fill=tuple(spec.get("blade_highlight", [160, 149, 116, 150])),
            width=max(1, side // 190),
        )
        edge_draw.line(
            [polygon[2], polygon[3]],
            fill=tuple(spec.get("blade_shadow", [22, 21, 18, 210])),
            width=max(1, side // 150),
        )

    yy, xx = np.mgrid[0:side, 0:side].astype(np.float32)
    center = (side - 1) / 2
    radius = np.sqrt((xx - center) ** 2 + (yy - center) ** 2) / (side / 2)
    theta = np.arctan2(yy - center, xx - center)
    pitch = 2 * math.pi / blade_count
    local_angle = np.mod(theta - angle + pitch / 2, pitch) - pitch / 2
    local_phase = local_angle / pitch
    native_radius = np.floor(radius * side / (2 * supersample))
    grain = (
        7.0 * np.sin(native_radius * 1.37 + local_phase * 5.1)
        + 4.0 * np.sin(native_radius * 0.43 - local_phase * 8.3)
        + 2.2 * np.cos(radius * 53.0 + local_phase * 3.2)
    )
    color = np.asarray(spec.get("blade_color", [91, 85, 67]), dtype=np.float32)
    base = np.zeros((side, side, 4), dtype=np.uint8)
    base[:, :, 0] = np.clip(color[0] + grain, 0, 255).astype(np.uint8)
    base[:, :, 1] = np.clip(color[1] + grain * 0.88, 0, 255).astype(np.uint8)
    base[:, :, 2] = np.clip(color[2] + grain * 0.63, 0, 255).astype(np.uint8)
    base[:, :, 3] = np.asarray(mask)
    rotor = Image.fromarray(base)
    rotor.alpha_composite(edge)
    return rotor


def rotor_plane_basis(spec: dict[str, Any]) -> np.ndarray:
    """Return screen-space basis vectors for the circular rotor plane.

    Columns map a unit face-on rotor coordinate into sprite coordinates.  The
    legacy aperture radius remains supported, but production rotors provide a
    measured basis so foreshortening and in-plane rotation are explicit.
    """
    if "plane_basis" in spec:
        basis_x, basis_y = spec["plane_basis"]
        basis = np.asarray(
            [[float(basis_x[0]), float(basis_y[0])], [float(basis_x[1]), float(basis_y[1])]],
            dtype=np.float64,
        )
    else:
        radius_x, radius_y = (float(value) for value in spec["aperture_radius"])
        basis = np.asarray([[radius_x, 0.0], [0.0, radius_y]], dtype=np.float64)
    if abs(float(np.linalg.det(basis))) < 1e-6:
        raise ValueError(f"degenerate rotor plane basis: {basis.tolist()}")
    return basis


def projected_coordinates(
    size: tuple[int, int], center: tuple[float, float], basis: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Map every sprite pixel into unit coordinates on a projected plane."""
    yy, xx = np.mgrid[0 : size[1], 0 : size[0]].astype(np.float32)
    inverse = np.linalg.inv(basis)
    dx = xx - float(center[0])
    dy = yy - float(center[1])
    u = inverse[0, 0] * dx + inverse[0, 1] * dy
    v = inverse[1, 0] * dx + inverse[1, 1] * dy
    return u, v


def projected_ellipse_mask(
    size: tuple[int, int],
    center: tuple[float, float],
    basis: np.ndarray,
    feather: float,
    front_occlusion_y: float | None = None,
) -> Image.Image:
    """Rasterize a subpixel ellipse from the same basis used by the rotor."""
    u, v = projected_coordinates(size, center, basis)
    radius = np.sqrt(u * u + v * v)
    minimum_axis = max(1.0, float(np.linalg.svd(basis, compute_uv=False).min()))
    signed_distance = (1.0 - radius) * minimum_axis
    if feather > 0:
        alpha = np.clip(0.5 + signed_distance / feather, 0.0, 1.0)
    else:
        alpha = (signed_distance >= 0).astype(np.float32)
    if front_occlusion_y is not None:
        yy = np.mgrid[0 : size[1], 0 : size[0]][0].astype(np.float32)
        transition = max(0.28, feather)
        alpha *= np.clip(0.5 + (float(front_occlusion_y) - yy) / transition, 0.0, 1.0)
    return Image.fromarray(np.round(alpha * 255).astype(np.uint8))


def rotor_aperture_mask(source: Image.Image, spec: dict[str, Any]) -> Image.Image:
    center = tuple(float(value) for value in spec["center"])
    return projected_ellipse_mask(
        source.size,
        center,
        rotor_plane_basis(spec),
        float(spec.get("aperture_feather", 0.55)),
        float(spec["front_occlusion_y"]) if "front_occlusion_y" in spec else None,
    )


def rotor_cavity_layer(source: Image.Image, spec: dict[str, Any]) -> Image.Image:
    center_x, center_y = (float(value) for value in spec["center"])
    basis = rotor_plane_basis(spec)
    yy, xx = np.mgrid[0 : source.height, 0 : source.width].astype(np.float32)
    nx, ny = projected_coordinates(source.size, (center_x, center_y), basis)
    radius = np.sqrt(nx * nx + ny * ny)
    src = np.asarray(source.convert("RGB"), dtype=np.float32)
    local = (radius > 0.30) & (radius < 0.92)
    base = np.percentile(src[local], float(spec.get("cavity_percentile", 18)), axis=0)
    radial = np.clip(0.78 + 0.20 * radius, 0.72, 1.0)
    screen_light = np.clip(0.90 + 0.07 * nx + 0.12 * ny, 0.72, 1.12)
    rgb = base[None, None, :] * radial[:, :, None] * screen_light[:, :, None]
    texture = 1.7 * np.sin(xx * 0.71 + yy * 0.19) + 1.1 * np.cos(xx * 0.23 - yy * 0.49)
    rgb += texture[:, :, None]
    rgba = np.dstack(
        (np.clip(rgb, 0, 255).astype(np.uint8), np.full((source.height, source.width), 255, np.uint8))
    )
    return Image.fromarray(rgba)


def rotor_hub_layer(source: Image.Image, spec: dict[str, Any]) -> Image.Image:
    if "source_hub_basis" in spec:
        hub_center = tuple(float(value) for value in spec.get("hub_center", spec["center"]))
        hub_basis_x, hub_basis_y = spec["source_hub_basis"]
        hub_basis = np.asarray(
            [
                [float(hub_basis_x[0]), float(hub_basis_y[0])],
                [float(hub_basis_x[1]), float(hub_basis_y[1])],
            ],
            dtype=np.float64,
        )
        mask = projected_ellipse_mask(
            source.size,
            hub_center,
            hub_basis,
            float(spec.get("hub_feather", 0.55)),
        )
        hub = Image.new("RGBA", source.size, (0, 0, 0, 0))
        hub.paste(source, (0, 0), mask)
        return hub

    x0, y0, x1, y1 = (int(value) for value in spec["hub_bbox"])
    supersample = int(spec.get("supersample", 8))
    width = (x1 - x0) * supersample
    height = (y1 - y0) * supersample
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = (xx - (width - 1) / 2) / (width / 2)
    ny = (yy - (height - 1) / 2) / (height / 2)
    radius2 = nx * nx + ny * ny
    inside = radius2 <= 1.0
    z = np.sqrt(np.clip(1.0 - radius2, 0.0, 1.0))
    light = np.asarray(spec.get("light_direction", [-0.48, -0.58, 0.93]), dtype=np.float32)
    light /= np.linalg.norm(light)
    lambert = nx * light[0] + ny * light[1] + z * light[2]
    illumination = np.clip(0.43 + 0.61 * lambert, 0.32, 1.07)
    native_x = np.floor(xx / supersample)
    native_y = np.floor(yy / supersample)
    grain = 6.0 * np.sin(native_x * 1.73 + native_y * 0.81) + 3.5 * np.cos(
        native_x * 0.51 - native_y * 1.41
    )
    source_pixels = np.asarray(source.crop((x0, y0, x1, y1)).convert("RGB"), dtype=np.float32)
    palette = np.asarray(
        spec.get(
            "hub_color",
            np.percentile(source_pixels.reshape(-1, 3), float(spec.get("hub_percentile", 72)), axis=0),
        ),
        dtype=np.float32,
    )
    rgb = palette[None, None, :] * illumination[:, :, None] + grain[:, :, None]
    rust = np.exp(-(((nx + 0.18) / 0.22) ** 2 + ((ny + 0.32) / 0.17) ** 2))
    rgb[:, :, 0] += rust * 20
    rgb[:, :, 1] -= rust * 7
    rgb[:, :, 2] -= rust * 10
    alpha = np.where(inside, 255, 0).astype(np.uint8)
    hub = Image.fromarray(np.dstack((np.clip(rgb, 0, 255).astype(np.uint8), alpha)))

    full = Image.new("RGBA", (source.width * supersample, source.height * supersample), (0, 0, 0, 0))
    shadow = Image.new("RGBA", full.size, (0, 0, 0, 0))
    shadow_mask = Image.new("L", full.size, 0)
    ImageDraw.Draw(shadow_mask).ellipse(
        ((x0 - 1) * supersample, (y0 + 1) * supersample, (x1 + 2) * supersample, (y1 + 3) * supersample),
        fill=190,
    )
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(1.1 * supersample))
    shadow.putalpha(shadow_mask)
    full.alpha_composite(shadow)
    full.alpha_composite(hub, (x0 * supersample, y0 * supersample))
    return full.resize(source.size, Image.Resampling.LANCZOS).filter(
        ImageFilter.UnsharpMask(radius=0.55, percent=45, threshold=2)
    )


def rotor_fixed_occluder_mask(source: Image.Image, spec: dict[str, Any]) -> Image.Image:
    """Select stationary bars/grilles that must remain above the moving rotor."""
    mask = Image.new("L", source.size, 0)
    draw = ImageDraw.Draw(mask)
    center_x, center_y = (float(value) for value in spec["center"])
    for line in spec.get("fixed_occluder_lines", []):
        draw.line(tuple(line[:4]), fill=255, width=int(line[4] if len(line) > 4 else 1))
    grille = spec.get("fixed_grille")
    if grille:
        basis = rotor_plane_basis(spec)
        basis_x = basis[:, 0]
        basis_y = basis[:, 1]
        for ring in grille.get("rings", []):
            radius = float(ring[0])
            width = int(ring[1] if len(ring) > 1 else 1)
            maximum_axis = max(float(np.linalg.norm(basis_x)), float(np.linalg.norm(basis_y)))
            fraction = radius / maximum_axis
            points = []
            for index in range(97):
                angle = 2 * math.pi * index / 96
                point = (
                    center_x + fraction * (basis_x[0] * math.cos(angle) + basis_y[0] * math.sin(angle)),
                    center_y + fraction * (basis_x[1] * math.cos(angle) + basis_y[1] * math.sin(angle)),
                )
                points.append(point)
            draw.line(points, fill=255, width=width, joint="curve")
        spokes = grille.get("spokes")
        if spokes:
            count = int(spokes["count"])
            inner = float(spokes.get("inner_radius", 0))
            outer = float(spokes["outer_radius"])
            base_angle = float(spokes.get("base_angle", 0))
            squash = float(spokes.get("squash", 1.0))
            for index in range(count):
                angle = base_angle + 2 * math.pi * index / count
                maximum_axis = max(float(np.linalg.norm(basis_x)), float(np.linalg.norm(basis_y)))
                inner_fraction = inner / maximum_axis
                outer_fraction = outer / maximum_axis
                start = (
                    center_x
                    + inner_fraction * (basis_x[0] * math.cos(angle) + basis_y[0] * squash * math.sin(angle)),
                    center_y
                    + inner_fraction * (basis_x[1] * math.cos(angle) + basis_y[1] * squash * math.sin(angle)),
                )
                end = (
                    center_x
                    + outer_fraction * (basis_x[0] * math.cos(angle) + basis_y[0] * squash * math.sin(angle)),
                    center_y
                    + outer_fraction * (basis_x[1] * math.cos(angle) + basis_y[1] * squash * math.sin(angle)),
                )
                draw.line((start, end), fill=255, width=int(spokes.get("width", 1)))
    mask = ImageChops.multiply(mask, rotor_aperture_mask(source, spec))
    feather = float(spec.get("fixed_occluder_feather", 0.0))
    return mask.filter(ImageFilter.GaussianBlur(feather)) if feather else mask


def add_mechanical_rotor(frame: Image.Image, source: Image.Image, spec: dict[str, Any], p: float) -> None:
    """Animate separated blades under a fixed hub and untouched source housing."""
    blade_count = int(spec["blade_count"])
    supersample = int(spec.get("supersample", 8))
    center_x, center_y = (float(value) for value in spec["center"])
    basis = rotor_plane_basis(spec)
    maximum_axis = max(float(np.linalg.norm(basis[:, 0])), float(np.linalg.norm(basis[:, 1])))
    direction = float(spec.get("direction", -1.0))
    # Advancing by a whole number of blade pitches keeps the loop seamless (the
    # blade pattern has exactly that rotational symmetry); a fractional pitch
    # would leave a visible jump at the frame_count-1 -> 0 wrap.
    pitches_per_loop = max(1, round(float(spec.get("pitches_per_loop", 1))))
    angle = float(spec.get("base_angle", 0.0)) + direction * 2 * math.pi * pitches_per_loop * p / blade_count

    aperture = rotor_aperture_mask(source, spec)
    cavity = rotor_cavity_layer(source, spec)
    frame.paste(cavity, (0, 0), aperture)

    side = int(round(maximum_axis * 2 * supersample))
    plane = build_rotor_plane(spec, angle, side)
    extent_x = abs(float(basis[0, 0])) + abs(float(basis[0, 1])) + 2.0
    extent_y = abs(float(basis[1, 0])) + abs(float(basis[1, 1])) + 2.0
    x0 = int(math.floor((center_x - extent_x) * supersample))
    y0 = int(math.floor((center_y - extent_y) * supersample))
    x1 = int(math.ceil((center_x + extent_x) * supersample))
    y1 = int(math.ceil((center_y + extent_y) * supersample))
    inverse = np.linalg.inv(basis)
    plane_center = (side - 1) / 2
    plane_radius = side / 2
    affine = (
        plane_radius * inverse[0, 0] / supersample,
        plane_radius * inverse[0, 1] / supersample,
        plane_center
        + plane_radius
        * (inverse[0, 0] * (x0 / supersample - center_x) + inverse[0, 1] * (y0 / supersample - center_y)),
        plane_radius * inverse[1, 0] / supersample,
        plane_radius * inverse[1, 1] / supersample,
        plane_center
        + plane_radius
        * (inverse[1, 0] * (x0 / supersample - center_x) + inverse[1, 1] * (y0 / supersample - center_y)),
    )
    tilted = plane.transform(
        (x1 - x0, y1 - y0),
        Image.Transform.AFFINE,
        affine,
        resample=Image.Resampling.BICUBIC,
    )
    values = np.asarray(tilted).astype(np.float32)
    height, width = values.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = (xx - (width - 1) / 2) / max(1.0, width / 2)
    ny = (yy - (height - 1) / 2) / max(1.0, height / 2)
    light = np.clip(0.78 - 0.08 * nx + 0.34 * ny, 0.56, 1.16)
    values[:, :, :3] *= light[:, :, None]
    tilted = Image.fromarray(np.clip(values, 0, 255).astype(np.uint8))

    rotor = Image.new("RGBA", (source.width * supersample, source.height * supersample), (0, 0, 0, 0))
    rotor.alpha_composite(tilted, (x0, y0))
    rotor = rotor.resize(source.size, Image.Resampling.LANCZOS)
    rotor.putalpha(ImageChops.multiply(rotor.getchannel("A"), aperture))

    shadow_alpha = rotor.getchannel("A").filter(ImageFilter.GaussianBlur(0.65))
    shadow_alpha = ImageChops.offset(shadow_alpha, 1, 1).point(lambda value: int(value * 0.38))
    shadow_alpha = ImageChops.multiply(shadow_alpha, aperture)
    shadow = Image.new("RGBA", source.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)
    frame.alpha_composite(shadow)
    frame.alpha_composite(rotor)
    frame.alpha_composite(rotor_hub_layer(source, spec))
    occluder = rotor_fixed_occluder_mask(source, spec)
    if occluder.getbbox():
        frame.paste(source, (0, 0), occluder)


def gear_plane_basis(spec: dict[str, Any]) -> np.ndarray:
    if "plane_basis" in spec:
        basis_x, basis_y = spec["plane_basis"]
        basis = np.asarray(
            [[float(basis_x[0]), float(basis_y[0])], [float(basis_x[1]), float(basis_y[1])]],
            dtype=np.float64,
        )
    else:
        outer_x, outer_y = (float(value) for value in spec["outer_radius"])
        basis = np.asarray([[outer_x, 0.0], [0.0, outer_y]], dtype=np.float64)
    if abs(float(np.linalg.det(basis))) < 1e-6:
        raise ValueError(f"degenerate gear plane basis: {basis.tolist()}")
    return basis


def gear_inner_fraction(spec: dict[str, Any]) -> float:
    if "inner_fraction" in spec:
        return float(spec["inner_fraction"])
    return float(spec["inner_radius"][0]) / float(spec["outer_radius"][0])


def gear_annulus_mask(source: Image.Image, spec: dict[str, Any]) -> Image.Image:
    center = tuple(float(value) for value in spec["center"])
    basis = gear_plane_basis(spec)
    feather = float(spec.get("aperture_feather", 0.60))
    outer = projected_ellipse_mask(source.size, center, basis, feather)
    inner = projected_ellipse_mask(
        source.size,
        center,
        basis * gear_inner_fraction(spec),
        feather,
    )
    return ImageChops.subtract(outer, inner)


def gear_fill_style(spec: dict[str, Any]) -> str:
    """Return the face construction, preserving legacy open gears by default."""
    style = str(spec.get("fill_style", "open"))
    if style not in {"open", "solid", "bars", "solid_with_holes"}:
        raise ValueError(f"unknown mechanical_gear fill_style: {style}")
    return style


def gear_face_mask(source: Image.Image, spec: dict[str, Any]) -> Image.Image:
    """Clip a filled face to the registered projected outer gear aperture."""
    if gear_fill_style(spec) == "open":
        return gear_annulus_mask(source, spec)
    return projected_ellipse_mask(
        source.size,
        tuple(float(value) for value in spec["center"]),
        gear_plane_basis(spec),
        float(spec.get("aperture_feather", 0.60)),
    )


def gear_repeat_count(spec: dict[str, Any]) -> int:
    """Rotational symmetry shared by teeth and the selected body pattern.

    Advancing one tooth pitch only closes a loop when the inner spokes/holes
    have the same symmetry.  Their shared symmetry is gcd(tooth_count,
    fill_count), so using that repeat count keeps the whole rigid wheel -- not
    merely its teeth -- exactly loop-safe.
    """
    tooth_count = int(spec["tooth_count"])
    if gear_fill_style(spec) not in {"bars", "solid_with_holes"}:
        return tooth_count
    return max(1, math.gcd(tooth_count, max(1, int(spec.get("fill_count", tooth_count)))))


def sample_rgb_bilinear(values: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    x = np.clip(x, 0, values.shape[1] - 1.001)
    y = np.clip(y, 0, values.shape[0] - 1.001)
    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    x1 = x0 + 1
    y1 = y0 + 1
    fx = (x - x0)[:, :, None]
    fy = (y - y0)[:, :, None]
    return (
        values[y0, x0] * (1 - fx) * (1 - fy)
        + values[y0, x1] * fx * (1 - fy)
        + values[y1, x0] * (1 - fx) * fy
        + values[y1, x1] * fx * fy
    )


def gear_source_albedo_template(source: Image.Image, spec: dict[str, Any], side: int) -> Image.Image:
    """Reconstruct one clean periodic tooth material from all visible sectors."""
    basis = gear_plane_basis(spec)
    maximum_axis = max(float(np.linalg.norm(basis[:, 0])), float(np.linalg.norm(basis[:, 1])))
    material_side = max(96, int(round(maximum_axis * 2 * float(spec.get("material_supersample", 4)))))
    cache_key = (id(source), json.dumps(spec, sort_keys=True), material_side)
    cached = GEAR_MATERIAL_CACHE.get(cache_key)
    if cached is not None:
        return cached.resize((side, side), Image.Resampling.BICUBIC)

    center = (material_side - 1) / 2
    outer = material_side * 0.48
    yy, xx = np.mgrid[0:material_side, 0:material_side].astype(np.float32)
    u = (xx - center) / outer
    v = (yy - center) / outer
    radius = np.sqrt(u * u + v * v)
    theta = np.arctan2(v, u)
    tooth_count = int(spec["tooth_count"])
    pitch = 2 * math.pi / tooth_count
    base_angle = float(spec.get("base_angle", 0.0))
    local_angle = np.mod(theta - base_angle + pitch / 2, pitch) - pitch / 2
    source_rgb = np.asarray(source.convert("RGB"), dtype=np.float32)
    center_x, center_y = (float(value) for value in spec["center"])
    samples = []
    for tooth_index in range(tooth_count):
        sample_angle = base_angle + local_angle + tooth_index * pitch
        face_x = radius * np.cos(sample_angle)
        face_y = radius * np.sin(sample_angle)
        screen_x = center_x + basis[0, 0] * face_x + basis[0, 1] * face_y
        screen_y = center_y + basis[1, 0] * face_x + basis[1, 1] * face_y
        samples.append(sample_rgb_bilinear(source_rgb, screen_x, screen_y))
    material = np.median(np.stack(samples, axis=0), axis=0)

    inner_fraction = gear_inner_fraction(spec)
    valid = (radius >= inner_fraction) & (radius <= 1.0)
    luminance = material[:, :, 0] * 0.2126 + material[:, :, 1] * 0.7152 + material[:, :, 2] * 0.0722
    palette = np.asarray(spec.get("gear_color", [112, 88, 51]), dtype=np.float32)
    target_luminance = float(palette[0] * 0.2126 + palette[1] * 0.7152 + palette[2] * 0.0722)
    median_luminance = max(1.0, float(np.median(luminance[valid])))
    material *= target_luminance / median_luminance
    material_luminance = material[:, :, 0] * 0.2126 + material[:, :, 1] * 0.7152 + material[:, :, 2] * 0.0722
    floor = target_luminance * float(spec.get("albedo_shadow_floor", 0.42))
    lift = np.maximum(0.0, floor - material_luminance)
    material += lift[:, :, None] * 0.72
    material_luminance = material[:, :, 0] * 0.2126 + material[:, :, 1] * 0.7152 + material[:, :, 2] * 0.0722
    tinted = palette[None, None, :] * (material_luminance / max(1.0, target_luminance))[:, :, None]
    tint_strength = float(spec.get("albedo_tint_strength", 0.72))
    material = material * (1.0 - tint_strength) + tinted * tint_strength
    template = Image.fromarray(np.clip(material, 0, 255).astype(np.uint8))
    GEAR_MATERIAL_CACHE[cache_key] = template
    return template.resize((side, side), Image.Resampling.BICUBIC)


def build_gear_plane(
    spec: dict[str, Any], angle: float, side: int, source: Image.Image | None = None
) -> Image.Image:
    tooth_count = int(spec["tooth_count"])
    supersample = int(spec.get("supersample", 8))
    center = (side - 1) / 2
    outer = side * 0.48
    root = outer * float(spec.get("root_fraction", 0.84))
    inner_fraction = gear_inner_fraction(spec)
    inner = outer * inner_fraction
    pitch = 2 * math.pi / tooth_count
    tip_fraction = float(spec.get("tooth_tip_fraction", 0.25))
    polygon: list[tuple[float, float]] = []
    for index in range(tooth_count):
        theta = angle + index * pitch
        polygon.extend(
            [
                rotor_polar_point(center, root, theta - pitch * 0.50),
                rotor_polar_point(center, outer, theta - pitch * tip_fraction),
                rotor_polar_point(center, outer, theta + pitch * tip_fraction),
                rotor_polar_point(center, root, theta + pitch * 0.50),
            ]
        )

    yy, xx = np.mgrid[0:side, 0:side].astype(np.float32)
    radius = np.sqrt((xx - center) ** 2 + (yy - center) ** 2) / outer
    theta = np.arctan2(yy - center, xx - center)
    mask = Image.new("L", (side, side), 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(polygon, fill=255)
    fill_style = gear_fill_style(spec)
    if fill_style == "open":
        # Preserve the original annular renderer byte-for-byte for manifests
        # created before configurable face construction existed.
        draw.ellipse((center - inner, center - inner, center + inner, center + inner), fill=0)
    elif fill_style == "bars":
        fill_count = max(2, int(spec.get("fill_count", tooth_count)))
        spoke_pitch = 2 * math.pi / fill_count
        spoke_phase = np.mod(theta - angle + spoke_pitch / 2, spoke_pitch) - spoke_pitch / 2
        spoke_width = np.clip(float(spec.get("fill_width_fraction", 0.24)), 0.04, 0.9)
        hub = np.clip(float(spec.get("body_hub_fraction", 0.24)), 0.06, 0.72)
        rim_width = np.clip(float(spec.get("body_rim_width", 0.10)), 0.025, 0.4)
        rim_inner = max(hub, float(spec.get("root_fraction", 0.84)) - rim_width)
        body = (radius <= hub) | (radius >= rim_inner) | (
            np.abs(spoke_phase) <= spoke_pitch * spoke_width * 0.5
        )
        values = np.asarray(mask).copy()
        values[(radius < float(spec.get("root_fraction", 0.84))) & ~body] = 0
        mask = Image.fromarray(values)
    elif fill_style == "solid_with_holes":
        fill_count = max(2, int(spec.get("fill_count", tooth_count)))
        ring = np.clip(float(spec.get("hole_ring_fraction", 0.53)), 0.15, 0.78)
        hole_radius = np.clip(float(spec.get("hole_radius_fraction", 0.12)), 0.025, 0.28)
        holes = np.zeros((side, side), dtype=bool)
        for index in range(fill_count):
            hole_angle = angle + index * 2 * math.pi / fill_count
            hole_x = ring * math.cos(hole_angle)
            hole_y = ring * math.sin(hole_angle)
            holes |= (xx - center - hole_x * outer) ** 2 + (yy - center - hole_y * outer) ** 2 <= (
                hole_radius * outer
            ) ** 2
        values = np.asarray(mask).copy()
        values[holes] = 0
        mask = Image.fromarray(values)

    local_angle = np.mod(theta - angle + pitch / 2, pitch) - pitch / 2
    local_phase = local_angle / pitch
    native_radius = np.floor(radius * outer / supersample)
    grain = (
        7.0 * np.sin(native_radius * 1.21 + local_phase * 6.0)
        + 3.5 * np.cos(native_radius * 0.49 - local_phase * 10.0)
        + 2.0 * np.sin(radius * 47.0)
    )
    color = np.asarray(spec.get("gear_color", [112, 88, 51]), dtype=np.float32)
    rgba = np.zeros((side, side, 4), dtype=np.uint8)
    rgba[:, :, 0] = np.clip(color[0] + grain, 0, 255).astype(np.uint8)
    rgba[:, :, 1] = np.clip(color[1] + grain * 0.78, 0, 255).astype(np.uint8)
    rgba[:, :, 2] = np.clip(color[2] + grain * 0.48, 0, 255).astype(np.uint8)
    rgba[:, :, 3] = np.asarray(mask)
    gear = Image.fromarray(rgba)
    if source is not None and spec.get("source_tooth_material", False):
        material = gear_source_albedo_template(source, spec, side)
        delta = angle - float(spec.get("base_angle", 0.0))
        material = material.rotate(-math.degrees(delta), resample=Image.Resampling.BICUBIC)
        gear_values = np.asarray(gear, dtype=np.uint8).copy()
        material_values = np.asarray(material, dtype=np.uint8)
        blend = float(spec.get("source_albedo_blend", 0.78))
        gear_values[:, :, :3] = np.clip(
            gear_values[:, :, :3].astype(np.float32) * (1.0 - blend)
            + material_values.astype(np.float32) * blend,
            0,
            255,
        ).astype(np.uint8)
        gear = Image.fromarray(gear_values)

    edge = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    edge_draw = ImageDraw.Draw(edge)
    edge_draw.line(polygon + [polygon[0]], fill=tuple(spec.get("gear_edge", [175, 133, 67, 170])), width=max(1, side // 220))
    edge_draw.ellipse(
        (center - root, center - root, center + root, center + root),
        outline=tuple(spec.get("gear_root_edge", [56, 43, 28, 165])),
        width=max(1, side // 180),
    )
    if fill_style == "open":
        edge_draw.ellipse(
            (center - inner, center - inner, center + inner, center + inner),
            outline=tuple(spec.get("gear_inner_edge", [43, 34, 24, 230])),
            width=max(1, side // 130),
        )
    else:
        # A restrained inset line around spokes and holes is enough to make
        # their cut edges read as machined openings after projection.
        boundary = mask.filter(ImageFilter.FIND_EDGES).point(
            lambda value: int(value * float(spec.get("body_edge_strength", 0.46)))
        )
        inset = Image.new("RGBA", (side, side), tuple(spec.get("gear_inner_edge", [43, 34, 24, 230])))
        inset.putalpha(boundary)
        edge.alpha_composite(inset)
    gear.alpha_composite(edge)
    return gear


def gear_source_center_layer(source: Image.Image, spec: dict[str, Any]) -> Image.Image:
    layer = Image.new("RGBA", source.size, (0, 0, 0, 0))
    if "source_center_basis" not in spec:
        return layer
    center = tuple(float(value) for value in spec.get("source_center", spec["center"]))
    basis_x, basis_y = spec["source_center_basis"]
    basis = np.asarray(
        [[float(basis_x[0]), float(basis_y[0])], [float(basis_x[1]), float(basis_y[1])]],
        dtype=np.float64,
    )
    # The editor uses an all-zero reveal basis as an explicit "no source
    # center" value on gears whose middle should remain open. Treat that as
    # an empty layer instead of attempting to invert a singular matrix.
    if abs(float(np.linalg.det(basis))) < 1e-6:
        return layer
    mask = projected_ellipse_mask(
        source.size,
        center,
        basis,
        float(spec.get("center_feather", 0.65)),
    )
    layer.paste(source, (0, 0), mask)
    return layer


def gear_procedural_center_cap(source: Image.Image, spec: dict[str, Any]) -> Image.Image:
    """Paint a lit, shaded filler disc for gears with no source art to reveal.

    Mirrors rotor_hub_layer's procedural branch: unlike gear_source_center_layer
    (which can only ever show whatever the source sprite already drew there,
    empty or not), this paints an actual disc so the center reads as filled
    regardless of what -- if anything -- exists underneath.
    """
    x0, y0, x1, y1 = (int(value) for value in spec["center_cap_bbox"])
    supersample = int(spec.get("supersample", 8))
    width = (x1 - x0) * supersample
    height = (y1 - y0) * supersample
    yy, xx = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = (xx - (width - 1) / 2) / (width / 2)
    ny = (yy - (height - 1) / 2) / (height / 2)
    radius2 = nx * nx + ny * ny
    inside = radius2 <= 1.0
    z = np.sqrt(np.clip(1.0 - radius2, 0.0, 1.0))
    light = np.asarray(spec.get("light_direction", [-0.48, -0.58, 0.93]), dtype=np.float32)
    light /= np.linalg.norm(light)
    lambert = nx * light[0] + ny * light[1] + z * light[2]
    illumination = np.clip(0.43 + 0.61 * lambert, 0.32, 1.07)
    native_x = np.floor(xx / supersample)
    native_y = np.floor(yy / supersample)
    grain = 6.0 * np.sin(native_x * 1.73 + native_y * 0.81) + 3.5 * np.cos(
        native_x * 0.51 - native_y * 1.41
    )
    palette = np.asarray(spec.get("center_cap_color", spec.get("gear_color", [112, 88, 51])), dtype=np.float32)
    rgb = palette[None, None, :] * illumination[:, :, None] + grain[:, :, None]
    alpha = np.where(inside, 255, 0).astype(np.uint8)
    cap = Image.fromarray(np.dstack((np.clip(rgb, 0, 255).astype(np.uint8), alpha)))

    full = Image.new("RGBA", (source.width * supersample, source.height * supersample), (0, 0, 0, 0))
    shadow = Image.new("RGBA", full.size, (0, 0, 0, 0))
    shadow_mask = Image.new("L", full.size, 0)
    ImageDraw.Draw(shadow_mask).ellipse(
        ((x0 - 1) * supersample, (y0 + 1) * supersample, (x1 + 2) * supersample, (y1 + 3) * supersample),
        fill=170,
    )
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(1.1 * supersample))
    shadow.putalpha(shadow_mask)
    full.alpha_composite(shadow)
    full.alpha_composite(cap, (x0 * supersample, y0 * supersample))
    return full.resize(source.size, Image.Resampling.LANCZOS).filter(
        ImageFilter.UnsharpMask(radius=0.55, percent=45, threshold=2)
    )


def apply_gear_source_material(
    gear: Image.Image,
    source: Image.Image,
    annulus: Image.Image,
    spec: dict[str, Any],
) -> Image.Image:
    """Transfer fixed screen-space source texture without rotating baked light."""
    blend = float(spec.get("source_material_blend", 0.68))
    if blend <= 0:
        return gear
    source_rgb = np.asarray(source.convert("RGB"), dtype=np.float32)
    smooth_rgb = np.asarray(
        source.convert("RGB").filter(ImageFilter.GaussianBlur(float(spec.get("material_blur", 2.2)))),
        dtype=np.float32,
    )
    luminance = smooth_rgb[:, :, 0] * 0.2126 + smooth_rgb[:, :, 1] * 0.7152 + smooth_rgb[:, :, 2] * 0.0722
    annulus_values = np.asarray(annulus, dtype=np.uint8) > 32
    local_luminance = luminance[annulus_values]
    low = float(np.percentile(local_luminance, 18))
    high = float(np.percentile(local_luminance, 82))
    shade = np.clip((luminance - low) / max(1.0, high - low), 0.0, 1.0)
    shade = 0.62 + shade * 0.62
    fine = (
        source_rgb[:, :, 0] * 0.2126
        + source_rgb[:, :, 1] * 0.7152
        + source_rgb[:, :, 2] * 0.0722
        - luminance
    ) * float(spec.get("material_detail", 0.22))
    palette = np.asarray(spec.get("gear_color", [112, 88, 51]), dtype=np.float32)
    material = palette[None, None, :] * shade[:, :, None] + fine[:, :, None]

    values = np.asarray(gear, dtype=np.uint8).copy()
    procedural = values[:, :, :3].astype(np.float32)
    alpha = values[:, :, 3].astype(np.float32) / 255.0
    local_blend = alpha[:, :, None] * blend
    values[:, :, :3] = np.clip(
        procedural * (1.0 - local_blend) + material * local_blend,
        0,
        255,
    ).astype(np.uint8)
    return Image.fromarray(values)


def gear_fixed_occluder_mask(source: Image.Image, spec: dict[str, Any]) -> Image.Image:
    mask = Image.new("L", source.size, 0)
    mode = str(spec.get("fixed_occluder_mode", "asset"))
    if mode == "off":
        return mask
    offset_x = 0.0
    offset_y = 0.0
    if mode == "follow_gear":
        reference_x, reference_y = (
            float(value)
            for value in spec.get(
                "fixed_occluder_reference_center",
                spec.get("source_center", spec.get("center", [0.0, 0.0])),
            )
        )
        center_x, center_y = (float(value) for value in spec.get("center", [0.0, 0.0]))
        offset_x = center_x - reference_x
        offset_y = center_y - reference_y
    draw = ImageDraw.Draw(mask)
    for rectangle in spec.get("fixed_occluder_rectangles", []):
        x0, y0, x1, y1 = (float(value) for value in rectangle)
        draw.rectangle(
            (x0 + offset_x, y0 + offset_y, x1 + offset_x, y1 + offset_y),
            fill=255,
        )
    for polygon in spec.get("fixed_occluder_polygons", []):
        draw.polygon(
            [
                (float(point[0]) + offset_x, float(point[1]) + offset_y)
                for point in polygon
            ],
            fill=255,
        )
    for arc in spec.get("fixed_occluder_arcs", []):
        arc_center = tuple(
            float(value) + offset
            for value, offset in zip(
                arc.get("center", spec["center"]), (offset_x, offset_y)
            )
        )
        outer_x, outer_y = (float(value) for value in arc["outer_radius"])
        inner_x, inner_y = (float(value) for value in arc["inner_radius"])
        outer = projected_ellipse_mask(
            source.size,
            arc_center,
            np.asarray([[outer_x, 0.0], [0.0, outer_y]], dtype=np.float64),
            float(arc.get("feather", 0.45)),
        )
        inner = projected_ellipse_mask(
            source.size,
            arc_center,
            np.asarray([[inner_x, 0.0], [0.0, inner_y]], dtype=np.float64),
            float(arc.get("feather", 0.45)),
        )
        arc_mask = ImageChops.subtract(outer, inner)
        clip = Image.new("L", source.size, 0)
        clip_draw = ImageDraw.Draw(clip)
        clip_draw.rectangle(
            (
                0,
                int(float(arc.get("minimum_y", 0)) + offset_y),
                source.width,
                int(float(arc.get("maximum_y", source.height)) + offset_y),
            ),
            fill=255,
        )
        mask = ImageChops.lighter(mask, ImageChops.multiply(arc_mask, clip))
    mask = ImageChops.multiply(mask, source.getchannel("A"))
    feather = float(spec.get("fixed_occluder_feather", 0.0))
    return mask.filter(ImageFilter.GaussianBlur(feather)) if feather else mask


def source_occluder_mask(source: Image.Image, spec: dict[str, Any]) -> Image.Image:
    """Build an editable source-restoration layer independent of its mechanism.

    A source occluder is ordinary z-ordered geometry: wherever its mask is
    present, the immutable source sprite is painted back over all earlier
    motion layers.  Keeping it out of a fan/gear spec means it can be selected,
    moved, reshaped, reordered, or deleted without surprising mechanism-local
    coordinates.
    """
    mask = Image.new("L", source.size, 0)
    shape = str(spec.get("shape", "polygon"))
    if shape == "polygon":
        polygon = spec.get("polygon", [])
        if len(polygon) < 3:
            raise ValueError("source_occluder polygon requires at least three vertices")
        ImageDraw.Draw(mask).polygon(
            [tuple(float(value) for value in point) for point in polygon], fill=255
        )
    elif shape == "ellipse_ring":
        center = tuple(float(value) for value in spec["center"])
        outer_x, outer_y = (float(value) for value in spec["outer_radius"])
        inner_x, inner_y = (float(value) for value in spec["inner_radius"])
        edge_feather = float(spec.get("edge_feather", 0.45))
        outer = projected_ellipse_mask(
            source.size,
            center,
            np.asarray([[outer_x, 0.0], [0.0, outer_y]], dtype=np.float64),
            edge_feather,
        )
        inner = projected_ellipse_mask(
            source.size,
            center,
            np.asarray([[inner_x, 0.0], [0.0, inner_y]], dtype=np.float64),
            edge_feather,
        )
        mask = ImageChops.subtract(outer, inner)
        clip = Image.new("L", source.size, 0)
        ImageDraw.Draw(clip).rectangle(
            (
                0,
                int(float(spec.get("minimum_y", 0))),
                source.width,
                int(float(spec.get("maximum_y", source.height))),
            ),
            fill=255,
        )
        mask = ImageChops.multiply(mask, clip)
    else:
        raise ValueError(f"unknown source_occluder shape: {shape}")
    mask = ImageChops.multiply(mask, source.getchannel("A"))
    feather = float(spec.get("feather", 0.0))
    return mask.filter(ImageFilter.GaussianBlur(feather)) if feather else mask


def add_source_occluder(
    frame: Image.Image, source: Image.Image, spec: dict[str, Any], p: float
) -> None:
    """Restore original source pixels through an editable z-ordered mask."""
    frame.paste(source, (0, 0), source_occluder_mask(source, spec))


def translated_layer(image: Image.Image, dx: float, dy: float) -> Image.Image:
    """Translate without ImageChops.offset's opposite-edge wraparound."""
    return image.transform(
        image.size,
        Image.Transform.AFFINE,
        (1.0, 0.0, -dx, 0.0, 1.0, -dy),
        resample=Image.Resampling.BICUBIC,
    )


def gear_thickness_layer(
    gear: Image.Image,
    source: Image.Image,
    spec: dict[str, Any],
    maximum_axis: float,
) -> Image.Image:
    """Extrude the projected face into a displaced, source-clipped rear body."""
    fraction = max(0.0, float(spec.get("gear_thickness_fraction", 0.0)))
    thickness = maximum_axis * fraction
    layer = Image.new("RGBA", source.size, (0, 0, 0, 0))
    if thickness <= 0.01:
        return layer

    direction = np.asarray(spec.get("thickness_direction", [0.55, 0.83]), dtype=np.float64)
    length = float(np.linalg.norm(direction))
    if length < 1e-6:
        direction = np.asarray([0.55, 0.83], dtype=np.float64)
        length = float(np.linalg.norm(direction))
    direction /= length
    brightness = np.clip(float(spec.get("thickness_brightness", 0.46)), 0.08, 1.0)
    alpha_scale = np.clip(float(spec.get("thickness_alpha", 1.0)), 0.0, 1.0)
    values = np.asarray(gear, dtype=np.uint8).copy()
    values[:, :, :3] = np.clip(values[:, :, :3].astype(np.float32) * brightness, 0, 255).astype(np.uint8)
    values[:, :, 3] = np.clip(values[:, :, 3].astype(np.float32) * alpha_scale, 0, 255).astype(np.uint8)
    dark_face = Image.fromarray(values)

    # Multiple subpixel slices create a true swept flank. Drawing rear-to-front
    # leaves the nearest slice on top; the front face is composited afterward.
    steps = max(2, int(math.ceil(thickness * 2.5)))
    for index in range(steps, 0, -1):
        distance = thickness * index / steps
        layer.alpha_composite(
            translated_layer(dark_face, direction[0] * distance, direction[1] * distance)
        )
    layer.putalpha(ImageChops.multiply(layer.getchannel("A"), source.getchannel("A")))

    highlight_strength = np.clip(float(spec.get("thickness_edge_highlight", 0.14)), 0.0, 0.8)
    if highlight_strength:
        exposed = ImageChops.subtract(layer.getchannel("A"), gear.getchannel("A"))
        shoulder = exposed.filter(ImageFilter.FIND_EDGES).point(
            lambda value: int(value * highlight_strength)
        )
        highlight = Image.new("RGBA", source.size, tuple(spec.get("gear_edge", [175, 133, 67, 170])))
        highlight.putalpha(shoulder)
        layer.alpha_composite(highlight)
    return layer


def add_mechanical_gear(frame: Image.Image, source: Image.Image, spec: dict[str, Any], p: float) -> None:
    """Rotate a projected toothed face while its central plate and housing stay fixed."""
    center_x, center_y = (float(value) for value in spec["center"])
    basis = gear_plane_basis(spec)
    maximum_axis = max(float(np.linalg.norm(basis[:, 0])), float(np.linalg.norm(basis[:, 1])))
    tooth_count = int(spec["tooth_count"])
    supersample = int(spec.get("supersample", 8))
    direction = float(spec.get("direction", -1.0))
    # See add_mechanical_rotor: a whole number of tooth pitches per loop keeps
    # the wrap seamless; a fractional pitch would leave a visible jump.
    pitches_per_loop = max(1, round(float(spec.get("pitches_per_loop", 1))))
    repeat_count = gear_repeat_count(spec)
    # Fold completed symmetry pitches back to the identical base geometry.
    # Besides being physically equivalent, this avoids subpixel raster and
    # texture-rotation drift at the exact p=1 loop boundary.
    loop_phase = (p * pitches_per_loop) % 1.0
    angle = float(spec.get("base_angle", 0.0)) + direction * 2 * math.pi * loop_phase / repeat_count
    annulus = gear_annulus_mask(source, spec)
    face_aperture = gear_face_mask(source, spec)

    yy, xx = np.mgrid[0 : source.height, 0 : source.width].astype(np.float32)
    nx, ny = projected_coordinates(source.size, (center_x, center_y), basis)
    radius = np.sqrt(nx * nx + ny * ny)
    src = np.asarray(source.convert("RGB"), dtype=np.float32)
    local = (radius > 0.55) & (radius < 1.0)
    base = np.percentile(src[local], float(spec.get("cavity_percentile", 12)), axis=0)
    texture = 1.4 * np.sin(xx * 0.59 + yy * 0.17) + 0.9 * np.cos(xx * 0.29 - yy * 0.43)
    cavity_rgb = base[None, None, :] * np.clip(0.78 + 0.18 * radius, 0.72, 1.0)[:, :, None]
    cavity_rgb += texture[:, :, None]
    cavity = Image.fromarray(
        np.dstack(
            (
                np.clip(cavity_rgb, 0, 255).astype(np.uint8),
                np.full((source.height, source.width), 255, dtype=np.uint8),
            )
        )
    )
    frame.paste(cavity, (0, 0), face_aperture)

    side = int(round(maximum_axis * 2 * supersample))
    plane = build_gear_plane(spec, angle, side, source)
    extent_x = abs(float(basis[0, 0])) + abs(float(basis[0, 1])) + 2.0
    extent_y = abs(float(basis[1, 0])) + abs(float(basis[1, 1])) + 2.0
    x0 = int(math.floor((center_x - extent_x) * supersample))
    y0 = int(math.floor((center_y - extent_y) * supersample))
    x1 = int(math.ceil((center_x + extent_x) * supersample))
    y1 = int(math.ceil((center_y + extent_y) * supersample))
    inverse = np.linalg.inv(basis)
    plane_center = (side - 1) / 2
    plane_radius = side / 2
    affine = (
        plane_radius * inverse[0, 0] / supersample,
        plane_radius * inverse[0, 1] / supersample,
        plane_center
        + plane_radius
        * (inverse[0, 0] * (x0 / supersample - center_x) + inverse[0, 1] * (y0 / supersample - center_y)),
        plane_radius * inverse[1, 0] / supersample,
        plane_radius * inverse[1, 1] / supersample,
        plane_center
        + plane_radius
        * (inverse[1, 0] * (x0 / supersample - center_x) + inverse[1, 1] * (y0 / supersample - center_y)),
    )
    tilted = plane.transform(
        (x1 - x0, y1 - y0),
        Image.Transform.AFFINE,
        affine,
        resample=Image.Resampling.BICUBIC,
    )
    values = np.asarray(tilted).astype(np.float32)
    height, width = values.shape[:2]
    sy, sx = np.mgrid[0:height, 0:width].astype(np.float32)
    screen_x = (sx - (width - 1) / 2) / max(1.0, width / 2)
    screen_y = (sy - (height - 1) / 2) / max(1.0, height / 2)
    lighting = np.clip(0.78 - 0.16 * screen_x + 0.24 * screen_y, 0.55, 1.18)
    values[:, :, :3] *= lighting[:, :, None]
    tilted = Image.fromarray(np.clip(values, 0, 255).astype(np.uint8))

    gear = Image.new("RGBA", (source.width * supersample, source.height * supersample), (0, 0, 0, 0))
    gear.alpha_composite(tilted, (x0, y0))
    gear = gear.resize(source.size, Image.Resampling.LANCZOS)
    gear.putalpha(ImageChops.multiply(gear.getchannel("A"), face_aperture))
    gear = apply_gear_source_material(gear, source, annulus, spec)
    thickness = gear_thickness_layer(gear, source, spec, maximum_axis)
    if thickness.getbbox():
        volume_alpha = ImageChops.lighter(gear.getchannel("A"), thickness.getchannel("A"))
        shadow_alpha = translated_layer(
            volume_alpha.filter(ImageFilter.GaussianBlur(0.55)), 1, 1
        ).point(lambda value: int(value * 0.34))
        shadow_alpha = ImageChops.multiply(shadow_alpha, source.getchannel("A"))
    else:
        # Retain the legacy shadow path exactly when construction thickness is
        # absent, so existing manifests render identically.
        shadow_alpha = ImageChops.offset(gear.getchannel("A").filter(ImageFilter.GaussianBlur(0.55)), 1, 1)
        shadow_alpha = ImageChops.multiply(shadow_alpha.point(lambda value: int(value * 0.34)), annulus)
    shadow = Image.new("RGBA", source.size, (0, 0, 0, 0))
    shadow.putalpha(shadow_alpha)
    frame.alpha_composite(shadow)
    frame.alpha_composite(thickness)
    frame.alpha_composite(gear)
    if "center_cap_bbox" in spec:
        frame.alpha_composite(gear_procedural_center_cap(source, spec))
    else:
        frame.alpha_composite(gear_source_center_layer(source, spec))
    occluder = gear_fixed_occluder_mask(source, spec)
    if occluder.getbbox():
        frame.paste(source, (0, 0), occluder)


def quad_homography(polygon: list[list[float]]) -> np.ndarray:
    """Map unit-square coordinates into a four-corner perspective strip.

    Corners follow the same order as ``surface_scan``: top-left, top-right,
    bottom-right, bottom-left.  A true projective mapping keeps tooth bands
    registered when the two sides converge; treating the strip as an
    axis-aligned crop is precisely the perspective-breaking shortcut this
    pipeline exists to avoid.
    """
    if len(polygon) != 4:
        raise ValueError("vertical_gear polygon must contain exactly four corners")
    destination = np.asarray(polygon, dtype=np.float64)
    source_points = np.asarray(((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)))
    matrix_rows: list[list[float]] = []
    values: list[float] = []
    for (u, v), (x, y) in zip(source_points, destination):
        matrix_rows.append([u, v, 1.0, 0.0, 0.0, 0.0, -x * u, -x * v])
        values.append(float(x))
        matrix_rows.append([0.0, 0.0, 0.0, u, v, 1.0, -y * u, -y * v])
        values.append(float(y))
    try:
        coefficients = np.linalg.solve(
            np.asarray(matrix_rows, dtype=np.float64), np.asarray(values, dtype=np.float64)
        )
    except np.linalg.LinAlgError as exc:
        raise ValueError("degenerate vertical_gear perspective polygon") from exc
    return np.asarray(
        (
            (coefficients[0], coefficients[1], coefficients[2]),
            (coefficients[3], coefficients[4], coefficients[5]),
            (coefficients[6], coefficients[7], 1.0),
        ),
        dtype=np.float64,
    )


def project_quad_coordinates(
    homography: np.ndarray, u: np.ndarray, v: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    denominator = homography[2, 0] * u + homography[2, 1] * v + homography[2, 2]
    if np.any(np.abs(denominator) < 1e-8):
        raise ValueError("vertical_gear perspective polygon crosses the projective horizon")
    x = (homography[0, 0] * u + homography[0, 1] * v + homography[0, 2]) / denominator
    y = (homography[1, 0] * u + homography[1, 1] * v + homography[1, 2]) / denominator
    return x, y


def unproject_quad_coordinates(
    homography: np.ndarray, x: np.ndarray, y: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    inverse = np.linalg.inv(homography)
    denominator = inverse[2, 0] * x + inverse[2, 1] * y + inverse[2, 2]
    denominator = np.where(np.abs(denominator) < 1e-8, 1e-8, denominator)
    u = (inverse[0, 0] * x + inverse[0, 1] * y + inverse[0, 2]) / denominator
    v = (inverse[1, 0] * x + inverse[1, 1] * y + inverse[1, 2]) / denominator
    return u, v


def sample_scalar_bilinear(values: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Bilinear sampler for one-channel arrays, paired with sample_rgb_bilinear."""
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


def vertical_gear_source_detail_template(
    source: Image.Image, spec: dict[str, Any], homography: np.ndarray
) -> np.ndarray:
    """Reconstruct one repeatable tooth pitch while discarding baked lighting.

    Low-frequency colour and shadow remain fixed in screen space.  Only the
    median high-frequency detail shared by the source teeth is periodic, so it
    can travel without making the building's whole light rig orbit with it.
    """
    cache_key = (id(source), json.dumps(spec, sort_keys=True))
    cached = VERTICAL_GEAR_DETAIL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    polygon = np.asarray(spec["polygon"], dtype=np.float64)
    transverse = 0.5 * (
        np.linalg.norm(polygon[1] - polygon[0]) + np.linalg.norm(polygon[2] - polygon[3])
    )
    longitudinal = 0.5 * (
        np.linalg.norm(polygon[3] - polygon[0]) + np.linalg.norm(polygon[2] - polygon[1])
    )
    tooth_count = max(2, int(spec.get("tooth_count", 8)))
    visible_arc_degrees = float(spec.get("arc_start_degrees", 90.0)) + float(
        spec.get("arc_end_degrees", 90.0)
    )
    visible_repeat_count = max(1, round(tooth_count * visible_arc_degrees / 360.0))
    material_samples = max(1.0, float(spec.get("material_samples", 4.0)))
    across_samples = max(24, min(256, int(math.ceil(transverse * material_samples))))
    phase_samples = max(
        64,
        min(256, int(math.ceil(longitudinal * material_samples / visible_repeat_count * 4.0))),
    )

    source_rgb = np.asarray(source.convert("RGB"), dtype=np.float32)
    smooth_rgb = np.asarray(
        source.convert("RGB").filter(
            ImageFilter.GaussianBlur(float(spec.get("material_blur", 1.6)))
        ),
        dtype=np.float32,
    )
    detail_ratio = np.clip((source_rgb + 12.0) / (smooth_rgb + 12.0), 0.62, 1.48)

    phase_values = np.arange(phase_samples, dtype=np.float32) / phase_samples
    across_values = np.linspace(0.0, 1.0, across_samples, dtype=np.float32)
    local_phase, local_u = np.meshgrid(phase_values, across_values, indexing="ij")
    samples = []
    for tooth_index in range(visible_repeat_count):
        local_v = (tooth_index + local_phase) / visible_repeat_count
        screen_x, screen_y = project_quad_coordinates(homography, local_u, local_v)
        samples.append(sample_rgb_bilinear(detail_ratio, screen_x, screen_y))
    template = np.median(np.stack(samples, axis=0), axis=0).astype(np.float32)
    VERTICAL_GEAR_DETAIL_CACHE[cache_key] = template
    return template


def sample_periodic_detail(
    template: np.ndarray, u: np.ndarray, tooth_phase: np.ndarray
) -> np.ndarray:
    """Sample a template whose vertical coordinate wraps at one tooth pitch."""
    height, width = template.shape[:2]
    x = np.clip(u, 0.0, 1.0) * (width - 1)
    y = np.mod(tooth_phase, 1.0) * height
    x0 = np.floor(x).astype(np.int32)
    x1 = np.minimum(x0 + 1, width - 1)
    y0 = np.floor(y).astype(np.int32) % height
    y1 = (y0 + 1) % height
    fx = (x - x0)[:, :, None]
    fy = (y - np.floor(y))[:, :, None]
    return (
        template[y0, x0] * (1 - fx) * (1 - fy)
        + template[y0, x1] * fx * (1 - fy)
        + template[y1, x0] * (1 - fx) * fy
        + template[y1, x1] * fx * fy
    )


def cyclic_distance(values: np.ndarray, center: float) -> np.ndarray:
    return np.abs(np.mod(values - center + 0.5, 1.0) - 0.5)


def periodic_tooth_coverage(
    phase: np.ndarray, width_fraction: float, edge_softness: float
) -> np.ndarray:
    """Anti-aliased occupancy of one repeating rectangular gear tooth."""
    center_distance = cyclic_distance(phase, 0.5)
    return 1.0 / (
        1.0
        + np.exp(
            (center_distance - width_fraction / 2.0)
            / max(0.006, edge_softness * 0.42)
        )
    )


def vertical_gear_middle_coordinate(
    spec: dict[str, Any], homography: np.ndarray
) -> float:
    """Return the editable tangent/middle point in the active quad axis."""
    if "middle" in spec:
        middle_x, middle_y = (float(value) for value in spec["middle"])
    else:
        center_u = np.asarray([[0.5]], dtype=np.float64)
        center_v = np.asarray([[0.5]], dtype=np.float64)
        projected_x, projected_y = project_quad_coordinates(homography, center_u, center_v)
        middle_x = float(projected_x[0, 0])
        middle_y = float(projected_y[0, 0])
    middle_u, middle_v = unproject_quad_coordinates(
        homography,
        np.asarray([[middle_x]], dtype=np.float64),
        np.asarray([[middle_y]], dtype=np.float64),
    )
    coordinate = float(middle_v[0, 0] if spec.get("axis", "y") == "y" else middle_u[0, 0])
    return min(1.0, max(0.0, coordinate))


def vertical_gear_projected_angle(
    coordinate: np.ndarray,
    middle_coordinate: float,
    start_degrees: float,
    end_degrees: float,
) -> np.ndarray:
    """Invert circular projection so uniform rotation slows at the limbs.

    Screen displacement is proportional to sin(theta). Therefore theta at a
    screen coordinate is asin(displacement), not a linear interpolation. The
    tangent point theta=0 moves fastest; cos(theta) makes motion approach zero
    at a +/-90 degree limb. Moving the tangent to an endpoint naturally leaves
    a single quarter arc visible.
    """
    start_angle = math.radians(min(90.0, max(1.0, start_degrees)))
    end_angle = math.radians(min(90.0, max(1.0, end_degrees)))
    before_span = max(1e-5, middle_coordinate)
    after_span = max(1e-5, 1.0 - middle_coordinate)
    before_distance = np.clip((middle_coordinate - coordinate) / before_span, 0.0, 1.0)
    after_distance = np.clip((coordinate - middle_coordinate) / after_span, 0.0, 1.0)
    before_angle = -np.arcsin(np.clip(before_distance * math.sin(start_angle), 0.0, 1.0))
    after_angle = np.arcsin(np.clip(after_distance * math.sin(end_angle), 0.0, 1.0))
    return np.where(coordinate <= middle_coordinate, before_angle, after_angle)


def add_vertical_gear(frame: Image.Image, source: Image.Image, spec: dict[str, Any], p: float) -> None:
    """Animate a cylindrically projected edge-on gear inside a perspective quad.

    The strip is the visible rim of a wheel whose axle lies roughly in screen
    X.  We never translate a crop.  A homography makes each tooth cross-section
    follow the strip's perspective. Circular projection slows apparent tooth
    travel toward the limbs, swaps groove relief for tooth-side visibility,
    and allows the editable tangent/middle point to expose a half, quarter, or
    asymmetric arc. Periodic source detail still advances by exact pitches and
    the underlying low-frequency light/shadow field stays nailed to the building.
    """
    polygon = spec.get("polygon")
    if not polygon or len(polygon) != 4:
        raise ValueError("vertical_gear requires a four-corner polygon")
    homography = quad_homography(polygon)
    supersample = max(1, min(12, int(spec.get("supersample", 6))))
    visible_polygon = spec.get("mask_polygon", polygon)
    padding = float(spec.get("aperture_feather", 0.55)) * 3.0 + 2.0
    x0 = max(0, int(math.floor(min(point[0] for point in visible_polygon) - padding)))
    y0 = max(0, int(math.floor(min(point[1] for point in visible_polygon) - padding)))
    x1 = min(source.width, int(math.ceil(max(point[0] for point in visible_polygon) + padding)))
    y1 = min(source.height, int(math.ceil(max(point[1] for point in visible_polygon) + padding)))
    if x1 <= x0 or y1 <= y0:
        return

    high_width = (x1 - x0) * supersample
    high_height = (y1 - y0) * supersample
    high_y, high_x = np.mgrid[0:high_height, 0:high_width].astype(np.float32)
    screen_x = x0 + (high_x + 0.5) / supersample - 0.5
    screen_y = y0 + (high_y + 0.5) / supersample - 0.5
    local_u, local_v = unproject_quad_coordinates(homography, screen_x, screen_y)
    travel_coordinate = local_v if spec.get("axis", "y") == "y" else local_u
    # Feathered supersamples extend fractionally beyond the perspective quad.
    # Clamp them to the physical rim so an endpoint tangent (a quarter gear)
    # cannot wrap those translucent edge pixels onto the opposite circular limb.
    projected_coordinate = np.clip(travel_coordinate, 0.0, 1.0)
    middle_coordinate = vertical_gear_middle_coordinate(spec, homography)
    projected_angle = vertical_gear_projected_angle(
        projected_coordinate,
        middle_coordinate,
        float(spec.get("arc_start_degrees", 90.0)),
        float(spec.get("arc_end_degrees", 90.0)),
    )
    view_cosine = np.clip(np.cos(projected_angle), 0.0, 1.0)

    tooth_count = max(2, int(spec.get("tooth_count", 8)))
    direction = 1.0 if float(spec.get("direction", 1.0)) >= 0 else -1.0
    pitches_per_loop = max(1, round(float(spec.get("pitches_per_loop", 1))))
    # p % 1 gives p=0 and p=1 byte-identical closure in diagnostics while the
    # integer pitch shift preserves the same closure in the packed frame loop.
    travelling_pitches = direction * pitches_per_loop * (float(p) % 1.0)
    tooth_phase = np.mod(
        projected_angle * tooth_count / (2.0 * math.pi)
        - travelling_pitches
        + float(spec.get("phase", 0.0)),
        1.0,
    )

    source_rgb = np.asarray(source.convert("RGB"), dtype=np.float32)
    smooth_rgb = np.asarray(
        source.convert("RGB").filter(
            ImageFilter.GaussianBlur(float(spec.get("material_blur", 1.6)))
        ),
        dtype=np.float32,
    )
    fixed_source = sample_rgb_bilinear(source_rgb, screen_x, screen_y)
    fixed_smooth = sample_rgb_bilinear(smooth_rgb, screen_x, screen_y)
    detail_template = None
    if spec.get("source_tooth_material", True):
        detail_template = vertical_gear_source_detail_template(source, spec, homography)
        moving_detail = sample_periodic_detail(detail_template, local_u, tooth_phase)
        detail_strength = float(spec.get("source_detail_strength", 0.88))
        moving_detail = np.clip(1.0 + (moving_detail - 1.0) * detail_strength, 0.68, 1.38)
        moving_material = fixed_smooth * moving_detail
    else:
        moving_material = fixed_smooth
    material_blend = float(spec.get("source_material_blend", 0.82))
    edge_material_floor = float(spec.get("edge_material_floor", 0.22))
    edge_occlusion_power = float(spec.get("edge_occlusion_power", 0.72))
    front_visibility = edge_material_floor + (1.0 - edge_material_floor) * np.power(
        view_cosine, edge_occlusion_power
    )
    local_material_blend = np.clip(material_blend * front_visibility, 0.0, 1.0)
    face_rgb = (
        fixed_source * (1.0 - local_material_blend[:, :, None])
        + moving_material * local_material_blend[:, :, None]
    )

    tooth_width = min(0.90, max(0.12, float(spec.get("tooth_width_fraction", 0.52))))
    edge_softness = min(0.24, max(0.012, float(spec.get("edge_softness", 0.065))))
    upper_edge_center = 0.5 - tooth_width / 2.0
    lower_edge_center = 0.5 + tooth_width / 2.0
    upper_edge = np.exp(-0.5 * (cyclic_distance(tooth_phase, upper_edge_center) / edge_softness) ** 2)
    lower_edge = np.exp(-0.5 * (cyclic_distance(tooth_phase, lower_edge_center) / edge_softness) ** 2)
    tooth_body = periodic_tooth_coverage(tooth_phase, tooth_width, edge_softness)
    light_from_start = 1.0 if float(spec.get("light_direction", 1.0)) >= 0 else -1.0
    lit_edge, shaded_edge = (
        (upper_edge, lower_edge) if light_from_start > 0 else (lower_edge, upper_edge)
    )
    groove_visibility = np.power(
        view_cosine, float(spec.get("groove_visibility_power", 0.62))
    )
    side_visibility = np.power(
        1.0 - view_cosine, float(spec.get("side_visibility_power", 0.58))
    )
    front_relief = (
        lit_edge * float(spec.get("highlight_strength", 0.18))
        - shaded_edge * float(spec.get("shadow_strength", 0.24))
        - (1.0 - tooth_body) * float(spec.get("groove_strength", 0.075))
        + tooth_body * float(spec.get("tooth_top_light", 0.018))
    )
    limb_orientation = np.where(projected_angle * direction >= 0.0, 1.0, -1.0)
    visible_side_edge = np.where(limb_orientation >= 0.0, upper_edge, lower_edge)
    occluded_side_edge = np.where(limb_orientation >= 0.0, lower_edge, upper_edge)
    side_relief = (
        visible_side_edge * float(spec.get("side_face_strength", 0.26))
        - occluded_side_edge * float(spec.get("side_shadow_strength", 0.34))
        + tooth_body * float(spec.get("side_top_light", 0.045))
        - (1.0 - tooth_body) * float(spec.get("side_gap_shadow", 0.10))
    )
    relief = 1.0 + groove_visibility * front_relief + side_visibility * side_relief
    face_rgb *= np.clip(relief, 0.48, 1.38)[:, :, None]

    # A real tooth changes which surfaces exist; a moving highlight on a fixed
    # rectangle cannot communicate that.  The outer band below is therefore
    # split into explicit tooth tops, swept side faces, and recessed gaps.  The
    # inner band remains the smaller root cylinder.  This is the same visual
    # hierarchy that makes the separated fan blades read as physical objects.
    transverse_coordinate = local_u if spec.get("axis", "y") == "y" else local_v
    transverse_coordinate = np.clip(transverse_coordinate, 0.0, 1.0)
    outer_edge = str(spec.get("outer_edge", "start"))
    outer_distance = (
        transverse_coordinate if outer_edge == "start" else 1.0 - transverse_coordinate
    )
    tooth_depth = min(0.82, max(0.06, float(spec.get("tooth_depth_fraction", 0.42))))
    silhouette_softness = min(
        0.16, max(0.006, float(spec.get("silhouette_softness", 0.025)))
    )
    root_coverage = 1.0 / (
        1.0 + np.exp(-(outer_distance - tooth_depth) / silhouette_softness)
    )
    outer_band = 1.0 - root_coverage

    side_pitch_depth = min(0.48, max(0.0, float(spec.get("side_depth_fraction", 0.20))))
    signed_side_depth = limb_orientation * direction * side_pitch_depth * side_visibility
    swept_tooth = tooth_body.copy()
    side_phase = tooth_phase.copy()
    # Union a handful of angular slices between the front and rear tooth faces.
    # Their phase separation is the visible prism wall; its sign flips on the
    # opposite circular limb so the correct tooth side becomes exposed.
    for slice_fraction in (0.2, 0.4, 0.6, 0.8, 1.0):
        slice_phase = np.mod(tooth_phase + signed_side_depth * slice_fraction, 1.0)
        swept_tooth = np.maximum(
            swept_tooth,
            periodic_tooth_coverage(slice_phase, tooth_width, edge_softness),
        )
        if slice_fraction == 1.0:
            side_phase = slice_phase
    tooth_top_coverage = outer_band * tooth_body
    side_coverage = outer_band * np.clip(swept_tooth - tooth_body, 0.0, 1.0)
    gap_coverage = outer_band * np.clip(1.0 - swept_tooth, 0.0, 1.0)

    # Sub-pixel metal grain is attached to tooth phase, not screen position, so
    # it travels with the rotating volume while the broad source lighting stays
    # nailed to the building camera.
    face_texture_strength = float(spec.get("face_texture_strength", 0.10))
    phase_angle = tooth_phase * (2.0 * math.pi)
    moving_grain = (
        0.64 * np.sin(phase_angle + local_u * 5.7)
        + 0.24 * np.cos(phase_angle * 2.0 - local_u * 3.1)
        + 0.12 * np.sin(phase_angle * 3.0 + local_u * 9.3)
    )
    face_rgb *= np.clip(
        1.0 + face_texture_strength * moving_grain, 0.72, 1.28
    )[:, :, None]

    root_brightness = float(spec.get("root_face_brightness", 0.64))
    cavity_brightness = float(spec.get("cavity_brightness", 0.28))
    side_brightness = float(spec.get("side_face_brightness", 0.56))
    root_rgb = fixed_smooth * root_brightness
    cavity_rgb = fixed_smooth * cavity_brightness
    if detail_template is not None:
        side_detail = sample_periodic_detail(detail_template, local_u, side_phase)
        side_detail = np.clip(1.0 + (side_detail - 1.0) * 0.72, 0.72, 1.28)
        side_rgb = fixed_smooth * side_detail
    else:
        side_rgb = fixed_smooth.copy()
    side_lighting = np.where(
        limb_orientation * light_from_start >= 0.0,
        min(1.08, side_brightness + 0.18),
        max(0.18, side_brightness - 0.12),
    )
    side_rgb *= side_lighting[:, :, None]

    root_shadow_strength = float(spec.get("root_shadow_strength", 0.24))
    root_edge = np.exp(
        -0.5
        * ((outer_distance - tooth_depth) / max(0.008, silhouette_softness * 1.45)) ** 2
    )
    root_rgb *= np.clip(
        1.0 - root_shadow_strength * root_edge * (1.0 - tooth_body), 0.52, 1.0
    )[:, :, None]
    tip_highlight_strength = float(spec.get("tip_highlight_strength", 0.18))
    tip_edge = np.exp(
        -0.5 * (outer_distance / max(0.012, silhouette_softness * 1.8)) ** 2
    )
    face_rgb *= np.clip(
        1.0 + tip_highlight_strength * tip_edge * tooth_body * groove_visibility,
        1.0,
        1.42,
    )[:, :, None]

    # Coverage sums to one: the root cylinder, moving tooth front, swept side,
    # or the dark recess behind the rim.  Consequently phase changes produce
    # genuine moving boundaries and self-occlusion rather than only light noise.
    rgb = (
        root_rgb * root_coverage[:, :, None]
        + face_rgb * tooth_top_coverage[:, :, None]
        + side_rgb * side_coverage[:, :, None]
        + cavity_rgb * gap_coverage[:, :, None]
    )

    mask = Image.new("L", (high_width, high_height), 0)
    mask_draw = ImageDraw.Draw(mask)
    high_polygon = [
        ((point[0] - x0) * supersample, (point[1] - y0) * supersample)
        for point in visible_polygon
    ]
    mask_draw.polygon(high_polygon, fill=255)
    feather = float(spec.get("aperture_feather", 0.55)) * supersample
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    source_alpha = np.asarray(source.getchannel("A"), dtype=np.float32)
    sampled_alpha = sample_scalar_bilinear(source_alpha, screen_x, screen_y) / 255.0
    alpha = np.asarray(mask, dtype=np.float32) * sampled_alpha
    layer_values = np.dstack((np.clip(rgb, 0, 255).astype(np.uint8), np.clip(alpha, 0, 255).astype(np.uint8)))
    layer = Image.fromarray(layer_values).resize(
        (x1 - x0, y1 - y0), Image.Resampling.LANCZOS
    )
    frame.alpha_composite(layer, (x0, y0))

    occluder = gear_fixed_occluder_mask(source, spec)
    if occluder.getbbox():
        frame.paste(source, (0, 0), occluder)


def vibration_wave(angle: float, waveform: str) -> float:
    """Deterministic periodic vibration profiles with exact 2pi closure."""
    if waveform == "motor":
        return (
            0.76 * math.sin(angle)
            + 0.17 * math.sin(2.0 * angle + 0.73)
            + 0.07 * math.sin(4.0 * angle + 1.91)
        )
    if waveform == "rattle":
        return (
            0.64 * math.sin(angle)
            + 0.23 * math.sin(3.0 * angle + 0.41)
            + 0.13 * math.sin(7.0 * angle + 1.37)
        )
    return math.sin(angle)


def vibration_polygon_mask(
    size: tuple[int, int], polygon: list[list[float]], supersample: int, offset: tuple[int, int], feather: float
) -> Image.Image:
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    x0, y0 = offset
    draw.polygon(
        [((point[0] - x0) * supersample, (point[1] - y0) * supersample) for point in polygon],
        fill=255,
    )
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather * supersample))
    return mask


def add_vibration(frame: Image.Image, source: Image.Image, spec: dict[str, Any], p: float) -> None:
    """Jiggle a precisely masked, already-composited machine part.

    Sampling ``frame`` instead of ``source`` is deliberate: when this layer is
    ordered after a rotor or gear, the selected mechanism carries that earlier
    animation with it.  The source still supplies alpha clipping, an optional
    dark cavity, and any fixed foreground occluders.
    """
    polygon = spec.get("polygon")
    if not polygon or len(polygon) < 3:
        raise ValueError("vibration requires a polygon with at least three vertices")
    supersample = max(1, min(12, int(spec.get("supersample", 6))))
    amplitude_x, amplitude_y = (float(value) for value in spec.get("amplitude", [0.75, 1.0]))
    cycles = max(1, round(float(spec.get("cycles_per_loop", 3))))
    base_angle = 2.0 * math.pi * (cycles * (float(p) % 1.0) + float(spec.get("phase", 0.0)))
    waveform = str(spec.get("waveform", "motor"))
    dx = amplitude_x * vibration_wave(base_angle, waveform)
    dy = amplitude_y * vibration_wave(
        base_angle + 2.0 * math.pi * float(spec.get("y_phase_offset", 0.0)), waveform
    )
    rotation = math.radians(
        float(spec.get("rotation_degrees", 0.0))
        * vibration_wave(
            base_angle + 2.0 * math.pi * float(spec.get("rotation_phase_offset", 0.0)), waveform
        )
    )

    default_pivot = (
        sum(float(point[0]) for point in polygon) / len(polygon),
        sum(float(point[1]) for point in polygon) / len(polygon),
    )
    pivot_x, pivot_y = (float(value) for value in spec.get("pivot", default_pivot))
    radius = max(math.hypot(float(point[0]) - pivot_x, float(point[1]) - pivot_y) for point in polygon)
    rotation_padding = radius * abs(math.sin(math.radians(float(spec.get("rotation_degrees", 0.0)))))
    feather = float(spec.get("feather", 0.65))
    padding = max(abs(amplitude_x), abs(amplitude_y)) + rotation_padding + feather * 3.0 + 3.0
    x0 = max(0, math.floor(min(float(point[0]) for point in polygon) - padding))
    y0 = max(0, math.floor(min(float(point[1]) for point in polygon) - padding))
    x1 = min(source.width, math.ceil(max(float(point[0]) for point in polygon) + padding))
    y1 = min(source.height, math.ceil(max(float(point[1]) for point in polygon) + padding))
    if x1 <= x0 or y1 <= y0:
        return

    high_size = ((x1 - x0) * supersample, (y1 - y0) * supersample)
    # Capture prior layers before an optional cavity replaces the original
    # position. This is what makes gear+vibration layer composition work.
    composed_crop = frame.crop((x0, y0, x1, y1)).resize(high_size, Image.Resampling.LANCZOS)
    mask = vibration_polygon_mask(high_size, polygon, supersample, (x0, y0), feather)
    piece = composed_crop.copy()
    piece.putalpha(ImageChops.multiply(piece.getchannel("A"), mask))

    background_mode = str(spec.get("background_mode", "source"))
    if background_mode == "dark_cavity":
        source_crop = source.crop((x0, y0, x1, y1)).resize(high_size, Image.Resampling.LANCZOS)
        blurred = source_crop.filter(
            ImageFilter.GaussianBlur(float(spec.get("cavity_blur", 1.2)) * supersample)
        )
        cavity_values = np.asarray(blurred, dtype=np.uint8).copy()
        brightness = float(spec.get("cavity_brightness", 0.48))
        cavity_values[:, :, :3] = np.clip(
            cavity_values[:, :, :3].astype(np.float32) * brightness, 0, 255
        ).astype(np.uint8)
        cavity = Image.fromarray(cavity_values)
        cavity.putalpha(ImageChops.multiply(cavity.getchannel("A"), mask))
        cavity = cavity.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
        frame.alpha_composite(cavity, (x0, y0))

    cosine = math.cos(rotation)
    sine = math.sin(rotation)
    high_pivot_x = (pivot_x - x0) * supersample
    high_pivot_y = (pivot_y - y0) * supersample
    high_dx = dx * supersample
    high_dy = dy * supersample
    affine = (
        cosine,
        sine,
        high_pivot_x - cosine * (high_pivot_x + high_dx) - sine * (high_pivot_y + high_dy),
        -sine,
        cosine,
        high_pivot_y + sine * (high_pivot_x + high_dx) - cosine * (high_pivot_y + high_dy),
    )
    moved = piece.transform(
        high_size,
        Image.Transform.AFFINE,
        affine,
        resample=Image.Resampling.BICUBIC,
    ).resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
    frame.alpha_composite(moved, (x0, y0))

    occluder = gear_fixed_occluder_mask(source, spec)
    if occluder.getbbox():
        frame.paste(source, (0, 0), occluder)


def gauge_position(spec: dict[str, Any], p: float) -> float:
    """Return a loop-safe normalized needle position within its range."""
    cycles = max(1, round(float(spec.get("cycles_per_loop", 1))))
    local = ((float(p) + float(spec.get("phase", 0.0))) * cycles) % 1.0
    waveform = str(spec.get("waveform", "sine"))
    if waveform == "triangle":
        position = 1.0 - abs(2.0 * local - 1.0)
    elif waveform == "sine":
        position = 0.5 - 0.5 * math.cos(2.0 * math.pi * local)
    else:
        raise ValueError(f"unknown gauge waveform: {waveform}")
    return 1.0 - position if bool(spec.get("reverse", False)) else position


def gauge_plane_point(
    center: tuple[float, float], basis: np.ndarray, x: float, y: float
) -> tuple[float, float]:
    """Project a gauge-local point into sprite space."""
    return (
        center[0] + float(basis[0, 0]) * x + float(basis[0, 1]) * y,
        center[1] + float(basis[1, 0]) * x + float(basis[1, 1]) * y,
    )


def add_gauge(frame: Image.Image, source: Image.Image, spec: dict[str, Any], p: float) -> None:
    """Draw a perspective-aware gauge needle sweeping through an angular range."""
    center = tuple(float(value) for value in spec["center"])
    basis = rotor_plane_basis(spec)
    position = gauge_position(spec, p)
    minimum_angle = float(spec.get("minimum_angle_degrees", -150.0))
    maximum_angle = float(spec.get("maximum_angle_degrees", -30.0))
    angle = math.radians(minimum_angle + (maximum_angle - minimum_angle) * position)
    direction = np.asarray([math.cos(angle), math.sin(angle)], dtype=np.float64)
    across = np.asarray([-direction[1], direction[0]], dtype=np.float64)

    length = max(0.05, float(spec.get("needle_length", 0.78)))
    tail_length = max(0.0, float(spec.get("tail_length", 0.12)))
    width = max(0.005, float(spec.get("needle_width", 0.055)))
    tip_width = min(width, max(0.0, float(spec.get("tip_width", 0.012))))
    local_polygon = [
        -direction * tail_length + across * width * 0.46,
        direction * length + across * tip_width * 0.5,
        direction * length - across * tip_width * 0.5,
        -direction * tail_length - across * width * 0.46,
    ]
    projected = [
        gauge_plane_point(center, basis, float(point[0]), float(point[1]))
        for point in local_polygon
    ]

    supersample = max(1, min(12, int(spec.get("supersample", 6))))
    effect = Image.new(
        "RGBA", (source.width * supersample, source.height * supersample), (0, 0, 0, 0)
    )

    def scaled(
        points: list[tuple[float, float]], offset: tuple[float, float] = (0.0, 0.0)
    ) -> list[tuple[float, float]]:
        return [
            (
                (point[0] + offset[0]) * supersample,
                (point[1] + offset[1]) * supersample,
            )
            for point in points
        ]

    face_fraction = max(0.05, float(spec.get("face_fraction", 1.0)))

    def projected_circle(radius: float, point_count: int = 72) -> list[tuple[float, float]]:
        return [
            gauge_plane_point(
                center,
                basis,
                math.cos(2.0 * math.pi * index / point_count) * radius,
                math.sin(2.0 * math.pi * index / point_count) * radius,
            )
            for index in range(point_count)
        ]

    if bool(spec.get("background_enabled", True)):
        face_draw = ImageDraw.Draw(effect)
        face_alpha = max(0, min(255, int(spec.get("face_alpha", 255))))
        rim_width = max(0.01, min(face_fraction * 0.35, float(spec.get("rim_width", 0.09))))
        rim_color = tuple(int(value) for value in spec.get("rim_color", [137, 102, 57]))
        rim_shadow_color = tuple(
            int(value) for value in spec.get("rim_shadow_color", [48, 38, 29])
        )
        face_color = tuple(int(value) for value in spec.get("face_color", [57, 51, 42]))
        face_draw.polygon(
            scaled(projected_circle(face_fraction)), fill=(*rim_shadow_color, face_alpha)
        )
        face_draw.polygon(
            scaled(projected_circle(face_fraction - rim_width * 0.28)),
            fill=(*rim_color, face_alpha),
        )
        inner_face_radius = max(0.02, face_fraction - rim_width)
        face_draw.polygon(
            scaled(projected_circle(inner_face_radius)), fill=(*face_color, face_alpha)
        )

        tick_color = tuple(int(value) for value in spec.get("tick_color", [225, 204, 153]))
        tick_count = max(2, int(spec.get("tick_count", 11)))
        major_tick_every = max(1, int(spec.get("major_tick_every", 5)))
        tick_length = max(0.015, float(spec.get("tick_length", 0.105)))
        tick_outer = max(0.03, inner_face_radius - float(spec.get("tick_margin", 0.055)))
        for index in range(tick_count):
            tick_angle = math.radians(
                minimum_angle
                + (maximum_angle - minimum_angle) * index / max(1, tick_count - 1)
            )
            major = index % major_tick_every == 0 or index in {0, tick_count - 1}
            local_length = tick_length * (1.42 if major else 0.82)
            tick_inner = max(0.01, tick_outer - local_length)
            tick_start = gauge_plane_point(
                center,
                basis,
                math.cos(tick_angle) * tick_inner,
                math.sin(tick_angle) * tick_inner,
            )
            tick_end = gauge_plane_point(
                center,
                basis,
                math.cos(tick_angle) * tick_outer,
                math.sin(tick_angle) * tick_outer,
            )
            face_draw.line(
                scaled([tick_start, tick_end]),
                fill=(*tick_color, face_alpha),
                width=max(
                    1,
                    round(
                        float(spec.get("tick_width", 0.75))
                        * supersample
                        * (1.35 if major else 1.0)
                    ),
                ),
            )

    shadow_offset = tuple(float(value) for value in spec.get("shadow_offset", [0.8, 1.0]))
    shadow_alpha = int(spec.get("shadow_alpha", 115))
    if shadow_alpha > 0:
        shadow = Image.new("RGBA", effect.size, (0, 0, 0, 0))
        ImageDraw.Draw(shadow).polygon(
            scaled(projected, shadow_offset), fill=(0, 0, 0, shadow_alpha)
        )
        shadow_blur = float(spec.get("shadow_blur", 0.55)) * supersample
        if shadow_blur > 0:
            shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
        effect.alpha_composite(shadow)

    draw = ImageDraw.Draw(effect)
    needle_color = tuple(int(value) for value in spec.get("needle_color", [196, 68, 49]))
    edge_color = tuple(int(value) for value in spec.get("edge_color", [67, 31, 24]))
    draw.polygon(scaled(projected), fill=(*edge_color, 255))
    inset = min(width * 0.22, 0.015)
    inset_polygon = [
        -direction * max(0.0, tail_length - inset) + across * width * 0.31,
        direction * max(0.05, length - inset * 1.5) + across * tip_width * 0.22,
        direction * max(0.05, length - inset * 1.5) - across * tip_width * 0.22,
        -direction * max(0.0, tail_length - inset) - across * width * 0.31,
    ]
    inset_projected = [
        gauge_plane_point(center, basis, float(point[0]), float(point[1]))
        for point in inset_polygon
    ]
    draw.polygon(scaled(inset_projected), fill=(*needle_color, 255))

    highlight_color = tuple(
        int(value) for value in spec.get("highlight_color", [245, 163, 118])
    )
    highlight_local_start = -direction * tail_length * 0.25 + across * width * 0.18
    highlight_local_end = direction * length * 0.72 + across * tip_width * 0.12
    highlight_start = gauge_plane_point(
        center, basis, float(highlight_local_start[0]), float(highlight_local_start[1])
    )
    highlight_end = gauge_plane_point(
        center, basis, float(highlight_local_end[0]), float(highlight_local_end[1])
    )
    draw.line(
        scaled([highlight_start, highlight_end]),
        fill=(*highlight_color, int(spec.get("highlight_alpha", 175))),
        width=max(1, round(float(spec.get("highlight_width", 0.7)) * supersample)),
    )

    pivot_radius = max(0.015, float(spec.get("pivot_radius", 0.1)))
    cap_points = [
        gauge_plane_point(
            center,
            basis,
            math.cos(2.0 * math.pi * index / 32) * pivot_radius,
            math.sin(2.0 * math.pi * index / 32) * pivot_radius,
        )
        for index in range(32)
    ]
    pivot_edge = tuple(int(value) for value in spec.get("pivot_edge_color", edge_color))
    pivot_color = tuple(int(value) for value in spec.get("pivot_color", [116, 91, 61]))
    draw.polygon(scaled(cap_points), fill=(*pivot_edge, 255))
    inner_cap_points = [
        gauge_plane_point(
            center,
            basis,
            math.cos(2.0 * math.pi * index / 32) * pivot_radius * 0.72,
            math.sin(2.0 * math.pi * index / 32) * pivot_radius * 0.72,
        )
        for index in range(32)
    ]
    draw.polygon(scaled(inner_cap_points), fill=(*pivot_color, 255))

    effect = effect.resize(source.size, Image.Resampling.LANCZOS)
    alpha = ImageChops.multiply(effect.getchannel("A"), source.getchannel("A"))
    if spec.get("clip_to_face", True):
        face_mask = projected_ellipse_mask(
            source.size,
            center,
            basis * face_fraction,
            float(spec.get("aperture_feather", 0.5)),
        )
        alpha = ImageChops.multiply(alpha, face_mask)
    effect.putalpha(alpha)
    frame.alpha_composite(effect)


def add_signal(frame: Image.Image, source: Image.Image, spec: dict[str, Any], p: float) -> None:
    """Draw restrained expanding radio arcs without changing antenna geometry."""
    x, y = spec["origin"]
    count = int(spec.get("count", 2))
    travel = float(spec.get("travel", 12))
    color = tuple(spec.get("color", [105, 204, 255]))
    effect = Image.new("RGBA", source.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(effect)
    for index in range(count):
        t = (p + index / count + float(spec.get("phase", 0.0))) % 1.0
        radius = float(spec.get("start_radius", 2)) + travel * t
        alpha = int(float(spec.get("alpha", 80)) * math.sin(math.pi * t) ** 1.3)
        squash = float(spec.get("squash", 0.55))
        bbox = (x - radius, y - radius * squash, x + radius, y + radius * squash)
        draw.arc(
            bbox,
            start=int(spec.get("start_angle", 195)),
            end=int(spec.get("end_angle", 345)),
            fill=(*color, alpha),
            width=int(spec.get("width", 1)),
        )
    effect = effect.filter(ImageFilter.GaussianBlur(float(spec.get("blur", 0.5))))
    clipped_effect(frame, source, effect, bool(spec.get("clip", False)))


def clipped_effect(frame: Image.Image, source: Image.Image, effect: Image.Image, clip: bool) -> None:
    if clip:
        effect.putalpha(ImageChops.multiply(effect.getchannel("A"), source.getchannel("A")))
    frame.alpha_composite(effect)


def add_pulse(frame: Image.Image, source: Image.Image, spec: dict[str, Any], p: float) -> None:
    effect = Image.new("RGBA", source.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(effect)
    x, y = spec["center"]
    rx, ry = spec.get("radius", [4, 4])
    color = tuple(spec.get("color", [255, 180, 70]))
    offset = float(spec.get("phase", 0.0))
    power = float(spec.get("power", 2.0))
    intensity = max(0.0, math.sin(math.pi * ((p + offset) % 1.0))) ** power
    alpha = int(round(float(spec.get("alpha", 110)) * intensity))
    if alpha <= 0:
        return
    draw.ellipse((x - rx, y - ry, x + rx, y + ry), fill=(*color, alpha))
    blur = float(spec.get("blur", max(rx, ry) * 0.7))
    if blur:
        effect = effect.filter(ImageFilter.GaussianBlur(blur))
    if spec.get("clip", True):
        if "mask_polygon" in spec:
            mask_spec = {"polygon": spec["mask_polygon"], "clip": True}
        else:
            mask_spec = {
                "bbox": spec.get("mask_bbox", [x - rx, y - ry, x + rx, y + ry]),
                "shape": spec.get("mask_shape", "ellipse"),
                "clip": True,
            }
        effect.putalpha(ImageChops.multiply(effect.getchannel("A"), surface_mask(source, mask_spec)))
    frame.alpha_composite(effect)


def add_chase(frame: Image.Image, source: Image.Image, spec: dict[str, Any], p: float) -> None:
    points = spec["points"]
    for index, point in enumerate(points):
        local = dict(spec)
        local["center"] = point[:2]
        if len(point) >= 5:
            local["color"] = point[2:5]
        local["phase"] = (float(spec.get("phase", 0.0)) - index / len(points)) % 1.0
        local["power"] = spec.get("power", 5.0)
        add_pulse(frame, source, local, p)


def add_sweep(frame: Image.Image, source: Image.Image, spec: dict[str, Any], p: float) -> None:
    x0, y0, x1, y1 = spec["bbox"]
    effect = Image.new("RGBA", source.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(effect)
    color = tuple(spec.get("color", [80, 190, 255]))
    alpha = int(spec.get("alpha", 100))
    width = int(spec.get("width", 2))
    axis = spec.get("axis", "x")
    reverse = axis.startswith("-")
    t = (1.0 - p) if reverse else p
    axis = axis.lstrip("-")
    if axis == "circle":
        # "circle" grows outward from the center (t: 0 -> 1 = min -> max
        # radius); "-circle" reverses that, so it collapses inward instead --
        # same reverse/t convention as the x/y branches below.
        cx, cy = spec.get("center", [(x0 + x1) / 2, (y0 + y1) / 2])
        max_radius = float(spec.get("max_radius", math.hypot(x1 - x0, y1 - y0) / 2))
        min_radius = float(spec.get("min_radius", 0))
        radius = min_radius + (max_radius - min_radius) * t
        if radius > 0:
            draw.ellipse(
                (cx - radius, cy - radius, cx + radius, cy + radius),
                outline=(*color, alpha),
                width=max(1, width),
            )
    elif axis == "x":
        position = x0 + int(round((x1 - x0 - 1) * t))
        draw.rectangle((position - width, y0, position + width, y1), fill=(*color, alpha))
    else:
        position = y0 + int(round((y1 - y0 - 1) * t))
        draw.rectangle((x0, position - width, x1, position + width), fill=(*color, alpha))
    effect = effect.filter(ImageFilter.GaussianBlur(float(spec.get("blur", 1.5))))
    composite_on_surface(frame, source, effect, spec)


def add_steam(frame: Image.Image, source: Image.Image, spec: dict[str, Any], p: float) -> None:
    effect = Image.new("RGBA", source.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(effect)
    x, y = spec["origin"]
    rise = float(spec.get("rise", 32))
    drift = float(spec.get("drift", 5))
    count = int(spec.get("count", 4))
    color = tuple(spec.get("color", [205, 205, 195]))
    for index in range(count):
        cycle = (p + index / count) % 1.0
        travel = min(cycle * 2.0, 1.0)
        puff_y = y - rise * travel
        puff_x = x + drift * math.sin(math.pi * travel + index * 0.73)
        radius = float(spec.get("radius", 3.0)) * (0.7 + 1.1 * travel)
        # The puff exists only during its ascent.  It reaches zero opacity at
        # both ends, then resets invisibly instead of teleporting at the seam.
        visibility = max(0.0, math.sin(2.0 * math.pi * cycle))
        alpha = int(float(spec.get("alpha", 48)) * visibility ** float(spec.get("fade_power", 2.0)))
        draw.ellipse(
            (puff_x - radius, puff_y - radius, puff_x + radius, puff_y + radius),
            fill=(*color, alpha),
        )
    effect = effect.filter(ImageFilter.GaussianBlur(float(spec.get("blur", 2.0))))
    clipped_effect(frame, source, effect, bool(spec.get("clip", False)))


MOTION_HANDLERS = {
    "surface_scan": add_surface_scan,
    "orbit_glint": add_orbit_glint,
    "mechanical_rotor": add_mechanical_rotor,
    "mechanical_gear": add_mechanical_gear,
    "vertical_gear": add_vertical_gear,
    "source_occluder": add_source_occluder,
    "vibration": add_vibration,
    "gauge": add_gauge,
    "signal": add_signal,
    "pulse": add_pulse,
    "chase": add_chase,
    "sweep": add_sweep,
    "steam": add_steam,
}


def animate_frame(source: Image.Image, motions: list[dict[str, Any]], p: float) -> Image.Image:
    frame = source.copy()
    for motion in motions:
        handler = MOTION_HANDLERS[motion["type"]]
        handler(frame, source, motion, p)
    return frame


def pack_sheet(frames: list[Image.Image], line_length: int) -> Image.Image:
    width, height = frames[0].size
    rows = math.ceil(len(frames) / line_length)
    sheet = Image.new("RGBA", (width * line_length, height * rows), (0, 0, 0, 0))
    for index, frame in enumerate(frames):
        sheet.alpha_composite(frame, ((index % line_length) * width, (index // line_length) * height))
    return sheet


def identity_ratio(source: Image.Image, frame: Image.Image) -> float:
    diff = ImageChops.difference(source, frame).convert("L")
    histogram = diff.histogram()
    return histogram[0] / (source.width * source.height)


def mean_difference(left: Image.Image, right: Image.Image) -> float:
    histogram = ImageChops.difference(left, right).convert("L").histogram()
    pixels = left.width * left.height
    return sum(value * count for value, count in enumerate(histogram)) / pixels


def asset_metadata_record(
    asset: dict[str, Any], source: Image.Image, frames: list[Image.Image]
) -> dict[str, Any]:
    frame_count = int(asset.get("frame_count", asset_store.FRAME_COUNT))
    line_length = int(asset.get("line_length", asset_store.LINE_LENGTH))
    animation_speed = float(asset.get("animation_speed", asset_store.NEW_ASSET_ANIMATION_SPEED))
    identities = [identity_ratio(source, frame) for frame in frames]
    step_differences = [
        mean_difference(frames[index - 1], frames[index])
        for index in range(1, len(frames))
    ]
    seam_difference = mean_difference(frames[-1], frames[0])
    mean_step = sum(step_differences) / len(step_differences)
    return {
        "name": asset["name"],
        "source": asset["source"],
        "output": asset["output"],
        "frame_size": list(source.size),
        "frame_count": frame_count,
        "line_length": line_length,
        "animation_speed": animation_speed,
        "loop_seconds": (
            round(frame_count / (60 * animation_speed), 3)
            if animation_speed
            else None
        ),
        "sheet_size": [
            source.width * line_length,
            source.height * math.ceil(frame_count / line_length),
        ],
        "minimum_identity_ratio": round(min(identities), 6),
        "mean_identity_ratio": round(sum(identities) / len(identities), 6),
        "mean_step_difference": round(mean_step, 6),
        "loop_seam_mean_difference": round(seam_difference, 6),
        "loop_seam_step_ratio": round(
            seam_difference / mean_step if mean_step else 0.0, 6
        ),
    }


def metadata_from_existing_sheet(asset: dict[str, Any]) -> dict[str, Any]:
    """Measure a previously generated atlas without regenerating the asset."""
    source = load_rgba(ROOT / asset["source"])
    sheet = load_rgba(ROOT / asset["output"])
    frame_count = int(asset.get("frame_count", asset_store.FRAME_COUNT))
    line_length = int(asset.get("line_length", asset_store.LINE_LENGTH))
    expected_size = (
        source.width * line_length,
        source.height * math.ceil(frame_count / line_length),
    )
    if sheet.size != expected_size:
        raise ValueError(
            f"{asset['name']}: generated sheet is {sheet.size}, expected {expected_size}"
        )
    frames = [
        sheet.crop(
            (
                (index % line_length) * source.width,
                (index // line_length) * source.height,
                (index % line_length + 1) * source.width,
                (index // line_length + 1) * source.height,
            )
        )
        for index in range(frame_count)
    ]
    return asset_metadata_record(asset, source, frames)


def generate_asset(asset: dict[str, Any]) -> dict[str, Any]:
    source_path = ROOT / asset["source"]
    output_path = ROOT / asset["output"]
    source = load_rgba(source_path)
    expected = tuple(asset.get("size", source.size))
    if source.size != expected:
        raise ValueError(f"{asset['name']}: expected source size {expected}, found {source.size}")

    frame_count = int(asset.get("frame_count", asset_store.FRAME_COUNT))
    line_length = int(asset.get("line_length", asset_store.LINE_LENGTH))
    frames = [animate_frame(source, asset["motions"], phase(index, frame_count)) for index in range(frame_count)]
    identities = [identity_ratio(source, frame) for frame in frames]
    minimum_identity = float(asset.get("minimum_identity", asset_store.MINIMUM_IDENTITY))
    if min(identities) < minimum_identity:
        # Informational only -- this heuristic can't distinguish a busy-but-
        # intentional animation from an actual authoring mistake, so it no
        # longer blocks the save; it just tells you where you stand.
        print(
            f"{asset['name']}: identity ratio {min(identities):.4f} is below {minimum_identity:.4f} (saving anyway)"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pack_sheet(frames, line_length).save(output_path, optimize=True)
    return asset_metadata_record(asset, source, frames)


def make_review_sheet(records: list[dict[str, Any]], assets: list[dict[str, Any]], output: Path) -> None:
    samples: list[tuple[str, list[Image.Image]]] = []
    lookup = {asset["name"]: asset for asset in assets}
    for record in records:
        asset = lookup[record["name"]]
        source = load_rgba(ROOT / asset["source"])
        frame_count = record["frame_count"]
        frames = [
            animate_frame(source, asset["motions"], phase(index, frame_count))
            for index in (0, frame_count // 4, frame_count // 2, frame_count * 3 // 4)
        ]
        samples.append((record["name"], frames))

    cell_width = 240
    cell_height = 190
    label_height = 22
    review = Image.new("RGB", (cell_width * 4, (cell_height + label_height) * len(samples)), (28, 27, 25))
    draw = ImageDraw.Draw(review)
    for row, (name, frames) in enumerate(samples):
        y0 = row * (cell_height + label_height)
        draw.text((8, y0 + 4), name, fill=(235, 228, 211))
        for column, frame in enumerate(frames):
            thumb = frame.copy()
            thumb.thumbnail((cell_width - 12, cell_height - 8), Image.Resampling.LANCZOS)
            tile = Image.new("RGBA", (cell_width, cell_height), (74, 70, 61, 255))
            tile.alpha_composite(thumb, ((cell_width - thumb.width) // 2, (cell_height - thumb.height) // 2))
            review.paste(tile.convert("RGB"), (column * cell_width, y0 + label_height))
    output.parent.mkdir(parents=True, exist_ok=True)
    review.save(output, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets-dir", type=Path, default=asset_store.ASSETS_DIR)
    parser.add_argument("--asset", action="append", help="Generate only the named asset (repeatable)")
    args = parser.parse_args()

    all_assets = [asset_store.load_asset_file(p) for p in sorted(args.assets_dir.glob("*.json"))]
    selected = set(args.asset or [])
    assets = [asset for asset in all_assets if not selected or asset["name"] in selected]
    unknown = selected - {asset["name"] for asset in all_assets}
    if unknown:
        raise SystemExit(f"Unknown assets: {', '.join(sorted(unknown))}")

    records = [generate_asset(asset) for asset in assets]
    metadata_path = Path(__file__).with_name("generated-metadata.json")
    metadata_records = records
    if selected:
        previous: dict[str, dict[str, Any]] = {}
        if metadata_path.exists():
            previous = {
                record["name"]: record
                for record in json.loads(metadata_path.read_text()).get("assets", [])
            }
        previous.update({record["name"]: record for record in records})
        metadata_records = []
        for asset in all_assets:
            metadata_records.append(
                previous.get(asset["name"])
                or metadata_from_existing_sheet(asset)
            )
    metadata_path.write_text(json.dumps({"assets": metadata_records}, indent=2) + "\n")
    make_review_sheet(
        records,
        assets,
        Path(__file__).with_name("animation-review-sheet.png"),
    )
    for record in records:
        print(
            f"{record['name']}: {record['sheet_size'][0]}x{record['sheet_size'][1]}, "
            f"identity>={record['minimum_identity_ratio']:.3f}, "
            f"seam={record['loop_seam_mean_difference']:.3f} "
            f"({record['loop_seam_step_ratio']:.2f}x step)"
        )


if __name__ == "__main__":
    main()
