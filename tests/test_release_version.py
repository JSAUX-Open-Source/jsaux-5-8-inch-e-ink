import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReleaseVersionTests(unittest.TestCase):
    def test_game_and_desktop_user_visible_versions_are_v12(self):
        desktop_source = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
        game_source = (ROOT / "dist" / "index.js").read_text(encoding="utf-8")

        self.assertIn('CURRENT_FW = "V1.2"', desktop_source)
        self.assertIn('LATEST_FW = "V1.2"', desktop_source)
        self.assertIn(
            'resolveFirmwareUi("1.2", "1.2", false, {',
            game_source,
        )
        self.assertNotIn(
            'resolveFirmwareUi("1.1.0--test", "1.1.0--test", false, {',
            game_source,
        )

    def test_release_metadata_and_all_version_labels_are_v12(self):
        package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
        plugin = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
        daemon_source = (ROOT / "eink_daemon.py").read_text(encoding="utf-8")
        display_source = (ROOT / "main.py").read_text(encoding="utf-8")
        game_source = (ROOT / "dist" / "index.js").read_text(encoding="utf-8")

        self.assertEqual(package.get("version"), "1.2")
        self.assertEqual(plugin.get("version"), "1.2")
        self.assertTrue('SERVICE_VERSION = "1.2"' in daemon_source)
        self.assertTrue('FW_VERSION = "V1.2"' in display_source)
        for legacy in ("1.0.0", "1.1.0--test"):
            self.assertFalse(
                legacy in game_source, f"legacy version remains in game UI bundle: {legacy}"
            )


if __name__ == "__main__":
    unittest.main()
