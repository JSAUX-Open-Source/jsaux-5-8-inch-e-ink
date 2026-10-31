import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop_i18n import DESKTOP_TEXT, SUPPORTED_LANGUAGES, resolve_language

GAME_BUNDLE = ROOT / "dist" / "index.js"
STEAM_LANGUAGE_MAP = {
    "arabic": "ar",
    "brazilian": "pt-br",
    "bulgarian": "bg",
    "czech": "cs",
    "danish": "da",
    "dutch": "nl",
    "english": "en",
    "finnish": "fi",
    "french": "fr",
    "german": "de",
    "greek": "el",
    "hungarian": "hu",
    "indonesian": "id",
    "italian": "it",
    "japanese": "ja",
    "koreana": "ko",
    "latam": "es-419",
    "malay": "ms",
    "norwegian": "no",
    "polish": "pl",
    "portuguese": "pt",
    "romanian": "ro",
    "russian": "ru",
    "schinese": "zh",
    "spanish": "es",
    "swedish": "sv",
    "tchinese": "zh-tw",
    "thai": "th",
    "turkish": "tr",
    "ukrainian": "uk",
    "vietnamese": "vi",
}
EXPECTED_LANGUAGES = tuple(dict.fromkeys(STEAM_LANGUAGE_MAP.values()))


class FullLanguageLocalizationTests(unittest.TestCase):
    def test_desktop_supports_every_steam_client_language(self):
        self.assertEqual(SUPPORTED_LANGUAGES, EXPECTED_LANGUAGES)
        self.assertEqual(tuple(DESKTOP_TEXT), EXPECTED_LANGUAGES)

    def test_desktop_resolves_steam_and_locale_aliases(self):
        for steam_name, expected in STEAM_LANGUAGE_MAP.items():
            with self.subTest(steam_name=steam_name):
                self.assertEqual(resolve_language([steam_name]), expected)

        locale_aliases = {
            "ar_SA.UTF-8": "ar",
            "pt_BR.UTF-8": "pt-br",
            "bg_BG.UTF-8": "bg",
            "cs_CZ.UTF-8": "cs",
            "da_DK.UTF-8": "da",
            "nl_NL.UTF-8": "nl",
            "fi_FI.UTF-8": "fi",
            "el_GR.UTF-8": "el",
            "hu_HU.UTF-8": "hu",
            "id_ID.UTF-8": "id",
            "it_IT.UTF-8": "it",
            "es_419.UTF-8": "es-419",
            "ms_MY.UTF-8": "ms",
            "nb_NO.UTF-8": "no",
            "pl_PL.UTF-8": "pl",
            "pt_PT.UTF-8": "pt",
            "ro_RO.UTF-8": "ro",
            "sv_SE.UTF-8": "sv",
            "th_TH.UTF-8": "th",
            "tr_TR.UTF-8": "tr",
            "uk_UA.UTF-8": "uk",
            "vi_VN.UTF-8": "vi",
        }
        for locale_name, expected in locale_aliases.items():
            with self.subTest(locale_name=locale_name):
                self.assertEqual(resolve_language([locale_name]), expected)

    def test_desktop_translation_tables_have_the_complete_key_set(self):
        english_keys = set(DESKTOP_TEXT["en"])
        for language in EXPECTED_LANGUAGES:
            with self.subTest(language=language):
                self.assertEqual(set(DESKTOP_TEXT[language]), english_keys)
                self.assertTrue(all(DESKTOP_TEXT[language][key] for key in english_keys))

    def test_game_bundle_covers_the_same_steam_language_set_and_adapts_long_text(self):
        source = GAME_BUNDLE.read_text(encoding="utf-8")
        match = re.search(
            r"const SUPPORTED_GAME_LANGUAGES = Object\.freeze\((\[[^\n]+\])\);",
            source,
        )
        self.assertIsNotNone(match, "game language list is missing")
        self.assertEqual(tuple(json.loads(match.group(1))), EXPECTED_LANGUAGES)
        for steam_name, language in STEAM_LANGUAGE_MAP.items():
            self.assertIn(f'"{steam_name}": "{language}"', source)
        self.assertIn('lang.startsWith("zh-hans")', source)
        self.assertIn('lang.startsWith("zh-hant")', source)
        self.assertIn("const fitUiFontSize =", source)
        self.assertIn('fitUiFontSize(confirmedConnectedMac ? t("connectionConnected")', source)
        self.assertIn("fitUiFontSize(t(m.labelKey)", source)


if __name__ == "__main__":
    unittest.main()
