from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

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
        session.save([{"type": "pulse", "center": [8, 6]}], 0.5)
        on_disk = json.loads(path.read_text())
        self.assertEqual(on_disk["animation_speed"], 0.5)
        self.assertEqual(on_disk["motions"][0]["type"], "pulse")

        on_disk["animation_speed"] = 0.75
        path.write_text(json.dumps(on_disk))
        self.assertEqual(session.reload()["asset"]["animation_speed"], 0.75)


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
            {"motions": asset["motions"], "selected_index": 0, "phases": [0.0], "isolate": True}
        )
        self.assertEqual(len(result["frames"]), 1)
        self.assertGreater(len(result["frames"][0]), 20)


if __name__ == "__main__":
    unittest.main()
