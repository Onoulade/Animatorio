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
from pathlib import Path
from typing import Any

PIPELINE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PIPELINE_DIR / "animations"

# A 24-frame loop laid out 6-per-row is fixed by how the sheet packer
# expects sprite sheets -- every asset in this pipeline uses the same values,
# so they're pipeline constants rather than something to repeat inside each asset file.
FRAME_COUNT = 24
LINE_LENGTH = 6
MINIMUM_IDENTITY = 0.84

# Starting point for a brand-new asset file only. Once saved, animation_speed
# is explicit per asset -- nothing falls back to this afterward.
NEW_ASSET_ANIMATION_SPEED = 0.25


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
    }
