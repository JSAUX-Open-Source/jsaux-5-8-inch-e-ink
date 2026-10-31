#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
import types
from pathlib import Path
from typing import Any, Optional

PLUGIN_ROOT = Path(__file__).resolve().parent
PY_MODULES = PLUGIN_ROOT / "py_modules"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))
if str(PY_MODULES) not in sys.path:
    # Always prefer the offline wheels shipped with this plugin.  SteamOS
    # releases can expose a different system aiohttp/ABI than this daemon.
    sys.path.insert(0, str(PY_MODULES))
try:
    from aiohttp import WSMsgType, web
except ModuleNotFoundError:
    if str(PY_MODULES) not in sys.path:
        sys.path.insert(0, str(PY_MODULES))
    from aiohttp import WSMsgType, web


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 39062
DEFAULT_SETTINGS_DIR = Path.home() / "homebrew" / "settings" / "jsaux-eink-display"
SERVICE_NAME = "jsaux-eink-daemon"
SERVICE_VERSION = "1.2"
LOGGER = logging.getLogger(SERVICE_NAME)

RPC_METHODS = {
    "get_status",
    "get_control_state",
    "get_settings",
    "save_settings",
    "scan",
    "connect",
    "set_connection_enabled",
    "disconnect",
    "desktop_disconnect",
    "refresh_now",
    "send_module",
    "send_dashboard",
    "send_clock",
    "send_weather",
    "set_mode",
    "set_timeline_sec",
    "set_auto_refresh",
    "set_photo_frame_folder",
    "import_photo_frame_asset",
    "list_photo_frame_files",
    "exclude_photo_frame_file",
    "set_photo_frame_selected_file",
    "list_user_files",
    "list_custom_assets",
    "import_custom_asset",
    "delete_custom_asset",
    "set_custom_selected_path",
    "set_custom_slideshow_enabled",
    "send_custom_file",
    "send_next_custom_file",
    "get_ip_location",
    "get_display_options",
    "get_weather_location_options",
    "search_weather_locations",
    "get_module_data",
    "set_module_data",
    "get_agent_status",
    "set_agent_status",
    "clear_agent_status",
}

CONTROL_STATE_MUTATION_METHODS = frozenset(
    {
        "save_settings",
        "connect",
        "set_connection_enabled",
        "disconnect",
        "desktop_disconnect",
        "send_module",
        "send_dashboard",
        "send_clock",
        "send_weather",
        "set_mode",
        "set_timeline_sec",
        "set_auto_refresh",
        "set_photo_frame_folder",
        "import_photo_frame_asset",
        "exclude_photo_frame_file",
        "set_photo_frame_selected_file",
        "import_custom_asset",
        "delete_custom_asset",
        "set_custom_selected_path",
        "set_custom_slideshow_enabled",
        "send_custom_file",
        "send_next_custom_file",
    }
)


class EventHub:
    def __init__(self) -> None:
        self._sockets: set[web.WebSocketResponse] = set()

    async def publish(self, event: str, payload: Any = None) -> None:
        message = {"event": event, "payload": payload}
        stale: list[web.WebSocketResponse] = []
        for socket in tuple(self._sockets):
            try:
                await socket.send_json(message)
            except (ConnectionError, RuntimeError):
                stale.append(socket)
        for socket in stale:
            self._sockets.discard(socket)

    def add(self, socket: web.WebSocketResponse) -> None:
        self._sockets.add(socket)

    def discard(self, socket: web.WebSocketResponse) -> None:
        self._sockets.discard(socket)

    async def close(self) -> None:
        sockets = tuple(self._sockets)
        self._sockets.clear()
        for socket in sockets:
            await socket.close(code=1001, message=b"daemon stopping")


EVENT_HUB_KEY = web.AppKey("event_hub", EventHub)
SETTINGS_DIR_KEY = web.AppKey("settings_dir", Path)
STATE_KEY = web.AppKey("state", dict)


class DeckyLoggerAdapter:
    def info(self, message: str, *args: Any) -> None:
        LOGGER.info(message, *args)

    def warning(self, message: str, *args: Any) -> None:
        LOGGER.warning(message, *args)

    def error(self, message: str, *args: Any) -> None:
        LOGGER.error(message, *args)


def resolve_settings_dir() -> Path:
    configured = os.environ.get("JSAUX_EINK_SETTINGS_DIR", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_SETTINGS_DIR


def load_core(event_hub: EventHub, settings_dir: Path):
    settings_dir.mkdir(parents=True, exist_ok=True)
    decky = types.ModuleType("decky")
    decky.DECKY_PLUGIN_SETTINGS_DIR = str(settings_dir)  # type: ignore[attr-defined]
    decky.logger = DeckyLoggerAdapter()  # type: ignore[attr-defined]
    decky.emit = event_hub.publish  # type: ignore[attr-defined]
    sys.modules["decky"] = decky

    backend = importlib.import_module("main")
    core = backend.EInkCore()
    core._daemon_control_mode = True
    return core


async def runtime_context(app: web.Application):
    event_hub = app[EVENT_HUB_KEY]
    core = app[STATE_KEY]["core"]
    if core is None:
        core = load_core(event_hub, app[SETTINGS_DIR_KEY])
        app[STATE_KEY]["core"] = core
    await core._main()
    app[STATE_KEY]["ready"] = True
    await event_hub.publish("daemon_ready", {"version": SERVICE_VERSION})
    try:
        yield
    finally:
        app[STATE_KEY]["ready"] = False
        await core._unload()
        await event_hub.close()


async def health_handler(request: web.Request) -> web.Response:
    app = request.app
    return web.json_response(
        {
            "ok": True,
            "service": SERVICE_NAME,
            "version": SERVICE_VERSION,
            "ready": bool(app[STATE_KEY]["ready"]),
            "pid": os.getpid(),
            "settings_dir": str(app[SETTINGS_DIR_KEY]),
        }
    )


async def get_control_state_snapshot(app: web.Application) -> dict[str, Any]:
    """Build the shared UI state without changing Bluetooth or persisted settings."""
    state = app[STATE_KEY]
    snapshot = dict(await state["core"].get_control_state())
    snapshot["epoch"] = str(state.get("control_state_epoch") or os.getpid())
    snapshot["revision"] = int(state.get("control_state_revision", 0) or 0)
    return snapshot


async def publish_control_state(app: web.Application) -> dict[str, Any]:
    """Broadcast the daemon-owned device and module state to every UI client."""
    state = app[STATE_KEY]
    state["control_state_revision"] = int(state.get("control_state_revision", 0) or 0) + 1
    snapshot = await get_control_state_snapshot(app)
    await app[EVENT_HUB_KEY].publish("control_state_update", snapshot)
    return snapshot


async def rpc_handler(request: web.Request) -> web.Response:
    method = request.match_info["method"]
    if method not in RPC_METHODS:
        return web.json_response(
            {"ok": False, "error": f"Unsupported RPC method: {method}"}, status=404
        )
    try:
        body = await request.json() if request.can_read_body else {}
        args = body.get("args", [])
        kwargs = body.get("kwargs", {})
        if not isinstance(args, list) or not isinstance(kwargs, dict):
            raise ValueError("RPC args must be a list and kwargs must be an object")
        if method == "get_control_state":
            result = await get_control_state_snapshot(request.app)
        else:
            target = getattr(request.app[STATE_KEY]["core"], method)
            result = await target(*args, **kwargs)
            if method in CONTROL_STATE_MUTATION_METHODS:
                await publish_control_state(request.app)
        return web.json_response({"ok": True, "result": result})
    except (json.JSONDecodeError, ValueError, TypeError) as error:
        return web.json_response({"ok": False, "error": str(error)}, status=400)
    except Exception as error:
        LOGGER.exception("RPC %s failed", method)
        return web.json_response(
            {"ok": False, "error": f"{type(error).__name__}: {error}"}, status=500
        )


@web.middleware
async def local_rpc_only_middleware(request: web.Request, handler):
    # Daemon is loopback-only; reject anything that is not localhost.
    if request.remote not in (None, "127.0.0.1", "::1"):
        return web.json_response({"ok": False, "error": "Local-only EInk RPC"}, status=403)
    return await handler(request)


async def events_handler(request: web.Request) -> web.WebSocketResponse:
    socket = web.WebSocketResponse(heartbeat=20.0)
    await socket.prepare(request)
    event_hub = request.app[EVENT_HUB_KEY]
    event_hub.add(socket)
    try:
        await socket.send_json(
            {
                "event": "daemon_ready",
                "payload": {
                    "version": SERVICE_VERSION,
                    "ready": bool(request.app[STATE_KEY]["ready"]),
                },
            }
        )
        status = await request.app[STATE_KEY]["core"].get_status()
        await socket.send_json({"event": "status_update", "payload": status})
        control_state = await get_control_state_snapshot(request.app)
        await socket.send_json({"event": "control_state_update", "payload": control_state})
        async for message in socket:
            if message.type == WSMsgType.TEXT and message.data == "ping":
                await socket.send_str("pong")
            elif message.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                break
    finally:
        event_hub.discard(socket)
    return socket


def create_app(core: Any = None, settings_dir: Optional[Path] = None) -> web.Application:
    app = web.Application(client_max_size=2 * 1024 * 1024, middlewares=[local_rpc_only_middleware])
    app[EVENT_HUB_KEY] = EventHub()
    app[SETTINGS_DIR_KEY] = settings_dir or resolve_settings_dir()
    app[STATE_KEY] = {
        "core": core,
        "ready": False,
        "control_state_revision": 0,
        "control_state_epoch": f"{os.getpid()}-{id(app)}",
    }
    app.cleanup_ctx.append(runtime_context)
    app.router.add_get("/v1/health", health_handler)
    app.router.add_get("/v1/events", events_handler)
    app.router.add_post("/v1/rpc/{method}", rpc_handler)
    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="JSAUX E-INK local daemon")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", default=DEFAULT_PORT, type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    host = args.host
    if host != DEFAULT_HOST:
        raise SystemExit("EInk daemon host must be 127.0.0.1 (local ingest / LAN bind removed)")
    web.run_app(
        create_app(),
        host=host,
        port=args.port,
        handle_signals=True,
        print=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
