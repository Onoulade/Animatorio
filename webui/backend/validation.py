from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .errors import ApiError

ASSET_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def require_object(value: Any, label: str = "request body") -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ApiError(f"{label} must be a JSON object", code="invalid_json")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ApiError(f"{label} must be a list", code="invalid_field")
    return value


def require_number(value: Any, label: str, *, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(f"{label} must be a number", code="invalid_field")
    number = float(value)
    if minimum is not None and number < minimum:
        raise ApiError(f"{label} must be at least {minimum:g}", code="invalid_field")
    return number


def require_asset_name(value: Any) -> str:
    if not isinstance(value, str) or not ASSET_NAME_PATTERN.fullmatch(value):
        raise ApiError(
            "Asset name must be 1–80 letters, numbers, dots, dashes, or underscores",
            code="invalid_asset_name",
        )
    return value


def validate_asset(asset: Any) -> dict[str, Any]:
    obj = dict(require_object(asset, "asset"))
    require_asset_name(obj.get("name"))
    for field in ("source", "output"):
        if not isinstance(obj.get(field), str) or not obj[field].strip():
            raise ApiError(f"asset.{field} must be a non-empty string", code="invalid_asset")
    size = require_list(obj.get("size"), "asset.size")
    if len(size) != 2 or any(isinstance(v, bool) or not isinstance(v, int) or v <= 0 for v in size):
        raise ApiError("asset.size must contain two positive integers", code="invalid_asset")
    motions = require_list(obj.get("motions"), "asset.motions")
    for index, motion in enumerate(motions):
        if not isinstance(motion, Mapping) or not isinstance(motion.get("type"), str):
            raise ApiError(f"asset.motions[{index}] must have a motion type", code="invalid_asset")
    speed = obj.get("animation_speed", 0.25)
    require_number(speed, "asset.animation_speed", minimum=0.01)
    return obj


def validate_motions(value: Any) -> list[dict[str, Any]]:
    motions = require_list(value, "motions")
    for index, motion in enumerate(motions):
        if not isinstance(motion, Mapping) or not isinstance(motion.get("type"), str):
            raise ApiError(f"motions[{index}] must have a motion type", code="invalid_motion")
    return [dict(motion) for motion in motions]
