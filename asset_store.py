#!/usr/bin/env python3
"""Per-asset animation file storage.

Each asset is one self-contained JSON file under ASSETS_DIR
(animations/<name>.json): name, source image, output sheet path,
motions and animation_speed live in that single
file. There is no shared manifest and no asset list to browse -- every
script that needs "all assets" gets there by scanning ASSETS_DIR.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

PIPELINE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PIPELINE_DIR / "animations"

# The default loop is 24 frames. Other composite frame counts are supported;
# sheet columns are derived from the count so the atlas stays rectangular.
FRAME_COUNT = 24
MAX_FRAME_COUNT = 64
SHEET_COLUMN_TARGET = 6
# Compatibility alias for diagnostic scripts that still use the historical
# constant. Asset files no longer author a column count.
LINE_LENGTH = SHEET_COLUMN_TARGET
MINIMUM_IDENTITY = 0.84

# Starting point for a brand-new asset file only. Once saved, animation_speed
# is explicit per asset -- nothing falls back to this afterward.
NEW_ASSET_ANIMATION_SPEED = 0.25

# Lighting is authored once per asset and can be overridden by individual
# material-producing motion layers. Angles are measured from screen-left;
# positive angles turn toward screen-top, so 35 degrees is the default
# soft upper-left direction.
DEFAULT_LIGHTING = {
    "enabled": True,
    "direction_degrees": 35.0,
    "strength": 0.24,
    "ambient": 0.82,
}


def is_prime(value: int) -> bool:
    if value < 2:
        return False
    for divisor in range(2, math.isqrt(value) + 1):
        if value % divisor == 0:
            return False
    return True


def validate_frame_count(value: Any, label: str = "frame_count") -> int:
    """Return a supported frame count or raise ValueError with a useful message."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"{label} must be a whole number")
    count = int(number)
    if count < 1 or count > MAX_FRAME_COUNT:
        raise ValueError(f"{label} must be between 1 and {MAX_FRAME_COUNT}")
    if is_prime(count):
        raise ValueError(f"{label} cannot be prime")
    return count


def frame_count_for(asset: dict[str, Any]) -> int:
    return validate_frame_count(asset.get("frame_count", FRAME_COUNT), "asset.frame_count")


def sheet_columns(frame_count: int) -> int:
    """Choose a divisor near the six-column default; never use a partial row."""
    frame_count = validate_frame_count(frame_count)
    divisors = [value for value in range(1, frame_count + 1) if frame_count % value == 0]
    return min(
        divisors,
        key=lambda value: (
            abs(value - SHEET_COLUMN_TARGET),
            abs(value - math.sqrt(frame_count)),
            value,
        ),
    )


def asset_path(name: str) -> Path:
    return ASSETS_DIR / f"{name}.json"


def asset_names() -> list[str]:
    return sorted(p.stem for p in ASSETS_DIR.glob("*.json"))


def load_asset_file(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_asset(name: str) -> dict[str, Any]:
    return load_asset_file(asset_path(name))


def load_all_assets() -> list[dict[str, Any]]:
    return [load_asset_file(p) for p in sorted(ASSETS_DIR.glob("*.json"))]


def save_asset(asset: dict[str, Any], path: Path | None = None) -> None:
    target = path or asset_path(asset["name"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asset, indent=2) + "\n")


def new_asset(name: str, source: str, output: str, size: tuple[int, int]) -> dict[str, Any]:
    return {
        "name": name,
        "source": source,
        "output": output,
        "size": list(size),
        "motions": [],
        "animation_speed": NEW_ASSET_ANIMATION_SPEED,
        "frame_count": FRAME_COUNT,
        "lighting": dict(DEFAULT_LIGHTING),
    }
