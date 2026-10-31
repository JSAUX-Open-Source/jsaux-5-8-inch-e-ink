import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_renderer_module():
    fake_decky = types.SimpleNamespace(
        DECKY_PLUGIN_SETTINGS_DIR=str(ROOT),
        logger=types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
        ),
        emit=lambda *args, **kwargs: None,
    )
    sys.modules["decky"] = fake_decky
    spec = importlib.util.spec_from_file_location("monoink_render_main", ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    module._ensure_pillow()
    return module


def _pillow_native_available() -> bool:
    py_modules = str(ROOT / "py_modules")
    if py_modules not in sys.path:
        sys.path.insert(0, py_modules)
    try:
        from PIL import Image as _pil_image  # noqa: F401
        from PIL import _imaging as _pil_core  # noqa: F401

        return True
    except Exception:
        return False


@unittest.skipUnless(
    _pillow_native_available(),
    "Vendored Pillow wheels target SteamOS/Linux; skip on hosts without matching _imaging.",
)
class FullscreenDisplayBatteryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = load_renderer_module()

    def test_shared_battery_renderer_contract_is_available(self):
        self.assertTrue(
            hasattr(self.main, "_normalise_display_battery_snapshot"),
            "The six fullscreen renderers need a shared normalized battery snapshot helper.",
        )
        self.assertTrue(
            hasattr(self.main, "_draw_display_battery"),
            "The six fullscreen renderers need one shared battery renderer.",
        )

    def test_battery_text_and_fill_follow_accepted_percentages(self):
        self.assertTrue(
            hasattr(self.main, "_battery_text"),
            "Battery label construction must be shared with the renderer.",
        )
        self.assertTrue(
            hasattr(self.main, "_battery_fill_width"),
            "Battery fill width must use one left-to-right percentage rule.",
        )
        for percent, charging, text, width in (
            (100, False, "100", 30),
            (90, False, "90", 27),
            (85, False, "85", 25),
            (50, False, "50", 15),
            (49, False, "49", 14),
            (30, False, "30", 9),
            (29, False, "29", 8),
            (20, False, "20", 6),
            (0, False, "0", 0),
            (12, True, "12", 3),
            (None, False, "--", 0),
        ):
            snapshot = self.main._normalise_display_battery_snapshot(percent, charging)
            self.assertEqual(self.main._battery_text(snapshot), text)
            self.assertEqual(self.main._battery_fill_width(snapshot, 30), width)

    def test_compact_shared_battery_geometry_matches_the_module_reference(self):
        self.assertEqual(self.main.DISPLAY_BATTERY_BOX, (588, 22, 626, 39))

    def test_battery_snapshot_helper_preserves_module_data(self):
        self.assertTrue(
            hasattr(
                self.main,
                "_with_display_battery_snapshot"),
            "All fullscreen transfer routes must attach a device battery snapshot before rendering.",
        )
        source = {"weekday": "Tue"}
        payload = self.main._with_display_battery_snapshot(source, 85, False, 123.0)
        self.assertEqual(source, {"weekday": "Tue"})
        self.assertEqual(payload["weekday"], "Tue")
        self.assertEqual(
            payload["_display_battery_snapshot"],
            {"batteryPercent": 85, "isCharging": False, "updatedAt": 123.0},
        )

    def test_renderer_fills_left_to_right_and_keeps_unknown_empty(self):
        x0, y0, _, _ = self.main.DISPLAY_BATTERY_BOX
        for percent, charging, pixel in (
            (100, False, (0, 0, 0)),
            (85, False, (0, 0, 0)),
            (0, False, (255, 255, 255)),
            (None, False, (255, 255, 255)),
        ):
            image = self.main.Image.new("RGB", (648, 480), "white")
            draw = self.main.ImageDraw.Draw(image)
            snapshot = self.main._normalise_display_battery_snapshot(percent, charging)
            self.main._draw_display_battery(image, draw, snapshot)
            self.assertEqual(image.getpixel((x0 + 3, y0 + 3)), pixel)

    def test_all_six_fullscreen_renderers_use_the_shared_component(self):
        calls = []
        original = self.main._draw_display_battery
        self.main._draw_display_battery = lambda image, draw, snapshot: calls.append(snapshot)
        data = {
            "_display_battery_snapshot": {
                "batteryPercent": 85,
                "isCharging": False,
                "updatedAt": 1.0,
            }
        }
        try:
            for renderer in (
                self.main.render_p0_fullscreen,
                self.main.render_p1_fullscreen,
                self.main.render_p2_fullscreen,
                self.main.render_p3_fullscreen,
                self.main.render_p4_fullscreen,
                self.main.render_p5_fullscreen,
            ):
                renderer(data)
        finally:
            self.main._draw_display_battery = original
        self.assertEqual(len(calls), 6)
        self.assertTrue(all(call["batteryPercent"] == 85 for call in calls))

    def test_year_progress_uses_calendar_and_iso_boundaries(self):
        self.assertTrue(
            hasattr(self.main, "_year_progress_snapshot"),
            "The time module needs a shared year and ISO-week progress calculation.",
        )
        self.assertEqual(
            self.main._year_progress_snapshot(self.main.datetime(2026, 1, 1)),
            {"day": "1 / 365", "week": "1 / 53"},
        )
        self.assertEqual(
            self.main._year_progress_snapshot(self.main.datetime(2024, 12, 31))["day"],
            "366 / 366",
        )

    def test_reference_layout_deltas_are_present_in_the_six_renderers(self):
        import inspect

        self.assertIn("YEAR PROGRESS", inspect.getsource(self.main.render_p4_fullscreen))
        self.assertIn("(568, 303)", inspect.getsource(self.main.render_p4_fullscreen))
        self.assertIn("ampm_x", inspect.getsource(self.main.render_p0_fullscreen))
        self.assertIn("550, 102", inspect.getsource(self.main.render_p1_fullscreen))
        self.assertIn("PERE MON", inspect.getsource(self.main.render_p2_fullscreen))
        self.assertIn(
            "side_box = [404, 56, 621, 348]", inspect.getsource(self.main.render_p3_fullscreen)
        )
        calendar_source = inspect.getsource(self.main._draw_calendar_layout)
        self.assertIn("draw.text((40, title_y), year_text", calendar_source)
        self.assertIn("month_width", calendar_source)

    def test_module_transfer_reuses_existing_device_info_for_the_pending_frame(self):
        import inspect

        dashboard_source = inspect.getsource(self.main.MonoInkCore._send_dashboard_internal)
        clock_source = inspect.getsource(self.main.MonoInkCore.send_clock)
        weather_source = inspect.getsource(self.main.MonoInkCore.send_weather)
        dispatch_source = inspect.getsource(self.main.MonoInkCore._dispatch_module)
        transfer_source = inspect.getsource(self.main.MonoInkCore._send_prepared_bytes)
        for source in (dashboard_source, clock_source, weather_source, dispatch_source):
            self.assertIn("_with_display_battery_snapshot", source)
        self.assertIn('render_mode="module"', dispatch_source)
        self.assertIn('render_mode="dashboard"', dashboard_source)
        self.assertIn('render_mode="clock"', clock_source)
        self.assertIn('render_mode="weather"', weather_source)
        self.assertIn("render_mode in DISPLAY_BATTERY_RENDER_MODES", transfer_source)
        self.assertIn("info.battery", transfer_source)

    def test_weather_module_right_column_matches_the_reference_layout(self):
        import inspect

        source = inspect.getsource(self.main.render_p3_fullscreen)
        self.assertIn("side_box = [404, 56, 621, 348]", source)
        self.assertIn("y = 75 + idx * 99", source)
        self.assertIn("forecast_box = [404, 357, 621, 454]", source)
        self.assertIn("cell_x - 3, 366, cell_x - 3, 447", source)
        self.assertIn("(cell_x + 13, 366), day_text", source)
        self.assertIn('cell_x + 13, 386, item["icon"]', source)
        self.assertIn("(cell_x + 17, 418), hi_text", source)
        self.assertIn("(cell_x + 17, 435), lo_text", source)
        self.assertIn(
            "_draw_eink_text(img, (cell_x + 17, 435), lo_text, lo_font)",
            source,
        )

    def test_weather_card_forwards_the_device_battery_snapshot(self):
        captured = {}
        original = self.main.render_p3_fullscreen
        expected = {"batteryPercent": 85, "isCharging": False, "updatedAt": 123.0}
        self.main.render_p3_fullscreen = lambda data: captured.update(data)
        try:
            self.main.render_weather_card(
                {
                    "temp": 30,
                    "hum": 45,
                    "wind": 35,
                    "icon": "sun",
                    "forecast": [],
                    "_display_battery_snapshot": expected,
                }
            )
        finally:
            self.main.render_p3_fullscreen = original
        self.assertEqual(captured.get("_display_battery_snapshot"), expected)

    def test_time_module_year_progress_values_are_offset_left(self):
        import inspect

        source = inspect.getsource(self.main.render_p4_fullscreen)
        self.assertIn('progress["day"], 564, 421', source)
        self.assertIn('progress["week"], 564, 445', source)

    def test_dashboard_weather_icon_is_shifted_right_and_doubled(self):
        import inspect

        source = inspect.getsource(self.main.render_p0_fullscreen)
        self.assertIn("min(540, ampm_x + ampm_width + 42)", source)
        self.assertIn('size=92 if weather_icon == "sun" else 104', source)

    def test_control_state_snapshot_contains_one_device_and_selected_module(self):
        core = self.main.MonoInkCore()
        core.settings = {
            "mode": "timeline",
            "display_mode": "single",
            "single_module_id": 4,
            "connection_enabled": True,
            "device_address": "AA:BB:CC:10:00:09",
            "module_switch_enabled": True,
            "module_switch_interval_minutes": 15,
            "photo_frame_interval_enabled": False,
            "photo_frame_interval_minutes": 5,
            "custom_selected_path": "/home/deck/Pictures/clock.png",
        }
        core._device_connected = True
        core._connection_state = "on"
        core._last_error = ""
        core._display_battery_percent = 80
        core._display_battery_sample = (80, 1.0)
        core._active_module_id = 4
        core._timeline_idx = 4
        core._cycle_pos = 0
        core.device_info = types.SimpleNamespace(
            battery=80,
            width=648,
            height=480,
            color_count=2,
        )

        snapshot = core._build_control_state()

        self.assertEqual(snapshot["status"]["address"], "AA:BB:CC:10:00:09")
        self.assertTrue(snapshot["status"]["connected"])
        self.assertEqual(snapshot["settings"]["mode"], "timeline")
        self.assertEqual(snapshot["settings"]["single_module_id"], 4)
        self.assertEqual(snapshot["settings"]["current_display_mode"], "clock")
        self.assertTrue(snapshot["settings"]["module_switch_enabled"])


if __name__ == "__main__":
    unittest.main()
