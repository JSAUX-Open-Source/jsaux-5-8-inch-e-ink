from __future__ import annotations

import asyncio
import inspect
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

PLUGIN_ROOT = Path(__file__).resolve().parent
PY_MODULES = PLUGIN_ROOT / "py_modules"
try:
    import aiohttp
except ModuleNotFoundError:
    if str(PY_MODULES) not in sys.path:
        sys.path.insert(0, str(PY_MODULES))
    import aiohttp


DEFAULT_HTTP_URL = os.environ.get("JSAUX_EINK_DAEMON_URL", "http://127.0.0.1:39062").rstrip("/")
DEFAULT_WS_URL = os.environ.get("JSAUX_EINK_DAEMON_WS", "ws://127.0.0.1:39062/v1/events")
DAEMON_SERVICE = "jsaux-eink-daemon.service"


class DaemonUnavailableError(RuntimeError):
    pass


EventCallback = Callable[[str, Any], Optional[Awaitable[None]]]


class AsyncDaemonClient:
    def __init__(
        self,
        base_url: str = DEFAULT_HTTP_URL,
        ws_url: str = DEFAULT_WS_URL,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url
        self._session: Optional[aiohttp.ClientSession] = None
        self._event_task: Optional[asyncio.Task] = None
        self._closed = False

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._closed:
            raise DaemonUnavailableError("EInk daemon client is closed")
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def health(self, timeout: float = 3.0) -> dict[str, Any]:
        session = await self._get_session()
        try:
            async with session.get(
                f"{self.base_url}/v1/health",
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                payload = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            raise DaemonUnavailableError(f"EInk daemon unavailable: {error}") from error
        if response.status != 200 or not payload.get("ok"):
            raise DaemonUnavailableError(
                payload.get("error") or f"EInk daemon health returned {response.status}"
            )
        return payload

    async def wait_until_ready(self, timeout: float = 12.0) -> dict[str, Any]:
        """Wait for the user daemon to bind its loopback socket after resume/login."""
        deadline = asyncio.get_running_loop().time() + max(1.0, timeout)
        last_error: Exception | None = None
        while asyncio.get_running_loop().time() < deadline:
            try:
                remaining = max(0.5, deadline - asyncio.get_running_loop().time())
                return await self.health(timeout=min(2.0, remaining))
            except DaemonUnavailableError as error:
                last_error = error
                await asyncio.sleep(0.35)
        if last_error is not None:
            raise last_error
        raise DaemonUnavailableError("EInk daemon did not become ready")

    async def call(
        self,
        method: str,
        *args: Any,
        timeout: float = 180.0,
        **kwargs: Any,
    ) -> Any:
        session = await self._get_session()
        try:
            async with session.post(
                f"{self.base_url}/v1/rpc/{method}",
                json={"args": list(args), "kwargs": kwargs},
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                payload = await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            raise DaemonUnavailableError(f"EInk daemon unavailable: {error}") from error
        if response.status != 200 or not payload.get("ok"):
            raise RuntimeError(
                payload.get("error") or f"Daemon RPC {method} failed with HTTP {response.status}"
            )
        return payload.get("result")

    async def start_events(self, callback: EventCallback) -> None:
        if self._event_task and not self._event_task.done():
            return
        self._event_task = asyncio.create_task(self._event_loop(callback))

    async def _event_loop(self, callback: EventCallback) -> None:
        while not self._closed:
            try:
                session = await self._get_session()
                async with session.ws_connect(self.ws_url, heartbeat=20.0) as socket:
                    async for message in socket:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            payload = message.json()
                            event = str(payload.get("event") or "")
                            if not event:
                                continue
                            pending = callback(event, payload.get("payload"))
                            if inspect.isawaitable(pending):
                                await pending
                        elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
            except asyncio.CancelledError:
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                if not self._closed:
                    await asyncio.sleep(1.0)

    async def close(self) -> None:
        self._closed = True
        event_task = self._event_task
        self._event_task = None
        if event_task and not event_task.done():
            event_task.cancel()
            try:
                await event_task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def get_status(self) -> dict[str, Any]:
        return await self.call("get_status", timeout=10)

    async def get_control_state(self) -> dict[str, Any]:
        return dict(await self.call("get_control_state", timeout=10) or {})

    async def get_settings(self) -> dict[str, Any]:
        return await self.call("get_settings", timeout=10)

    async def save_settings(self, values: dict[str, Any]) -> bool:
        return bool(await self.call("save_settings", values, timeout=30))

    async def scan(self) -> list[dict[str, Any]]:
        return list(await self.call("scan", timeout=60) or [])

    async def connect(self, address: str) -> bool:
        return bool(await self.call("connect", address, timeout=90))

    async def set_connection_enabled(self, enabled: bool) -> bool:
        return bool(await self.call("set_connection_enabled", enabled, timeout=30))

    async def disconnect(self) -> bool:
        return bool(await self.call("disconnect", timeout=30))

    async def desktop_disconnect(self) -> bool:
        return bool(await self.call("desktop_disconnect", timeout=30))

    async def send_module(self, module_id: int) -> bool:
        return bool(await self.call("send_module", module_id, timeout=180))

    async def send_dashboard(self) -> bool:
        return bool(await self.call("send_dashboard", timeout=180))

    async def send_clock(self) -> bool:
        return bool(await self.call("send_clock", timeout=180))

    async def send_weather(self, latitude: float, longitude: float) -> bool:
        return bool(await self.call("send_weather", latitude, longitude, timeout=180))

    async def refresh_now(self) -> bool:
        return bool(await self.call("refresh_now", timeout=180))

    async def set_mode(self, mode: str, interval: int) -> bool:
        return bool(await self.call("set_mode", mode, interval, timeout=30))

    async def set_timeline_sec(self, seconds: int) -> bool:
        return bool(await self.call("set_timeline_sec", seconds, timeout=30))

    async def set_photo_frame_folder(self, folder_path: str) -> bool:
        return bool(await self.call("set_photo_frame_folder", folder_path, timeout=30))

    async def import_photo_frame_asset(self, source_path: str) -> dict[str, Any]:
        return dict(await self.call("import_photo_frame_asset", source_path, timeout=60) or {})

    async def list_photo_frame_files(self) -> list[dict[str, Any]]:
        return list(await self.call("list_photo_frame_files", timeout=30) or [])

    async def exclude_photo_frame_file(self, path: str) -> bool:
        return bool(await self.call("exclude_photo_frame_file", path, timeout=30))

    async def set_photo_frame_selected_file(self, path: str) -> bool:
        return bool(await self.call("set_photo_frame_selected_file", path, timeout=30))

    async def list_user_files(self, directory: str = "") -> list[dict[str, Any]]:
        return list(await self.call("list_user_files", directory, timeout=60) or [])

    async def import_custom_asset(self, source_path: str) -> dict[str, Any]:
        return dict(await self.call("import_custom_asset", source_path, timeout=60) or {})

    async def delete_custom_asset(self, path: str) -> bool:
        return bool(await self.call("delete_custom_asset", path, timeout=30))

    async def set_custom_selected_path(self, path: str) -> bool:
        return bool(await self.call("set_custom_selected_path", path, timeout=30))

    async def set_custom_slideshow_enabled(self, enabled: bool) -> bool:
        return bool(await self.call("set_custom_slideshow_enabled", enabled, timeout=30))

    async def send_custom_file(self, path: str, title: str = "") -> bool:
        return bool(await self.call("send_custom_file", path, title, timeout=180))

    async def get_agent_status(self) -> dict[str, Any]:
        return dict(await self.call("get_agent_status", timeout=10) or {})

    async def set_agent_status(self, event: dict[str, Any]) -> dict[str, Any]:
        return dict(await self.call("set_agent_status", event, timeout=30) or {})

    async def clear_agent_status(self) -> bool:
        return bool(await self.call("clear_agent_status", timeout=30))

    async def get_ip_location(self) -> dict[str, Any]:
        return dict(await self.call("get_ip_location", timeout=30) or {})

    async def get_display_options(self) -> dict:
        return dict(await self.call("get_display_options", timeout=10) or {})

    async def get_weather_location_options(
        self,
        country_code: str = "",
        query: str = "",
        offset: int = 0,
        limit: int = 40,
        language: str = "en",
    ) -> dict:
        return dict(
            await self.call(
                "get_weather_location_options",
                country_code,
                query,
                offset,
                limit,
                language,
                timeout=10,
            )
            or {}
        )

    async def search_weather_locations(
        self, query: str, language: str = "en", country_code: str = ""
    ) -> list:
        return list(
            await self.call("search_weather_locations", query, language, country_code, timeout=15)
            or []
        )


def request_daemon_start() -> None:
    try:
        subprocess.run(
            ["systemctl", "--user", "start", DAEMON_SERVICE],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        pass


class DaemonPluginBridge:
    def __init__(self) -> None:
        self._client = AsyncDaemonClient()
        self._decky = None
        self._last_error = ""
        self._last_status: dict[str, Any] = {}

    async def _main(self) -> None:
        import decky

        self._decky = decky
        request_daemon_start()
        await self._client.start_events(self._forward_event)
        try:
            await self._client.wait_until_ready()
            status = await self._client.get_status()
        except Exception as error:
            self._last_error = str(error)
            status = self._offline_status()
        else:
            self._last_status = dict(status)
        await decky.emit("status_update", status)

    async def _unload(self) -> None:
        await self._client.close()

    async def _forward_event(self, event: str, payload: Any) -> None:
        if event == "status_update" and isinstance(payload, dict):
            self._last_status = dict(payload)
        if self._decky is not None:
            await self._decky.emit(event, payload)

    def _offline_status(self) -> dict[str, Any]:
        if self._last_status:
            status = dict(self._last_status)
            status["connected"] = False
            status["connection_state"] = "off"
            status["last_error"] = self._last_error or "EInk daemon unavailable"
            status["daemon_available"] = False
            return status
        return {
            "connected": False,
            "connection_enabled": False,
            "connection_state": "off",
            "configured": False,
            "address": "",
            "battery": 0,
            "width": 0,
            "height": 0,
            "color_count": 0,
            "last_error": self._last_error or "EInk daemon unavailable",
            "render_ready": False,
            "daemon_available": False,
        }

    async def get_status(self) -> dict[str, Any]:
        try:
            status = await self._client.get_status()
            status["daemon_available"] = True
            self._last_status = dict(status)
            self._last_error = ""
            return status
        except Exception as error:
            self._last_error = str(error)
            return self._offline_status()

    async def get_control_state(self) -> dict[str, Any]:
        try:
            return await self._client.get_control_state()
        except Exception as error:
            self._last_error = str(error)
            return {"status": self._offline_status(), "settings": {}}

    async def get_settings(self) -> dict[str, Any]:
        try:
            return await self._client.get_settings()
        except Exception as error:
            self._last_error = str(error)
            return {}

    async def scan(self) -> list[dict[str, Any]]:
        return await self._client.scan()

    async def connect(self, address: str) -> bool:
        return await self._client.connect(address)

    async def set_connection_enabled(self, enabled: bool) -> bool:
        return await self._client.set_connection_enabled(enabled)

    async def disconnect(self) -> bool:
        return await self._client.disconnect()

    async def save_settings(self, values: dict[str, Any]) -> bool:
        return await self._client.save_settings(values)

    async def set_mode(self, mode: str, interval: int) -> bool:
        return await self._client.set_mode(mode, interval)

    async def set_timeline_sec(self, seconds: int) -> bool:
        return await self._client.set_timeline_sec(seconds)

    async def set_photo_frame_folder(self, folder_path: str) -> bool:
        return await self._client.set_photo_frame_folder(folder_path)

    async def import_photo_frame_asset(self, source_path: str) -> dict[str, Any]:
        return await self._client.import_photo_frame_asset(source_path)

    async def list_photo_frame_files(self) -> list[dict[str, Any]]:
        return await self._client.list_photo_frame_files()

    async def exclude_photo_frame_file(self, path: str) -> bool:
        return await self._client.exclude_photo_frame_file(path)

    async def set_photo_frame_selected_file(self, path: str) -> bool:
        return await self._client.set_photo_frame_selected_file(path)

    async def refresh_now(self) -> bool:
        return await self._client.refresh_now()

    async def send_module(self, module_id: int) -> bool:
        return await self._client.send_module(module_id)

    async def send_dashboard(self) -> bool:
        return await self._client.send_dashboard()

    async def send_clock(self) -> bool:
        return await self._client.send_clock()

    async def send_weather(self, latitude: float, longitude: float) -> bool:
        return await self._client.send_weather(latitude, longitude)

    async def list_user_files(self, directory: str = "") -> list[dict[str, Any]]:
        return await self._client.list_user_files(directory)

    async def import_custom_asset(self, source_path: str) -> dict[str, Any]:
        return await self._client.import_custom_asset(source_path)

    async def delete_custom_asset(self, path: str) -> bool:
        return await self._client.delete_custom_asset(path)

    async def set_custom_selected_path(self, path: str) -> bool:
        return await self._client.set_custom_selected_path(path)

    async def set_custom_slideshow_enabled(self, enabled: bool) -> bool:
        return await self._client.set_custom_slideshow_enabled(enabled)

    async def send_custom_file(self, path: str, title: str = "") -> bool:
        return await self._client.send_custom_file(path, title)

    async def get_ip_location(self) -> dict[str, Any]:
        return await self._client.get_ip_location()

    async def get_display_options(self) -> dict:
        return await self._client.get_display_options()

    async def get_weather_location_options(
        self,
        country_code: str = "",
        query: str = "",
        offset: int = 0,
        limit: int = 40,
        language: str = "en",
    ) -> dict:
        return await self._client.get_weather_location_options(
            country_code, query, offset, limit, language
        )

    async def search_weather_locations(
        self, query: str, language: str = "en", country_code: str = ""
    ) -> list:
        return await self._client.search_weather_locations(query, language, country_code)
