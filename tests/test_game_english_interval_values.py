import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME_BUNDLE = ROOT / "dist" / "index.js"


class GameEnglishIntervalValueLayoutTests(unittest.TestCase):
    def test_only_english_interval_values_are_kept_on_one_line(self):
        source = GAME_BUNDLE.read_text(encoding="utf-8")

        self.assertIn(
            'const intervalValueStyle = getSystemLanguage() === "en"',
            source,
        )
        self.assertIn('minWidth: "48px"', source)
        self.assertIn('flex: "0 0 auto"', source)
        self.assertIn('whiteSpace: "nowrap"', source)
        self.assertIn("screenControlIntervalValueStyle", source)

        photo_start = source.index('key: "photo-frame"')
        photo_end = source.index('key: "module-switch"', photo_start)
        photo_row = source[photo_start:photo_end]
        self.assertIn('key: "value", style: screenControlIntervalValueStyle', photo_row)
        self.assertNotIn('key: "value", style: styles.rowValue', photo_row)

        module_start = source.index('key: "module-switch"')
        module_end = source.index('key: "modules"', module_start)
        module_row = source[module_start:module_end]
        self.assertIn('key: "value", style: screenControlIntervalValueStyle', module_row)
        self.assertNotIn('key: "value", style: styles.rowValue', module_row)


if __name__ == "__main__":
    unittest.main()
