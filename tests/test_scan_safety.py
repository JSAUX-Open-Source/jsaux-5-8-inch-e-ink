import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


async def _noop_emit(*args, **kwargs):
    return None


def load_main_module():
    fake_decky = types.SimpleNamespace(
        DECKY_PLUGIN_SETTINGS_DIR=str(ROOT),
        logger=types.SimpleNamespace(
            info=lambda *args, **kwargs: None,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
        ),
        emit=_noop_emit,
    )
    sys.modules["decky"] = fake_decky
    spec = importlib.util.spec_from_file_location("monoink_scan_safety_main", ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _AsyncLease:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class ScanSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = load_main_module()

    def _connected_core(self):
        core = self.main.EInkCore()
        core.settings = {
            "connection_enabled": True,
            "device_address": "AA:BB:CC:10:00:09",
        }
        core._device_connected = True
        core._connection_state = self.main.CONNECTION_STATE_ON
        core.device_info = self.main.DeviceInfo(
            is_dual_screen=False,
            color_mode=0,
            width=648,
            height=480,
            packet_size=240,
            battery=80,
        )
        core._last_scan_results = [{"address": "AA:BB:CC:10:00:09", "connected": True}]
        core._ble_lock = asyncio.Lock()
        core._begin_foreground_scan_request = lambda: "test-scan"
        core._finish_foreground_scan_request = lambda token: None

        async def no_emit():
            return None

        core._emit_status = no_emit
        return core

    def test_scan_preserves_existing_connection_state_and_device_info(self):
        core = self._connected_core()

        async def discover(**kwargs):
            return {}

        original_lease = self.main.SharedBleAdapterLease
        original_scanner = self.main.BleakScanner
        self.main.SharedBleAdapterLease = lambda *args, **kwargs: _AsyncLease()
        self.main.BleakScanner = types.SimpleNamespace(discover=discover)
        try:
            results = asyncio.run(core.scan())
        finally:
            self.main.SharedBleAdapterLease = original_lease
            self.main.BleakScanner = original_scanner

        self.assertEqual(results, [])
        self.assertTrue(core._device_connected)
        self.assertEqual(core._connection_state, self.main.CONNECTION_STATE_ON)
        self.assertIsNotNone(core.device_info)
        self.assertEqual(core.settings["device_address"], "AA:BB:CC:10:00:09")

    def test_scan_excludes_generic_uart_but_keeps_named_or_signed_monoink(self):
        core = self._connected_core()
        target_payload = bytes([
            0x91,
            self.main.CMD_QUERY_INFO,
            0x01,
            0x00,
            0x02,
            0x88,
            0x01,
            0xE0,
            0x00,
            0xF0,
            80,
            0x19,
        ])

        def device(name, address):
            return types.SimpleNamespace(name=name, address=address, rssi=-50)

        def advertisement(name, *, manufacturer_data=None):
            return types.SimpleNamespace(
                local_name=name,
                service_uuids=[self.main.SERVICE_UUID],
                manufacturer_data=manufacturer_data or {},
                rssi=-50,
                tx_power=-60,
            )

        discoveries = {
            "generic": (
                device("Wireless Serial", "AA:BB:CC:10:00:01"),
                advertisement("Wireless Serial"),
            ),
            "named": (
                device("JSAUX E-INK", "AA:BB:CC:10:00:02"),
                advertisement("JSAUX E-INK"),
            ),
            "signed": (
                device("Unknown", "AA:BB:CC:10:00:03"),
                advertisement("Unknown", manufacturer_data={1: target_payload}),
            ),
        }

        results = core._scan_bleak_devices(discoveries)

        by_address = {item["address"]: item for item in results}
        self.assertSetEqual(
            set(by_address),
            {"AA:BB:CC:10:00:02", "AA:BB:CC:10:00:03"},
        )
        self.assertEqual(by_address["AA:BB:CC:10:00:03"]["width"], 648)
        self.assertEqual(by_address["AA:BB:CC:10:00:03"]["height"], 480)

    def test_daemon_is_the_only_ble_owner_for_both_user_interfaces(self):
        daemon_source = (ROOT / "eink_daemon.py").read_text(encoding="utf-8")
        desktop_source = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
        bridge_source = (ROOT / "daemon_client.py").read_text(encoding="utf-8")
        backend_source = (ROOT / "main.py").read_text(encoding="utf-8")

        self.assertIn("core._daemon_control_mode = True", daemon_source)
        self.assertNotIn("BleakClient", desktop_source)
        self.assertNotIn("BleakScanner", desktop_source)
        self.assertIn("class Plugin(DaemonPluginBridge):", backend_source)
        self.assertIn("class DaemonPluginBridge:", bridge_source)


if __name__ == "__main__":
    unittest.main()
