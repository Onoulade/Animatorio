from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    pipeline_dir: Path
    webui_dir: Path
    asset_root: Path
    assets_dir: Path
    metadata_path: Path

    @classmethod
    def from_environment(cls) -> "AppConfig":
        webui_dir = Path(__file__).resolve().parents[1]
        pipeline_dir = webui_dir.parent
        asset_root = Path(
            os.environ.get(
                "ANIMATORIO_ASSET_ROOT",
                os.environ.get("ANIMATORIO_ROOT", pipeline_dir),
            )
        ).expanduser().resolve()
        return cls(
            pipeline_dir=pipeline_dir,
            webui_dir=webui_dir,
            asset_root=asset_root,
            assets_dir=asset_root / "animations",
            metadata_path=pipeline_dir / "generated-metadata.json",
        )
