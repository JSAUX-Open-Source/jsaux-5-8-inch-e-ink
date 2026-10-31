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
    spec = importlib.util.spec_from_file_location(
        "monoink_scan_send_recovery_main", ROOT / "main.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ScanSendRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = load_main_module()

    def test_client_target_ignores_stale_bledevice_cached_by_scan(self):
        main = self.main
        core = main.EInkCore()
        address = "AA:BB:CC:10:00:09"
        stale = object()
        core._ble_device_targets = {address: stale}

        async def no_manager():
            raise RuntimeError("BlueZ unavailable in unit test")

        original_manager = main.get_global_bluez_manager
        main.get_global_bluez_manager = no_manager
        try:
            target = asyncio.run(core._get_ble_client_target(address))
        finally:
            main.get_global_bluez_manager = original_manager

        self.assertEqual(target, address)
        self.assertIsNot(target, stale)

    def test_device_not_found_is_rediscoverable(self):
        self.assertTrue(
            self.main.EInkCore._ble_failure_needs_rediscovery(
                RuntimeError("device 'dev_AA_BB_CC_10_00_09' not found")
            )
        )

    def test_background_send_rediscovers_same_address_before_retry(self):
        main = self.main
        core = main.EInkCore()
        address = "AA:BB:CC:10:00:09"
        core.settings = {"connection_enabled": True, "device_address": address}
        core._ble_lock = asyncio.Lock()
        core._background_refresh_task = None
        core._desktop_owner_active = lambda: False
        core._reject_desktop_owned_ble = lambda _operation: False
        core._set_connection_state = lambda *_args, **_kwargs: None
        core._ensure_reconnect_task = lambda: None
        core._emit_status = _noop_emit

        requested_addresses = []
        attempted_targets = []

        async def stale_target(_address):
            return "stale-target"

        async def rediscover(requested_address):
            requested_addresses.append(requested_address)
            return "fresh-target"

        async def device_info(_client, _display):
            return main.DeviceInfo(
                is_dual_screen=False,
                color_mode=0,
                width=648,
                height=480,
                packet_size=64,
                battery=80,
            )

        class FakeClient:
            def __init__(self, target, timeout):
                self.target = target
                self.timeout = timeout
                self.is_connected = False
                attempted_targets.append(target)

            async def connect(self):
                if self.target == "stale-target":
                    raise RuntimeError("device 'dev_AA_BB_CC_10_00_09' not found")
                self.is_connected = True

            async def disconnect(self):
                self.is_connected = False

            async def start_notify(self, _uuid, _callback):
                return None

            async def stop_notify(self, _uuid):
                return None

            async def write_gatt_char(self, _uuid, _packet, response=True):
                return None

        original_client = main.BleakClient
        original_sleep = main.asyncio.sleep
        main.BleakClient = FakeClient
        main.asyncio.sleep = _noop_emit
        core._get_ble_client_target = stale_target
        core._rediscover_ble_client_target = rediscover
        core._query_device_info = device_info
        try:
            result = asyncio.run(
                core._send_prepared_bytes.__wrapped__(
                    core,
                    b"one-packet",
                    foreground_request=None,
                )
            )
        finally:
            main.BleakClient = original_client
            main.asyncio.sleep = original_sleep

        self.assertTrue(result)
        self.assertEqual(requested_addresses, [address])
        self.assertEqual(attempted_targets, ["stale-target", "fresh-target"])


if __name__ == "__main__":
    unittest.main()
