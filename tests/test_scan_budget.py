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
    spec = importlib.util.spec_from_file_location("monoink_scan_budget_main", ROOT / "main.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ScanBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.main = load_main_module()

    def test_manual_scan_reserves_end_to_end_budget(self):
        main = self.main
        observed = {}

        class CapturingLease:
            def __init__(self, *args, **kwargs):
                observed["lease_timeout"] = kwargs.get("timeout")

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

        async def discover(**kwargs):
            observed["discover_timeout"] = kwargs.get("timeout")
            return {}

        core = main.EInkCore()
        core.settings = {"connection_enabled": True, "device_address": "AA:BB:CC:10:00:09"}
        core._ble_lock = asyncio.Lock()
        core._begin_foreground_scan_request = lambda: "test-scan"
        core._finish_foreground_scan_request = lambda token: None
        core._emit_status = _noop_emit

        original_lease = main.SharedBleAdapterLease
        original_scanner = main.BleakScanner
        original_monotonic = main.time.monotonic
        main.SharedBleAdapterLease = CapturingLease
        main.BleakScanner = types.SimpleNamespace(discover=discover)
        main.time.monotonic = lambda: 100.0
        try:
            asyncio.run(core.scan())
            remaining_budget = getattr(
                main, "_remaining_manual_scan_budget", lambda _started: -1.0
            )(100.0)
        finally:
            main.SharedBleAdapterLease = original_lease
            main.BleakScanner = original_scanner
            main.time.monotonic = original_monotonic

        self.assertEqual(getattr(main, "MANUAL_BLE_SCAN_TOTAL_TIMEOUT_SEC", None), 30.0)
        self.assertEqual(remaining_budget, 30.0)
        self.assertEqual(observed["lease_timeout"], main.MANUAL_BLE_SCAN_LEASE_TIMEOUT_SEC)
        self.assertEqual(observed["discover_timeout"], main.MANUAL_BLE_SCAN_TIMEOUT_SEC)
        self.assertEqual(main.MANUAL_BLE_SCAN_TIMEOUT_SEC, 12.0)
        self.assertEqual(main.MANUAL_BLE_SCAN_LEASE_TIMEOUT_SEC, 8.0)


if __name__ == "__main__":
    unittest.main()
