import asyncio
import importlib.util
import inspect
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_daemon_module():
    spec = importlib.util.spec_from_file_location("eink_daemon_test", ROOT / "eink_daemon.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ControlStatePublicationTests(unittest.TestCase):
    def test_publication_broadcasts_one_revisioned_snapshot_to_all_clients(self):
        daemon = load_daemon_module()

        class Core:
            async def get_control_state(self):
                return {
                    "status": {"connected": True, "address": "AA:BB:CC:10:00:09"},
                    "settings": {"active_module_id": 4, "current_display_mode": "clock"},
                }

        class Hub:
            def __init__(self):
                self.events = []

            async def publish(self, event, payload):
                self.events.append((event, payload))

        hub = Hub()
        app = {
            daemon.STATE_KEY: {
                "core": Core(),
                "control_state_revision": 0,
                "control_state_epoch": "test-epoch",
            },
            daemon.EVENT_HUB_KEY: hub,
        }

        first = asyncio.run(daemon.publish_control_state(app))
        second = asyncio.run(daemon.publish_control_state(app))

        self.assertEqual(first["epoch"], "test-epoch")
        self.assertEqual(first["revision"], 1)
        self.assertEqual(second["revision"], 2)
        self.assertEqual(first["settings"]["active_module_id"], 4)
        self.assertEqual(
            hub.events, [("control_state_update", first), ("control_state_update", second)]
        )

    def test_rpc_and_event_contract_publish_control_state(self):
        daemon = load_daemon_module()
        self.assertIn("get_control_state", daemon.RPC_METHODS)
        self.assertIn(
            "publish_control_state(request.app)",
            inspect.getsource(daemon.rpc_handler),
        )
        self.assertIn(
            '"event": "control_state_update"',
            inspect.getsource(daemon.events_handler),
        )

    def test_plugin_bridge_and_desktop_client_consume_control_state_updates(self):
        client_spec = importlib.util.spec_from_file_location(
            "daemon_client_test", ROOT / "daemon_client.py"
        )
        client_module = importlib.util.module_from_spec(client_spec)
        assert client_spec.loader is not None
        client_spec.loader.exec_module(client_module)

        self.assertTrue(hasattr(client_module.AsyncDaemonClient, "get_control_state"))
        self.assertTrue(hasattr(client_module.DaemonPluginBridge, "get_control_state"))
        desktop_source = (ROOT / "desktop_app.py").read_text(encoding="utf-8")
        gaming_source = (ROOT / "dist" / "index.js").read_text(encoding="utf-8")
        self.assertIn("def _apply_control_state", desktop_source)
        self.assertIn('event == "control_state_update"', desktop_source)
        self.assertIn('addEventListener("control_state_update"', gaming_source)
        self.assertIn("applyControlState", gaming_source)

    def test_gaming_bundle_declares_control_state_refs_after_gamepad_state_object(self):
        gaming_source = (ROOT / "dist" / "index.js").read_text(encoding="utf-8")
        gamepad_state_start = gaming_source.index(
            "const gamepadStateRef = _local_SP_REACT.useRef({"
        )
        gamepad_state_end = gaming_source.index("    });", gamepad_state_start)
        epoch_ref = gaming_source.index(
            "const controlStateEpochRef = _local_SP_REACT.useRef", gamepad_state_start
        )
        revision_ref = gaming_source.index(
            "const controlStateRevisionRef = _local_SP_REACT.useRef", gamepad_state_start
        )

        self.assertGreater(
            epoch_ref,
            gamepad_state_end,
            "controlStateEpochRef must be declared after the gamepad state object closes",
        )
        self.assertGreater(revision_ref, epoch_ref)

    def test_gaming_bundle_keeps_control_state_callback_outside_layout_effect(self):
        gaming_source = (ROOT / "dist" / "index.js").read_text(encoding="utf-8")
        device_status_start = gaming_source.index(
            "const applyDeviceStatus = _local_SP_REACT.useCallback"
        )
        device_status_end = gaming_source.index("    }, []);", device_status_start)
        control_state_start = gaming_source.index(
            "const applyControlState = _local_SP_REACT.useCallback", device_status_end
        )
        control_state_end = gaming_source.index("    }, [applyDeviceStatus]);", control_state_start)
        layout_effect_before_callback = gaming_source.find(
            "_local_SP_REACT.useLayoutEffect",
            device_status_end,
            control_state_start,
        )

        self.assertEqual(
            layout_effect_before_callback,
            -1,
            "applyControlState must not be declared inside the layout effect callback",
        )
        self.assertGreater(
            gaming_source.index("_local_SP_REACT.useLayoutEffect", control_state_end),
            control_state_end,
        )


if __name__ == "__main__":
    unittest.main()
