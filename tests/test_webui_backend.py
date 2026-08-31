from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

import asset_store
import generate_animations as ga
from webui.backend.app import EditorApplication
from webui.backend.assets import AssetService
from webui.backend.config import AppConfig
from webui.backend.errors import ApiError, NoAssetOpenError
from webui.backend.session import EditorSession
from webui.backend.validation import validate_asset


class BackendFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.webui_dir = Path(__file__).resolve().parents[1] / "webui"
        self.config = AppConfig(
            pipeline_dir=self.root,
            webui_dir=self.webui_dir,
            asset_root=self.root,
            assets_dir=self.root / "animations",
            metadata_path=self.root / "generated-metadata.json",
        )
        self.image_path = self.root / "sprite.png"
        Image.new("RGBA", (16, 12), (20, 40, 60, 255)).save(self.image_path)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_asset(self, name: str = "sample") -> dict:
        return {
            "name": name,
            "source": "sprite.png",
            "output": "sheet.png",
            "size": [16, 12],
            "motions": [],
            "animation_speed": 0.25,
        }


class ValidationTests(BackendFixture):
    def test_validates_asset_contract(self) -> None:
        self.assertEqual(validate_asset(self.make_asset())["size"], [16, 12])

    def test_rejects_unsafe_asset_name(self) -> None:
        asset = self.make_asset("../outside")
        with self.assertRaisesRegex(ApiError, "Asset name"):
            validate_asset(asset)

    def test_rejects_motion_without_type(self) -> None:
        asset = self.make_asset()
        asset["motions"] = [{}]
        with self.assertRaisesRegex(ApiError, "motion type"):
            validate_asset(asset)

    def test_rejects_prime_frame_count(self) -> None:
        asset = self.make_asset()
        asset["frame_count"] = 13
        with self.assertRaisesRegex(ApiError, "cannot be prime"):
            validate_asset(asset)

    def test_frame_count_derives_rectangular_sheet_columns(self) -> None:
        self.assertEqual(asset_store.sheet_columns(24), 6)
        self.assertEqual(asset_store.sheet_columns(20), 5)
        self.assertEqual(asset_store.sheet_columns(49), 7)

    def test_lighting_defaults_and_layer_override(self) -> None:
        asset = validate_asset(self.make_asset())
        self.assertEqual(asset["lighting"], asset_store.DEFAULT_LIGHTING)
        custom = {
            **self.make_asset(),
            "lighting": {"direction_degrees": 90},
            "motions": [{"type": "mechanical_gear", "lighting": {"mode": "custom", "direction_degrees": 180}}],
        }
        normalized = validate_asset(custom)
        self.assertEqual(normalized["lighting"]["direction_degrees"], 90)
        self.assertEqual(normalized["motions"][0]["lighting"]["mode"], "custom")

    def test_directional_lighting_follows_direction(self) -> None:
        nx = np.asarray([[-1.0, 1.0]], dtype=np.float32)
        ny = np.zeros_like(nx)
        field = ga.directional_lighting(nx, ny, {"direction_degrees": 0, "strength": 0.5, "ambient": 0.5})
        self.assertGreater(field[0, 0], field[0, 1])
        top_bottom = np.asarray([[-1.0], [1.0]], dtype=np.float32)
        vertical = ga.directional_lighting(
            np.zeros_like(top_bottom), top_bottom,
            {"direction_degrees": 90, "strength": 0.5, "ambient": 0.5},
        )
        self.assertGreater(vertical[0, 0], vertical[1, 0])


class AssetServiceTests(BackendFixture):
    def test_save_load_and_browse_are_configurable(self) -> None:
        service = AssetService(self.config)
        target = self.config.assets_dir / "sample.json"
        service.save(self.make_asset(), target)

        self.assertEqual(service.load(target)["name"], "sample")
        listing = service.browse("", "json")
        self.assertEqual([entry["name"] for entry in listing["entries"]], ["sample.json"])

    def test_create_reads_dimensions_without_persisting(self) -> None:
        service = AssetService(self.config)
        asset, target = service.create("new-sprite", self.image_path, self.root / "output.png")

        self.assertEqual(asset["size"], [16, 12])
        self.assertFalse(target.exists())

    def test_find_by_source_ignores_broken_asset_files(self) -> None:
        service = AssetService(self.config)
        self.config.assets_dir.mkdir(parents=True)
        (self.config.assets_dir / "broken.json").write_text("not json")
        service.save(self.make_asset(), self.config.assets_dir / "sample.json")

        found = service.find_by_source(self.image_path.resolve())
        self.assertIsNotNone(found)
        self.assertEqual(found[0]["name"], "sample")


class EditorSessionTests(BackendFixture):
    def test_session_requires_an_open_asset(self) -> None:
        session = EditorSession(AssetService(self.config))
        with self.assertRaises(NoAssetOpenError):
            session.current()

    def test_open_save_and_reload_lifecycle(self) -> None:
        service = AssetService(self.config)
        path = self.config.assets_dir / "sample.json"
        service.save(self.make_asset(), path)
        session = EditorSession(service)

        session.open(path)
        session.save(
            [{"type": "pulse", "center": [8, 6]}],
            0.5,
            lighting={"direction_degrees": 90},
        )
        on_disk = json.loads(path.read_text())
        self.assertEqual(on_disk["animation_speed"], 0.5)
        self.assertEqual(on_disk["motions"][0]["type"], "pulse")
        self.assertEqual(on_disk["lighting"]["direction_degrees"], 90)

        on_disk["animation_speed"] = 0.75
        path.write_text(json.dumps(on_disk))
        self.assertEqual(session.reload()["asset"]["animation_speed"], 0.75)

    def test_save_persists_frame_count_and_removes_legacy_columns(self) -> None:
        service = AssetService(self.config)
        asset = self.make_asset()
        asset["line_length"] = 4
        path = self.config.assets_dir / "sample.json"
        service.save(asset, path)
        session = EditorSession(service)
        session.open(path)
        session.save([], 0.5, 20)

        on_disk = json.loads(path.read_text())
        self.assertEqual(on_disk["frame_count"], 20)
        self.assertNotIn("line_length", on_disk)


class ApplicationTests(BackendFixture):
    def test_health_and_asset_metadata(self) -> None:
        application = EditorApplication(self.config)
        self.assertEqual(application.health({})["api_version"], 1)
        self.assertIsNone(application.get_asset({})["asset"])

    def test_preview_uses_production_renderer(self) -> None:
        service = AssetService(self.config)
        asset = self.make_asset()
        asset["motions"] = [
            {
                "type": "pulse",
                "center": [8, 6],
                "radius": [3, 2],
                "color": [255, 120, 30],
                "alpha": 60,
                "blur": 1,
            }
        ]
        path = self.config.assets_dir / "sample.json"
        service.save(asset, path)
        application = EditorApplication(self.config)
        application.open_on_startup(path)

        result = application.preview(
            {"motions": asset["motions"], "selected_index": 0, "frame_count": 12, "isolate": True}
        )
        self.assertEqual(len(result["frames"]), 12)
        self.assertGreater(len(result["frames"][0]), 20)

    def test_export_uses_requested_frame_count(self) -> None:
        service = AssetService(self.config)
        asset = self.make_asset()
        asset["motions"] = [
            {
                "type": "pulse",
                "center": [8, 6],
                "radius": [3, 2],
                "color": [255, 120, 30],
                "alpha": 60,
                "blur": 1,
            }
        ]
        path = self.config.assets_dir / "sample.json"
        service.save(asset, path)
        application = EditorApplication(self.config)
        application.open_on_startup(path)

        result = application.export_gif(
            {
                "motions": asset["motions"],
                "selected_index": 0,
                "frame_count": 12,
                "isolate": True,
                "animation_speed": 0.25,
            }
        )
        self.assertEqual(result["frame_count"], 12)


if __name__ == "__main__":
    unittest.main()
