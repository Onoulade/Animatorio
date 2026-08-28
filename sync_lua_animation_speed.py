#!/usr/bin/env python3
"""Keep prototypes/shared/generated_animation_speeds.lua in sync with the per-asset animation files.

Each asset file under animations/ is the source of truth for that
building's own animation_speed. The Lua side reads all of them from one
shared module (required by every entity file whose sprites the pipeline
generates) rather than a value duplicated per file, since animation_speed
is a mod-wide pipeline setting, not something tied to any one entity file.
This script rewrites that module's generated ANIMATION_SPEEDS table
(delimited by the BEGIN/END markers below) to match -- it never touches
anything else in the file.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import asset_store

PIPELINE_DIR = Path(__file__).resolve().parent
ROOT = Path(os.environ.get("ANIMATORIO_ASSET_ROOT", os.environ.get("ANIMATORIO_ROOT", PIPELINE_DIR)))
# Optional downstream target; if missing, sync is a no-op for standalone usage.
LUA_MODULE_PATH = ROOT / "prototypes" / "shared" / "generated_animation_speeds.lua"

BEGIN_MARKER = "-- BEGIN GENERATED ANIMATION_SPEEDS"
END_MARKER = "-- END GENERATED ANIMATION_SPEEDS"
BLOCK_RE = re.compile(re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)


def resolve_speed(asset: dict[str, Any]) -> float:
    return float(asset.get("animation_speed", asset_store.NEW_ASSET_ANIMATION_SPEED))


def build_block(entries: list[tuple[str, float]]) -> str:
    lines = [BEGIN_MARKER, "M.ANIMATION_SPEEDS = {"]
    for name, speed in sorted(entries):
        lines.append(f'  ["{name}"] = {speed:g},')
    lines.append("}")
    lines.append(END_MARKER)
    return "\n".join(lines)


def sync(assets: list[dict[str, Any]] | None = None) -> bool:
    """Rewrite the shared Lua module's ANIMATION_SPEEDS table. Returns True if it changed."""
    if assets is None:
        assets = asset_store.load_all_assets()

    entries = [(asset["name"], resolve_speed(asset)) for asset in assets]

    if not LUA_MODULE_PATH.exists():
        # Standalone mode: no Lua prototypes to sync; treat as no-op.
        return False
    text = LUA_MODULE_PATH.read_text()
    if not BLOCK_RE.search(text):
        raise ValueError(
            f"{LUA_MODULE_PATH}: no {BEGIN_MARKER} .. {END_MARKER} block found -- "
            "add the ANIMATION_SPEEDS marker block by hand once before syncing."
        )
    new_block = build_block(entries)
    new_text = BLOCK_RE.sub(lambda _match: new_block, text, count=1)
    if new_text != text:
        LUA_MODULE_PATH.write_text(new_text)
        return True
    return False


if __name__ == "__main__":
    if sync():
        print(f"Updated: {LUA_MODULE_PATH.relative_to(ROOT)}")
    else:
        print("Already in sync.")
