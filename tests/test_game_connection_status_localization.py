import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAME_BUNDLE = ROOT / "dist" / "index.js"
SUPPORTED_LANGUAGES = ("en", "zh", "zh-tw", "ja", "ko", "de", "fr", "es", "ru")
REQUIRED_UI_TEXT_KEYS = (
    "connectionConnected:",
    "connectionDisconnected:",
    "connectionStatus:",
    "minutesSuffix:",
    "disconnectCurrentDevice:",
    "sendFailed:",
    "folderUnavailable:",
    "deleteFailed:",
    "errorMessage:",
)


class GameConnectionStatusLocalizationTests(unittest.TestCase):
    def test_connection_status_uses_the_system_language_translation_table(self):
        source = GAME_BUNDLE.read_text(encoding="utf-8")

        for language in SUPPORTED_LANGUAGES:
            language_selector = f'"{language}"' if "-" in language else language
            language_block = re.search(
                rf"^    {re.escape(language_selector)}: \{{(.*?)^    \}},$",
                source,
                re.MULTILINE | re.DOTALL,
            )
            self.assertIsNotNone(language_block, language)
            for key in REQUIRED_UI_TEXT_KEYS:
                self.assertIn(key, language_block.group(1), f"{language}: {key}")

        status_start = source.index('key: "connection-entry-status"')
        status_end = source.index('key: "connection-entry-chevron"', status_start)
        status = source[status_start:status_end]
        self.assertIn(
            'confirmedConnectedMac ? t("connectionConnected") : t("connectionDisconnected")',
            status,
        )
        self.assertNotIn('confirmedConnectedMac ? "已连接" : "未连接"', status)

    def test_game_visible_messages_do_not_bypass_the_translation_table(self):
        source = GAME_BUNDLE.read_text(encoding="utf-8")

        self.assertIn('label: `${value}${t("minutesSuffix")}`', source)
        self.assertIn('`${photoFrameInterval}${t("minutesSuffix")}`', source)
        self.assertIn('"aria-label": t("connectionStatus")', source)
        # disconnectCurrentDevice is shipped in the i18n tables for all locales.
        self.assertIn("disconnectCurrentDevice:", source)
        self.assertIn('body: t("sendFailed")', source)
        self.assertIn('new Error(t("folderUnavailable"))', source)
        self.assertIn('body: t("deleteFailed")', source)
        self.assertIn('body: formatUiText("errorMessage", { error: e })', source)
        self.assertIn('body: formatUiText("errorMessage", { error })', source)

        self.assertNotIn("label: `${value} min`", source)
        self.assertNotIn("`${photoFrameInterval} min`", source)
        self.assertNotIn('"aria-label": "Connection status"', source)
        self.assertNotIn('body: "Send failed."', source)
        self.assertNotIn('new Error("Unable to use this folder")', source)
        self.assertNotIn('body: "Delete failed."', source)
        self.assertNotIn("body: `Error: ${e}`", source)
        self.assertNotIn("body: `Error: ${error}`", source)


if __name__ == "__main__":
    unittest.main()
