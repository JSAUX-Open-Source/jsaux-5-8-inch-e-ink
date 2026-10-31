"""JSAUX E-INK Decky Loader Plugin Backend v1.2"""

from __future__ import annotations

import asyncio
import base64
import fcntl
import importlib
import io
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import time
import uuid
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional

# Bootstrap offline wheels BEFORE bleak/httpx/local protocol imports.
# isort: off
plugin_dir = os.path.dirname(os.path.realpath(__file__))
if plugin_dir not in sys.path:
    sys.path.insert(0, plugin_dir)
py_modules_dir = os.path.join(plugin_dir, "py_modules")
if py_modules_dir not in sys.path:
    sys.path.insert(0, py_modules_dir)

pillow_libs = os.path.join(py_modules_dir, "pillow.libs")
if os.path.isdir(pillow_libs):
    import ctypes

    for lib_file in sorted(os.listdir(pillow_libs)):
        if ".so" in lib_file:
            try:
                ctypes.CDLL(os.path.join(pillow_libs, lib_file), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass

import decky

# Decky's runtime can preload an incompatible Pillow from the user site-packages.
# Drop any cached PIL modules so imports resolve from this plugin's bundled wheels.
for _mod in tuple(sys.modules):
    if _mod == "PIL" or _mod.startswith("PIL."):
        sys.modules.pop(_mod, None)

_stdlib_path = sysconfig.get_paths().get("stdlib", "")
if _stdlib_path and _stdlib_path not in sys.path:
    sys.path.append(_stdlib_path)

import xml

_xml_in_pymod = os.path.join(py_modules_dir, "xml")
for _p in [_xml_in_pymod, os.path.join(_stdlib_path, "xml") if _stdlib_path else ""]:
    if os.path.isdir(_p) and _p not in xml.__path__:
        xml.__path__.insert(0, _p)
import xml.etree
import xml.etree.ElementTree

from bleak import BleakClient, BleakScanner
from bleak.backends.bluezdbus.manager import get_global_bluez_manager
from bleak.backends.device import BLEDevice

# httpcore versions bundled in older V1.2 payloads mutate typing.Union and
# fail on SteamOS Python 3.14 before the first weather request. Prefer the
# SteamOS-maintained httpx/httpcore pair on 3.14+, while retaining the offline
# bundle as a fallback for older images without a system httpx installation.
if sys.version_info >= (3, 14):
    _saved_python_path = list(sys.path)
    while py_modules_dir in sys.path:
        sys.path.remove(py_modules_dir)
    try:
        httpx = importlib.import_module("httpx")
        # Import the matching transport while the bundle is hidden as well.
        # Otherwise httpx can be imported from the system image but resolve
        # its lazy httpcore dependency from this plugin's Python 3.11 wheel
        # after sys.path is restored.
        importlib.import_module("httpcore")
    except ModuleNotFoundError:
        sys.path[:] = _saved_python_path
        httpx = importlib.import_module("httpx")
        importlib.import_module("httpcore")
    finally:
        sys.path[:] = _saved_python_path
else:
    import httpx

from agent_status import read_codex_status
from agent_status import format_agent_number, is_agent_active, normalize_agent_event
from ble_lease import (
    SharedBleAdapterLease,
    claim_foreground_ble_priority,
    clear_foreground_ble_priority,
    desktop_lease_active,
    shared_ble_operation,
)
from daemon_client import DaemonPluginBridge
from device_identity import (
    TARGET_COLOR_MODE,
    TARGET_IS_DUAL_SCREEN,
    TARGET_SCREEN_H,
    TARGET_SCREEN_W,
)
from display_preferences import DEFAULTS as DISPLAY_DEFAULTS
from display_preferences import SETTING_KEYS as DISPLAY_SETTING_KEYS
from display_preferences import WEATHER_KEYS as WEATHER_SETTING_KEYS
from display_preferences import clock_parts, display_now
from display_preferences import options as display_options
from display_preferences import render_context
from display_preferences import validate_update as validate_display_update
from display_preferences import weather_now, with_context
from eink_display import (
    CMD_QUERY_INFO,
    CMD_SEND_DATA,
    DISPLAY_A,
    DISPLAY_AB,
    FOOTER_CMD,
    HEADER_CMD,
    NOTIFY_UUID,
    SERVICE_UUID,
    WRITE_UUID,
    DataAckStatus,
    DeviceInfo,
    build_display_data_packet,
    build_query_info_command,
    data_ack_status,
    parse_device_info_payload,
    parse_response_frame,
)
from weather_locations import location_options as weather_location_options

# isort: on

Image = None
ImageDraw = None
ImageFont = None
_PILLOW_IMPORT_ERROR = ""

def _prefer_plugin_python_paths() -> None:
    preferred = [plugin_dir, py_modules_dir]
    for path in preferred:
        while path in sys.path:
            sys.path.remove(path)
    for path in reversed(preferred):
        sys.path.insert(0, path)


def _ensure_pillow() -> None:
    global Image, ImageDraw, ImageFont, _PILLOW_IMPORT_ERROR
    if Image is not None and ImageDraw is not None and ImageFont is not None:
        return

    _prefer_plugin_python_paths()
    for _mod in tuple(sys.modules):
        if _mod == "PIL" or _mod.startswith("PIL."):
            sys.modules.pop(_mod, None)

    try:
        from PIL import Image as pil_image
        from PIL import ImageDraw as pil_image_draw
        from PIL import ImageFont as pil_image_font
    except Exception as exc:
        _PILLOW_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        raise RuntimeError(_PILLOW_IMPORT_ERROR) from exc

    Image = pil_image
    ImageDraw = pil_image_draw
    ImageFont = pil_image_font
    _PILLOW_IMPORT_ERROR = ""


def _get_render_helper_python() -> str:
    executable = (sys.executable or "").strip()
    if executable:
        exe_name = Path(executable).name.lower()
        if exe_name.startswith("python"):
            return executable

    for candidate in ("/usr/bin/python3", "python3"):
        if candidate.startswith("/") and Path(candidate).exists():
            return candidate
        if not candidate.startswith("/"):
            return candidate

    return executable or "python3"


# ──────────────────────────────────────────────
# Layout & constants
# ──────────────────────────────────────────────
SCREEN_W = 648
SCREEN_H = 480
CUSTOM_THUMBNAIL_W = 208
CUSTOM_THUMBNAIL_H = 154
FW_VERSION = "V1.2"
HW_DESC = "E-INK"

BLE_SCAN_TIMEOUT_SEC = 10.0
BLE_SCAN_RETRY_DELAY_SEC = 3.0
MANUAL_BLE_SCAN_TOTAL_TIMEOUT_SEC = 30.0
MANUAL_BLE_SCAN_TIMEOUT_SEC = 12.0
MANUAL_BLE_SCAN_LEASE_TIMEOUT_SEC = 8.0
MANUAL_BLE_SCAN_LOCK_TIMEOUT_SEC = 8.0
FOREGROUND_BLE_WAIT_TIMEOUT_SEC = 45.0
STARTUP_SAVED_CONNECT_TIMEOUT_SEC = 8.0
DESKTOP_LEASE_POLL_SEC = 1.0
CONNECTION_RETRY_DELAY_SEC = 30.0
# A failed BLE transfer must not depend on a manual scan to recover. Keep the
# retries bounded, spaced out, and serialized through the existing BLE lock.
CONNECTION_RETRY_DELAYS_SEC = (5.0, 15.0, 30.0, 60.0)
BLE_DISCONNECT_SETTLE_SEC = 0.8
BLE_CANCEL_DRAIN_TIMEOUT_SEC = 8.0
CONNECTION_STATE_OFF = "off"
CONNECTION_STATE_CONNECTING = "connecting"
CONNECTION_STATE_ON = "on"
MAX_DEVICE_CANDIDATES = 12
BLE_NEARBY_DISTANCE_LIMIT_M = 2.0
BLE_NEARBY_RSSI_THRESHOLD = -68
BLE_DEFAULT_TX_POWER_DBM = -60
BLE_PATH_LOSS_EXPONENT = 2.0
BLE_DISPLAY_SERVICE_UUIDS = {
    SERVICE_UUID.lower(),
}


def _remaining_manual_scan_budget(started_at: float) -> float:
    elapsed = max(0.0, time.monotonic() - float(started_at))
    return max(0.0, MANUAL_BLE_SCAN_TOTAL_TIMEOUT_SEC - elapsed)


# [x, y, w, h] for each module on the dashboard
MODULE_RECTS = [
    (0, 0, 648, 60),  # P0 status bar
    (0, 60, 320, 100),  # P1 game
    (320, 60, 328, 100),  # P2 performance
    (0, 160, 216, 120),  # P3 weather
    (216, 160, 216, 120),  # P4 monohub
    (432, 160, 216, 120),  # P5 calendar
    (0, 280, 648, 200),  # P6 custom
]

# Watermark [x, y, text] per module
WATERMARKS = [
    (576, 47, "Jsaux"),
    (232, 143, "Jsaux Gaming"),
    (548, 143, "Jsaux Gaming"),
    (140, 263, "Gaming E-Ink"),
    (356, 263, "Gaming E-Ink"),
    (572, 263, "Gaming E-Ink"),
    (576, 462, "Jsaux"),
]

GRAY_WM = (170, 170, 170)
GRAY_BORDER = (120, 120, 120)
LIGHT_BORDER = (175, 175, 175)
TIMELINE_DEFAULT_SEC = 300
TIMELINE_MIN_SEC = 300
TIMELINE_MAX_SEC = 3600
CUSTOM_SLIDESHOW_INTERVAL_MIN = 5
CUSTOM_SLIDESHOW_INTERVAL_SEC = CUSTOM_SLIDESHOW_INTERVAL_MIN * 60
PHOTO_FRAME_INTERVAL_MIN = 1
PHOTO_FRAME_INTERVAL_MAX = 60
PHOTO_FRAME_INTERVAL_DEFAULT = 5
MODULE_SWITCH_INTERVAL_MIN = 5
MODULE_SWITCH_INTERVAL_MAX = 60
MODULE_SWITCH_INTERVAL_STEP = 5
MODULE_SWITCH_INTERVAL_DEFAULT = 5
PHOTO_FRAME_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"})
GAME_TIME_DISPLAY_MODES = ("time", "poster", "auto")
GAME_TIME_POSTER_REFRESH_SEC = 5 * 60
GAME_ARTWORK_CACHE_DIR_NAME = "game-artwork"
GAME_ARTWORK_NETWORK_TIMEOUT_SEC = 8.0
POSTER_SCALE = 1.8
POSTER_CONTENT_SHIFT_PX = 82
MODULE_SWITCH_MODULE_IDS = (0, 4, 3, 1, 2, 5)
AGENT_MODULE_ID = 7
AGENT_RESULT_HOLD_SEC = 30.0
AGENT_MODULE_ID = 7
AGENT_RESULT_HOLD_SEC = 30.0
# Display update cadence is kept separate from data freshness.  A BLE session is
# created only for the scheduled frame transfer and released after its ACKs.
LIVE_DISPLAY_REFRESH_SEC = 60
WEATHER_DISPLAY_REFRESH_SEC = 4 * 60 * 60
CALENDAR_DISPLAY_REFRESH_SEC = 12 * 60 * 60
GAME_PROGRESS_REFRESH_SEC = LIVE_DISPLAY_REFRESH_SEC
CALENDAR_REFRESH_SEC = CALENDAR_DISPLAY_REFRESH_SEC
WEATHER_REFRESH_SEC = WEATHER_DISPLAY_REFRESH_SEC
IP_LOCATION_REFRESH_SEC = 6 * 60 * 60
HARDWARE_SAMPLE_INTERVAL_SEC = 60.0
HARDWARE_HISTORY_MINUTES = 30
DISPLAY_CHARGING_HOLD_SEC = 15 * 60
DISPLAY_MODE_SEQUENCE = ("deck_status", "timeline", "clock", "weather")
NO_GAME_LABEL = "No Game"

WMO_CODES = {
    0: "Clear",
    1: "Mainly Clear",
    2: "Partly Cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime Fog",
    51: "Lt Drizzle",
    53: "Drizzle",
    55: "Hvy Drizzle",
    61: "Lt Rain",
    63: "Rain",
    65: "Hvy Rain",
    71: "Lt Snow",
    73: "Snow",
    75: "Hvy Snow",
    80: "Showers",
    81: "Showers",
    82: "Hvy Showers",
    95: "Thunderstorm",
    96: "T-storm+Hail",
    99: "Hvy T-storm",
}
WEEKDAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
FORECAST_WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")

# CLDR supplemental weekData territories whose first calendar day is Sunday.
# Regions not listed here use the CLDR Monday-first default for this module.
CLDR_SUNDAY_FIRST_TERRITORIES = frozenset(
    {
        "AG",
        "AS",
        "BD",
        "BR",
        "BS",
        "BT",
        "BW",
        "BZ",
        "CA",
        "CO",
        "DM",
        "DO",
        "ET",
        "GT",
        "GU",
        "HK",
        "HN",
        "ID",
        "IL",
        "IN",
        "JM",
        "JP",
        "KE",
        "KH",
        "KR",
        "LA",
        "MH",
        "MM",
        "MO",
        "MX",
        "MZ",
        "NI",
        "NP",
        "PA",
        "PE",
        "PH",
        "PK",
        "PR",
        "PT",
        "PY",
        "SA",
        "SG",
        "SV",
        "TH",
        "TT",
        "TW",
        "UM",
        "US",
        "VE",
        "VI",
        "WS",
        "YE",
        "ZA",
        "ZW",
    }
)


def _normalize_country_code(value: object) -> str:
    country = str(value or "").strip().upper()
    return country if re.fullmatch(r"[A-Z]{2}", country) else ""


def _country_from_locale_value(locale_value: object) -> str:
    value = str(locale_value or "").strip()
    if re.fullmatch(r"[A-Z]{2}", value):
        return value
    value = value.split(".", 1)[0].split("@", 1)[0]
    for part in reversed(re.split(r"[_-]", value)[1:]):
        country = _normalize_country_code(part)
        if country:
            return country
    return ""


def _system_locale_country() -> str:
    for variable in ("LC_ALL", "LC_TIME", "LANG"):
        country = _country_from_locale_value(os.environ.get(variable, ""))
        if country:
            return country
    try:
        result = subprocess.run(
            ["localectl", "status"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in result.stdout.splitlines():
        if "System Locale:" not in line:
            continue
        country = _country_from_locale_value(line)
        if country:
            return country
    return ""


def _resolve_calendar_country(
    ip_country: object = "", locale_value: Optional[object] = None
) -> str:
    country = _normalize_country_code(ip_country)
    if country:
        return country
    if locale_value is not None:
        return _country_from_locale_value(locale_value)
    return _system_locale_country()


def _calendar_first_weekday(country_code: object = "") -> int:
    import calendar as cal_mod

    if _normalize_country_code(country_code) in CLDR_SUNDAY_FIRST_TERRITORIES:
        return cal_mod.SUNDAY
    return cal_mod.MONDAY


def _calendar_month_layout(
    year: int, month: int, country_code: object = ""
) -> tuple[list[str], list[list[int]]]:
    import calendar as cal_mod

    first_weekday = _calendar_first_weekday(country_code)
    weekdays = WEEKDAYS_SHORT[first_weekday:] + WEEKDAYS_SHORT[:first_weekday]
    weeks = cal_mod.Calendar(firstweekday=first_weekday).monthdayscalendar(year, month)
    return weekdays, weeks


def _parse_device_info_payload(raw: bytes) -> Optional[DeviceInfo]:
    """Delegate device-info parsing to the closed protocol package."""
    return parse_device_info_payload(raw)


# ──────────────────────────────────────────────
# Fonts (lazy init)
# ──────────────────────────────────────────────
_F: Dict[int, ImageFont.FreeTypeFont] = {}
_FR: Dict[int, ImageFont.FreeTypeFont] = {}
_CPU_SAMPLE: Optional[tuple[int, int]] = None


def _new_hardware_history() -> dict[str, deque]:
    return {
        "cpu": deque(maxlen=HARDWARE_HISTORY_MINUTES),
        "gpu": deque(maxlen=HARDWARE_HISTORY_MINUTES),
        "ram": deque(maxlen=HARDWARE_HISTORY_MINUTES),
    }


def _get_font(size: int) -> ImageFont.FreeTypeFont:
    _ensure_pillow()
    if size in _F:
        return _F[size]
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in paths:
        try:
            _F[size] = ImageFont.truetype(p, size)
            return _F[size]
        except Exception:
            pass
    _F[size] = ImageFont.load_default()
    return _F[size]


def F(pt):
    return _get_font(pt)


def _get_font_regular(size: int) -> ImageFont.FreeTypeFont:
    _ensure_pillow()
    if size in _FR:
        return _FR[size]
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for p in paths:
        try:
            _FR[size] = ImageFont.truetype(p, size)
            return _FR[size]
        except Exception:
            pass
    _FR[size] = ImageFont.load_default()
    return _FR[size]


def FR(pt):
    return _get_font_regular(pt)


def _weather_value_font(text: str, size: int, width: int):
    for point_size in range(size, 3, -1):
        font = FR(point_size)
        bounds = font.getbbox(str(text))
        if bounds[2] - bounds[0] <= width:
            return font
    return FR(4)


def _city_font(name: object, size: int):
    return _get_agent_font(size) if any(ord(char) > 127 for char in str(name)) else FR(size)


def _city_label(name: object, size: int, width: int) -> str:
    label = str(name or "")
    font = _city_font(label, size)
    if font.getlength(label) <= width:
        return label
    while label and font.getlength(label + "...") > width:
        label = label[:-1]
    return label + "..."


DISPLAY_BATTERY_BOX = (588, 22, 626, 39)
DISPLAY_BATTERY_RENDER_MODES = frozenset(("dashboard", "clock", "weather", "module"))


def _normalise_display_battery_snapshot(percent, is_charging, updated_at=None):
    if percent is None:
        return {"batteryPercent": None, "isCharging": False, "updatedAt": None}
    try:
        value = max(0, min(100, int(percent)))
    except (TypeError, ValueError):
        return {"batteryPercent": None, "isCharging": False, "updatedAt": None}
    # Charging cannot be inferred reliably from the display protocol.
    return {
        "batteryPercent": value,
        "isCharging": False,
        "updatedAt": updated_at,
    }


def _with_display_battery_snapshot(data: dict, percent, is_charging, updated_at=None) -> dict:
    payload = dict(data) if isinstance(data, dict) else {}
    payload["_display_battery_snapshot"] = _normalise_display_battery_snapshot(
        percent,
        is_charging,
        updated_at,
    )
    return payload


def _battery_text(snapshot) -> str:
    value = snapshot.get("batteryPercent")
    return "--" if value is None else str(value)


def _battery_fill_width(snapshot, body_width: int) -> int:
    value = snapshot.get("batteryPercent")
    return 0 if value is None else int(max(0, int(body_width)) * value / 100)


def _draw_display_battery(image, draw, snapshot) -> None:
    snapshot = _normalise_display_battery_snapshot(
        snapshot.get("batteryPercent") if isinstance(snapshot, dict) else None,
        snapshot.get("isCharging") if isinstance(snapshot, dict) else False,
        snapshot.get("updatedAt") if isinstance(snapshot, dict) else None,
    )
    x0, y0, x1, y1 = DISPLAY_BATTERY_BOX
    body_right = x1 - 5
    interior_left, interior_top = x0 + 2, y0 + 2
    interior_right, interior_bottom = body_right - 2, y1 - 2
    interior_width = max(0, interior_right - interior_left + 1)

    draw.rounded_rectangle(
        [x0, y0, body_right, y1],
        radius=3,
        fill="white",
        outline="black",
        width=1,
    )
    terminal_top = y0 + max(4, (y1 - y0) // 3)
    terminal_bottom = y1 - max(4, (y1 - y0) // 3)
    draw.rounded_rectangle(
        [body_right, terminal_top, x1, terminal_bottom],
        radius=1,
        fill="white",
        outline="black",
        width=1,
    )

    fill_width = _battery_fill_width(snapshot, interior_width)
    if fill_width > 0:
        draw.rectangle(
            [interior_left, interior_top, interior_left + fill_width - 1, interior_bottom],
            fill="black",
        )

    glyph_width = max(1, interior_width)
    glyph_height = max(1, interior_bottom - interior_top + 1)
    glyph_mask = Image.new("L", (glyph_width, glyph_height), 0)
    glyph_draw = ImageDraw.Draw(glyph_mask)
    label = _battery_text(snapshot)
    font = FR(10)
    label_box = font.getbbox(label)
    label_width = max(1, label_box[2] - label_box[0])
    label_height = max(1, label_box[3] - label_box[1])
    has_lightning = bool(snapshot["isCharging"] and snapshot["batteryPercent"] is not None)
    lightning_size = 7 if has_lightning else 0
    group_width = lightning_size + (2 if has_lightning else 0) + label_width
    group_x = max(0, (glyph_width - group_width) // 2)
    label_x = group_x + lightning_size + (2 if has_lightning else 0)
    label_y = max(0, (glyph_height - label_height) // 2 - label_box[1])
    if has_lightning:
        _draw_lightning_icon(
            glyph_draw,
            group_x,
            max(0, (glyph_height - lightning_size) // 2),
            size=lightning_size,
            fill=255,
        )
    glyph_draw.text((label_x, label_y), label, fill=255, font=font)
    image.paste("black", (interior_left, interior_top), glyph_mask)

    if fill_width > 0:
        white_mask = Image.new("L", glyph_mask.size, 0)
        white_mask.paste(
            glyph_mask.crop((0, 0, min(fill_width, glyph_width), glyph_height)),
            (0, 0),
        )
        image.paste("white", (interior_left, interior_top), white_mask)


# ──────────────────────────────────────────────


def _display_battery_snapshot_from_payload(data: dict) -> dict:
    raw = data.get("_display_battery_snapshot") if isinstance(data, dict) else None
    if not isinstance(raw, dict):
        return _normalise_display_battery_snapshot(None, False)
    return _normalise_display_battery_snapshot(
        raw.get("batteryPercent"),
        raw.get("isCharging"),
        raw.get("updatedAt"),
    )


def _year_progress_snapshot(now: datetime) -> dict:
    year_start = datetime(now.year, 1, 1)
    next_year_start = datetime(now.year + 1, 1, 1)
    day_number = (now.date() - year_start.date()).days + 1
    total_days = (next_year_start.date() - year_start.date()).days
    return {
        "day": f"{day_number} / {total_days}",
        "week": f"{now.isocalendar().week} / {datetime(now.year, 12, 28).isocalendar().week}",
    }


# Draw helpers
# ──────────────────────────────────────────────
def _wm(draw, idx):
    x, y, text = WATERMARKS[idx]
    draw.text((x, y), text, fill=GRAY_WM, font=F(11))


def _hline(draw, y, x0=0, x1=SCREEN_W, w=1, color=GRAY_BORDER):
    draw.line([(x0, y), (x1, y)], fill=color, width=w)


def _vline(draw, x, y0=0, y1=SCREEN_H, w=1, color=GRAY_BORDER):
    draw.line([(x, y0), (x, y1)], fill=color, width=w)


def _bar(draw, x, y, w, h, pct, fill="black"):
    draw.rectangle([x, y, x + w, y + h], outline="black", width=1)
    fw = int((w - 2) * max(0, min(100, pct)) / 100)
    if fw > 0:
        draw.rectangle([x + 1, y + 1, x + 1 + fw, y + h - 1], fill=fill)


def _center_text(draw, text, y, font, x0=0, w=SCREEN_W, fill="black"):
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    draw.text((x0 + (w - tw) // 2, y), text, fill=fill, font=font)


def _right_text(draw, text, x, y, font, fill="black"):
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    draw.text((x - tw, y), text, fill=fill, font=font)


def _draw_spaced_text(
    draw,
    xy,
    text: str,
    font,
    spacing: int = 0,
    fill="black",
    round_colon: bool = False,
) -> int:
    x, y = xy
    cursor = float(x)
    for char in str(text):
        advance = font.getlength(char)
        if round_colon and char == ":":
            font_size = int(getattr(font, "size", 118))
            radius = max(2, int(round(font_size * 0.06)))
            center_x = int(round(cursor + advance / 2))
            for center_y in (
                y + int(round(font_size * 0.41)),
                y + int(round(font_size * 0.805)),
            ):
                draw.ellipse(
                    [center_x - radius, center_y - radius, center_x + radius, center_y + radius],
                    fill=fill,
                )
        else:
            draw.text((int(round(cursor)), y), char, fill=fill, font=font)
        cursor += advance + spacing
    return int(round(cursor - x - (spacing if text else 0)))


def _draw_wide_clock_text(
    image,
    xy,
    text: str,
    font,
    *,
    x_scale: float = 1.0,
    spacing: int = 0,
    fill="black",
    round_colon: bool = False,
) -> int:
    """Draw clock glyphs wider without enlarging their vertical footprint."""
    x, y = xy
    cursor = int(x)
    for char in str(text):
        bbox = font.getbbox(char)
        glyph_width = max(1, bbox[2] - bbox[0])
        wide_width = max(1, int(round(glyph_width * x_scale)))
        if round_colon and char == ":":
            font_size = int(getattr(font, "size", 178))
            radius = max(2, int(round(font_size * 0.067)))
            center_x = int(round(cursor + wide_width / 2))
            image_draw = ImageDraw.Draw(image)
            for center_y in (
                y + int(round(font_size * 0.445)),
                y + int(round(font_size * 0.876)),
            ):
                image_draw.ellipse(
                    [center_x - radius, center_y - radius, center_x + radius, center_y + radius],
                    fill=fill,
                )
        else:
            glyph_height = max(1, bbox[3] - bbox[1])
            glyph = Image.new("L", (glyph_width, glyph_height), 0)
            glyph_draw = ImageDraw.Draw(glyph)
            glyph_draw.text((-bbox[0], -bbox[1]), char, fill=255, font=font)
            if wide_width != glyph_width:
                glyph = glyph.resize((wide_width, glyph_height), Image.Resampling.LANCZOS)
            color = 0 if fill == "black" else fill
            image.paste(color, (cursor, int(y + bbox[1])), glyph)
        cursor += wide_width + spacing
    return cursor - int(x) - (spacing if text else 0)


def _draw_dotted_line(draw, x0, y0, x1, y1, color="black", step=5, dot=2):
    if x0 == x1:
        start, end = sorted((y0, y1))
        for y in range(start, end + 1, step):
            y1_seg = min(y + dot - 1, end)
            draw.rectangle([x0, y, x0, y1_seg], fill=color)
        return
    if y0 == y1:
        start, end = sorted((x0, x1))
        for x in range(start, end + 1, step):
            x1_seg = min(x + dot - 1, end)
            draw.rectangle([x, y0, x1_seg, y0], fill=color)


def _draw_calendar_accent(draw, x, y, color=LIGHT_BORDER):
    for col in range(2):
        for row in range(6):
            px = x + col * 4
            py = y + row * 4
            draw.ellipse([px, py, px + 1, py + 1], fill=color)


def _wrap_text_lines(text: str, font, max_width: int, max_lines: int = 2) -> list[str]:
    words = str(text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) <= max_width or not current:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) >= max_lines - 1:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) < max_lines and len("".join(lines)) == 0:
        lines.append(str(text))
    return lines[:max_lines]


def _draw_halftone_box(draw, box, color=LIGHT_BORDER, spacing=6):
    x0, y0, x1, y1 = box
    for y in range(y0 + 3, y1 - 2, spacing):
        offset = ((y - y0) // spacing) % 2
        for x in range(x0 + 3 + offset * 2, x1 - 2, spacing):
            draw.ellipse([x, y, x + 1, y + 1], fill=color)


def _draw_eink_halftone_bar(draw, box):
    x0, y0, x1, y1 = (int(value) for value in box)
    for py in range(y0, y1 + 1, 2):
        offset = ((py - y0) // 2) % 2
        for px in range(x0 + offset, x1 + 1, 2):
            draw.point((px, py), fill="black")


def _draw_eink_text(image, xy, text: str, font, *, halftone: bool = False) -> None:
    value = str(text or "")
    if not value:
        return
    bbox = font.getbbox(value)
    width = max(1, bbox[2] - bbox[0])
    height = max(1, bbox[3] - bbox[1])
    mask = Image.new("L", (width, height), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.text((-bbox[0], -bbox[1]), value, fill=255, font=font)
    mask = mask.point(lambda value: 255 if value >= 96 else 0)
    if halftone:
        pixels = list(mask.getdata())
        mask.putdata(
            [
                pixel if ((index % width) + (index // width)) % 2 == 0 else 0
                for index, pixel in enumerate(pixels)
            ]
        )
    image.paste("black", (int(xy[0] + bbox[0]), int(xy[1] + bbox[1])), mask)


def _draw_corner_brackets(draw, box, size=18, color="black", width=1):
    x0, y0, x1, y1 = box
    segments = [
        ((x0, y0), (x0 + size, y0)),
        ((x0, y0), (x0, y0 + size)),
        ((x1 - size, y0), (x1, y0)),
        ((x1, y0), (x1, y0 + size)),
        ((x0, y1), (x0 + size, y1)),
        ((x0, y1 - size), (x0, y1)),
        ((x1 - size, y1), (x1, y1)),
        ((x1, y1 - size), (x1, y1)),
    ]
    for start, end in segments:
        draw.line([start, end], fill=color, width=width)


def _draw_rounded_dashed_box(draw, box, radius=16, color=LIGHT_BORDER, step=6, dot=2):
    x0, y0, x1, y1 = box
    _draw_dotted_line(draw, x0 + radius, y0, x1 - radius, y0, color=color, step=step, dot=dot)
    _draw_dotted_line(draw, x0 + radius, y1, x1 - radius, y1, color=color, step=step, dot=dot)
    _draw_dotted_line(draw, x0, y0 + radius, x0, y1 - radius, color=color, step=step, dot=dot)
    _draw_dotted_line(draw, x1, y0 + radius, x1, y1 - radius, color=color, step=step, dot=dot)
    for deg in range(0, 91, 12):
        rad = math.radians(deg)
        for cx, cy, sx, sy in (
            (x0 + radius, y0 + radius, -1, -1),
            (x1 - radius, y0 + radius, 1, -1),
            (x0 + radius, y1 - radius, -1, 1),
            (x1 - radius, y1 - radius, 1, 1),
        ):
            px = int(round(cx + sx * radius * math.cos(rad)))
            py = int(round(cy + sy * radius * math.sin(rad)))
            draw.rectangle([px, py, px, py], fill=color)


def _draw_wireless_gamepad_icon(draw, x: int, y: int, connected: bool, compact: bool = False):
    body_w = 40 if compact else 50
    body_h = 20 if compact else 24
    radius = 9 if compact else 10
    draw.rounded_rectangle([x, y, x + body_w, y + body_h], radius=radius, outline="black", width=1)
    draw.ellipse([x + 6, y + 7, x + 12, y + 13], fill="black")
    draw.ellipse([x + body_w - 12, y + 7, x + body_w - 6, y + 13], fill="black")
    draw.rectangle([x + 15, y + 8, x + 18, y + 15], fill="black")
    draw.rectangle([x + 13, y + 10, x + 20, y + 13], fill="black")
    draw.ellipse([x + body_w - 18, y + 8, x + body_w - 15, y + 11], fill="black")
    draw.ellipse([x + body_w - 12, y + 8, x + body_w - 9, y + 11], fill="black")
    draw.ellipse([x + body_w - 18, y + 13, x + body_w - 15, y + 16], fill="black")
    draw.ellipse([x + body_w - 12, y + 13, x + body_w - 9, y + 16], fill="black")
    draw.arc([x + 6, y + body_h - 2, x + 18, y + body_h + 8], 190, 340, fill="black", width=1)
    draw.arc(
        [x + body_w - 18, y + body_h - 2, x + body_w - 6, y + body_h + 8],
        200,
        350,
        fill="black",
        width=1,
    )

    center_x = x + body_w // 2
    base_y = y - (6 if compact else 8)
    if connected:
        for spread in ([8, 5], [14, 11], [20, 17]):
            draw.arc(
                [
                    center_x - spread[0],
                    base_y - spread[1],
                    center_x + spread[0],
                    base_y + spread[1],
                ],
                210,
                330,
                fill="black",
                width=1,
            )
        draw.ellipse([center_x - 1, y - 2, center_x + 1, y], fill="black")
    else:
        draw.line([(center_x - 7, y - 1), (center_x + 7, y - 1)], fill="black", width=1)


def _draw_lightning_icon(draw, x: int, y: int, size: int = 18, fill="black"):
    points = [
        (x + int(size * 0.45), y),
        (x + int(size * 0.18), y + int(size * 0.52)),
        (x + int(size * 0.42), y + int(size * 0.52)),
        (x + int(size * 0.24), y + size),
        (x + size, y + int(size * 0.32)),
        (x + int(size * 0.58), y + int(size * 0.32)),
    ]
    draw.polygon(points, fill=fill)


def _draw_battery_level_icon(draw, x: int, y: int, width: int = 29, height: int = 17):
    body_w = width - 4
    draw.rounded_rectangle(
        [x, y, x + body_w, y + height],
        radius=3,
        outline="black",
        width=2,
    )
    terminal_y = y + max(3, height // 3)
    draw.rounded_rectangle(
        [x + body_w, terminal_y, x + width, y + height - max(3, height // 3)],
        radius=1,
        fill="black",
    )
    bar_top = y + 4
    bar_bottom = y + height - 4
    for bar_x in (x + 5, x + 10, x + 15):
        draw.rectangle([bar_x, bar_top, bar_x + 2, bar_bottom], fill="black")


def _weather_icon_key(code: int) -> str:
    if code in (0, 1):
        return "sun"
    if code in (2, 3, 45, 48):
        return "partly"
    if code in (51, 53, 55, 61, 63, 65, 71, 73, 75, 80, 81, 82, 95, 96, 99):
        return "rain"
    return "partly"


def _normalize_weather_icon(icon: str) -> str:
    key = str(icon or "").strip().lower()
    if key in ("sun", "sunny", "clear"):
        return "sun"
    if key in ("rain", "snow", "storm", "thunder", "drizzle", "showers"):
        return "rain"
    return "partly"


def _weather_condition_label(icon: str) -> str:
    return {
        "sun": "Sunny",
        "partly": "Cloudy",
        "rain": "Rainy",
    }[_normalize_weather_icon(icon)]


def _forecast_weekday_label(raw_date: str, now: datetime, offset_days: int) -> str:
    try:
        target = datetime.fromisoformat(str(raw_date)[:10])
    except (TypeError, ValueError):
        target = now + timedelta(days=offset_days)
    return FORECAST_WEEKDAYS[target.weekday()]


def _draw_round_line(draw, points, width: int, fill="black", close: bool = False):
    pixel_points = [(int(round(px)), int(round(py))) for px, py in points]
    if close:
        pixel_points.append(pixel_points[0])
    draw.line(pixel_points, fill=fill, width=width, joint="curve")
    if close or not pixel_points:
        return
    radius = max(1, width // 2)
    for px, py in (pixel_points[0], pixel_points[-1]):
        draw.ellipse([px - radius, py - radius, px + radius, py + radius], fill=fill)


def _sample_cubic(start, control_a, control_b, end, steps: int = 10):
    points = []
    for index in range(1, steps + 1):
        t = index / steps
        one_minus_t = 1.0 - t
        points.append(
            (
                one_minus_t**3 * start[0]
                + 3 * one_minus_t**2 * t * control_a[0]
                + 3 * one_minus_t * t**2 * control_b[0]
                + t**3 * end[0],
                one_minus_t**3 * start[1]
                + 3 * one_minus_t**2 * t * control_a[1]
                + 3 * one_minus_t * t**2 * control_b[1]
                + t**3 * end[1],
            )
        )
    return points


def _draw_reference_sun(draw, x: float, y: float, size: float, compact: bool = False):
    cx = x + size * 0.5
    cy = y + size * 0.5
    stroke = max(1, int(round(size * (0.038 if not compact else 0.032))))
    radius = size * 0.205
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        outline="black",
        width=stroke,
    )
    for deg in range(0, 360, 45):
        rad = math.radians(deg)
        inner = size * 0.34
        outer = size * 0.47
        _draw_round_line(
            draw,
            [
                (cx + inner * math.cos(rad), cy + inner * math.sin(rad)),
                (cx + outer * math.cos(rad), cy + outer * math.sin(rad)),
            ],
            stroke,
        )


def _draw_reference_cloud(
    draw,
    x: float,
    y: float,
    size: float,
    stroke: int,
    height_scale: float = 1.0,
):
    def point(px: float, py: float):
        return (x + size * px, y + size * py * height_scale)

    start = point(0.18, 0.67)
    cloud = [start]
    segments = [
        ((0.10, 0.67), (0.05, 0.59), (0.05, 0.49)),
        ((0.05, 0.38), (0.13, 0.30), (0.25, 0.30)),
        ((0.31, 0.11), (0.45, 0.04), (0.59, 0.08)),
        ((0.75, 0.12), (0.84, 0.24), (0.84, 0.40)),
        ((0.95, 0.39), (1.00, 0.48), (0.97, 0.57)),
        ((0.95, 0.64), (0.89, 0.67), (0.81, 0.67)),
    ]
    current = (0.18, 0.67)
    for control_a, control_b, end in segments:
        cloud.extend(
            _sample_cubic(point(*current), point(*control_a), point(*control_b), point(*end))
        )
        current = end
    cloud.append(start)
    draw.polygon([(int(round(px)), int(round(py))) for px, py in cloud], fill="white")
    _draw_round_line(draw, cloud, stroke, close=True)


def _draw_weather_icon(draw, x: int, y: int, icon: str, size: int):
    icon = _normalize_weather_icon(icon)
    size = max(8, int(size))
    if icon == "sun":
        _draw_reference_sun(draw, x, y, size, compact=size < 50)
        return

    stroke = max(1, int(round(size * 0.035)))
    if icon == "partly":
        sun_size = size * 0.75
        _draw_reference_sun(draw, x, y, sun_size, compact=size < 50)
        _draw_reference_cloud(
            draw,
            x + size * 0.18,
            y + size * 0.30,
            size * 0.85,
            stroke,
            height_scale=0.85,
        )
        return

    _draw_reference_cloud(draw, x, y, size, stroke, height_scale=0.90)
    rain_strokes = (
        ((0.22, 0.75), (0.16, 0.82)),
        ((0.42, 0.72), (0.28, 0.88)),
        ((0.58, 0.80), (0.49, 0.91)),
        ((0.70, 0.73), (0.64, 0.80)),
        ((0.89, 0.74), (0.77, 0.87)),
    )
    for start, end in rain_strokes:
        _draw_round_line(
            draw,
            [
                (x + size * start[0], y + size * start[1]),
                (x + size * end[0], y + size * end[1]),
            ],
            stroke,
        )


def _format_session_clock(session_min: int) -> str:
    session_min = max(0, int(session_min or 0))
    return f"{session_min // 60:02d}:{session_min % 60:02d}"


def _format_total_minutes_label(total_minutes: Optional[int]) -> str:
    if total_minutes is None:
        return "--"
    try:
        minutes = int(total_minutes)
    except (TypeError, ValueError):
        return "--"
    if minutes < 0:
        return "--"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _format_total_hours_label(total_hours: int) -> str:
    total_hours = max(0, int(total_hours or 0))
    return f"{total_hours} h"


def _read_cpu_percent() -> int:
    global _CPU_SAMPLE
    if platform.system() != "Linux":
        return 0
    try:
        parts = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
        values = [int(v) for v in parts]
        idle = values[3] + values[4]
        total = sum(values)
        if _CPU_SAMPLE is None:
            _CPU_SAMPLE = (total, idle)
            return 0
        prev_total, prev_idle = _CPU_SAMPLE
        diff_total = max(1, total - prev_total)
        diff_idle = max(0, idle - prev_idle)
        _CPU_SAMPLE = (total, idle)
        return max(0, min(100, int(round(100 * (diff_total - diff_idle) / diff_total))))
    except Exception:
        return 0


def _read_gpu_percent() -> int:
    if platform.system() != "Linux":
        return 0
    for candidate in (
        "/sys/class/drm/card0/device/gpu_busy_percent",
        "/sys/class/drm/card1/device/gpu_busy_percent",
    ):
        try:
            path = Path(candidate)
            if path.exists():
                return max(0, min(100, int(path.read_text().strip())))
        except Exception:
            pass
    return 0


def _read_memory_percent() -> int:
    if platform.system() != "Linux":
        return 0
    try:
        meminfo = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            meminfo[key] = int(value.strip().split()[0])
        total = meminfo.get("MemTotal", 0)
        avail = meminfo.get("MemAvailable", 0)
        if total <= 0:
            return 0
        used = total - avail
        return max(0, min(100, int(round(100 * used / total))))
    except Exception:
        return 0


def _parse_active_refresh_rate(output: str) -> Optional[int]:
    clean_output = re.sub(r"\x1b\[[0-9;]*m", "", output or "")
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\*", clean_output)
    if not match:
        return None
    return int(math.floor(float(match.group(1)) + 0.5))


def _read_display_refresh_rate() -> Optional[int]:
    if platform.system() != "Linux":
        return None

    runtime_dir = Path(f"/run/user/{os.getuid()}")
    command_env = os.environ.copy()
    try:
        for line in (runtime_dir / "gamescope-environment").read_text(errors="ignore").splitlines():
            key, separator, value = line.partition("=")
            if separator and key in {"DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR"}:
                command_env[key] = value
    except Exception:
        pass
    command_env.setdefault("DISPLAY", ":0")
    command_env.setdefault("XDG_RUNTIME_DIR", str(runtime_dir))
    if not command_env.get("XAUTHORITY"):
        try:
            command_env["XAUTHORITY"] = str(
                max(runtime_dir.glob("xauth_*"), key=lambda path: path.stat().st_mtime)
            )
        except Exception:
            pass

    try:
        output = subprocess.check_output(
            ["xrandr", "--current"],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
            env=command_env,
        )
        refresh_rate = _parse_active_refresh_rate(output)
        if refresh_rate is not None:
            return refresh_rate
    except Exception:
        pass

    if (runtime_dir / "wayland-0").exists():
        command_env["WAYLAND_DISPLAY"] = "wayland-0"
    try:
        output = subprocess.check_output(
            ["kscreen-doctor", "-o"],
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
            env=command_env,
        )
        return _parse_active_refresh_rate(output)
    except Exception:
        return None


def _format_percent(value) -> str:
    try:
        return f"{int(value)}%"
    except Exception:
        return "--%"


def _normalize_series(values, fallback: int = 0) -> list[int]:
    series = []
    for value in list(values or []):
        try:
            series.append(max(0, min(100, int(value))))
        except Exception:
            pass
    if not series:
        series = [max(0, min(100, int(fallback or 0)))] * 2
    return series


def _draw_trend_line(draw, box, values, color="black", width=2, slot_count: Optional[int] = None):
    x0, y0, x1, y1 = box
    vals = _normalize_series(values)
    if len(vals) == 1:
        vals = vals * 2
    slots = max(len(vals), int(slot_count or len(vals)))
    step_x = (x1 - x0) / max(1, slots - 1)
    start_slot = max(0, slots - len(vals))
    points = []
    for idx, value in enumerate(vals):
        px = x0 + (start_slot + idx) * step_x
        norm = value / 100.0
        py = y1 - norm * (y1 - y0)
        points.append((px, py))
    draw.line(points, fill=color, width=width)


def _histogram_slot_centers(box, slot_count: int) -> list[int]:
    x0, _y0, x1, _y1 = box
    slots = max(1, int(slot_count))
    slot_w = (x1 - x0) / slots
    return [int(round(x0 + (index + 0.5) * slot_w)) for index in range(slots)]


def _draw_histogram(
    draw,
    box,
    values,
    color="black",
    bar_width: Optional[int] = None,
    slot_count: Optional[int] = None,
):
    x0, y0, x1, y1 = box
    vals = _normalize_series(values)
    count = len(vals)
    if count <= 0:
        return
    slots = max(count, int(slot_count or count))
    slot_w = max(1.0, (x1 - x0) / slots)
    start_slot = max(0, slots - count)
    bar_w = max(1, int(bar_width)) if bar_width is not None else max(1, int(slot_w * 0.42))
    for idx, value in enumerate(vals):
        px = x0 + (start_slot + idx) * slot_w + (slot_w - bar_w) / 2
        bar_h = max(2, int((y1 - y0) * value / 100))
        draw.rectangle(
            [int(round(px)), y1 - bar_h, int(round(px + bar_w)), y1],
            fill=color,
        )


def _draw_calendar_layout(
    draw,
    width: int,
    height: int,
    now: datetime,
    compact: bool = False,
    country_code: object = "",
) -> None:
    import calendar as cal_mod

    yr, mo, day = now.year, now.month, now.day
    month_name = cal_mod.month_name[mo]
    weekdays, weeks = _calendar_month_layout(yr, mo, country_code)
    row_count = max(5, len(weeks))

    if compact:
        side_margin = 8
        top_margin = 6
        title_font = FR(17)
        year_font = FR(16)
        weekday_font = FR(8)
        day_font = FR(9)
        selected_day_font = FR(10)
        title_y = top_margin
        accent_y = title_y + 2
        grid_top = 28
        header_h = 12
        grid_bottom = height - 6
        radius = 10
        text_pad_x = 4
        text_pad_y = 2
    else:
        side_margin = 20
        top_margin = 8
        title_font = FR(50)
        year_font = FR(46)
        weekday_font = FR(17)
        day_font = FR(16)
        selected_day_font = FR(26)
        title_y = top_margin
        accent_y = title_y + 12
        grid_top = 84
        header_h = 28
        grid_bottom = height - 18
        radius = 18
        text_pad_x = 10
        text_pad_y = 8

    grid_left = side_margin
    grid_right = width - side_margin
    grid_width = grid_right - grid_left
    cell_w = grid_width / 7.0
    grid_height = grid_bottom - grid_top
    row_h = (grid_height - header_h) / row_count

    year_text = str(yr)
    if compact:
        _draw_calendar_accent(draw, max(2, side_margin - 12), accent_y)
        _draw_calendar_accent(draw, width - side_margin + 2, accent_y)
    else:
        pass
        _draw_eink_halftone_bar(draw, [20, 20, 26, 55])
        draw.text((40, title_y), year_text, fill="black", font=year_font)
        month_width = title_font.getbbox(month_name)[2] - title_font.getbbox(month_name)[0]
        draw.text(((width - month_width) // 2, title_y), month_name, fill="black", font=title_font)
    if compact:
        draw.text((side_margin + 12, title_y), month_name, fill="black", font=title_font)
        _right_text(draw, year_text, width - side_margin - 2, title_y, year_font, fill="black")

    outer_box = [grid_left, grid_top, grid_right, grid_bottom]
    draw.rounded_rectangle(outer_box, radius=radius, outline=LIGHT_BORDER, width=1)

    header_y = int(grid_top + header_h)
    _draw_dotted_line(draw, grid_left + radius, header_y, grid_right - radius, header_y)
    for row in range(1, row_count):
        y = int(grid_top + header_h + row * row_h)
        _draw_dotted_line(draw, grid_left, y, grid_right, y)
    for col in range(1, 7):
        x = int(grid_left + col * cell_w)
        _draw_dotted_line(draw, x, grid_top, x, grid_bottom)

    for col, wd in enumerate(weekdays):
        cx0 = grid_left + col * cell_w
        cx1 = grid_left + (col + 1) * cell_w
        label = wd.upper()
        bbox = weekday_font.getbbox(label)
        label_w = bbox[2] - bbox[0]
        label_h = bbox[3] - bbox[1]
        tx = int(cx0 + ((cx1 - cx0) - label_w) / 2)
        ty = int(grid_top + (header_h - label_h) / 2) - 1
        draw.text((tx, ty), label, fill="black", font=weekday_font)

    for row_idx, week in enumerate(weeks):
        for col, date_num in enumerate(week):
            if date_num == 0:
                continue
            cell_left = int(grid_left + col * cell_w)
            cell_top = int(grid_top + header_h + row_idx * row_h)
            cell_right = int(grid_left + (col + 1) * cell_w)
            cell_bottom = int(grid_top + header_h + (row_idx + 1) * row_h)
            if date_num == day:
                highlight = [
                    cell_left + 2,
                    cell_top + 2,
                    cell_right - 2,
                    cell_bottom - 2,
                ]
                draw.rectangle(highlight, fill="black")
                draw.text(
                    (cell_left + text_pad_x, cell_top + max(3, text_pad_y - 2)),
                    str(date_num),
                    fill="white",
                    font=selected_day_font,
                )
            else:
                draw.text(
                    (cell_left + text_pad_x, cell_top + text_pad_y),
                    str(date_num),
                    fill="black",
                    font=day_font,
                )


def _prepare(source) -> bytes:
    """Convert PIL Image / path / bytes → 1-bit e-ink byte array."""
    _ensure_pillow()
    if isinstance(source, Image.Image):
        img = source.copy()
    elif isinstance(source, (bytes, bytearray)):
        img = Image.open(io.BytesIO(source))
    else:
        img = Image.open(source)

    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    img.thumbnail((SCREEN_W, SCREEN_H), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (SCREEN_W, SCREEN_H), (255, 255, 255))
    canvas.paste(img, ((SCREEN_W - img.width) // 2, (SCREEN_H - img.height) // 2))
    bw = canvas.convert("1")
    pixels = list(bw.getdata())
    data = []
    for i in range(0, len(pixels), 8):
        byte = 0
        for j in range(8):
            if i + j < len(pixels) and pixels[i + j] > 0:
                byte |= 1 << (7 - j)
        data.append(byte)
    return bytes(data)


def _render_bytes_locally(mode: str, payload: dict) -> bytes:
    if mode == "dashboard":
        return _prepare(render_p0_fullscreen(payload.get("P0", payload)))
    if mode == "module":
        return _prepare(render_module_fullscreen(int(payload["module_id"]), payload["data"]))
    if mode == "clock":
        return _prepare(render_p4_fullscreen(payload.get("data", {})))
    if mode == "weather":
        return _prepare(render_weather_card(payload["data"]))
    if mode == "deck_status":
        return _prepare(render_status_card(payload["data"]))
    if mode == "custom_file":
        return _prepare(render_p6_fullscreen(payload["data"]))
    if mode == "image_path":
        return _prepare(payload["path"])
    raise ValueError(f"Unknown render mode: {mode}")


# ──────────────────────────────────────────────
# Module renderers
# ──────────────────────────────────────────────
def render_p0(data: dict) -> Image.Image:
    """P0 — Status bar 648×60"""
    img = Image.new("RGB", (648, 60), "white")
    draw = ImageDraw.Draw(img)

    bt = data.get("bt", "---")
    bat = data.get("bat", "--%")
    fw = data.get("fw", FW_VERSION)
    now = " ".join(part for part in clock_parts(data) if part)
    try:
        bat_n = int(str(bat).replace("%", "").strip())
        bat_warn = "  [LOW]" if bat_n < 20 else ""
    except Exception:
        bat_warn = ""

    draw.text((8, 5), f"BT:{bt}  |  {HW_DESC}  |  BAT:{bat}{bat_warn}", fill="black", font=F(15))
    draw.text((8, 30), f"SteamOS  |  FW:{fw}  |  {now}", fill="black", font=F(15))
    _wm(draw, 0)
    _hline(draw, 59, x0=0, x1=648, w=1)
    return img


def render_p1(data: dict) -> Image.Image:
    """P1 — Game progress 320×100"""
    img = Image.new("RGB", (320, 100), "white")
    draw = ImageDraw.Draw(img)
    snapshot = get_game_progress_snapshot(data)
    draw.text((8, 4), "Session Time", fill="black", font=FR(9))
    _draw_wireless_gamepad_icon(draw, 270, 6, snapshot["controller_connected"], compact=True)
    _center_text(draw, snapshot["session_clock"], 18, F(38), x0=0, w=320)

    draw.text((18, 68), "Game", fill="black", font=FR(8))
    _draw_dotted_line(draw, 8, 74, 8, 94, color="black", step=4, dot=2)
    for idx, line in enumerate(_wrap_text_lines(snapshot["game"], FR(12), 124, max_lines=2)):
        draw.text((18, 78 + idx * 12), line, fill="black", font=FR(12))

    draw.text((210, 68), "Total", fill="black", font=FR(8))
    box = [190, 78, 312, 96]
    _draw_halftone_box(draw, [box[0] + 4, box[1] + 2, box[2] - 4, box[3] - 2], spacing=5)
    _draw_corner_brackets(draw, box, size=10, width=1)
    total_text = snapshot["total_label"]
    total_bbox = FR(14).getbbox(total_text)
    total_w = total_bbox[2] - total_bbox[0]
    draw.text(
        (int((box[0] + box[2] - total_w) / 2), box[1] + 2), total_text, fill="black", font=FR(14)
    )
    _vline(draw, 319, y0=0, y1=100)
    return img


def render_p2(data: dict) -> Image.Image:
    """P2 — Performance 328×100"""
    img = Image.new("RGB", (328, 100), "white")
    draw = ImageDraw.Draw(img)
    snapshot = get_performance_snapshot(data)

    top_boxes = [
        (
            "GPU",
            snapshot["gpu_percent"],
            snapshot["gpu_history"],
            [8, 6, 320, 34],
            [14, 22, 314, 28],
        ),
        (
            "CPU",
            snapshot["cpu_percent"],
            snapshot["cpu_history"],
            [8, 38, 320, 66],
            [14, 54, 314, 60],
        ),
    ]
    for label, value, history, box, graph_box in top_boxes:
        _draw_rounded_dashed_box(draw, box, radius=10, step=4, dot=1)
        draw.text((box[0] + 8, box[1] + 4), label, fill="black", font=FR(10))
        value_text = _format_percent(value)
        value_w = FR(10).getbbox(value_text)[2] - FR(10).getbbox(value_text)[0]
        draw.text((box[2] - value_w - 8, box[1] + 4), value_text, fill="black", font=FR(10))
        _draw_trend_line(draw, graph_box, history, width=2)

    ram_box = [8, 70, 168, 98]
    fps_box = [198, 72, 320, 96]
    _draw_rounded_dashed_box(draw, ram_box, radius=10, step=4, dot=1)
    draw.text((ram_box[0] + 8, ram_box[1] + 4), "RAM", fill="black", font=FR(10))
    ram_text = _format_percent(snapshot["ram_percent"])
    ram_w = FR(10).getbbox(ram_text)[2] - FR(10).getbbox(ram_text)[0]
    draw.text((ram_box[2] - ram_w - 8, ram_box[1] + 4), ram_text, fill="black", font=FR(10))
    _draw_histogram(
        draw,
        [ram_box[0] + 8, ram_box[1] + 12, ram_box[2] - 8, ram_box[3] - 3],
        snapshot["ram_history"],
    )

    _draw_halftone_box(
        draw, [fps_box[0] + 8, fps_box[1] + 4, fps_box[2] - 8, fps_box[3] - 4], spacing=5
    )
    _draw_corner_brackets(draw, fps_box, size=9, width=1)
    draw.text((fps_box[0] + 10, fps_box[1] + 5), "FPS", fill="black", font=FR(10))
    fps_value = str(snapshot["fps"])
    fps_font = FR(18)
    draw.text((fps_box[0] + 50, fps_box[1] + 1), fps_value, fill="black", font=fps_font)

    return img


def render_p3(data: dict) -> Image.Image:
    """P3 — Weather 216×120"""
    img = Image.new("RGB", (216, 120), "white")
    draw = ImageDraw.Draw(img)
    snapshot = get_weather_snapshot(data)

    _draw_weather_icon(draw, 5, 0, snapshot["icon"], size=78)
    _draw_rounded_dashed_box(draw, [112, 4, 212, 78], radius=12, color="black", step=5, dot=2)
    metrics = [
        (snapshot["temp_label"], "Temp"),
        (snapshot["hum_label"], "Humidity"),
        (snapshot["wind_label"], "Wind"),
    ]
    for idx, (value, label) in enumerate(metrics):
        y = 12 + idx * 22
        _draw_dotted_line(draw, 124, y - 1, 124, y + 15, color="black", step=4, dot=2)
        draw.text((134, y - 2), value, fill="black", font=FR(11))
        draw.text((134, y + 9), label, fill="black", font=FR(7))

    _draw_dotted_line(draw, 18, 84, 18, 114, color="black", step=4, dot=2)
    draw.text((28, 80), snapshot["weekday"], fill="black", font=FR(22))
    draw.text((28, 104), snapshot["date_full"], fill="black", font=FR(9))
    _draw_dotted_line(draw, 94, 84, 94, 114, color="black", step=4, dot=2)
    draw.text((104, 80), snapshot["desc"], fill="black", font=FR(14))
    draw.text((104, 104), snapshot["city"], fill="black", font=FR(8))

    forecast_box = [108, 82, 212, 116]
    _draw_rounded_dashed_box(draw, forecast_box, radius=10, color="black", step=5, dot=2)
    fc = snapshot["forecast"][:3]
    cell_w = (forecast_box[2] - forecast_box[0] - 8) // 3
    for idx, item in enumerate(fc):
        cell_x = forecast_box[0] + 4 + idx * cell_w
        if idx > 0:
            _draw_dotted_line(
                draw,
                cell_x - 2,
                forecast_box[1] + 4,
                cell_x - 2,
                forecast_box[3] - 4,
                color="black",
                step=4,
                dot=2,
            )
        draw.text((cell_x + 4, forecast_box[1] + 4), item["weekday"], fill="black", font=FR(7))
        _draw_weather_icon(draw, cell_x + cell_w - 10, forecast_box[1] + 4, item["icon"], size=8)
        for y, value in ((13, item["hi"]), (22, item["lo"])):
            text = f"{value:+d}°"
            draw.text(
                (cell_x + 4, forecast_box[1] + y),
                text,
                fill="black",
                font=_weather_value_font(text, 6, cell_w - 8),
            )

    _vline(draw, 215, y0=0, y1=120)
    return img


def render_p4(data: dict) -> Image.Image:
    """P4 — MonoHub 216×120"""
    img = Image.new("RGB", (216, 120), "white")
    draw = ImageDraw.Draw(img)
    snapshot = get_monohub_snapshot(data)

    draw.text((8, 6), snapshot["date_label"][:18], fill="black", font=FR(8))
    draw.text((184, 6), snapshot["ampm"], fill="black", font=FR(9))
    _center_text(draw, snapshot["clock_12h"], 20, F(42), x0=0, w=216)
    _draw_dotted_line(draw, 8, 82, 208, 82, color="black", step=4, dot=2)

    _draw_dotted_line(draw, 10, 88, 10, 112, color="black", step=4, dot=2)
    weather_text = snapshot["desc"]
    draw.text((20, 84), weather_text, fill="black", font=FR(14))
    draw.text((20, 104), snapshot["city"], fill="black", font=FR(8))
    _draw_weather_icon(draw, 122, 88, snapshot["icon"], size=16)

    _draw_dotted_line(draw, 118, 88, 118, 112, color="black", step=4, dot=2)
    draw.text((128, 84), snapshot["charging_label"], fill="black", font=FR(8))
    draw.text((128, 96), snapshot["battery_label"], fill="black", font=FR(18))
    if snapshot["battery_charging"]:
        _draw_lightning_icon(draw, 190, 84, size=12)
    draw.rounded_rectangle([128, 108, 204, 116], radius=4, outline="black", width=1)
    fill_w = int(74 * max(0, min(100, snapshot["battery_percent"])) / 100)
    if fill_w > 0:
        draw.rounded_rectangle([129, 109, 129 + fill_w, 115], radius=3, fill="black")
    return img


def render_p5(data: dict) -> Image.Image:
    """P5 — Calendar 216×120"""
    img = Image.new("RGB", (216, 120), "white")
    draw = ImageDraw.Draw(img)
    _draw_calendar_layout(
        draw,
        216,
        120,
        display_now(data),
        compact=True,
        country_code=data.get("calendar_country", ""),
    )
    return img


def render_p6(data: dict) -> Image.Image:
    """P6 — Custom 648×200"""
    img = Image.new("RGB", (648, 200), "white")
    draw = ImageDraw.Draw(img)

    title = data.get("title", "Custom Display")
    body = data.get("body", "")
    img_b64 = data.get("image", "")

    draw.text((8, 4), title[:48], fill="black", font=F(22))
    _hline(draw, 34, color="black")

    tx = 8
    if img_b64:
        try:
            import base64

            cimg = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
            cimg.thumbnail((200, 155), Image.LANCZOS)
            img.paste(cimg, (8, 40))
            tx = 222
        except Exception:
            pass

    # Word-wrap body
    words = body.split()
    lines, cur = [], ""
    max_w = 648 - tx - 8
    for w in words:
        test = (cur + " " + w).strip()
        if F(15).getlength(test) < max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    for i, line in enumerate(lines[:10]):
        draw.text((tx, 40 + i * 16), line, fill="black", font=F(15))

    _wm(draw, 6)
    return img


# ──────────────────────────────────────────────
# Dashboard & fullscreen
# ──────────────────────────────────────────────
def render_dashboard(module_data: dict) -> Image.Image:
    """Composite P0-P6 into a 648×480 dashboard."""
    canvas = Image.new("RGB", (SCREEN_W, SCREEN_H), "white")
    renderers = [render_p0, render_p1, render_p2, render_p3, render_p4, render_p5, render_p6]
    keys = ["P0", "P1", "P2", "P3", "P4", "P5", "P6"]
    for i, ((x, y, w, h), renderer, key) in enumerate(zip(MODULE_RECTS, renderers, keys)):
        try:
            mod_img = renderer(module_data.get(key, {}))
            canvas.paste(mod_img.crop((0, 0, w, h)), (x, y))
        except Exception as e:
            decky.logger.error("Module %s render failed: %s", key, e)
    return canvas


def render_module_fullscreen(module_id: int, data: dict) -> Image.Image:
    """每个模块独立渲染为 648×480 全屏，字体大清晰."""
    _ensure_pillow()
    fs_renderers = [
        render_p0_fullscreen,
        render_p1_fullscreen,
        render_p2_fullscreen,
        render_p3_fullscreen,
        render_p4_fullscreen,
        render_p5_fullscreen,
        render_p6_fullscreen,
        render_agent_fullscreen,
    ]
    if 0 <= module_id < len(fs_renderers):
        try:
            if module_id == 1:
                poster_mode = str(data.get("game_time_display_mode", "time"))
                has_game_poster = bool(
                    str(data.get("app_id") or "").strip()
                    and str(data.get("poster_path") or "").strip()
                )
                if poster_mode == "poster" or (poster_mode == "auto" and has_game_poster):
                    return _render_game_time_poster_image(data)
            return fs_renderers[module_id](data)
        except Exception as e:
            decky.logger.error("Fullscreen render failed for P%d: %s", module_id, e)
    return render_clock_card(data=data)


# ──────────────────────────────────────────────
# Existing card renderers
# ──────────────────────────────────────────────
def render_clock_card(now: datetime = None, data: Optional[dict] = None) -> Image.Image:
    if now is None:
        now = display_now(data)
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), "white")
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, SCREEN_W, 32], fill="black")
    draw.text((8, 8), "JSAUX E-INK", fill="white", font=F(15))

    time_str = " ".join(
        part
        for part in clock_parts(
            with_context(data, DISPLAY_DEFAULTS)
            if data is None and now is None
            else {
                **(data or {}),
                "_display_context": {
                    **(data or {}).get("_display_context", {}),
                    "now": now.isoformat(),
                },
            }
        )
        if part
    )
    date_str = now.strftime("%Y-%m-%d")
    wd_str = WEEKDAYS_SHORT[now.weekday()]

    bbox = F(64).getbbox(time_str)
    time_x = (SCREEN_W - (bbox[2] - bbox[0])) // 2
    draw.text((time_x, 110), time_str, fill="black", font=F(64))
    _hline(draw, 196, x0=SCREEN_W // 2 - 120, x1=SCREEN_W // 2 + 120, w=2, color="black")
    _center_text(draw, date_str, 206, F(28))
    _center_text(draw, wd_str, 245, F(22))

    _hline(draw, SCREEN_H - 40, color=GRAY_BORDER)
    draw.text((8, SCREEN_H - 30), "JSAUX E-INK", fill=GRAY_BORDER, font=F(11))
    draw.text((SCREEN_W - 58, SCREEN_H - 30), FW_VERSION, fill=GRAY_BORDER, font=F(11))
    return img


def render_weather_card(weather_data: dict) -> Image.Image:
    snapshot = get_weather_snapshot(weather_data)
    if isinstance(weather_data, dict) and "_display_battery_snapshot" in weather_data:
        snapshot["_display_battery_snapshot"] = weather_data["_display_battery_snapshot"]
    return render_p3_fullscreen(snapshot)


def render_status_card(status: dict) -> Image.Image:
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), "white")
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, SCREEN_W, 32], fill="black")
    draw.text((8, 8), "JSAUX E-INK  |  Host Status", fill="white", font=F(15))

    y = 50
    bat = status.get("battery_percent")
    if bat is not None:
        draw.text((8, y), "Battery", fill=GRAY_BORDER, font=F(15))
        y += 22
        chg = " (Charging)" if status.get("battery_charging") else ""
        draw.text((130, y - 22), f"{bat}%{chg}", fill="black", font=F(15))
        _bar(draw, 8, y, 400, 14, bat)
        y += 24
        _hline(draw, y, color=GRAY_BORDER)
        y += 10

    for label, key in [
        ("Game", "current_game"),
        ("WiFi", "wifi_ssid"),
        ("CPU Temp", "cpu_temp"),
        ("Host", "hostname"),
    ]:
        val = status.get(key)
        if val is None:
            val = "--"
        if key == "cpu_temp" and val != "--":
            val = f"{val:.1f} °C"
        draw.text((8, y), label, fill=GRAY_BORDER, font=F(15))
        draw.text((130, y), str(val)[:30], fill="black", font=F(15))
        y += 24
        _hline(draw, y, color=GRAY_BORDER)
        y += 10

    _hline(draw, SCREEN_H - 40, color=GRAY_BORDER)
    draw.text((8, SCREEN_H - 30), "JSAUX E-INK", fill=GRAY_BORDER, font=F(11))
    return img


# ──────────────────────────────────────────────
# Weather API
# ──────────────────────────────────────────────
async def fetch_ip_location() -> dict:
    """通过公网 IP 自动获取地理位置（无需 API key）"""
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get("https://ipwho.is/")
            r.raise_for_status()
            d = r.json()
            if d.get("success") is not False:
                return {
                    "ip": d.get("ip", ""),
                    "lat": d.get("latitude", 0.0),
                    "lon": d.get("longitude", 0.0),
                    "city": d.get("city", ""),
                    "country": d.get("country_code", ""),
                    "timezone": (d.get("timezone") or {}).get("id", ""),
                }
    except Exception as e:
        decky.logger.warning("IP location failed: %s", e)
    return {}


async def fetch_weather(lat: float, lon: float) -> Optional[dict]:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "timezone": "auto",
        "forecast_days": 4,
        "temperature_unit": "celsius",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except Exception as e:
        decky.logger.error("Weather fetch failed: %s", e)
        return None


def get_deck_status() -> dict:
    s = {
        "battery_percent": None,
        "battery_charging": False,
        "current_game": "",
        "wifi_ssid": "",
        "wifi_signal": "",
        "cpu_temp": None,
        "hostname": "",
        "external_controller_connected": False,
        "external_controller_name": "",
        "external_controller_count": 0,
    }
    try:
        s["hostname"] = platform.node()
    except BaseException:
        pass
    if platform.system() == "Linux":
        for name in ["BAT1", "BAT0"]:
            try:
                bp = Path(f"/sys/class/power_supply/{name}")
                if bp.exists():
                    s["battery_percent"] = int((bp / "capacity").read_text().strip())
                    s["battery_charging"] = False
                    break
            except BaseException:
                pass
        try:
            out = subprocess.check_output(
                ["pgrep", "-a", "-f", "steamapps/common"], text=True, timeout=3
            )
            for line in out.strip().splitlines():
                parts = line.split("steamapps/common/")
                if len(parts) > 1:
                    s["current_game"] = parts[1].split("/")[0]
                    break
        except BaseException:
            pass
        try:
            s["wifi_ssid"] = subprocess.check_output(
                ["iwgetid", "-r"], text=True, timeout=3
            ).strip()
        except BaseException:
            pass
        try:
            out = subprocess.check_output(["iwconfig", "wlan0"], text=True, timeout=3)
            for line in out.splitlines():
                if "Signal level" in line:
                    s["wifi_signal"] = line.split("Signal level=")[-1].split()[0]
        except BaseException:
            pass
        try:
            tp = Path("/sys/class/thermal/thermal_zone0/temp")
            if tp.exists():
                s["cpu_temp"] = int(tp.read_text().strip()) / 1000.0
        except BaseException:
            pass
        try:
            controller = get_external_controller_status()
            s["external_controller_connected"] = controller["connected"]
            s["external_controller_name"] = controller["name"]
            s["external_controller_count"] = controller["count"]
        except Exception:
            pass
    return s


def get_external_controller_status() -> dict:
    status = {"connected": False, "name": "", "count": 0}
    if platform.system() != "Linux":
        return status
    try:
        raw = Path("/proc/bus/input/devices").read_text(errors="ignore")
    except Exception:
        return status

    devices = []
    current = {}
    for line in raw.splitlines():
        if not line.strip():
            if current:
                devices.append(current)
                current = {}
            continue
        if line.startswith("N: Name="):
            current["name"] = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("H: Handlers="):
            current["handlers"] = line.split("=", 1)[1].strip()
    if current:
        devices.append(current)

    matches = []
    for device in devices:
        name = device.get("name", "")
        handlers = device.get("handlers", "")
        name_l = name.lower()
        if "steam deck controller" in name_l:
            continue
        if not any(
            token in name_l
            for token in (
                "controller",
                "gamepad",
                "joystick",
                "x-box",
                "xbox",
                "dualshock",
                "dualsense",
                "pro controller",
                "pad",
            )
        ):
            continue
        if "js" not in handlers and "event" not in handlers:
            continue
        matches.append(name)

    if matches:
        status["connected"] = True
        status["name"] = matches[0]
        status["count"] = len(matches)
    return status


def _process_session_minutes(pid: int) -> int:
    try:
        clk_tck = os.sysconf("SC_CLK_TCK")
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        raw_stat = Path(f"/proc/{pid}/stat").read_text()
        stat_fields = raw_stat[raw_stat.rfind(")") + 2 :].split()
        started_at = int(stat_fields[19]) / clk_tck
        return max(0, int((uptime - started_at) / 60))
    except Exception:
        return 0


def _parse_gameprocess_log(content: str, now: Optional[datetime] = None) -> Optional[dict]:
    active_pids: dict[str, set[int]] = {}
    started_at: dict[str, datetime] = {}
    game_dirs: dict[str, str] = {}
    timestamp_pattern = "%Y-%m-%d %H:%M:%S"

    for line in content.splitlines():
        if "Client version:" in line:
            active_pids.clear()
            started_at.clear()
            game_dirs.clear()
            continue

        added = re.match(r"^\[([^]]+)] AppID (\d+) adding PID (\d+)", line)
        if added:
            timestamp_text, app_id, pid_text = added.groups()
            active_pids.setdefault(app_id, set()).add(int(pid_text))
            if app_id not in started_at:
                try:
                    started_at[app_id] = datetime.strptime(timestamp_text, timestamp_pattern)
                except ValueError:
                    started_at[app_id] = now or datetime.now()
            common_paths = re.findall(r"steamapps/common/([^/'\"]+)", line)
            if common_paths:
                game_dirs[app_id] = common_paths[-1]
            continue

        removed = re.match(r"^\[[^]]+] AppID (\d+) no longer tracking PID (\d+)", line)
        if not removed:
            continue
        app_id, pid_text = removed.groups()
        pids = active_pids.get(app_id)
        if pids is None:
            continue
        pids.discard(int(pid_text))
        if not pids:
            active_pids.pop(app_id, None)
            started_at.pop(app_id, None)
            game_dirs.pop(app_id, None)

    if not active_pids:
        return None
    app_id = max(active_pids, key=lambda value: started_at.get(value, datetime.min))
    current_time = now or datetime.now()
    session_min = max(
        0, int((current_time - started_at.get(app_id, current_time)).total_seconds() / 60)
    )
    return {
        "app_id": app_id,
        "session_min": session_min,
        "game_dir": game_dirs.get(app_id, ""),
    }


def _find_running_steam_game(steam_root: Optional[Path] = None) -> Optional[dict]:
    try:
        out = subprocess.check_output(
            ["pgrep", "-a", "-f", "SteamLaunch AppId="], text=True, timeout=3
        )
        for line in out.splitlines():
            match = re.match(r"^(\d+)\s+.*?SteamLaunch AppId=(\d+)", line)
            if not match:
                continue
            pid_text, app_id = match.groups()
            common_paths = re.findall(r"steamapps/common/([^/'\"]+)", line)
            return {
                "app_id": app_id,
                "session_min": _process_session_minutes(int(pid_text)),
                "game_dir": common_paths[-1] if common_paths else "",
            }
    except Exception:
        pass

    root = steam_root or (Path.home() / ".local/share/Steam")
    # Proton/pressure-vessel launches may omit ``SteamLaunch AppId=`` from
    # their visible command line. Their executable path still contains the
    # Steam library directory, which can be mapped to appmanifest_*.acf.
    try:
        out = subprocess.check_output(
            ["pgrep", "-a", "-f", "steamapps/common/"], text=True, timeout=3
        )
        for line in out.splitlines():
            match = re.match(r"^(\d+)\s+.*", line)
            common_paths = re.findall(r"steamapps/common/([^/'\"]+)", line)
            if not match or not common_paths:
                continue
            game_dir = common_paths[-1]
            return {
                "app_id": _steam_app_id_for_game_dir(game_dir, root),
                "session_min": _process_session_minutes(int(match.group(1))),
                "game_dir": game_dir,
            }
    except Exception:
        pass
    try:
        return _parse_gameprocess_log(
            (root / "logs/gameprocess_log.txt").read_text(errors="ignore")
        )
    except Exception:
        return None


def _extract_vdf_section(content: str, key: str) -> str:
    match = re.search(rf'"{re.escape(str(key))}"\s*\{{', content, flags=re.IGNORECASE)
    if not match:
        return ""
    opening = content.find("{", match.start())
    depth = 0
    for index in range(opening, len(content)):
        if content[index] == "{":
            depth += 1
        elif content[index] == "}":
            depth -= 1
            if depth == 0:
                return content[opening + 1 : index]
    return ""


def _steam_library_paths(steam_root: Path) -> list[Path]:
    libraries = [steam_root]
    try:
        content = (steam_root / "steamapps/libraryfolders.vdf").read_text(errors="ignore")
        for raw_path in re.findall(r'"path"\s*"([^"]+)"', content, flags=re.IGNORECASE):
            library = Path(raw_path.replace("\\\\", "\\"))
            if library not in libraries:
                libraries.append(library)
    except Exception:
        pass
    return libraries


def _read_steam_app_name(app_id: str, steam_root: Path) -> str:
    for library in _steam_library_paths(steam_root):
        manifest = library / "steamapps" / f"appmanifest_{app_id}.acf"
        try:
            content = manifest.read_text(errors="ignore")
        except Exception:
            continue
        match = re.search(r'^\s*"name"\s*"([^"]+)"', content, flags=re.MULTILINE | re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def _steam_app_id_for_game_dir(game_dir: str, steam_root: Path) -> str:
    """Resolve an installed game's AppID when Proton hides SteamLaunch args."""
    wanted = str(game_dir or "").strip().casefold()
    if not wanted:
        return ""
    for library in _steam_library_paths(steam_root):
        try:
            manifests = (library / "steamapps").glob("appmanifest_*.acf")
        except OSError:
            continue
        for manifest in manifests:
            try:
                content = manifest.read_text(errors="ignore")
            except OSError:
                continue
            installdir = re.search(
                r'^\s*"installdir"\s*"([^"]+)"', content, flags=re.MULTILINE | re.IGNORECASE
            )
            if not installdir or installdir.group(1).strip().casefold() != wanted:
                continue
            app_id = re.search(
                r'^\s*"appid"\s*"(\d+)"', content, flags=re.MULTILINE | re.IGNORECASE
            )
            if app_id:
                return app_id.group(1)
            stem = manifest.stem
            if stem.startswith("appmanifest_"):
                return stem.removeprefix("appmanifest_")
    return ""


def _steam_user_config_dir(steam_root: Path) -> Optional[Path]:
    """Select the most recent Steam account instead of mixing every user's stats."""
    userdata = steam_root / "userdata"
    try:
        users = _extract_vdf_section(
            (steam_root / "config/loginusers.vdf").read_text(errors="ignore"), "users"
        )
        candidates = []
        for steam_id in re.findall(r'"(\d{17})"\s*\{', users):
            account = _extract_vdf_section(users, steam_id)
            recent = re.search(r'"MostRecent"\s*"([01])"', account, re.IGNORECASE)
            timestamp = re.search(r'"Timestamp"\s*"(\d+)"', account, re.IGNORECASE)
            candidates.append(
                (
                    int(recent.group(1)) if recent else 0,
                    int(timestamp.group(1)) if timestamp else 0,
                    steam_id,
                )
            )
        if candidates:
            _recent, _timestamp, steam_id = max(candidates)
            config_dir = userdata / str(int(steam_id) & 0xFFFFFFFF) / "config"
            return config_dir if config_dir.is_dir() else None
    except (OSError, ValueError):
        pass
    try:
        configs = [
            path / "config"
            for path in userdata.iterdir()
            if path.is_dir() and path.name.isdigit() and (path / "config").is_dir()
        ]
        return configs[0] if len(configs) == 1 else None
    except OSError:
        return None


def _read_steam_playtime_minutes(app_id: str, steam_root: Path) -> Optional[int]:
    if not str(app_id).isdigit():
        return None
    config_dir = _steam_user_config_dir(steam_root)
    if config_dir is None:
        return None
    try:
        content = (config_dir / "localconfig.vdf").read_text(errors="ignore")
        for key in ("Software", "Valve", "Steam", "apps", str(app_id)):
            content = _extract_vdf_section(content, key)
            if not content:
                return None
        match = re.search(r'"Playtime"\s*"(\d+)"', content, flags=re.IGNORECASE)
        return int(match.group(1)) if match else None
    except (OSError, ValueError):
        return None


def _read_steam_achievement_counts(
    app_id: str, steam_root: Path
) -> tuple[Optional[int], Optional[int]]:
    if not str(app_id).isdigit():
        return None, None
    config_dir = _steam_user_config_dir(steam_root)
    if config_dir is None:
        return None, None
    try:
        raw = json.loads((config_dir / "librarycache" / (str(app_id) + ".json")).read_text())
        if isinstance(raw, list):
            sections = {
                item[0]: item[1]
                for item in raw
                if isinstance(item, list) and len(item) == 2 and isinstance(item[0], str)
            }
        elif isinstance(raw, dict):
            sections = raw
        else:
            return None, None
        data = sections.get("achievements", {}).get("data", {})
        total, unlocked = data.get("nTotal"), data.get("nAchieved")
        # A real 0/0 is valid; missing, negative and inconsistent counts are unknown.
        if isinstance(total, bool) or isinstance(unlocked, bool):
            return None, None
        if not re.fullmatch(r"\d+", str(total)) or not re.fullmatch(r"\d+", str(unlocked)):
            return None, None
        total_i, unlocked_i = int(total), int(unlocked)
        if 0 <= unlocked_i <= total_i:
            return unlocked_i, total_i
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None, None


def get_game_info() -> dict:
    """从 Steam 当前进程、日志和用户配置获取游戏信息。"""
    info = {
        "game": NO_GAME_LABEL,
        "app_id": "",
        "game_dir": "",
        "total_hours": 0,
        "total_minutes": 0,
        "session_min": 0,
        "achievement_unlocked": None,
        "achievement_total": None,
    }
    if platform.system() != "Linux":
        return info

    steam_root = Path.home() / ".local/share/Steam"
    running = _find_running_steam_game(steam_root)
    if not running:
        return info

    app_id = str(running.get("app_id", "") or "")
    game_dir = str(running.get("game_dir", "") or "")
    info["app_id"] = app_id
    info["game_dir"] = game_dir
    info["game"] = _read_steam_app_name(app_id, steam_root) or game_dir or f"App {app_id}"
    info["session_min"] = max(0, int(running.get("session_min", 0) or 0))
    info["total_minutes"] = _read_steam_playtime_minutes(app_id, steam_root)
    info["total_hours"] = (info["total_minutes"] or 0) // 60
    info["achievement_unlocked"], info["achievement_total"] = _read_steam_achievement_counts(
        app_id, steam_root
    )
    return info


def get_game_progress_snapshot(seed: Optional[dict] = None) -> dict:
    seed = dict(seed or {})
    game_info = get_game_info()
    controller = get_external_controller_status()
    game_name = game_info.get("game") or NO_GAME_LABEL
    total_hours = game_info.get("total_hours", 0)
    total_minutes = game_info.get("total_minutes")
    total_label = _format_total_minutes_label(total_minutes)
    session_min = game_info.get("session_min", 0)
    unlocked = game_info.get("achievement_unlocked")
    achievement_total = game_info.get("achievement_total")
    count_text = (
        f"{unlocked}/{achievement_total}"
        if unlocked is not None and achievement_total is not None
        else ""
    )
    snapshot = {
        "game": game_name,
        "app_id": str(game_info.get("app_id", "") or ""),
        "game_dir": str(game_info.get("game_dir", "") or ""),
        "session_min": session_min,
        "session_clock": _format_session_clock(session_min),
        "total_hours": total_hours,
        "total_minutes": total_minutes,
        "total_label": total_label,
        "controller_connected": controller["connected"],
        "controller_name": controller["name"],
        "controller_count": controller["count"],
        "today": _format_session_clock(session_min),
        "total": total_label,
        "pct": (
            int(100 * unlocked / achievement_total)
            if achievement_total and unlocked is not None
            else 0
        ),
        "ach": count_text,
        # Cached P1 seed fields may belong to a previous game or account.
        "achievement_unlocked": unlocked,
        "achievement_total": achievement_total,
    }
    signature_game = "" if game_name == NO_GAME_LABEL else game_name
    snapshot["refresh_signature"] = (
        signature_game,
        snapshot["app_id"],
        session_min,
        total_minutes,
        unlocked,
        achievement_total,
        controller["connected"],
        controller["count"],
    )
    return snapshot


def get_status_bar_snapshot(seed: Optional[dict] = None) -> dict:
    seed = dict(seed or {})
    now = display_now(seed)
    deck = get_deck_status()
    game = get_game_progress_snapshot(seed)
    cpu = int(seed["cpu_percent"]) if "cpu_percent" in seed else _read_cpu_percent()
    gpu = int(seed["gpu_percent"]) if "gpu_percent" in seed else _read_gpu_percent()
    ram = int(seed["ram_percent"]) if "ram_percent" in seed else _read_memory_percent()
    fps = _read_display_refresh_rate()
    if fps is None:
        fps = seed.get("fps")
    cpu_history = list(seed.get("cpu_history") or [cpu])[-HARDWARE_HISTORY_MINUTES:]
    gpu_history = list(seed.get("gpu_history") or [gpu])[-HARDWARE_HISTORY_MINUTES:]
    return {
        "date_label": now.strftime("%A, %b %d %Y"),
        "clock_12h": clock_parts(seed)[0],
        "ampm": clock_parts(seed)[1],
        "weather_icon": _normalize_weather_icon(
            seed.get("weather_icon") or seed.get("icon") or "sun"
        ),
        "cpu_percent": cpu,
        "gpu_percent": gpu,
        "ram_percent": ram,
        "fps": fps if fps not in (None, "") else "--",
        "cpu_history": cpu_history,
        "gpu_history": gpu_history,
        "game_name": game["game"],
        "session_clock": game["session_clock"],
        "total_label": game["total_label"],
        "controller_connected": game["controller_connected"],
        "battery_percent": deck.get("battery_percent"),
        "wifi_ssid": deck.get("wifi_ssid", ""),
        "refresh_signature": (
            now.strftime("%Y-%m-%d %H:%M"),
            cpu,
            gpu,
            ram,
            game["refresh_signature"],
        ),
    }


def get_performance_snapshot(seed: Optional[dict] = None) -> dict:
    seed = dict(seed or {})
    cpu = int(seed["cpu_percent"]) if "cpu_percent" in seed else _read_cpu_percent()
    gpu = int(seed["gpu_percent"]) if "gpu_percent" in seed else _read_gpu_percent()
    ram = int(seed["ram_percent"]) if "ram_percent" in seed else _read_memory_percent()
    fps = _read_display_refresh_rate()
    if fps is None:
        fps = seed.get("fps")
    if fps in (None, ""):
        fps = "--"
    cpu_history = list(seed.get("cpu_history") or [cpu])[-HARDWARE_HISTORY_MINUTES:]
    gpu_history = list(seed.get("gpu_history") or [gpu])[-HARDWARE_HISTORY_MINUTES:]
    ram_history = list(seed.get("ram_history") or [ram])[-HARDWARE_HISTORY_MINUTES:]
    return {
        "cpu_percent": cpu,
        "gpu_percent": gpu,
        "ram_percent": ram,
        "fps": fps,
        "cpu_history": cpu_history,
        "gpu_history": gpu_history,
        "ram_history": ram_history,
        "refresh_signature": (
            tuple(cpu_history),
            tuple(gpu_history),
            tuple(ram_history),
            str(fps),
        ),
    }


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def get_weather_snapshot(source: Optional[dict] = None) -> dict:
    source = dict(source or {})
    now = weather_now(source)
    target = source.get("_display_context", {}).get("temperature_unit", "celsius")
    unit = "°F" if target == "fahrenheit" else "°C"

    def to_celsius(value, input_unit):
        value = _safe_float(value, 0.0)
        return (value - 32.0) / 1.8 if input_unit in ("°F", "℉", "fahrenheit") else value

    def display_value(celsius):
        return int(round(celsius * 1.8 + 32.0 if target == "fahrenheit" else celsius))

    forecast = []
    if "current" in source or "daily" in source:
        current, daily = source.get("current", {}), source.get("daily", {})
        input_unit = source.get("current_units", {}).get("temperature_2m", "°C")
        temp_c = to_celsius(current.get("temperature_2m"), input_unit)
        hum = int(round(_safe_float(current.get("relative_humidity_2m"))))
        wind = int(round(_safe_float(current.get("wind_speed_10m"))))
        wcode = int(current.get("weather_code", 0) or 0)
        city = source.get("_city") or source.get("city", "")
        dates = daily.get("time", [])
        highs, lows, codes = (
            daily.get("temperature_2m_max", []),
            daily.get("temperature_2m_min", []),
            daily.get("weather_code", []),
        )
        daily_units = source.get("daily_units", {})
        future = [
            index for index, raw in enumerate(dates) if str(raw)[:10] > now.date().isoformat()
        ][:3]
        for order, index in enumerate(future):
            hi_c = to_celsius(
                highs[index] if index < len(highs) else 0,
                daily_units.get("temperature_2m_max", input_unit),
            )
            lo_c = to_celsius(
                lows[index] if index < len(lows) else 0,
                daily_units.get("temperature_2m_min", input_unit),
            )
            forecast.append(
                {
                    "date": str(dates[index]),
                    "weekday": _forecast_weekday_label(str(dates[index]), now, order + 1),
                    "icon": _weather_icon_key(int(codes[index] if index < len(codes) else 0)),
                    "_hi_c": hi_c,
                    "_lo_c": lo_c,
                }
            )
        refreshed_at = float(source.get("_refreshed_at", time.time()))
    else:
        input_unit = source.get("unit", "°C")
        temp_c = (
            _safe_float(source["_temp_c"])
            if "_temp_c" in source
            else to_celsius(source.get("temp"), input_unit)
        )
        hum = int(round(_safe_float(source.get("hum"))))
        wind = int(round(_safe_float(source.get("wind"))))
        city = source.get("city", "")
        wcode = int(source.get("weather_code", 0) or 0)
        for order, item in enumerate(source.get("forecast", [])[:3]):
            hi_c = (
                _safe_float(item["_hi_c"])
                if "_hi_c" in item
                else to_celsius(item.get("hi"), input_unit)
            )
            lo_c = (
                _safe_float(item["_lo_c"])
                if "_lo_c" in item
                else to_celsius(item.get("lo"), input_unit)
            )
            raw_date = str(item.get("date", ""))
            forecast.append(
                {
                    "date": raw_date,
                    "weekday": _forecast_weekday_label(raw_date, now, order + 1),
                    "icon": _normalize_weather_icon(
                        item.get("icon") or _weather_icon_key(int(item.get("weather_code", 0) or 0))
                    ),
                    "_hi_c": hi_c,
                    "_lo_c": lo_c,
                }
            )
        refreshed_at = float(source.get("_refreshed_at", 0) or 0)
    for item in forecast:
        item["hi"], item["lo"] = display_value(item["_hi_c"]), display_value(item["_lo_c"])
        item["temp_range"] = f"{item['hi']:+d}{unit} / {item['lo']:+d}{unit}"
    temp = display_value(temp_c)
    icon = _normalize_weather_icon(source.get("icon") or _weather_icon_key(wcode))
    available = source.get("_weather_available", True)
    return {
        "weekday": now.strftime("%a"),
        "date_full": now.strftime("%b %d %Y"),
        "desc": _weather_condition_label(icon) if available else "Unavailable",
        "city": city,
        "icon": icon,
        "temp": temp,
        "_temp_c": temp_c,
        "temp_label": f"{temp}{unit}" if available else "--",
        "unit": unit,
        "hum": hum,
        "hum_label": f"{hum}%" if available else "--",
        "wind": wind,
        "wind_label": f"{wind} km/h" if available else "--",
        "forecast": forecast,
        "_refreshed_at": refreshed_at,
        "_weather_timezone": source.get("_weather_timezone") or source.get("timezone", ""),
        "_location_key": source.get("_location_key"),
        "_weather_available": available,
        "_display_context": source.get("_display_context", {}),
        "refresh_signature": (
            now.strftime("%Y-%m-%d %H"),
            city,
            icon,
            temp,
            unit,
            hum,
            wind,
            tuple((item["weekday"], item["icon"], item["temp_range"]) for item in forecast),
        ),
    }


def get_monohub_snapshot(source: Optional[dict] = None) -> dict:
    source = dict(source or {})
    now = display_now(source)
    battery_percent = int(source.get("battery_percent", 0) or 0)
    charging = False
    city = source.get("city", "")
    desc = source.get("desc", "Clear")
    icon = _normalize_weather_icon(source.get("icon", "sun"))
    return {
        "date_label": f"{now.strftime('%A')} , {now.strftime('%b %d %Y')}",
        "clock_12h": clock_parts(source)[0],
        "ampm": clock_parts(source)[1],
        "city": city,
        "desc": desc,
        "icon": icon,
        "battery_percent": battery_percent,
        "battery_label": f"{battery_percent}%",
        "battery_charging": charging,
        "charging_label": "Charging" if charging else "Battery Level",
        "refresh_signature": (
            now.strftime("%Y-%m-%d %H:%M"),
            city,
            desc,
            icon,
            battery_percent,
            charging,
        ),
    }


# ──────────────────────────────────────────────
# Fullscreen module renderers (648×480)
# ──────────────────────────────────────────────
WEEKDAYS_FULL = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def render_p0_fullscreen(data: dict) -> Image.Image:
    """Status Bar — 648×480 全屏"""
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), "white")
    draw = ImageDraw.Draw(img)
    snapshot = get_status_bar_snapshot(data)

    draw.text((26, 64), snapshot["date_label"], fill="black", font=FR(18))
    weather_icon = _normalize_weather_icon(snapshot["weather_icon"])

    clock_font = FR(118)
    clock_text = snapshot["clock_12h"]
    clock_w = _draw_spaced_text(
        draw,
        (26, 89),
        clock_text,
        clock_font,
        spacing=6,
        round_colon=True,
    )
    ampm_x = 26 + clock_w + 18
    draw.text((ampm_x, 107), snapshot["ampm"], fill="black", font=FR(18))
    ampm_width = FR(18).getbbox(snapshot["ampm"])[2] - FR(18).getbbox(snapshot["ampm"])[0]
    _draw_weather_icon(
        draw,
        min(540, ampm_x + ampm_width + 42),
        106,
        weather_icon,
        size=92 if weather_icon == "sun" else 104,
    )

    gpu_box = [26, 249, 418, 331]
    cpu_box = [26, 341, 418, 422]
    ram_box = [26, 433, 218, 461]
    fps_box = [228, 433, 418, 461]
    game_box = [428, 249, 621, 461]

    for label, value, history, box in (
        ("GPU", snapshot["gpu_percent"], snapshot["gpu_history"], gpu_box),
        ("CPU", snapshot["cpu_percent"], snapshot["cpu_history"], cpu_box),
    ):
        _draw_rounded_dashed_box(draw, box, radius=16, color=GRAY_BORDER, step=7, dot=1)
        draw.text((box[0] + 12, box[1] + 7), label, fill="black", font=FR(14))
        value_text = f"{value}%"
        _right_text(draw, value_text, box[2] - 12, box[1] + 7, FR(14))
        _draw_dotted_line(
            draw,
            box[0] + 8,
            box[1] + 29,
            box[2] - 8,
            box[1] + 29,
            color="black",
            step=3,
            dot=1,
        )
        _draw_trend_line(
            draw, [box[0] + 14, box[1] + 40, box[2] - 14, box[3] - 10], history, width=1
        )

    for box, label, value in (
        (ram_box, "RAM", f"{snapshot['ram_percent']}%"),
        (fps_box, "FPS", str(snapshot["fps"])),
    ):
        _draw_rounded_dashed_box(draw, box, radius=12, color=GRAY_BORDER, step=7, dot=1)
        draw.text((box[0] + 12, box[1] + 5), label, fill="black", font=FR(14))
        value_bbox = FR(14).getbbox(value)
        value_w = value_bbox[2] - value_bbox[0]
        draw.text((box[2] - value_w - 12, box[1] + 5), value, fill="black", font=FR(14))

    _draw_rounded_dashed_box(draw, game_box, radius=16, color=GRAY_BORDER, step=7, dot=1)
    _draw_eink_halftone_bar(draw, [450, 270, 458, 321])

    game_name = snapshot["game_name"]
    game_lines = _wrap_text_lines(game_name, FR(20), 126, max_lines=2)
    for idx, line in enumerate(game_lines):
        draw.text((466, 266 + idx * 24), line, fill="black", font=FR(20))

    session_box = [451, 333, 599, 378]
    total_box = [451, 399, 599, 444]
    right_sections = [
        ("Session Time", snapshot["session_clock"], session_box, 316, FR(28)),
        ("Total Playtime", snapshot["total_label"], total_box, 382, FR(24)),
    ]
    for title, value, box, label_y, value_font in right_sections:
        title_bbox = FR(13).getbbox(title)
        title_w = title_bbox[2] - title_bbox[0]
        draw.text((int((box[0] + box[2] - title_w) / 2), label_y), title, fill="black", font=FR(13))
        _draw_halftone_box(draw, [box[0] + 8, box[1] + 6, box[2] - 8, box[3] - 6], spacing=11)
        _draw_corner_brackets(draw, box, size=12, width=2)
        value_bbox = value_font.getbbox(value)
        value_w = value_bbox[2] - value_bbox[0]
        value_h = value_bbox[3] - value_bbox[1]
        draw.text(
            (int((box[0] + box[2] - value_w) / 2), int((box[1] + box[3] - value_h) / 2) - 2),
            value,
            fill="black",
            font=value_font,
        )
    _draw_display_battery(img, draw, _display_battery_snapshot_from_payload(data))
    return img


def _game_artwork_cache_dir() -> Path:
    return Path(decky.DECKY_PLUGIN_SETTINGS_DIR) / GAME_ARTWORK_CACHE_DIR_NAME


def _steam_artwork_candidates(app_id: str, steam_root: Path) -> list[Path]:
    if not str(app_id).isdigit():
        return []
    result: list[Path] = []
    preferred = (
        "library_600x900_schinese.jpg",
        "library_600x900.jpg",
        "library_capsule.jpg",
        "header.jpg",
        "library_header.jpg",
        "library_hero.jpg",
    )
    for library in _steam_library_paths(steam_root):
        folder = library / "appcache" / "librarycache" / str(app_id)
        if not folder.is_dir():
            continue
        try:
            # SteamOS stores Recently Played artwork in hash-named child
            # directories. Search those directories while retaining the
            # preferred portrait order; never rely on a network request when a
            # local Steam artwork is already available.
            for name in preferred:
                for candidate in sorted(folder.rglob(name)):
                    if candidate.is_file() and candidate not in result:
                        result.append(candidate)
            for candidate in sorted(folder.rglob("*")):
                if (
                    candidate.is_file()
                    and candidate.suffix.casefold() in {".jpg", ".jpeg", ".png", ".webp"}
                    and candidate not in result
                ):
                    result.append(candidate)
        except OSError:
            pass
    return result


def _process_game_artwork(source_path: str, cache_path: str) -> bool:
    try:
        _ensure_pillow()
        from PIL import ImageEnhance, ImageOps

        target_size = (396 - 24, 462 - 54)
        with Image.open(source_path) as source:
            image = source.convert("RGB")
            grayscale = ImageOps.autocontrast(ImageOps.grayscale(image))
            grayscale = ImageEnhance.Contrast(grayscale).enhance(1.18)
            # Use one fixed portrait viewport for every game, preserving aspect
            # ratio and applying the same centered crop.
            canvas = ImageOps.fit(
                grayscale, target_size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
            )
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            canvas.save(cache_path, format="PNG", optimize=True)
        return True
    except Exception as exc:
        decky.logger.warning("Game artwork processing failed: %s", exc)
        return False


async def _download_game_artwork(app_id: str, cache_path: Path) -> bool:
    if not str(app_id).isdigit():
        return False
    urls = (
        f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_600x900.jpg",
        f"https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg",
    )
    try:
        async with httpx.AsyncClient(
            timeout=GAME_ARTWORK_NETWORK_TIMEOUT_SEC, follow_redirects=True
        ) as client:
            for url in urls:
                try:
                    response = await client.get(url)
                    response.raise_for_status()
                    source_path = cache_path.with_suffix(".source")
                    await asyncio.to_thread(source_path.write_bytes, bytes(response.content))
                    ok = await asyncio.to_thread(
                        _process_game_artwork, str(source_path), str(cache_path)
                    )
                    try:
                        source_path.unlink()
                    except OSError:
                        pass
                    if ok:
                        return True
                except Exception:
                    continue
    except Exception as exc:
        decky.logger.info("Game artwork request unavailable: %s", exc)
    return False


def _poster_achievement_counts(data: dict) -> tuple[Optional[int], Optional[int]]:
    """Prefer authoritative snapshot fields, including an explicit unknown value."""
    data = data if isinstance(data, dict) else {}

    def _int_value(*keys):
        for key in keys:
            value = data.get(key)
            if not isinstance(value, bool) and re.fullmatch(r"\d+", str(value)):
                return int(value)
        return None

    if "achievement_unlocked" in data or "achievement_total" in data:
        unlocked = _int_value("achievement_unlocked")
        total = _int_value("achievement_total")
    else:
        unlocked = _int_value("unlocked_achievements", "achievements_unlocked")
        total = _int_value("total_achievements", "achievements_total")
        if unlocked is None or total is None:
            raw = data.get("ach")
            if isinstance(raw, str):
                match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", raw)
                if match:
                    unlocked, total = map(int, match.groups())
    if unlocked is None or total is None or unlocked > total:
        return None, None
    return unlocked, total


def _render_game_time_poster_image(data: dict) -> Image.Image:
    _ensure_pillow()
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), "white")
    draw = ImageDraw.Draw(img)
    app_id = str(data.get("app_id") or "").strip()
    path = str(data.get("poster_path") or "")
    unlocked, total = _poster_achievement_counts(data)
    show_achievements = bool(app_id) and unlocked is not None and total is not None and total > 0
    # A stale poster belongs to the last game and must never be shown while
    # Steam reports no current AppID.  Keep the poster canvas white instead.
    if app_id and path and Path(path).is_file():
        try:
            with Image.open(path) as source:
                poster = source.convert("RGB")
                # Expand the artwork when there is no readable achievement set.
                # The enlarged viewport preserves the existing poster aspect ratio.
                viewport = (24, 54, 396, 462) if show_achievements else (24, 14, 434, 462)
                vw, vh = viewport[2] - viewport[0], viewport[3] - viewport[1]
                from PIL import ImageOps

                poster = ImageOps.fit(
                    poster, (vw, vh), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5)
                )
                img.paste(poster, (viewport[0], viewport[1]))
        except Exception as exc:
            decky.logger.warning("Game poster render failed: %s", exc)

    content_x = SCREEN_W - 270 + POSTER_CONTENT_SHIFT_PX
    content_w = SCREEN_W - content_x - 14
    content_shift_y = int(round(FR(14).getlength("x") * 4))
    draw.text((content_x, 58), "Game name", fill="black", font=FR(18))
    draw.text(
        (content_x, 88),
        str(data.get("game") or data.get("game_name") or "--")[:20],
        fill="black",
        font=FR(14),
    )
    if show_achievements:
        achievement_shift_y = int(round(FR(14).getlength("x") * 4))
        achievement_title_y = 118 + achievement_shift_y + content_shift_y
        achievement_bar_y = 148 + achievement_shift_y + content_shift_y
        achievement_count_y = 178 + achievement_shift_y + content_shift_y
        draw.text((content_x, achievement_title_y), "Achievements", fill="black", font=FR(14))
        count_text = (
            f"{unlocked}/{total}" if unlocked is not None and total is not None else "--/--"
        )
        pct = (100.0 * unlocked / total) if unlocked is not None and total and total > 0 else 0.0
        _bar(draw, content_x, achievement_bar_y, content_w, 18, pct)
        draw.text((content_x, achievement_count_y), count_text, fill="black", font=FR(22))
    # Move the Total Playtime title and value down another four character widths.
    total_playtime_shift_y = int(round(FR(14).getlength("x") * 4))
    draw.text(
        (content_x, 238 + content_shift_y + total_playtime_shift_y),
        "Total Playtime",
        fill="black",
        font=FR(13),
    )
    draw.text(
        (content_x, 260 + content_shift_y + total_playtime_shift_y),
        str(
            data.get("total_label")
            or data.get("total")
            or _format_total_minutes_label(data.get("total_minutes"))
        ),
        fill="black",
        font=FR(24),
    )
    _draw_display_battery(img, draw, _display_battery_snapshot_from_payload(data))
    return img


def render_p1_fullscreen(data: dict) -> Image.Image:
    """Game Progress — 648×480 全屏，自动检测当前游戏"""
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), "white")
    draw = ImageDraw.Draw(img)
    snapshot = get_game_progress_snapshot(data)
    draw.text((46, 42), "Session Time", fill="black", font=FR(22))
    _draw_wireless_gamepad_icon(draw, 550, 102, snapshot["controller_connected"], compact=False)

    clock_font = F(118)
    clock_text = snapshot["session_clock"]
    clock_bbox = clock_font.getbbox(clock_text)
    clock_w = clock_bbox[2] - clock_bbox[0]
    _draw_spaced_text(
        draw,
        ((SCREEN_W - clock_w) // 2, 112),
        clock_text,
        clock_font,
        round_colon=True,
    )

    draw.text((46, 336), "Game name", fill="black", font=FR(20))
    _draw_eink_halftone_bar(draw, [22, 360, 28, 434])
    game_lines = _wrap_text_lines(snapshot["game"], FR(34), 220, max_lines=3)
    for idx, line in enumerate(game_lines):
        draw.text((46, 368 + idx * 34), line, fill="black", font=FR(34))

    total_box = [406, 376, 620, 452]
    total_label = "Total Playtime"
    total_label_bbox = FR(20).getbbox(total_label)
    total_label_w = total_label_bbox[2] - total_label_bbox[0]
    total_label_x = int((total_box[0] + total_box[2] - total_label_w) / 2)
    draw.text((total_label_x, 330), total_label, fill="black", font=FR(20))
    _draw_halftone_box(
        draw, [total_box[0] + 10, total_box[1] + 8, total_box[2] - 10, total_box[3] - 8], spacing=7
    )
    _draw_corner_brackets(draw, total_box, size=18, width=2)
    total_text = snapshot["total_label"]
    total_bbox = FR(44).getbbox(total_text)
    total_w = total_bbox[2] - total_bbox[0]
    draw.text(
        (int((total_box[0] + total_box[2] - total_w) / 2), total_box[1] + 12),
        total_text,
        fill="black",
        font=FR(44),
    )
    _draw_display_battery(img, draw, _display_battery_snapshot_from_payload(data))
    return img


def render_p2_fullscreen(data: dict) -> Image.Image:
    """Performance — 648×480 全屏"""
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), "white")
    draw = ImageDraw.Draw(img)
    snapshot = get_performance_snapshot(data)
    draw.text((28, 18), "PERE MON", fill="black", font=FR(20))

    gpu_box = [27, 58, 621, 160]
    cpu_box = [27, 170, 621, 272]
    ram_box = [27, 282, 324, 456]
    fps_box = [378, 342, 594, 434]

    for label, value, history, box in (
        ("GPU", snapshot["gpu_percent"], snapshot["gpu_history"], gpu_box),
        ("CPU", snapshot["cpu_percent"], snapshot["cpu_history"], cpu_box),
    ):
        _draw_rounded_dashed_box(draw, box, radius=16, color="black", step=5, dot=1)
        draw.text((box[0] + 12, box[1] + 10), label, fill="black", font=FR(16))
        value_text = _format_percent(value)
        value_w = FR(16).getbbox(value_text)[2] - FR(16).getbbox(value_text)[0]
        draw.text((box[2] - value_w - 12, box[1] + 10), value_text, fill="black", font=FR(16))
        _draw_dotted_line(
            draw,
            box[0] + 8,
            box[1] + 28,
            box[2] - 8,
            box[1] + 28,
            color="black",
            step=3,
            dot=1,
        )
        _draw_trend_line(
            draw,
            [box[0] + 14, box[1] + 48, box[2] - 14, box[3] - 18],
            history,
            width=1,
            slot_count=HARDWARE_HISTORY_MINUTES,
        )

    _draw_rounded_dashed_box(draw, ram_box, radius=16, color="black", step=5, dot=1)
    draw.text((ram_box[0] + 12, ram_box[1] + 10), "RAM", fill="black", font=FR(16))
    ram_text = _format_percent(snapshot["ram_percent"])
    ram_w = FR(16).getbbox(ram_text)[2] - FR(16).getbbox(ram_text)[0]
    draw.text((ram_box[2] - ram_w - 12, ram_box[1] + 10), ram_text, fill="black", font=FR(16))
    ram_header_y = ram_box[1] + 28
    _draw_dotted_line(
        draw,
        ram_box[0] + 8,
        ram_header_y,
        ram_box[2] - 8,
        ram_header_y,
        color="black",
        step=3,
        dot=1,
    )
    histogram_box = [ram_box[0] + 7, ram_header_y + 1, ram_box[2] - 7, ram_box[3] - 2]
    for grid_x in _histogram_slot_centers(histogram_box, HARDWARE_HISTORY_MINUTES):
        _draw_dotted_line(
            draw,
            grid_x,
            histogram_box[1],
            grid_x,
            histogram_box[3],
            color=LIGHT_BORDER,
            step=4,
            dot=1,
        )
    _draw_histogram(
        draw,
        histogram_box,
        snapshot["ram_history"],
        bar_width=2,
        slot_count=HARDWARE_HISTORY_MINUTES,
    )

    _draw_halftone_box(
        draw, [fps_box[0] + 12, fps_box[1] + 8, fps_box[2] - 12, fps_box[3] - 8], spacing=6
    )
    _draw_corner_brackets(draw, fps_box, size=16, width=2)
    fps_value = str(snapshot["fps"])
    fps_font = FR(58)
    fps_label_font = FR(18)
    fps_w = fps_font.getbbox(fps_value)[2] - fps_font.getbbox(fps_value)[0]
    fps_x = fps_box[0] + 56
    fps_y = fps_box[1] + 10
    draw.text((fps_x, fps_y), fps_value, fill="black", font=fps_font)
    draw.text((fps_x + fps_w + 12, fps_y + 22), "FPS", fill="black", font=fps_label_font)
    _draw_display_battery(img, draw, _display_battery_snapshot_from_payload(data))
    return img


def render_p3_fullscreen(data: dict) -> Image.Image:
    """Weather — 648×480 全屏"""
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), "white")
    draw = ImageDraw.Draw(img)
    snapshot = get_weather_snapshot(data)

    hero_icon = _normalize_weather_icon(snapshot["icon"])
    hero_layout = {
        "sun": (92, 91, 218),
        "rain": (80, 82, 240),
        "partly": (68, 91, 265),
    }
    hero_x, hero_y, hero_size = hero_layout[hero_icon]
    _draw_weather_icon(draw, hero_x, hero_y, hero_icon, size=hero_size)

    side_box = [404, 56, 621, 348]
    _draw_rounded_dashed_box(draw, side_box, radius=16, color="black", step=6, dot=2)
    metrics = [
        ("temp", snapshot["temp_label"], "Temperature"),
        ("hum", snapshot["hum_label"], "Humidity"),
        ("wind", snapshot["wind_label"], "Wind Speed"),
    ]
    for idx, (kind, value, label) in enumerate(metrics):
        y = 75 + idx * 99
        _draw_eink_halftone_bar(draw, [457, y, 463, y + 57])
        if kind == "wind":
            number, unit = str(value).split(" ", 1) if " " in str(value) else (str(value), "")
            number_font = FR(34)
            unit_font = FR(15)
            number_w = number_font.getbbox(number)[2] - number_font.getbbox(number)[0]
            _draw_eink_text(img, (486, y - 2), number, number_font)
            _draw_eink_text(img, (486 + number_w + 5, y + 10), unit, unit_font)
        elif kind == "hum":
            number = str(snapshot["hum"]) if snapshot.get("_weather_available", True) else "--"
            number_font = FR(34)
            number_w = number_font.getbbox(number)[2] - number_font.getbbox(number)[0]
            _draw_eink_text(img, (486, y - 2), number, number_font)
            _draw_eink_text(img, (486 + number_w + 4, y + 10), "%", FR(18))
        else:
            _draw_eink_text(img, (486, y - 2), value, _weather_value_font(value, 34, 126))
        _draw_eink_text(img, (486, y + 48), label, FR(12))

    _draw_eink_halftone_bar(draw, [27, 393, 33, 454])
    _draw_eink_text(img, (60, 388), snapshot["weekday"], FR(40))
    _draw_eink_text(img, (61, 440), snapshot["date_full"], FR(15))

    _draw_eink_halftone_bar(draw, [194, 393, 200, 454])
    desc_font = FR(30) if snapshot["desc"] == "Unavailable" else FR(40)
    _draw_eink_text(img, (225, 388), snapshot["desc"], desc_font)
    _draw_eink_text(
        img, (225, 440), _city_label(snapshot["city"], 16, 168), _city_font(snapshot["city"], 16)
    )

    forecast_box = [404, 357, 621, 454]
    _draw_rounded_dashed_box(draw, forecast_box, radius=16, color="black", step=6, dot=2)
    fc = snapshot["forecast"][:3]
    cell_w = (forecast_box[2] - forecast_box[0] - 12) // 3
    for idx, item in enumerate(fc):
        cell_x = forecast_box[0] + 6 + idx * cell_w
        if idx > 0:
            _draw_dotted_line(
                draw, cell_x - 3, 366, cell_x - 3, 447, color=LIGHT_BORDER, step=4, dot=2
            )
        label_font = FR(13)
        day_text = item["weekday"]
        _draw_eink_text(img, (cell_x + 13, 366), day_text, label_font)
        _draw_weather_icon(draw, cell_x + 13, 386, item["icon"], size=30)
        hi_text = f"{item['hi']:+d}°"
        lo_text = f"{item['lo']:+d}°"
        hi_font = FR(12)
        lo_font = FR(11)
        _draw_eink_text(img, (cell_x + 17, 418), hi_text, hi_font)
        _draw_eink_text(img, (cell_x + 17, 435), lo_text, lo_font)
    _draw_display_battery(img, draw, _display_battery_snapshot_from_payload(data))
    # CC BY 4.0 attribution for Open-Meteo forecast data (also listed in THIRD_PARTY_LICENSES.md).
    draw.text((12, SCREEN_H - 18), "Open-Meteo", fill=GRAY_BORDER, font=F(9))
    return img


def render_p4_fullscreen(data: dict) -> Image.Image:
    """MonoHub — 648×480 全屏"""
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), "white")
    draw = ImageDraw.Draw(img)
    snapshot = get_monohub_snapshot(data)

    draw.text((55, 65), snapshot["date_label"], fill="black", font=FR(20))
    draw.text((568, 303), snapshot["ampm"], fill="black", font=F(20))
    _draw_wide_clock_text(
        img,
        (42, 104),
        snapshot["clock_12h"],
        FR(178),
        x_scale=1.06,
        spacing=4,
        round_colon=True,
    )

    _draw_dotted_line(draw, 27, 379, 620, 379, color="black", step=5, dot=1)
    _draw_eink_halftone_bar(draw, [27, 390, 33, 453])
    desc_font = FR(40)
    desc_lines = _wrap_text_lines(snapshot["desc"], desc_font, 300, max_lines=1)
    for idx, line in enumerate(desc_lines):
        _draw_wide_clock_text(
            img,
            (54, 383 + idx * 40),
            line,
            desc_font,
            x_scale=1.06,
        )
    draw.text(
        (55, 436),
        _city_label(snapshot["city"], 16, 320),
        fill="black",
        font=_city_font(snapshot["city"], 16),
    )

    _draw_eink_halftone_bar(draw, [388, 390, 394, 453])
    progress = _year_progress_snapshot(display_now(data))
    draw.text((415, 388), "YEAR PROGRESS", fill="black", font=FR(20))
    draw.text((434, 421), "DAY", fill="black", font=FR(15))
    _right_text(draw, progress["day"], 564, 421, FR(15))
    draw.text((434, 445), "WEEK", fill="black", font=FR(15))
    _right_text(draw, progress["week"], 564, 445, FR(15))
    _draw_display_battery(img, draw, _display_battery_snapshot_from_payload(data))
    return img


def render_p5_fullscreen(data: dict) -> Image.Image:
    """Calendar — 648×480 全屏"""
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), "white")
    draw = ImageDraw.Draw(img)
    _draw_calendar_layout(
        draw,
        SCREEN_W,
        SCREEN_H,
        display_now(data),
        compact=False,
        country_code=data.get("calendar_country", ""),
    )
    _draw_display_battery(img, draw, _display_battery_snapshot_from_payload(data))
    return img


_AGENT_RENDER_LANGUAGE = "en"


def _system_agent_language() -> str:
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        raw = str(os.environ.get(key) or "").strip().lower().replace("_", "-")
        if raw:
            base = raw.split(".", 1)[0].split("@", 1)[0].split("-", 1)[0]
            if base in {"en", "zh", "ja", "ko", "es", "de", "fr", "it"}:
                return base
    try:
        result = subprocess.run(
            ["localectl", "status"], capture_output=True, text=True, timeout=2, check=False
        )
        for raw in result.stdout.splitlines():
            if "LANG=" in raw:
                base = (
                    raw.split("LANG=", 1)[1]
                    .strip()
                    .lower()
                    .split(".", 1)[0]
                    .split("@", 1)[0]
                    .split("-", 1)[0]
                )
                if base in {"en", "zh", "ja", "ko", "es", "de", "fr", "it"}:
                    return base
    except (OSError, subprocess.SubprocessError):
        pass
    return "en"


def _get_agent_font(size: int, bold: bool = False):
    _ensure_pillow()
    language = str(globals().get("_AGENT_RENDER_LANGUAGE", "en")).split("-", 1)[0]
    cjk_index = {"ja": 0, "ko": 1, "zh": 2}.get(language, 0)
    cjk_path = (
        "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc"
        if bold
        else "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"
    )
    paths = [
        (cjk_path, cjk_index),
        (
            (
                "/usr/share/fonts/noto/NotoSans-Bold.ttf"
                if bold
                else "/usr/share/fonts/noto/NotoSans-Regular.ttf"
            ),
            0,
        ),
        (
            (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
                if bold
                else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
            ),
            0,
        ),
    ]
    for font_path, index in paths:
        try:
            return ImageFont.truetype(font_path, size, index=index)
        except Exception:
            pass
    return ImageFont.load_default()


def AF(size: int):
    return _get_agent_font(size, False)


def AFB(size: int):
    return _get_agent_font(size, True)


def _draw_agent_header_icon(draw, x: int = 24, y: int = 24, size: int = 30) -> None:
    half = size // 2
    draw.rounded_rectangle(
        [x - half, y - half, x + half, y + half], radius=6, outline="black", width=2
    )
    draw.ellipse([x - 10, y - 6, x - 4, y], fill="black")
    draw.ellipse([x + 4, y - 6, x + 10, y], fill="black")
    draw.arc([x - 10, y - 2, x + 10, y + 12], 10, 170, fill="black", width=2)
    draw.line([x, y - half, x, y - half - 5], fill="black", width=2)
    draw.ellipse([x - 2, y - half - 8, x + 2, y - half - 4], fill="black")


def _draw_agent_pet(draw, x: int, y: int, state: str) -> None:
    draw.ellipse([x - 9, y - 9, x + 9, y + 9], outline="white", width=1)
    draw.ellipse([x - 5, y - 3, x - 2, y], fill="white")
    draw.ellipse([x + 2, y - 3, x + 5, y], fill="white")
    if state in ("failed", "waiting_permission"):
        draw.line([x - 4, y + 5, x + 4, y - 3], fill="white", width=1)
        draw.line([x - 4, y - 3, x + 4, y + 5], fill="white", width=1)
    else:
        draw.arc([x - 5, y - 1, x + 5, y + 7], 10, 170, fill="white", width=1)


def _agent_label(key: str, data: dict | None = None) -> str:
    lang = str((data or {}).get("language") or "en").lower().split("-", 1)[0]
    labels = {
        "zh": {
            "today": "今日",
            "week": "近7天",
            "total": "累计",
            "available": "可用",
            "requests": "总请求数",
            "cache": "缓存",
            "output": "输出",
            "status": "状态：",
            "live": "实时",
            "task_progress": "任务进度",
            "five_hour_reset": "5小时重置",
            "weekly_reset": "7天重置",
        },
        "ja": {
            "today": "今日",
            "week": "過去7日",
            "total": "累計",
            "available": "利用",
            "requests": "リクエスト",
            "cache": "キャッシュ",
            "output": "出力",
            "status": "状態：",
            "live": "LIVE",
        },
        "ko": {
            "today": "오늘",
            "week": "최근 7일",
            "total": "누적",
            "available": "사용",
            "requests": "요청",
            "cache": "캐시",
            "output": "출력",
            "status": "상태:",
            "live": "LIVE",
        },
        "es": {
            "today": "HOY",
            "week": "7 DÍAS",
            "total": "TOTAL",
            "available": "DISP.",
            "requests": "SOLICITUDES",
            "cache": "CACHÉ",
            "output": "SALIDA",
            "status": "ESTADO:",
            "live": "EN VIVO",
        },
        "de": {
            "today": "HEUTE",
            "week": "7 TAGE",
            "total": "GESAMT",
            "available": "VERF.",
            "requests": "ANFRAGEN",
            "cache": "CACHE",
            "output": "AUSGABE",
            "status": "STATUS:",
            "live": "LIVE",
        },
        "fr": {
            "today": "AUJOURD'HUI",
            "week": "7 JOURS",
            "total": "TOTAL",
            "available": "DISP.",
            "requests": "REQUÊTES",
            "cache": "CACHE",
            "output": "SORTIE",
            "status": "ÉTAT :",
            "live": "LIVE",
        },
        "it": {
            "today": "OGGI",
            "week": "7 GIORNI",
            "total": "TOTALE",
            "available": "DISP.",
            "requests": "RICHIESTE",
            "cache": "CACHE",
            "output": "OUTPUT",
            "status": "STATO:",
            "live": "LIVE",
        },
    }
    default = {
        "today": "TODAY",
        "week": "LAST 7 DAYS",
        "total": "TOTAL",
        "available": "AVAILABLE",
        "requests": "TOTAL REQUESTS",
        "cache": "CACHE",
        "output": "OUTPUT",
        "status": "STATUS",
        "live": "LIVE",
        "task_progress": "TASK PROGRESS",
        "five_hour_reset": "5H RESET",
        "weekly_reset": "7D RESET",
    }
    return labels.get(lang, default).get(key, key.upper())


def _draw_agent_usage_icon(draw, x: int, y: int, kind: str) -> None:
    if kind == "today":
        draw.ellipse([x - 8, y - 8, x + 8, y + 8], outline="black", width=1)
        for dx, dy in ((0, -12), (0, 12), (-12, 0), (12, 0)):
            draw.line([x + dx // 2, y + dy // 2, x + dx, y + dy], fill="black", width=1)
    elif kind == "week":
        draw.rectangle([x - 9, y - 9, x + 9, y + 9], outline="black", width=1)
        draw.line([x - 6, y - 3, x + 6, y - 3], fill="black", width=1)
        draw.line([x - 6, y + 2, x + 6, y + 2], fill="black", width=1)
        draw.line([x - 6, y + 7, x + 3, y + 7], fill="black", width=1)
    else:
        draw.polygon(
            [
                (x - 8, y - 9),
                (x + 8, y - 9),
                (x + 3, y),
                (x + 8, y + 9),
                (x - 8, y + 9),
                (x - 3, y),
            ],
            outline="black",
            fill="white",
        )
        draw.line([x - 4, y - 4, x + 4, y - 4], fill="black", width=1)
        draw.line([x - 4, y + 4, x + 4, y + 4], fill="black", width=1)


def _agent_usage_card(
    draw,
    box: list[int],
    kind: str,
    title: str,
    value: str,
    cost: str,
    available: object,
    requests: str,
    cache: str,
    output: str,
    data: dict | None = None,
) -> None:
    _draw_rounded_dashed_box(draw, box, radius=16, color="black", step=5, dot=1)
    _draw_agent_usage_icon(draw, box[0] + 18, box[1] + 18, kind)
    draw.text((box[0] + 36, box[1] + 8), title, fill="black", font=AFB(18))
    draw.text(
        (box[2] - 12, box[1] + 10),
        format_agent_number(cost),
        fill="black",
        font=AF(16),
        anchor="ra",
    )
    value_text = format_agent_number(value)
    value_font = AF(20 if len(value_text) > 8 else 24)
    draw.text((box[0] + 12, box[1] + 39), value_text, fill="black", font=value_font)
    available_text = "--" if available is None else f"{max(0, min(100, int(available)))}%"
    draw.text(
        (box[2] - 12, box[1] + 43),
        f"{_agent_label('available', data)}{available_text}",
        fill="black",
        font=AF(16),
        anchor="ra",
    )
    bar = [box[0] + 12, box[1] + 70, box[2] - 12, box[1] + 79]
    _draw_rounded_dashed_box(draw, bar, radius=4, color="black", step=4, dot=1)
    try:
        ratio = max(0.0, min(100.0, float(available if available is not None else 0))) / 100.0
    except (TypeError, ValueError):
        ratio = 0.0
    if ratio > 0:
        draw.rounded_rectangle(
            [bar[0] + 1, bar[1] + 1, bar[0] + 1 + int((bar[2] - bar[0] - 2) * ratio), bar[3] - 1],
            radius=3,
            fill="black",
        )
    # Keep each metric on its own row so CJK glyphs and thousands separators remain legible.
    draw.text(
        (box[0] + 12, box[1] + 96),
        f"{_agent_label('requests', data)} {format_agent_number(requests)}",
        fill="black",
        font=AFB(13),
    )
    draw.text(
        (box[0] + 12, box[1] + 115),
        f"{_agent_label('cache', data)} {format_agent_number(cache)}",
        fill="black",
        font=AFB(13),
    )
    draw.text(
        (box[0] + 12, box[1] + 134),
        f"{_agent_label('output', data)} {format_agent_number(output)}",
        fill="black",
        font=AFB(13),
    )


AGENT_12_HOUR_COUNTRIES = frozenset(
    {
        "US",
        "CA",
        "AU",
        "NZ",
        "PH",
        "IN",
        "PK",
        "BD",
        "MY",
        "SG",
        "HK",
        "TW",
        "GB",
        "IE",
        "ZA",
        "EG",
        "SA",
        "AE",
    }
)


def _agent_clock_text(now: datetime | None = None, country: object = "") -> str:
    current = now or datetime.now()
    raw = str(country or "").strip().upper().replace("_", "-")
    code = raw.split("-", 1)[0] if raw else ""
    aliases = {
        "UNITED STATES": "US",
        "USA": "US",
        "UNITED KINGDOM": "GB",
        "UK": "GB",
        "CANADA": "CA",
        "AUSTRALIA": "AU",
        "NEW ZEALAND": "NZ",
        "PHILIPPINES": "PH",
        "INDIA": "IN",
        "SINGAPORE": "SG",
        "HONG KONG": "HK",
        "TAIWAN": "TW",
    }
    code = aliases.get(raw, aliases.get(raw.replace("-", " "), code))
    return current.strftime("%I:%M %p" if code in AGENT_12_HOUR_COUNTRIES else "%H:%M")


def _agent_screen_label(key: str, data: dict | None = None) -> str:
    lang = str(_AGENT_RENDER_LANGUAGE or _system_agent_language()).lower().split("-", 1)[0]
    labels = {
        "en": {
            "today": "TODAY",
            "week": "LAST 7 DAYS",
            "total": "TOTAL",
            "available": "Available",
            "requests": "Requests",
            "cache": "Cache",
            "output": "Output",
            "status": "STATUS",
            "live": "LIVE",
            "task": "AI Agent Status",
            "recent": "Recent Tool Calls",
            "session": "Session",
            "completed": "Completed",
            "in_progress": "In Progress",
            "pending": "Pending",
            "analyze": "Analyze",
            "plan": "Plan",
            "code": "Code",
            "test": "Test",
            "finish": "Finish",
            "five_hour_reset": "5H RESET",
            "weekly_reset": "7 DAYS RESET",
        },
        "zh": {
            "today": "今日",
            "week": "近7天",
            "total": "累计",
            "available": "可用",
            "requests": "总请求数",
            "cache": "缓存",
            "output": "输出",
            "status": "状态",
            "live": "实时",
            "task": "AI Agent 状态",
            "recent": "最近工具调用",
            "session": "会话",
            "completed": "已完成",
            "in_progress": "进行中",
            "pending": "待处理",
            "analyze": "分析",
            "plan": "计划",
            "code": "编码",
            "test": "测试",
            "finish": "完成",
            "five_hour_reset": "5小时重置",
            "weekly_reset": "7天重置",
        },
        "ja": {
            "today": "今日",
            "week": "過去7日",
            "total": "累計",
            "available": "利用可能",
            "requests": "リクエスト",
            "cache": "キャッシュ",
            "output": "出力",
            "status": "状態",
            "live": "LIVE",
            "task": "AI Agent ステータス",
            "recent": "最近のツール呼び出し",
            "session": "セッション",
            "completed": "完了",
            "in_progress": "進行中",
            "pending": "保留",
            "analyze": "分析",
            "plan": "計画",
            "code": "コード",
            "test": "テスト",
            "finish": "完了",
            "five_hour_reset": "5時間リセット",
            "weekly_reset": "7日間リセット",
        },
        "ko": {
            "today": "오늘",
            "week": "최근 7일",
            "total": "누적",
            "available": "사용 가능",
            "requests": "요청",
            "cache": "캐시",
            "output": "출력",
            "status": "상태",
            "live": "LIVE",
            "task": "AI Agent 상태",
            "recent": "최근 도구 호출",
            "session": "세션",
            "completed": "완료",
            "in_progress": "진행 중",
            "pending": "대기",
            "analyze": "분석",
            "plan": "계획",
            "code": "코드",
            "test": "테스트",
            "finish": "완료",
            "five_hour_reset": "5시간 재설정",
            "weekly_reset": "7일 재설정",
        },
        "es": {
            "today": "HOY",
            "week": "ÚLTIMOS 7 DÍAS",
            "total": "TOTAL",
            "available": "Disponible",
            "requests": "Solicitudes",
            "cache": "Caché",
            "output": "Salida",
            "status": "ESTADO",
            "live": "EN VIVO",
            "task": "Estado de AI Agent",
            "recent": "Llamadas recientes",
            "session": "Sesión",
            "completed": "Completado",
            "in_progress": "En curso",
            "pending": "Pendiente",
            "analyze": "Analizar",
            "plan": "Plan",
            "code": "Código",
            "test": "Prueba",
            "finish": "Finalizar",
            "five_hour_reset": "REINICIO 5H",
            "weekly_reset": "REINICIO 7 DÍAS",
        },
        "de": {
            "today": "HEUTE",
            "week": "LETZTE 7 TAGE",
            "total": "GESAMT",
            "available": "Verfügbar",
            "requests": "Anfragen",
            "cache": "Cache",
            "output": "Ausgabe",
            "status": "STATUS",
            "live": "LIVE",
            "task": "AI-Agent-Status",
            "recent": "Letzte Tool-Aufrufe",
            "session": "Sitzung",
            "completed": "Abgeschlossen",
            "in_progress": "In Bearbeitung",
            "pending": "Ausstehend",
            "analyze": "Analyse",
            "plan": "Plan",
            "code": "Code",
            "test": "Test",
            "finish": "Fertig",
            "five_hour_reset": "5H ZURÜCKSETZUNG",
            "weekly_reset": "7-TAGE-ZURÜCKSETZUNG",
        },
        "fr": {
            "today": "AUJOURD’HUI",
            "week": "7 DERNIERS JOURS",
            "total": "TOTAL",
            "available": "Disponible",
            "requests": "Requêtes",
            "cache": "Cache",
            "output": "Sortie",
            "status": "ÉTAT",
            "live": "EN DIRECT",
            "task": "État de l’AI Agent",
            "recent": "Appels d’outils récents",
            "session": "Session",
            "completed": "Terminé",
            "in_progress": "En cours",
            "pending": "En attente",
            "analyze": "Analyser",
            "plan": "Plan",
            "code": "Code",
            "test": "Test",
            "finish": "Terminer",
            "five_hour_reset": "RÉINITIALISATION 5H",
            "weekly_reset": "RÉINITIALISATION 7 JOURS",
        },
        "it": {
            "today": "OGGI",
            "week": "ULTIMI 7 GIORNI",
            "total": "TOTALE",
            "available": "Disponibile",
            "requests": "Richieste",
            "cache": "Cache",
            "output": "Output",
            "status": "STATO",
            "live": "LIVE",
            "task": "Stato AI Agent",
            "recent": "Chiamate strumenti recenti",
            "session": "Sessione",
            "completed": "Completato",
            "in_progress": "In corso",
            "pending": "In attesa",
            "analyze": "Analisi",
            "plan": "Piano",
            "code": "Codice",
            "test": "Test",
            "finish": "Fine",
            "five_hour_reset": "RESET 5 ORE",
            "weekly_reset": "RESET 7 GIORNI",
        },
    }
    return labels.get(lang, labels["en"]).get(key, labels["en"].get(key, key.upper()))


def _draw_agent_reference_brand(
    draw, x: int, y: int, size: int = 30, provider: str = "", agent_name: str = ""
) -> None:
    """Provider-specific monochrome mark for the first Agent row."""
    probe = f"{provider} {agent_name}".lower()
    if "gemini" in probe or "google" in probe:
        # Gemini-like four-point sparkle.
        half = max(5, size // 2)
        draw.polygon(
            [
                (x, y - half),
                (x + half // 3, y - half // 3),
                (x + half, y),
                (x + half // 3, y + half // 3),
                (x, y + half),
                (x - half // 3, y + half // 3),
                (x - half, y),
                (x - half // 3, y - half // 3),
            ],
            outline="black",
            fill=None,
        )
        draw.line((x - half // 2, y, x + half // 2, y), fill="black", width=2)
    elif "chatgpt" in probe or "openai" in probe:
        # ChatGPT/OpenAI-like interlocking loops.
        r = max(6, size // 3)
        for offset in (-5, 0, 5):
            draw.arc([x - r + offset, y - r, x + r + offset, y + r], 200, 20, fill="black", width=2)
        draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill="black")
    elif "codex" in probe:
        # Codex-like terminal prompt mark.
        r = max(9, size // 2)
        draw.rectangle([x - r, y - r, x + r, y + r], outline="black", width=2)
        draw.line((x - r // 2, y - 2, x - 2, y + 3, x - r // 2, y + 8), fill="black", width=2)
        draw.line((x + 3, y + 8, x + r // 2, y + 8), fill="black", width=2)
    else:
        r = max(6, size // 3)
        draw.ellipse([x - r, y - r, x + r, y + r], outline="black", width=2)
        draw.line((x - r, y, x + r, y), fill="black", width=2)
        draw.line((x, y - r, x, y + r), fill="black", width=2)


def _draw_agent_reference_usage_card(
    draw,
    box: list[int],
    kind: str,
    title: str,
    value: object,
    cost: object,
    available: object,
    requests: object,
    cache: object,
    output: object,
    data: dict,
    solid: bool = False,
) -> None:
    if solid:
        draw.rounded_rectangle(box, radius=18, outline="black", fill="white", width=2)
    else:
        _draw_rounded_dashed_box(draw, box, radius=18, color="black", step=5, dot=1)
    _draw_agent_usage_icon(draw, box[0] + 22, box[1] + 22, kind)
    draw.text((box[0] + 42, box[1] + 9), title, fill="black", font=AFB(15))
    draw.text(
        (box[2] - 16, box[1] + 9),
        format_agent_number(cost),
        fill="black",
        font=AFB(16),
        anchor="ra",
    )
    value_text = format_agent_number(value)
    draw.text((box[0] + 16, box[1] + 45), value_text, fill="black", font=AFB(23))
    available_text = (
        "--"
        if available is None
        else f"{max(0, min(100, int(available)))}% {_agent_screen_label('available', data)}"
    )
    draw.text((box[2] - 16, box[1] + 52), available_text, fill="black", font=AF(13), anchor="ra")
    bar = [box[0] + 16, box[1] + 81, box[2] - 16, box[1] + 96]
    _draw_rounded_dashed_box(draw, bar, radius=6, color="black", step=4, dot=1)
    try:
        ratio = max(0.0, min(100.0, float(available if available is not None else 0))) / 100.0
    except (TypeError, ValueError):
        ratio = 0.0
    if ratio:
        draw.rounded_rectangle(
            [bar[0] + 1, bar[1] + 1, bar[0] + 1 + int((bar[2] - bar[0] - 2) * ratio), bar[3] - 1],
            radius=5,
            fill="black",
        )
    rows = (("requests", requests), ("cache", cache), ("output", output))
    for index, (label, row_value) in enumerate(rows):
        draw.text(
            (box[0] + 18, box[1] + 99 + index * 17),
            f"{_agent_screen_label(label, data)}  {format_agent_number(row_value)}",
            fill="black",
            font=AF(12),
        )


def _agent_task_rows(data: dict) -> list[dict]:
    # Do not render a fabricated Analyze/Plan/Code checklist when no agent
    # session is active. Real task rows and result rows remain visible.
    state = str(data.get("state") or data.get("status") or "idle").lower()
    if (
        not data.get("agent_active")
        and state in {"idle", "unknown", "done", "completed", "failed", "error"}
        and not any(data.get(key) for key in ("tasks", "taskTitle", "currentStep", "result"))
    ):
        return []
    raw = data.get("tasks") if isinstance(data.get("tasks"), list) else []
    rows = [dict(item) for item in raw if isinstance(item, dict)][:5]
    if not rows:
        if data.get("taskTitle"):
            rows.append({"label": data.get("taskTitle"), "state": "active"})
        if data.get("currentStep"):
            rows.append({"label": data.get("currentStep"), "state": "active"})
        if data.get("result"):
            rows.append({"label": data.get("result"), "state": "done"})
    defaults = (
        ("analyze", "completed"),
        ("plan", "completed"),
        ("code", "in_progress"),
        ("test", "pending"),
        ("finish", "pending"),
    )
    for key, state in defaults:
        if len(rows) >= 5:
            break
        rows.append({"label": _agent_screen_label(key, data), "state": state})
    return rows[:5]


def _agent_task_state_label(state: str, data: dict) -> str:
    value = str(state or "pending").lower()
    if value in ("done", "success", "completed"):
        return _agent_screen_label("completed", data)
    if value in ("active", "running", "in_progress", "thinking", "calling_tool"):
        return _agent_screen_label("in_progress", data)
    return _agent_screen_label("pending", data)


def _draw_agent_task_mark(draw, x: int, y: int, size: int = 28) -> None:
    half = size // 2
    draw.rounded_rectangle([x - half, y - half, x + half, y + half], radius=6, fill="black")
    heights = (8, 16, 22, 12, 18)
    for index, height in enumerate(heights):
        px = x - 10 + index * 5
        draw.line([px, y - height // 2, px, y + height // 2], fill="white", width=2)


def _draw_agent_tool_mark(draw, x: int, y: int, size: int = 18) -> None:
    half = size // 2
    draw.polygon(
        [
            (x, y - half),
            (x + 3, y - 3),
            (x + half, y),
            (x + 3, y + 3),
            (x, y + half),
            (x - 3, y + 3),
            (x - half, y),
            (x - 3, y - 3),
        ],
        fill="black",
    )


def _draw_agent_reference_task_panel(draw, box: list[int], data: dict) -> None:
    _draw_rounded_dashed_box(draw, box, radius=18, color="black", step=5, dot=1)
    _draw_agent_task_mark(draw, box[0] + 28, box[1] + 28, 28)
    draw.text(
        (box[0] + 54, box[1] + 17), _agent_screen_label("task", data), fill="black", font=AFB(16)
    )
    _draw_dotted_line(
        draw, box[0] + 8, box[1] + 47, box[2] - 8, box[1] + 47, color="black", step=4, dot=1
    )
    for index, item in enumerate(_agent_task_rows(data)):
        y = box[1] + 65 + index * 20
        state = str(item.get("state") or "pending")
        mark = (
            "✓"
            if state.lower() in ("done", "success", "completed")
            else (
                "●"
                if state.lower() in ("active", "running", "in_progress", "thinking", "calling_tool")
                else "○"
            )
        )
        label = str(item.get("label") or "--")[:18]
        duration = str(item.get("duration") or item.get("elapsed") or "--:--")[:8]
        draw.text((box[0] + 30, y), mark, fill="black", font=AF(13))
        draw.text((box[0] + 48, y), label, fill="black", font=AFB(12))
        draw.text(
            (box[0] + 150, y), _agent_task_state_label(state, data), fill="black", font=AF(11)
        )
        draw.text((box[2] - 18, y), duration, fill="black", font=AF(11), anchor="ra")


def _draw_agent_reference_tools_panel(draw, box: list[int], data: dict) -> None:
    _draw_rounded_dashed_box(draw, box, radius=18, color="black", step=5, dot=1)
    _draw_agent_tool_mark(draw, box[0] + 28, box[1] + 26, 16)
    draw.text(
        (box[0] + 42, box[1] + 17), _agent_screen_label("recent", data), fill="black", font=AFB(13)
    )
    session = (
        data.get("session") or data.get("sessionDuration") or data.get("session_time") or "--:--:--"
    )
    draw.text(
        (box[2] - 16, box[1] + 19),
        f"{_agent_screen_label('session', data)}: {session}",
        fill="black",
        font=AF(10),
        anchor="ra",
    )
    calls = (
        data.get("recentToolCalls")
        or data.get("recent_tool_calls")
        or data.get("toolCalls")
        or data.get("tool_calls")
        or {}
    )
    if isinstance(calls, list):
        counts = {}
        for item in calls:
            name = str(item.get("name") if isinstance(item, dict) else item).upper()
            counts[name] = counts.get(name, 0) + 1
    elif isinstance(calls, dict):
        counts = {str(key).upper(): value for key, value in calls.items()}
    else:
        counts = {}
    if not counts and data.get("currentTool"):
        counts[str(data.get("currentTool")).upper()] = "--"
    preferred = ["MCP", "SEARCH", "READER", "ZREAD", "VISION"]
    # An idle screen must not invent recent tool calls. Keep the preferred
    # slots only when there is an actual event/count to display.
    names = (preferred + [name for name in counts if name not in preferred]) if counts else []
    for index, name in enumerate(names[:6]):
        col, row = index % 2, index // 2
        x = box[0] + 18 + col * 116
        y = box[1] + 48 + row * 31
        draw.rounded_rectangle(
            [x, y, x + 101, y + 21], radius=11, fill="white", outline="black", width=1
        )
        count_text = format_agent_number(counts.get(name, "--"))
        draw.text((x + 50, y + 5), f"{name}  {count_text}", fill="black", font=AFB(10), anchor="ma")


def _render_agent_reference_layout(data: dict) -> Image.Image:
    _ensure_pillow()
    data = dict(data or {})
    img = Image.new("RGB", (SCREEN_W, SCREEN_H), "white")
    draw = ImageDraw.Draw(img)
    agent_name = str(data.get("agentName") or "AI Agent")[:18]
    provider = str(data.get("provider") or "")[:10]
    version = str(data.get("agentVersion") or data.get("version") or "")[:9]
    state = str(data.get("state") or "unknown").replace("_", " ").upper()
    tool = str(data.get("currentTool") or "").strip().upper()
    status_text = f"{state}  ·  {tool}" if tool else state
    _draw_agent_reference_brand(draw, 28, 28, 30, provider, agent_name)
    # Keep provider/name/version together on the first row so the E-INK view
    # remains self-describing even when a browser event is not present.
    brand = agent_name
    if provider or version:
        brand = f"{agent_name} · {provider or 'AI'}" + (f" · {version}" if version else "")
    draw.text((54, 11), brand[:30], fill="black", font=AFB(22))
    draw.text(
        (476, 22), " ".join(part for part in clock_parts(data) if part), fill="black", font=AFB(17)
    )
    _draw_display_battery(img, draw, _display_battery_snapshot_from_payload(data))
    _draw_dotted_line(draw, 8, 59, 640, 59, color="black", step=4, dot=1)
    today_box = [16, 76, 369, 235]
    week_box = [378, 76, 632, 235]
    _draw_agent_reference_usage_card(
        draw,
        today_box,
        "today",
        _agent_screen_label("today", data),
        data.get("todayUsage", "--"),
        data.get("todayCostUsd", "--"),
        data.get("todayAvailablePercent"),
        data.get("todayRequests", "--"),
        data.get("todayCache", "--"),
        data.get("todayOutput", "--"),
        data,
        solid=True,
    )
    _draw_agent_reference_usage_card(
        draw,
        week_box,
        "week",
        _agent_screen_label("week", data),
        data.get("weekUsage", "--"),
        data.get("weekCostUsd", "--"),
        data.get("weekAvailablePercent"),
        data.get("weekRequests", "--"),
        data.get("weekCache", "--"),
        data.get("weekOutput", "--"),
        data,
    )
    status_reset_box = [16, 244, 369, 272]
    draw.rounded_rectangle(status_reset_box, radius=10, fill="black")
    draw.text((28, 251), _agent_screen_label("status", data), fill="white", font=AFB(12))
    draw.text((94, 250), status_text[:26], fill="white", font=AFB(13))
    _draw_agent_pet(draw, 326, 258, str(data.get("state") or "unknown"))
    draw.text((359, 251), _agent_screen_label("live", data), fill="white", font=AF(10), anchor="ra")
    draw.text(
        (399, 248),
        f"{_agent_screen_label('five_hour_reset', data)}: {data.get('fiveHourReset') or '--'}",
        fill="black",
        font=AFB(12),
    )
    draw.text(
        (399, 270),
        f"{_agent_screen_label('weekly_reset', data)}: {data.get('weeklyReset') or '--'}",
        fill="black",
        font=AFB(12),
    )
    _draw_agent_reference_task_panel(draw, [16, 300, 369, 472], data)
    _draw_agent_reference_tools_panel(draw, [378, 300, 632, 472], data)
    return img


def render_agent_fullscreen(data: dict) -> Image.Image:
    """Render the AI Agent status module; event/state handling remains unchanged."""
    _ensure_pillow()
    global _AGENT_RENDER_LANGUAGE
    payload = dict(data or {})
    _AGENT_RENDER_LANGUAGE = _system_agent_language()
    return _render_agent_reference_layout(payload)


def render_p6_fullscreen(data: dict) -> Image.Image:
    """Custom — 648×480 全屏，支持文件路径图片或文字"""
    title = data.get("title", "Custom Display")
    body = data.get("body", "")
    file_path = data.get("file_path", "")
    img_b64 = data.get("image", "")

    img = Image.new("RGB", (SCREEN_W, SCREEN_H), "white")
    draw = ImageDraw.Draw(img)

    def paste_fullscreen(source_img):
        cimg = source_img.convert("RGB")
        scale = max(SCREEN_W / cimg.width, SCREEN_H / cimg.height)
        resized = cimg.resize(
            (max(1, int(round(cimg.width * scale))), max(1, int(round(cimg.height * scale)))),
            Image.LANCZOS,
        )
        left = max(0, (resized.width - SCREEN_W) // 2)
        top = max(0, (resized.height - SCREEN_H) // 2)
        cropped = resized.crop((left, top, left + SCREEN_W, top + SCREEN_H))
        img.paste(cropped, (0, 0))

    # Image-only payloads should use the full screen instead of reserving a title bar.
    if not body and file_path:
        try:
            with Image.open(file_path) as source:
                source.seek(0)
                paste_fullscreen(source)
            return img
        except Exception:
            pass

    if not body and img_b64:
        try:
            import base64

            with Image.open(io.BytesIO(base64.b64decode(img_b64))) as source:
                source.seek(0)
                paste_fullscreen(source)
            return img
        except Exception:
            pass

    draw.rectangle([0, 0, SCREEN_W, 44], fill="black")
    draw.text((12, 12), title[:32], fill="white", font=F(20))

    ty = 60
    tx = 20
    img_placed = False

    # 优先从本地文件路径加载图片
    if file_path:
        try:
            cimg = Image.open(file_path).convert("RGB")
            cimg.thumbnail((300, 360), Image.LANCZOS)
            img.paste(cimg, (20, ty))
            tx = cimg.width + 36
            img_placed = True
        except Exception:
            pass

    # 其次从 base64
    if not img_placed and img_b64:
        try:
            import base64

            cimg = Image.open(io.BytesIO(base64.b64decode(img_b64))).convert("RGB")
            cimg.thumbnail((300, 360), Image.LANCZOS)
            img.paste(cimg, (20, ty))
            tx = cimg.width + 36
        except Exception:
            pass

    if body:
        max_w = SCREEN_W - tx - 20
        words = body.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if F(20).getlength(test) < max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        for i, line in enumerate(lines[:15]):
            draw.text((tx, ty + i * 26), line, fill="black", font=F(20))

    _hline(draw, SCREEN_H - 36, color=GRAY_BORDER)
    draw.text((8, SCREEN_H - 24), "JSAUX E-INK", fill=GRAY_BORDER, font=F(13))
    return img


# ──────────────────────────────────────────────
# Settings
# ──────────────────────────────────────────────
CUSTOM_LIBRARY_SETTING_KEYS = {
    "custom_selected_path",
    "custom_asset_paths",
    "custom_asset_sources",
    "custom_slideshow_enabled",
    "photo_frame_folder",
    "photo_frame_excluded_paths",
    "photo_frame_interval_minutes",
    "photo_frame_interval_enabled",
    "module_switch_interval_minutes",
    "module_switch_enabled",
}


def _clamp_photo_frame_interval_minutes(value: object) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = PHOTO_FRAME_INTERVAL_DEFAULT
    return max(PHOTO_FRAME_INTERVAL_MIN, min(PHOTO_FRAME_INTERVAL_MAX, minutes))


def _clamp_module_switch_interval_minutes(value: object) -> int:
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = MODULE_SWITCH_INTERVAL_DEFAULT
    minutes = max(MODULE_SWITCH_INTERVAL_MIN, min(MODULE_SWITCH_INTERVAL_MAX, minutes))
    return (
        MODULE_SWITCH_INTERVAL_MIN
        + ((minutes - MODULE_SWITCH_INTERVAL_MIN) // MODULE_SWITCH_INTERVAL_STEP)
        * MODULE_SWITCH_INTERVAL_STEP
    )


def _natural_photo_frame_sort_key(path: Path) -> tuple:
    parts = re.split(r"(\d+)", path.name.casefold())
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts)


def _resolve_existing_path_case_insensitive(path: str) -> Optional[Path]:
    """Resolve an existing local path, tolerating one unambiguous case mismatch."""
    candidate = Path(path).expanduser()
    try:
        return candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        pass

    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    parts = candidate.parts
    if not parts:
        return None
    current = Path(parts[0])
    for part in parts[1:]:
        exact = current / part
        if exact.exists():
            current = exact
            continue
        try:
            matches = [
                item for item in current.iterdir() if item.name.casefold() == part.casefold()
            ]
        except OSError:
            return None
        if len(matches) != 1:
            return None
        current = matches[0]
    try:
        return current.resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def _list_photo_frame_files(folder_path: str, excluded_paths=None) -> list[Path]:
    folder = _resolve_existing_path_case_insensitive(folder_path)
    if folder is None:
        return []
    if not folder.is_dir():
        return []
    excluded = {str(Path(item).expanduser().resolve()) for item in (excluded_paths or []) if item}
    files = []
    try:
        for item in folder.iterdir():
            if item.is_file() and item.suffix.casefold() in PHOTO_FRAME_IMAGE_EXTENSIONS:
                resolved = item.resolve()
                if str(resolved) not in excluded:
                    files.append(resolved)
    except OSError:
        return []
    return sorted(files, key=_natural_photo_frame_sort_key)


def _next_module_switch_id(current_module_id: Optional[int]) -> int:
    try:
        position = MODULE_SWITCH_MODULE_IDS.index(int(current_module_id))
    except (TypeError, ValueError):
        position = -1
    return MODULE_SWITCH_MODULE_IDS[(position + 1) % len(MODULE_SWITCH_MODULE_IDS)]


def _settings_path():
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, "settings.json")


def _settings_lock_path():
    return os.path.join(decky.DECKY_PLUGIN_SETTINGS_DIR, ".settings.lock")


def _hardware_history_path() -> Path:
    return Path(decky.DECKY_PLUGIN_SETTINGS_DIR) / "performance-history.json"


def _default_settings() -> dict:
    return {
        **DISPLAY_DEFAULTS,
        "mode": "dashboard",
        "display_mode": "single",
        "auto_refresh": False,
        "interval_minutes": 5,
        "timeline_sec": TIMELINE_DEFAULT_SEC,
        "stay_duration": TIMELINE_DEFAULT_SEC,
        "latitude": 0.0,
        "longitude": 0.0,
        "city": "",
        "country": "",
        "connection_enabled": False,
        "device_address": "",
        "desktop_last_device_address": "",
        "device_candidates": [],
        "display_battery_percent": None,
        "game_time_display_mode": "auto",
        "game_time_last_app_id": "",
        "game_time_last_name": "",
        "game_time_last_poster_path": "",
        "game_time_last_session_min": 0,
        "game_time_last_total_minutes": 0,
        "brightness": 80,
        "single_module_id": 0,
        "module_cycle_ids": [0, 1, 2, 3, 4, 5, 6],
        "custom_selected_path": "",
        "custom_asset_paths": [],
        "custom_asset_sources": {},
        "custom_slideshow_enabled": False,
        "photo_frame_folder": "",
        "photo_frame_excluded_paths": [],
        "photo_frame_interval_minutes": PHOTO_FRAME_INTERVAL_DEFAULT,
        "photo_frame_interval_enabled": False,
        "module_switch_interval_minutes": MODULE_SWITCH_INTERVAL_DEFAULT,
        "module_switch_enabled": False,
    }


def _load_settings() -> dict:
    settings = _default_settings()
    try:
        with open(_settings_path()) as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            settings.update(loaded)
            if "connection_enabled" not in loaded:
                settings["connection_enabled"] = bool(loaded.get("device_address"))
    except Exception:
        pass
    return settings


def _save_settings(s: dict, *, changed_keys=None):
    settings_path = _settings_path()
    settings_dir = os.path.dirname(settings_path)
    os.makedirs(settings_dir, exist_ok=True)
    with open(_settings_lock_path(), "a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        latest = _load_settings()
        keys = (set(s) - CUSTOM_LIBRARY_SETTING_KEYS) if changed_keys is None else set(changed_keys)
        for key in keys:
            if key in s:
                latest[key] = s[key]
        fd, temporary_path = tempfile.mkstemp(prefix=".settings-", suffix=".tmp", dir=settings_dir)
        try:
            with os.fdopen(fd, "w") as temporary_file:
                json.dump(latest, temporary_file, indent=2)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, settings_path)
        finally:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass
        s.clear()
        s.update(latest)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    return latest


def _normalize_settings(settings: dict) -> dict:
    normalized = dict(settings)
    normalized["connection_enabled"] = bool(normalized.get("connection_enabled"))
    candidates = []
    seen_addresses = set()
    for item in normalized.get("device_candidates", []) or []:
        if not isinstance(item, dict):
            continue
        address = str(item.get("address") or "").strip().upper()
        if not address or address in seen_addresses:
            continue
        seen_addresses.add(address)
        try:
            last_seen = float(item.get("last_seen") or 0.0)
        except (TypeError, ValueError):
            last_seen = 0.0
        candidates.append(
            {
                "address": address,
                "name": str(item.get("name") or "JSAUX E-INK"),
                "last_seen": last_seen,
            }
        )
    normalized["device_candidates"] = sorted(
        candidates,
        key=lambda item: item["last_seen"],
        reverse=True,
    )[:MAX_DEVICE_CANDIDATES]
    display_mode = str(normalized.get("game_time_display_mode", "auto") or "auto").strip().lower()
    normalized["game_time_display_mode"] = (
        display_mode if display_mode in GAME_TIME_DISPLAY_MODES else "auto"
    )
    mode = normalized.get("mode", "dashboard")
    if mode == "dashboard":
        normalized.setdefault("legacy_mode", "dashboard")
    if normalized.get("display_mode") == "multi" and mode == "timeline":
        normalized["mode"] = "carousel"
    if mode not in (*DISPLAY_MODE_SEQUENCE, "carousel", "custom", "dashboard", "module", "agent"):
        normalized["mode"] = "deck_status"
    try:
        stay_duration = int(
            normalized.get("stay_duration", normalized.get("timeline_sec", TIMELINE_DEFAULT_SEC))
        )
    except (TypeError, ValueError):
        stay_duration = TIMELINE_DEFAULT_SEC
    stay_duration = max(TIMELINE_MIN_SEC, min(TIMELINE_MAX_SEC, stay_duration))
    normalized["stay_duration"] = stay_duration
    normalized.setdefault(
        "display_mode", "multi" if normalized.get("mode") == "carousel" else "single"
    )
    normalized["photo_frame_folder"] = str(normalized.get("photo_frame_folder") or "").strip()
    normalized["photo_frame_interval_minutes"] = _clamp_photo_frame_interval_minutes(
        normalized.get("photo_frame_interval_minutes", PHOTO_FRAME_INTERVAL_DEFAULT)
    )
    normalized["photo_frame_interval_enabled"] = bool(
        normalized.get("photo_frame_interval_enabled")
    )
    normalized["module_switch_interval_minutes"] = _clamp_module_switch_interval_minutes(
        normalized.get("module_switch_interval_minutes", MODULE_SWITCH_INTERVAL_DEFAULT)
    )
    normalized["module_switch_enabled"] = bool(normalized.get("module_switch_enabled"))
    # These timers drive different targets, but their ON states are mutually
    # exclusive. Normalize persisted and remote state so no caller can leave
    # both schedulers enabled.
    if normalized["photo_frame_interval_enabled"]:
        normalized["module_switch_enabled"] = False
    elif normalized["module_switch_enabled"]:
        normalized["photo_frame_interval_enabled"] = False
    exclusions = []
    for item in normalized.get("photo_frame_excluded_paths", []) or []:
        try:
            resolved = str(Path(item).expanduser().resolve())
        except (OSError, RuntimeError, TypeError):
            continue
        if resolved not in exclusions:
            exclusions.append(resolved)
    normalized["photo_frame_excluded_paths"] = exclusions
    return normalized


# ──────────────────────────────────────────────
# Plugin
# ──────────────────────────────────────────────
# ??????????????????????????????????????????????
# Display refresh policy
# ??????????????????????????????????????????????
def _target_refresh_cadence(target: tuple[str, Optional[int]]) -> Optional[int]:
    """Return the physical display-update interval for an active target."""
    kind, module_id = target
    if kind in ("dashboard", "clock", "deck_status"):
        return LIVE_DISPLAY_REFRESH_SEC
    if kind == "weather":
        return WEATHER_DISPLAY_REFRESH_SEC
    if kind == "calendar":
        return CALENDAR_DISPLAY_REFRESH_SEC
    if kind == "game-time":
        return GAME_TIME_POSTER_REFRESH_SEC
    if kind in ("timeline", "module"):
        if module_id in (6, AGENT_MODULE_ID):
            return None
        if module_id == 3:
            return WEATHER_DISPLAY_REFRESH_SEC
        if module_id == 5:
            return CALENDAR_DISPLAY_REFRESH_SEC
        return LIVE_DISPLAY_REFRESH_SEC
    return None


def _target_refresh_key(
    target: tuple[str, Optional[int]], now: datetime
) -> Optional[tuple[object, ...]]:
    """Produce a wall-clock key so paused tasks resume on the next real boundary."""
    cadence = _target_refresh_cadence(target)
    if cadence is None:
        return None
    if cadence == CALENDAR_DISPLAY_REFRESH_SEC:
        return ("calendar", now.year, now.month, now.day, now.hour // 12)
    if cadence == WEATHER_DISPLAY_REFRESH_SEC:
        return ("weather", now.year, now.month, now.day, now.hour // 4)
    if cadence == GAME_TIME_POSTER_REFRESH_SEC:
        # Poster/AUTO frames are deliberately bucketed at the configured
        # five-minute cadence, rather than the generic live minute key.
        return ("game-time", target[1], int(now.timestamp()) // cadence)
    return ("live", target[0], target[1], int(now.timestamp()) // 60)


def _target_refresh_is_due(
    target: tuple[str, Optional[int]],
    now: datetime,
    previous_observed_at: Optional[datetime] = None,
) -> bool:
    cadence = _target_refresh_cadence(target)
    if previous_observed_at is None:
        return cadence is not None
    if cadence == LIVE_DISPLAY_REFRESH_SEC:
        current_minute = now.replace(second=0, microsecond=0)
        previous_minute = previous_observed_at.replace(second=0, microsecond=0)
        return int(previous_observed_at.timestamp()) // 60 < int(now.timestamp()) // 60 or (
            previous_minute == current_minute and previous_observed_at.second < 1 <= now.second
        )
    if cadence == GAME_TIME_POSTER_REFRESH_SEC:
        previous_bucket = int(previous_observed_at.timestamp()) // cadence
        current_bucket = int(now.timestamp()) // cadence
        return previous_bucket < current_bucket
    if cadence == WEATHER_DISPLAY_REFRESH_SEC:
        boundary = now.replace(
            hour=now.hour - (now.hour % 4),
            minute=0,
            second=0,
            microsecond=0,
        )
        return previous_observed_at.timestamp() < boundary.timestamp() <= now.timestamp() or (
            previous_observed_at.replace(
                hour=now.hour - (now.hour % 4),
                minute=0,
                second=0,
                microsecond=0,
            )
            == boundary
            and previous_observed_at.second < 1 <= now.second
        )
    if cadence == CALENDAR_DISPLAY_REFRESH_SEC:
        boundary = now.replace(
            hour=now.hour - (now.hour % 12),
            minute=0,
            second=0,
            microsecond=0,
        )
        return previous_observed_at.timestamp() < boundary.timestamp() <= now.timestamp() or (
            previous_observed_at.replace(
                hour=now.hour - (now.hour % 12), minute=0, second=0, microsecond=0
            )
            == boundary
            and previous_observed_at.second < 1 <= now.second
        )
    return False


class EInkCore:
    device_info: Optional[DeviceInfo] = None
    settings: dict = {}
    _refresh_task: Optional[asyncio.Task] = None
    _background_refresh_task: Optional[asyncio.Task] = None
    _cycle_task: Optional[asyncio.Task] = None
    _photo_frame_task: Optional[asyncio.Task] = None
    _hardware_task: Optional[asyncio.Task] = None
    _startup_connect_task: Optional[asyncio.Task] = None
    _reconnect_task: Optional[asyncio.Task] = None
    _timeline_idx: int = 0
    _cycle_pos: int = 0
    _module_data: dict = {}
    _ble_lock: Optional[asyncio.Lock] = None
    _device_connected: bool = False
    _connection_state: str = CONNECTION_STATE_OFF
    _last_error: str = ""
    _last_scan_results: list = []
    _last_game_progress_signature = None
    _last_status_bar_signature = None
    _last_performance_signature = None
    _last_weather_signature = None
    _last_monohub_signature = None
    _active_module_id: Optional[int] = None
    _desktop_control_mode: bool = False
    _daemon_control_mode: bool = False
    _pending_scheduled_refresh_key = None
    _scheduled_refresh_inflight_key = None
    _latest_background_refresh_request = None
    _background_ble_active: bool = False
    _background_refresh_stopping: bool = False
    _latest_foreground_display_request: int = 0
    _latest_foreground_scan_request: int = 0
    _foreground_display_task: Optional[asyncio.Task] = None
    _foreground_ble_rediscovery_request: Optional[int] = None
    _last_transfer: Optional[dict] = None
    _agent_status: Optional[dict] = None
    _agent_restore_target: Optional[dict] = None
    _agent_restore_task: Optional[asyncio.Task] = None
    _agent_takeover_active: bool = False
    _last_agent_signature: Optional[tuple] = None
    _game_artwork_attempted: set[str] = set()
    _codex_status: dict = {}
    _codex_status_refreshed_at: float = 0.0

    # ── Lifecycle ─────────────────────────────
    async def _main(self):
        self.settings = _normalize_settings(_load_settings())
        self._module_data = {}
        self._ble_lock = asyncio.Lock()
        self._shared_ble_adapter_lease = SharedBleAdapterLease(
            debug_logger=lambda message: decky.logger.info(message),
        )
        self._refresh_task = None
        self._background_refresh_task = None
        self._cycle_task = None
        self._photo_frame_task = None
        self._hardware_task = None
        self._startup_connect_task = None
        self._reconnect_task = None
        self._load_hardware_history()
        self._last_scheduled_refresh_key = None
        self._pending_scheduled_refresh_key = None
        self._scheduled_refresh_inflight_key = None
        self._latest_background_refresh_request = None
        self._background_ble_active = False
        self._background_refresh_stopping = False
        self._latest_foreground_display_request = 0
        self._latest_foreground_scan_request = 0
        self._foreground_display_task = None
        self._foreground_ble_rediscovery_request = None
        self._last_transfer = None
        self._agent_status = None
        self._agent_restore_target = None
        self._agent_restore_task = None
        self._agent_takeover_active = False
        self._last_agent_signature = None
        self._game_artwork_attempted = set()
        self._codex_status = {}
        self._codex_status_refreshed_at = 0.0
        self._last_scheduler_observed_at = None
        self._desktop_owner_seen = False
        self._location_cache = {}
        self._location_refreshed_at = 0.0
        self._weather_cache = {}
        self._weather_refresh_lock = asyncio.Lock()
        self._cycle_pos = 0
        self.device_info = None
        self._device_connected = False
        self._connection_state = (
            CONNECTION_STATE_CONNECTING if self._connection_enabled() else CONNECTION_STATE_OFF
        )
        try:
            saved_display_battery = int(self.settings.get("display_battery_percent"))
        except (TypeError, ValueError):
            saved_display_battery = None
        if saved_display_battery is not None:
            saved_display_battery = max(0, min(100, saved_display_battery))
        self._display_battery_percent = saved_display_battery
        self._display_battery_sample = (
            (saved_display_battery, time.time()) if saved_display_battery is not None else None
        )
        self._display_charging_until = 0.0
        self._last_error = ""
        self._last_scan_results = []
        self._ble_device_targets = {}
        self._last_game_progress_signature = None
        self._last_status_bar_signature = None
        self._last_performance_signature = None
        self._last_weather_signature = None
        self._last_monohub_signature = None
        self._active_module_id = None
        self._sync_cycle_position_from_current()
        decky.logger.info("JSAUX E-INK plugin v1.2 loaded")
        await decky.emit("status_update", self._build_status())
        self._start_hardware_sampler()
        self._sync_refresh_loop(restart=True)
        if self._connection_enabled() and (
            not self._desktop_control_mode or self._daemon_control_mode
        ):
            self._startup_connect_task = asyncio.get_running_loop().create_task(
                self._run_startup_autoconnect()
            )

    async def _unload(self):
        if self._agent_restore_task and not self._agent_restore_task.done():
            self._agent_restore_task.cancel()
            try:
                await self._agent_restore_task
            except asyncio.CancelledError:
                pass
            self._agent_restore_task = None
        await self._cancel_connection_tasks()
        self._stop_cycle_loop()
        self._stop_photo_frame_loop()
        self._stop_refresh_loop()
        await self._stop_background_refresh_queue()
        self._stop_hardware_sampler()
        decky.logger.info("Plugin unloaded")

    def _connection_enabled(self) -> bool:
        return bool(self.settings.get("connection_enabled"))

    def _display_target_enabled(self) -> bool:
        return self._connection_enabled() and bool(self.settings.get("device_address"))

    async def _cancel_connection_tasks(self) -> None:
        current_task = asyncio.current_task()
        pending = []
        for attribute in ("_startup_connect_task", "_reconnect_task"):
            task = getattr(self, attribute, None)
            setattr(self, attribute, None)
            if task and task is not current_task and not task.done():
                task.cancel()
                pending.append(task)
        for task in pending:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _cancel_foreground_display_task(self) -> None:
        current_task = asyncio.current_task()
        task = self._foreground_display_task
        # Invalidate all in-flight foreground requests before changing BLE
        # ownership. Their completion cannot write the connection state back ON.
        self._latest_foreground_display_request += 1
        self._foreground_ble_rediscovery_request = None
        self._foreground_display_task = None
        if task and task is not current_task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _cancel_background_display_task(self) -> None:
        self._latest_background_refresh_request = None
        self._scheduled_refresh_inflight_key = None
        task = self._background_refresh_task
        self._background_refresh_task = None
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._background_ble_active = False

    async def _wait_for_preempted_background_task(self) -> None:
        await asyncio.sleep(0)
        task = self._background_refresh_task
        background_had_ble = bool(self._background_ble_active)
        if task and task is not asyncio.current_task() and task.cancelling():
            try:
                await asyncio.wait_for(task, timeout=BLE_CANCEL_DRAIN_TIMEOUT_SEC)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                decky.logger.warning("Timed out draining cancelled background BLE refresh")
                # Give BlueZ a short interval to retire the old GATT operation
                # before the foreground request attempts a new connection.
                await asyncio.sleep(BLE_DISCONNECT_SETTLE_SEC)
        if not background_had_ble:
            self._foreground_ble_rediscovery_request = None

    async def _run_startup_autoconnect(self) -> None:
        try:
            connected = await self._startup_autoconnect()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            decky.logger.warning("Connection cycle failed: %s", exc)
            self._last_error = f"Connection failed: {exc}"
            connected = False
        if not connected and self._connection_enabled() and not self._device_connected:
            await self._finish_failed_connection_cycle()

    async def _finish_failed_connection_cycle(self) -> None:
        if self._device_connected or not self._connection_enabled():
            return
        error = self._last_error or "Unable to connect to any JSAUX E-INK device"
        if not str(self.settings.get("device_address") or "").strip():
            self.settings["connection_enabled"] = False
            _save_settings(self.settings, changed_keys={"connection_enabled"})
        self._set_connection_state(False, error=error, state=CONNECTION_STATE_OFF)
        self._sync_refresh_loop(restart=True)
        await self._emit_status()

    def _ensure_reconnect_task(self) -> None:
        if not self._connection_enabled() or self._device_connected:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        self._reconnect_task = asyncio.get_running_loop().create_task(
            self._connection_reconnect_loop()
        )

    async def _connection_reconnect_loop(self) -> None:
        for attempt, delay in enumerate(CONNECTION_RETRY_DELAYS_SEC, 1):
            await asyncio.sleep(delay)
            if not self._connection_enabled() or self._device_connected:
                return
            decky.logger.info(
                "Connection is interrupted; starting prioritized BLE connection cycle %d/%d",
                attempt,
                len(CONNECTION_RETRY_DELAYS_SEC),
            )
            try:
                connected = await self._startup_autoconnect()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                decky.logger.warning("Background BLE reconnect failed: %s", exc)
                self._last_error = f"Connection failed: {exc}"
                connected = False
            if connected or self._device_connected:
                return
            await self._emit_status()
        if self._connection_enabled() and not self._device_connected:
            await self._finish_failed_connection_cycle()

    async def _startup_autoconnect(self) -> bool:
        await asyncio.sleep(0)
        if self._device_connected:
            self._set_connection_state(True, device_info=self.device_info)
            await self._emit_status()
            return True
        if self._desktop_owner_active():
            decky.logger.info(
                "Desktop controller owns BLE; waiting to resume Decky startup auto-connect"
            )
        while self._desktop_owner_active():
            await asyncio.sleep(DESKTOP_LEASE_POLL_SEC)

        self._set_connection_state(False, state=CONNECTION_STATE_CONNECTING)
        await self._emit_status()

        saved_address = str(self.settings.get("device_address") or "").strip().upper()
        if self._connection_enabled() and saved_address:
            try:
                if await self._connect_saved_address_fast(saved_address):
                    return True
                decky.logger.warning(
                    "Saved EInk fast auto-connect failed for %s; retrying the saved address",
                    saved_address,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                decky.logger.warning(
                    "Saved EInk fast auto-connect failed for %s: %s; retrying the saved address",
                    saved_address,
                    exc,
                )
            try:
                if await self.connect(saved_address):
                    return True
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                decky.logger.warning(
                    "Saved EInk auto-connect retry failed for %s: %s",
                    saved_address,
                    exc,
                )
            decky.logger.warning(
                "Saved EInk auto-connect failed for %s; trying exact-address rediscovery",
                saved_address,
            )
            # A peripheral can disappear from BlueZ after an ATT failure and
            # later resume advertising under the same public MAC. Refresh the
            # exact saved target before giving up; do not choose another E-Ink
            # display merely because several are nearby.
            try:
                recovered_target = await self._rediscover_ble_client_target(saved_address)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                decky.logger.warning("Saved EInk rediscovery failed for %s: %s", saved_address, exc)
                recovered_target = None
            if recovered_target is not None:
                self._ble_device_targets[saved_address] = recovered_target
                try:
                    if await self.connect(saved_address):
                        return True
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    decky.logger.warning(
                        "Saved EInk rediscovered connect failed for %s: %s", saved_address, exc
                    )
            return False

        bluez_results = await asyncio.to_thread(self._scan_bluetoothctl_devices)
        connected_results = [item for item in bluez_results if item.get("connected")]
        if connected_results:
            ordered_connected = self._build_connection_candidates(
                connected_results, include_history=False
            )
            self._last_scan_results = ordered_connected
            decky.logger.info(
                "Trying %d BlueZ-connected EInk candidate(s) before discovery",
                len(ordered_connected),
            )
            if ordered_connected and await self.connect(ordered_connected[0]["address"]):
                return True

        decky.logger.info("Startup auto-connect scanning for a supported E-INK display")
        try:
            discovered = await self.scan()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            decky.logger.warning("Startup fallback scan failed: %s", exc)
            discovered = []

        candidates = self._build_connection_candidates(discovered)
        self._last_scan_results = candidates
        if candidates:
            decky.logger.info(
                "Trying %d EInk candidate(s) in BlueZ-connected/live-new-broadcast/saved-history order",
                len(candidates),
            )
            if await self.connect(candidates[0]["address"]):
                return True

        decky.logger.warning("Startup auto-connect did not find a reachable verified display")
        return False

    def _should_run_refresh_loop(self) -> bool:
        target = self._get_active_display_target()
        return bool(
            self._connection_enabled()
            and self._device_connected
            and self.settings.get("auto_refresh")
            and self.settings.get("device_address")
            and target is not None
            and self._is_scheduled_refresh_target(target)
        )

    @staticmethod
    def _is_scheduled_refresh_target(target: tuple[str, Optional[int]]) -> bool:
        return _target_refresh_cadence(target) is not None

    def _should_run_module_switch_loop(self) -> bool:
        return bool(
            not self._agent_takeover_active
            and not self._desktop_owner_active()
            and self._connection_enabled()
            and self._device_connected
            and self.settings.get("device_address")
            and self.settings.get("module_switch_enabled")
            and self.settings.get("mode", "deck_status") != "custom"
        )

    def _should_run_cycle_loop(self) -> bool:
        return self._should_run_module_switch_loop()

    def _should_run_photo_frame_loop(self) -> bool:
        return bool(
            not self._desktop_owner_active()
            and self._display_target_enabled()
            and self._device_connected
            and self.settings.get("mode") == "custom"
            and self.settings.get("photo_frame_interval_enabled")
            and _list_photo_frame_files(
                self.settings.get("photo_frame_folder", ""),
                self.settings.get("photo_frame_excluded_paths", []),
            )
        )

    def _sync_refresh_loop(self, restart: bool = False) -> None:
        current_task = asyncio.current_task()
        if restart and current_task is not self._refresh_task:
            self._last_scheduled_refresh_key = None
        if self._should_run_refresh_loop():
            if not self._refresh_task or self._refresh_task.done():
                self._start_refresh_loop()
        elif current_task is not self._refresh_task:
            self._stop_refresh_loop()

        if self._should_run_cycle_loop():
            if restart and current_task is not self._cycle_task:
                self._stop_cycle_loop()
            if not self._cycle_task or self._cycle_task.done():
                self._start_cycle_loop()
        elif current_task is not self._cycle_task:
            self._stop_cycle_loop()

        if self._should_run_photo_frame_loop():
            if restart and current_task is not self._photo_frame_task:
                self._stop_photo_frame_loop()
            if not self._photo_frame_task or self._photo_frame_task.done():
                self._start_photo_frame_loop()
        elif current_task is not self._photo_frame_task:
            self._stop_photo_frame_loop()

    def _desktop_owner_active(self) -> bool:
        return (
            not self._desktop_control_mode
            and not self._daemon_control_mode
            and desktop_lease_active()
        )

    def _reload_settings_after_desktop_handoff(self) -> None:
        self.settings = _normalize_settings(_load_settings())
        self._sync_cycle_position_from_current()

    def _reject_desktop_owned_ble(self, action: str) -> bool:
        if not self._desktop_owner_active():
            return False
        self._last_error = f"Desktop controller is active; {action} is unavailable in Decky"
        decky.logger.info(self._last_error)
        return True

    async def _emit_custom_file_selected(self, path: str) -> None:
        await decky.emit(
            "custom_file_selected",
            {
                "path": path,
                "name": Path(path).name if path else "",
            },
        )

    def _agent_signature(self, snapshot: Optional[dict]) -> tuple:
        if not isinstance(snapshot, dict):
            return ()
        return tuple(
            snapshot.get(key)
            for key in (
                "agentId",
                "taskId",
                "state",
                "currentTool",
                "taskTitle",
                "currentStep",
                "progress",
                "todayUsage",
                "weekUsage",
                "totalUsage",
                "result",
                "updatedAt",
            )
        )

    def _agent_display_payload(self) -> dict:
        snapshot = dict(self._agent_status or {})
        codex = dict(self._codex_status or {})
        # Optional local Codex snapshot (stub in the public tree) may only
        # supply identity while a session is active. Usage/account metadata
        # alone must not make an idle Agent screen claim that Codex is running.
        codex_sessions = codex.get("sessions") or {}
        codex_items = codex_sessions.get("items") or []
        codex_active = int(codex_sessions.get("running_count") or 0) > 0 or any(
            str(item.get("status") or "").lower() == "running" or bool(item.get("live"))
            for item in codex_items
            if isinstance(item, dict)
        )
        if codex_active and (not snapshot.get("provider") or not snapshot.get("agentName")):
            snapshot.setdefault("provider", "codex")
            snapshot.setdefault("agentName", "Codex")
            snapshot.setdefault("agentVersion", "CLI")
            snapshot["codex_status"] = codex
            account = next((a for a in codex.get("accounts", []) if a.get("active")), None)
            primary = (account or {}).get("primary") or {}
            secondary = (account or {}).get("secondary") or {}
            snapshot.setdefault(
                "todayAvailablePercent",
                (
                    max(0, 100 - int(primary.get("used_percent")))
                    if primary.get("used_percent") is not None
                    else None
                ),
            )
            snapshot.setdefault(
                "weekAvailablePercent",
                (
                    max(0, 100 - int(secondary.get("used_percent")))
                    if secondary.get("used_percent") is not None
                    else None
                ),
            )
            snapshot.setdefault("todayUsage", (codex.get("tokens") or {}).get("tokens_5h") or "--")
            snapshot.setdefault("weekUsage", (codex.get("tokens") or {}).get("tokens_7d") or "--")
            snapshot.setdefault(
                "taskTitle", ((codex.get("sessions") or {}).get("items") or [{}])[0].get("name", "")
            )
        snapshot.setdefault("language", _system_agent_language())
        snapshot.setdefault("agentName", "AI Agent")
        snapshot.setdefault("provider", "")
        snapshot.setdefault("agentVersion", "")
        snapshot.setdefault("state", "idle")
        snapshot.setdefault("todayUsage", "--")
        snapshot.setdefault("weekUsage", "--")
        snapshot.setdefault("totalUsage", "--")
        snapshot.setdefault("usageProgress", snapshot.get("progress") or 0)
        snapshot.setdefault("fiveHourReset", snapshot.get("todayReset") or "--")
        snapshot.setdefault("weeklyReset", snapshot.get("weekReset") or "--")
        snapshot.setdefault(
            "country",
            str(
                getattr(self, "_location_cache", {}).get("country")
                or self.settings.get("country", "")
                or self.settings.get("city", "")
                or _system_locale_country()
                or ""
            ),
        )
        return _with_display_battery_snapshot(snapshot, *self._pending_display_battery_state())

    def _capture_agent_restore_target(self) -> dict:
        return {
            "mode": self.settings.get("mode", "dashboard"),
            "display_mode": self.settings.get("display_mode", "single"),
            "single_module_id": self._get_single_module_id(),
            "auto_refresh": bool(self.settings.get("auto_refresh", False)),
            "timeline_idx": self._timeline_idx,
        }

    async def _restore_agent_target(self) -> bool:
        target = self._agent_restore_target
        self._agent_restore_target = None
        self._agent_takeover_active = False
        if not isinstance(target, dict):
            await self._emit_status()
            return False
        self.settings["mode"] = target.get("mode", "dashboard")
        self.settings["display_mode"] = target.get("display_mode", "single")
        previous_id = self._sanitize_module_id(target.get("single_module_id"))
        if previous_id is not None:
            self.settings["single_module_id"] = previous_id
            self._timeline_idx = int(target.get("timeline_idx", previous_id) or previous_id)
        self.settings["auto_refresh"] = bool(target.get("auto_refresh", False))
        _save_settings(
            self.settings, changed_keys={"mode", "display_mode", "single_module_id", "auto_refresh"}
        )
        self._sync_refresh_loop(restart=True)
        return await self._do_refresh() if self._display_target_enabled() else False

    async def _agent_restore_after_hold(self, task_id: str, updated_at: float) -> None:
        try:
            await asyncio.sleep(AGENT_RESULT_HOLD_SEC)
            current = self._agent_status or {}
            if (
                str(current.get("taskId") or "") == task_id
                and float(current.get("updatedAt") or 0.0) == updated_at
                and str(current.get("state") or "") in ("success", "failed")
            ):
                await self._restore_agent_target()
        except asyncio.CancelledError:
            pass

    async def set_agent_status(self, event: dict | None) -> dict:
        now = time.time()
        previous = self._agent_status
        previous_active = is_agent_active(previous, now=now)
        snapshot = normalize_agent_event(event, now=now)
        if not isinstance(event, dict) or not any(
            key in event for key in ("language", "lang", "locale")
        ):
            snapshot["language"] = _system_agent_language()
        current_active = is_agent_active(snapshot, now=now)
        signature = self._agent_signature(snapshot)
        self._agent_status = snapshot
        if (
            self._agent_restore_task
            and not self._agent_restore_task.done()
            and snapshot.get("state") not in ("success", "failed")
        ):
            self._agent_restore_task.cancel()
            self._agent_restore_task = None
        if current_active and not previous_active and not self._agent_takeover_active:
            self._agent_restore_target = self._capture_agent_restore_target()
            self._agent_takeover_active = True
            self.settings.update(
                {
                    "mode": "agent",
                    "display_mode": "single",
                    "single_module_id": AGENT_MODULE_ID,
                    "auto_refresh": False,
                }
            )
            _save_settings(
                self.settings,
                changed_keys={"mode", "display_mode", "single_module_id", "auto_refresh"},
            )
            self._timeline_idx = AGENT_MODULE_ID
            self._last_agent_signature = None
        await decky.emit("agent_status_update", snapshot)
        if (
            current_active
            and signature != self._last_agent_signature
            and self._display_target_enabled()
        ):
            self._last_agent_signature = signature
            await self._run_foreground_display_request(
                lambda request: self._dispatch_module(
                    AGENT_MODULE_ID, set_active=True, foreground_request=request
                )
            )
        elif not current_active and previous_active and self._agent_takeover_active:
            await self._restore_agent_target()
        elif (
            str(snapshot.get("state") or "") in ("success", "failed")
            and self._agent_takeover_active
        ):
            self._agent_restore_task = asyncio.create_task(
                self._agent_restore_after_hold(
                    str(snapshot.get("taskId") or ""), float(snapshot.get("updatedAt") or now)
                )
            )
        else:
            await self._emit_status()
        return snapshot

    async def get_agent_status(self) -> dict:
        await self._refresh_codex_status()
        snapshot = dict(self._agent_status or normalize_agent_event({}, now=time.time()))
        # In-app agent status remains authoritative; any Codex snapshot is additive.
        snapshot["codex_status"] = dict(self._codex_status)
        return snapshot

    async def _refresh_codex_status(self, force: bool = False) -> dict:
        now = time.time()
        if not force and now - self._codex_status_refreshed_at < 60:
            return dict(self._codex_status)
        try:
            self._codex_status = await asyncio.to_thread(read_codex_status, force)
        except Exception as exc:
            decky.logger.info("Codex agent status unavailable: %s", exc)
            self._codex_status = {
                "source": "codex",
                "authenticated": False,
                "error": str(exc),
                "accounts": [],
                "sessions": {"items": []},
                "tokens": {},
            }
        self._codex_status_refreshed_at = now
        return dict(self._codex_status)

    async def clear_agent_status(self) -> bool:
        await self.set_agent_status({"state": "idle"})
        return True

    def _set_active_module(self, module_id: Optional[int]) -> None:
        self._active_module_id = self._sanitize_module_id(module_id)
        if self._active_module_id is not None:
            self._timeline_idx = self._active_module_id
        # Selecting a display module starts its existing automatic refresh behavior.
        # Custom images remain manual-only and never enable the scheduler.
        current_mode = self.settings.get("mode", "")
        auto_target = current_mode not in ("custom", "agent") and (
            self._active_module_id != 6
            or current_mode in ("dashboard", "clock", "weather", "deck_status")
        )
        if auto_target and not self.settings.get("auto_refresh"):
            self.settings["auto_refresh"] = True
            _save_settings(self.settings, changed_keys={"auto_refresh"})
        if asyncio.current_task() in (
            self._refresh_task,
            self._background_refresh_task,
            self._cycle_task,
        ):
            return
        self._sync_refresh_loop(restart=True)

    @staticmethod
    def _sanitize_module_id(value: Optional[int]) -> Optional[int]:
        try:
            module_id = int(value)
        except (TypeError, ValueError):
            return None
        if module_id in (0, 1, 2, 3, 4, 5, 6, AGENT_MODULE_ID):
            return module_id
        return None

    def _clamp_stay_duration(self, seconds: int) -> int:
        return max(TIMELINE_MIN_SEC, min(TIMELINE_MAX_SEC, int(seconds)))

    def _get_stay_duration_sec(self) -> int:
        raw = self.settings.get("stay_duration", TIMELINE_DEFAULT_SEC)
        try:
            return self._clamp_stay_duration(int(raw))
        except (TypeError, ValueError):
            return TIMELINE_DEFAULT_SEC

    def _get_effective_root_mode(self) -> str:
        mode = self.settings.get("mode", "deck_status")
        if mode == "carousel":
            return DISPLAY_MODE_SEQUENCE[self._cycle_pos % len(DISPLAY_MODE_SEQUENCE)]
        if mode == "dashboard":
            return "dashboard"
        if mode == "custom":
            return "custom"
        if mode == "agent":
            return "agent"
        if mode in DISPLAY_MODE_SEQUENCE:
            return mode
        return "deck_status"

    def _get_cycle_module_ids(self) -> list[int]:
        raw = self.settings.get("module_cycle_ids") or [0, 1, 2, 3, 4, 5, 6]
        cycle_ids: list[int] = []
        for value in raw:
            module_id = self._sanitize_module_id(value)
            if (
                module_id is not None
                and module_id != AGENT_MODULE_ID
                and module_id not in cycle_ids
            ):
                cycle_ids.append(module_id)
        return cycle_ids or [0, 1, 2, 3, 4, 5, 6]

    def _get_single_module_id(self) -> Optional[int]:
        module_id = self._sanitize_module_id(self.settings.get("single_module_id"))
        if module_id is not None:
            return module_id
        return self._sanitize_module_id(self._active_module_id)

    def _get_effective_display_mode(self) -> str:
        return "multi" if self.settings.get("mode", "deck_status") == "carousel" else "single"

    def _sync_cycle_position_from_current(self) -> str:
        current_mode = self.settings.get("mode", "deck_status")
        effective = (
            current_mode
            if current_mode in DISPLAY_MODE_SEQUENCE
            else self._get_effective_root_mode()
        )
        if effective not in DISPLAY_MODE_SEQUENCE:
            effective = DISPLAY_MODE_SEQUENCE[0]
        self._cycle_pos = DISPLAY_MODE_SEQUENCE.index(effective)
        return effective

    def _advance_cycle_position(self) -> str:
        self._cycle_pos = (self._cycle_pos + 1) % len(DISPLAY_MODE_SEQUENCE)
        return DISPLAY_MODE_SEQUENCE[self._cycle_pos]

    def _get_active_display_target(self) -> Optional[tuple[str, Optional[int]]]:
        mode = self._get_effective_root_mode()
        if mode == "dashboard":
            return ("dashboard", None)
        if mode == "clock":
            return ("clock", None)
        if mode == "weather":
            return ("weather", None)
        if mode == "deck_status":
            return ("deck_status", None)
        if mode == "timeline":
            if self._get_effective_display_mode() == "single":
                module_id = self._get_single_module_id()
                if module_id is not None:
                    game_time_mode = (
                        str(self.settings.get("game_time_display_mode", "auto") or "auto")
                        .strip()
                        .lower()
                    )
                    if module_id == 1 and game_time_mode in ("poster", "auto"):
                        return ("game-time", module_id)
                    return ("module", module_id)
            return ("timeline", None)
        if mode == "custom":
            return ("custom", None)
        if mode == "agent":
            return ("module", AGENT_MODULE_ID)
        return None

    def _get_active_display_wait(self, target: tuple[str, Optional[int]]) -> int:
        kind, _module_id = target
        if kind == "game-time":
            return GAME_TIME_POSTER_REFRESH_SEC
        if kind == "timeline":
            return max(
                60,
                int(
                    self.settings.get("timeline_sec", TIMELINE_DEFAULT_SEC) or TIMELINE_DEFAULT_SEC
                ),
            )
        if kind == "custom":
            return CUSTOM_SLIDESHOW_INTERVAL_SEC
        if kind == "weather":
            return WEATHER_REFRESH_SEC
        return 60

    def _load_hardware_history(self) -> None:
        self._hardware_history = _new_hardware_history()
        self._hardware_sample_minutes = deque(maxlen=HARDWARE_HISTORY_MINUTES)
        try:
            payload = json.loads(_hardware_history_path().read_text(encoding="utf-8"))
            records = payload.get("samples", []) if isinstance(payload, dict) else []
        except Exception:
            records = []

        current_minute = int(time.time() // 60) * 60
        earliest_minute = current_minute - (HARDWARE_HISTORY_MINUTES - 1) * 60
        samples_by_minute = {}
        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                minute = int(record["minute"] // 60) * 60
                sample = {key: max(0, min(100, int(record[key]))) for key in ("cpu", "gpu", "ram")}
            except (KeyError, TypeError, ValueError):
                continue
            if earliest_minute <= minute <= current_minute:
                samples_by_minute[minute] = sample

        for minute in sorted(samples_by_minute)[-HARDWARE_HISTORY_MINUTES:]:
            self._hardware_sample_minutes.append(minute)
            for key in ("cpu", "gpu", "ram"):
                self._hardware_history[key].append(samples_by_minute[minute][key])

    def _save_hardware_history(self) -> None:
        history_path = _hardware_history_path()
        history_path.parent.mkdir(parents=True, exist_ok=True)
        samples = []
        for index, minute in enumerate(self._hardware_sample_minutes):
            samples.append(
                {
                    "minute": minute,
                    "cpu": self._hardware_history["cpu"][index],
                    "gpu": self._hardware_history["gpu"][index],
                    "ram": self._hardware_history["ram"][index],
                }
            )
        fd, temporary_path = tempfile.mkstemp(
            prefix=".performance-history-",
            suffix=".tmp",
            dir=history_path.parent,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
                json.dump({"version": 1, "samples": samples}, temporary_file, separators=(",", ":"))
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, history_path)
        finally:
            try:
                os.unlink(temporary_path)
            except FileNotFoundError:
                pass

    def _sample_hardware_once(self, sampled_at: Optional[float] = None) -> None:
        minute = int((time.time() if sampled_at is None else sampled_at) // 60) * 60
        values = {}
        for key, reader in (
            ("cpu", _read_cpu_percent),
            ("gpu", _read_gpu_percent),
            ("ram", _read_memory_percent),
        ):
            values[key] = max(0, min(100, int(reader())))

        earliest_minute = minute - (HARDWARE_HISTORY_MINUTES - 1) * 60
        while self._hardware_sample_minutes and self._hardware_sample_minutes[0] < earliest_minute:
            self._hardware_sample_minutes.popleft()
            for history in self._hardware_history.values():
                history.popleft()

        if self._hardware_sample_minutes and self._hardware_sample_minutes[-1] == minute:
            for key, value in values.items():
                self._hardware_history[key][-1] = value
        else:
            self._hardware_sample_minutes.append(minute)
            for key, value in values.items():
                self._hardware_history[key].append(value)
        try:
            self._save_hardware_history()
        except OSError as error:
            decky.logger.warning("Performance history save failed: %s", error)

    def _start_hardware_sampler(self) -> None:
        if not self._hardware_task or self._hardware_task.done():
            self._hardware_task = asyncio.get_running_loop().create_task(
                self._hardware_sample_loop()
            )

    def _stop_hardware_sampler(self) -> None:
        if self._hardware_task and not self._hardware_task.done():
            self._hardware_task.cancel()
        self._hardware_task = None

    async def _hardware_sample_loop(self) -> None:
        try:
            loop = asyncio.get_running_loop()
            next_sample_at = loop.time()
            while True:
                self._sample_hardware_once()
                next_sample_at += HARDWARE_SAMPLE_INTERVAL_SEC
                await asyncio.sleep(max(0.0, next_sample_at - loop.time()))
        except asyncio.CancelledError:
            pass

    def _hardware_snapshot(self) -> dict:
        snapshot = {}
        for key in ("cpu", "gpu", "ram"):
            history = list(self._hardware_history[key])
            current = history[-1] if history else 0
            snapshot[f"{key}_percent"] = current
            snapshot[f"{key}_history"] = history or [current]
        return snapshot

    async def _refresh_timeline_mode(self, *, advance_after_send: bool) -> bool:
        current_module = self._sanitize_module_id(self._timeline_idx)
        if current_module is None:
            current_module = 0
            self._timeline_idx = current_module
        ok = await self._dispatch_module(current_module, set_active=False)
        if ok and advance_after_send:
            self._timeline_idx = (current_module + 1) % 7
        return ok

    async def _refresh_active_display(self, target: tuple[str, Optional[int]]) -> bool:
        kind, _module_id = target
        if kind == "dashboard":
            return await self._send_dashboard_internal()
        if kind == "clock":
            return await self.send_clock()
        if kind == "weather":
            return await self.send_weather(
                self.settings.get("latitude", 0.0),
                self.settings.get("longitude", 0.0),
            )
        if kind == "deck_status":
            return await self.send_deck_status()
        if kind == "timeline":
            return await self._refresh_timeline_mode(advance_after_send=True)
        if kind in ("module", "game-time") and _module_id is not None:
            return await self._dispatch_module(_module_id, set_active=False)
        if kind == "custom":
            selected_path = (self.settings.get("custom_selected_path", "") or "").strip()
            if not selected_path:
                return False
            if self.settings.get("custom_slideshow_enabled"):
                return await self.send_next_custom_file()
            return await self._send_custom_file_internal(
                selected_path, Path(selected_path).name, set_active=False
            )
        return False

    async def _resolve_game_time_poster(self, snapshot: dict) -> Optional[str]:
        mode = str(self.settings.get("game_time_display_mode", "auto") or "auto")
        if mode == "time":
            return None
        app_id = str(snapshot.get("app_id") or "")
        if app_id:
            cache_path = _game_artwork_cache_dir() / f"{app_id}.png"
            if cache_path.is_file():
                try:
                    with Image.open(cache_path) as cached:
                        if cached.size == (396 - 24, 462 - 54):
                            return str(cache_path)
                except Exception:
                    pass
                try:
                    cache_path.unlink()
                except OSError:
                    pass
            if app_id not in self._game_artwork_attempted:
                self._game_artwork_attempted.add(app_id)
                for source in _steam_artwork_candidates(app_id, Path.home() / ".local/share/Steam"):
                    if await asyncio.to_thread(_process_game_artwork, str(source), str(cache_path)):
                        return str(cache_path)
                if await _download_game_artwork(app_id, cache_path):
                    return str(cache_path)
            return None
        return None

    async def _compose_game_time_render_data(self, seed: Optional[dict] = None) -> dict:
        payload, _signature = self._compose_game_progress_data(seed)
        snapshot = payload
        mode = str(self.settings.get("game_time_display_mode", "auto") or "auto")
        payload["game_time_display_mode"] = mode
        poster_path = await self._resolve_game_time_poster(snapshot)
        if snapshot.get("app_id") and poster_path:
            updates = {
                "game_time_last_app_id": snapshot["app_id"],
                "game_time_last_name": snapshot.get("game", NO_GAME_LABEL),
                "game_time_last_poster_path": poster_path,
                "game_time_last_session_min": int(snapshot.get("session_min", 0) or 0),
                "game_time_last_total_minutes": int(snapshot.get("total_minutes", 0) or 0),
            }
            changed = any(self.settings.get(key) != value for key, value in updates.items())
            self.settings.update(updates)
            if changed:
                _save_settings(self.settings, changed_keys=set(updates))
        # Do not carry a previous game's poster into a no-current-game render.
        if snapshot.get("app_id") and poster_path:
            payload["poster_path"] = poster_path
        else:
            payload.pop("poster_path", None)
        return payload

    def _compose_game_progress_data(self, seed: Optional[dict] = None) -> tuple[dict, tuple]:
        payload = dict(seed or {})
        snapshot = get_game_progress_snapshot(payload)
        payload.update(
            {
                "game": snapshot["game"],
                "app_id": snapshot["app_id"],
                "game_dir": snapshot["game_dir"],
                "today": snapshot["session_clock"],
                "total": snapshot["total_label"],
                "session_min": snapshot["session_min"],
                "session_clock": snapshot["session_clock"],
                "total_hours": snapshot["total_hours"],
                "total_minutes": snapshot["total_minutes"],
                "total_label": snapshot["total_label"],
                "ach": snapshot["ach"],
                "pct": snapshot["pct"],
                "controller_connected": snapshot["controller_connected"],
                "controller_name": snapshot["controller_name"],
                "controller_count": snapshot["controller_count"],
                "achievement_unlocked": snapshot.get("achievement_unlocked"),
                "achievement_total": snapshot.get("achievement_total"),
            }
        )
        signature = snapshot["refresh_signature"]
        return payload, signature

    def _compose_status_bar_data(self, seed: Optional[dict] = None) -> tuple[dict, tuple]:
        payload = with_context(seed, self.settings)
        payload.update(self._hardware_snapshot())
        snapshot = get_status_bar_snapshot(payload)
        payload.update(snapshot)
        return payload, snapshot["refresh_signature"]

    def _compose_performance_data(self, seed: Optional[dict] = None) -> tuple[dict, tuple]:
        payload = dict(seed or {})
        payload.update(self._hardware_snapshot())
        snapshot = get_performance_snapshot(payload)
        payload.update(snapshot)
        payload.update(
            {
                "cpu": _format_percent(snapshot["cpu_percent"]),
                "gpu": _format_percent(snapshot["gpu_percent"]),
                "ram": _format_percent(snapshot["ram_percent"]),
            }
        )
        return payload, snapshot["refresh_signature"]

    async def _resolve_ip_location(self, force: bool = False) -> dict:
        if self.settings.get("weather_location_mode") == "manual":
            selected = self.settings.get("weather_manual_location") or {}
            return {
                "lat": selected.get("latitude"),
                "lon": selected.get("longitude"),
                "city": selected.get("name", ""),
                "country": selected.get("country_code", ""),
                "timezone": selected.get("timezone", ""),
            }
        now_ts = time.time()
        if (
            not force
            and self._location_cache
            and now_ts - self._location_refreshed_at < IP_LOCATION_REFRESH_SEC
        ):
            return dict(self._location_cache)

        location = await fetch_ip_location()
        if self.settings.get("weather_location_mode") == "manual":
            return await self._resolve_ip_location(force=False)
        if not location:
            return dict(self._location_cache)

        self._location_cache = dict(location)
        self._location_refreshed_at = now_ts
        lat = float(location.get("lat", 0.0) or 0.0)
        lon = float(location.get("lon", 0.0) or 0.0)
        city = str(location.get("city", "") or "")
        changed_keys = set()
        if lat or lon:
            self.settings["latitude"] = lat
            self.settings["longitude"] = lon
            changed_keys.update({"latitude", "longitude"})
        if city:
            self.settings["city"] = city
            changed_keys.add("city")
        if location.get("timezone"):
            self.settings["weather_auto_timezone"] = location["timezone"]
            changed_keys.add("weather_auto_timezone")
        country = str(location.get("country") or location.get("country_code") or "").strip().upper()
        if country:
            self.settings["country"] = country
            changed_keys.add("country")
        if changed_keys:
            _save_settings(self.settings, changed_keys=changed_keys)
        return dict(self._location_cache)

    async def _calendar_country_for_render(self) -> str:
        now_ts = time.time()
        cached_location = dict(getattr(self, "_location_cache", {}) or {})
        cached_at = float(getattr(self, "_location_refreshed_at", 0.0) or 0.0)
        if cached_location and now_ts - cached_at < IP_LOCATION_REFRESH_SEC:
            location = cached_location
        else:
            location = await fetch_ip_location()
            if location:
                self._location_cache = dict(location)
                self._location_refreshed_at = now_ts
        return _resolve_calendar_country((location or {}).get("country", ""))

    async def _compose_weather_data(
        self, seed: Optional[dict] = None, force: bool = False
    ) -> tuple[dict, tuple]:
        if not hasattr(self, "_weather_refresh_lock"):
            self._weather_refresh_lock = asyncio.Lock()
        async with self._weather_refresh_lock:
            location = await self._resolve_ip_location(force=False)
            # Read the preferences after lookup: a user may select a city while an IP request runs.
            if self.settings.get("weather_location_mode") == "manual":
                selected = self.settings.get("weather_manual_location") or {}
                location = {
                    "lat": selected.get("latitude"),
                    "lon": selected.get("longitude"),
                    "city": selected.get("name", ""),
                    "timezone": selected.get("timezone", ""),
                }
            lat, lon = location.get("lat"), location.get("lon")
            if lat is None or lon is None:
                if self.settings.get("city"):
                    lat, lon = self.settings.get("latitude"), self.settings.get("longitude")
                else:
                    lat = lon = None
            city = str(location.get("city") or self.settings.get("city") or "")
            zone = location.get("timezone") or self.settings.get("weather_auto_timezone", "")
            point_key = [self.settings.get("weather_location_mode", "auto"), lat, lon]
            cached = dict(getattr(self, "_weather_cache", {}) or {})
            if cached.get("_location_key") != point_key:
                cached = {}
            now_ts = time.time()
            ready = bool(cached) and cached.get("_weather_available", False)
            age = now_ts - float(cached.get("_refreshed_at", 0) or 0)
            if force or not cached or age >= (WEATHER_REFRESH_SEC if ready else 60):
                generation = getattr(self, "_weather_preferences_revision", 0)
                raw = (
                    await fetch_weather(float(lat), float(lon))
                    if lat is not None and lon is not None
                    else None
                )
                if generation != getattr(self, "_weather_preferences_revision", 0):
                    # Never relabel an old in-flight request with the newly selected city's name.
                    raise ValueError(
                        "Weather location changed while fetching; retry with the selected city"
                    )
                if raw:
                    cached = {
                        **raw,
                        "_city": city,
                        "_weather_available": True,
                        "_weather_timezone": raw.get("timezone") or zone,
                        "_location_key": point_key,
                        "_refreshed_at": now_ts,
                    }
                elif not ready:
                    cached = {
                        "city": city,
                        "_weather_available": False,
                        "_weather_timezone": zone,
                        "_location_key": point_key,
                        "_refreshed_at": now_ts,
                    }
            payload = get_weather_snapshot(with_context(cached, self.settings))
            self._weather_cache = dict(
                cached
            )  # Cache unrounded Celsius source, never converted display values.
            return payload, payload["refresh_signature"]

    async def _compose_monohub_data(
        self, seed: Optional[dict] = None, force: bool = False
    ) -> tuple[dict, tuple]:
        weather_payload, _ = await self._compose_weather_data(
            self._module_data.get("P3", {}), force=force
        )
        self._module_data["P3"] = weather_payload
        await asyncio.to_thread(self._refresh_display_battery_from_bluez_cache)
        payload = with_context(seed, self.settings)
        payload.update(weather_payload)
        payload.update(
            {
                "battery_percent": self._display_battery_for_render(),
                "battery_charging": self._display_charging_for_render(),
            }
        )
        snapshot = get_monohub_snapshot(payload)
        payload.update(snapshot)
        return payload, snapshot["refresh_signature"]

    def _should_refresh_game_progress_dashboard(self) -> bool:
        payload, signature = self._compose_game_progress_data(self._module_data.get("P1", {}))
        self._module_data["P1"] = payload
        if not payload.get("controller_connected"):
            self._last_game_progress_signature = signature
            return False
        if payload.get("game") == NO_GAME_LABEL:
            self._last_game_progress_signature = signature
            return False
        if signature == self._last_game_progress_signature:
            return False
        self._last_game_progress_signature = signature
        return True

    def _should_refresh_performance_module(self) -> bool:
        payload, signature = self._compose_performance_data(self._module_data.get("P2", {}))
        self._module_data["P2"] = payload
        if signature == self._last_performance_signature:
            return False
        self._last_performance_signature = signature
        return True

    async def _should_refresh_weather_module(self) -> bool:
        payload, signature = await self._compose_weather_data(self._module_data.get("P3", {}))
        self._module_data["P3"] = payload
        if signature == self._last_weather_signature:
            return False
        self._last_weather_signature = signature
        return True

    async def _should_refresh_monohub_module(self) -> bool:
        payload, signature = await self._compose_monohub_data(self._module_data.get("P4", {}))
        self._module_data["P4"] = payload
        if signature == self._last_monohub_signature:
            return False
        self._last_monohub_signature = signature
        return True

    # ── BLE ───────────────────────────────────
    def _reset_device_state(self, clear_saved_address: bool = False) -> None:
        if clear_saved_address:
            self.settings["device_address"] = ""
            _save_settings(self.settings, changed_keys={"device_address"})
        self._set_connection_state(False)
        self._last_scan_results = []
        if self._last_error.startswith("Connect failed:") or self._last_error.startswith(
            "BLE send failed:"
        ):
            self._last_error = ""

    @staticmethod
    def _parse_int_field(line: str) -> Optional[int]:
        match = re.search(r"(-?\d+)", line)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    def _estimate_distance_m(
        self, rssi: Optional[int], tx_power: Optional[int] = None
    ) -> Optional[float]:
        if rssi is None:
            return None
        ref_power = tx_power if tx_power is not None else BLE_DEFAULT_TX_POWER_DBM
        try:
            distance = 10 ** ((ref_power - rssi) / (10 * BLE_PATH_LOSS_EXPONENT))
        except Exception:
            return None
        return round(max(distance, 0.05), 2)

    def _is_nearby_display(self, rssi: Optional[int], distance_m: Optional[float]) -> bool:
        if distance_m is not None:
            return distance_m <= BLE_NEARBY_DISTANCE_LIMIT_M
        if rssi is not None:
            return rssi >= BLE_NEARBY_RSSI_THRESHOLD
        return False

    def _matches_display_signature(
        self,
        name: Optional[str],
        local_name: Optional[str] = None,
        service_uuids: Optional[list] = None,
    ) -> tuple[bool, str]:
        display_name = (name or local_name or "").strip()
        normalized_name = " ".join(display_name.upper().replace("_", " ").split())
        accepted_names = ("JSAUX E-INK",)
        if any(token in normalized_name for token in accepted_names):
            return True, display_name
        return False, display_name

    def _make_scan_result(
        self,
        *,
        name: str,
        address: str,
        source: str,
        rssi: Optional[int] = None,
        tx_power: Optional[int] = None,
        connected: bool = False,
    ) -> dict:
        distance_m = self._estimate_distance_m(rssi, tx_power)
        return {
            "name": name,
            "address": address,
            "source": source,
            "rssi": rssi,
            "tx_power": tx_power,
            "approx_distance_m": distance_m,
            "nearby": connected or self._is_nearby_display(rssi, distance_m),
            "connected": connected,
            "seen_at": time.time(),
        }

    def _device_candidate_history(self) -> list:
        history = []
        seen = set()
        for item in self.settings.get("device_candidates", []):
            if not isinstance(item, dict):
                continue
            address = str(item.get("address") or "").strip().upper()
            if not address or address in seen:
                continue
            seen.add(address)
            history.append(
                {
                    "name": str(item.get("name") or "JSAUX E-INK"),
                    "address": address,
                    "source": "history",
                    "last_seen": float(item.get("last_seen") or 0.0),
                    "connected": False,
                    "nearby": False,
                }
            )
        for address in (
            self.settings.get("device_address"),
            self.settings.get("desktop_last_device_address"),
        ):
            normalized = str(address or "").strip().upper()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            history.append(
                {
                    "name": "JSAUX E-INK",
                    "address": normalized,
                    "source": "saved_history",
                    "last_seen": 0.0,
                    "connected": False,
                    "nearby": False,
                }
            )
        return sorted(history, key=lambda item: item.get("last_seen", 0.0), reverse=True)

    def _remember_device_candidate(
        self, address: str, name: str = "JSAUX E-INK", last_seen: Optional[float] = None
    ) -> None:
        normalized = str(address or "").strip().upper()
        if not normalized:
            return
        timestamp = float(last_seen if last_seen is not None else time.time())
        history = [
            item for item in self._device_candidate_history() if item.get("address") != normalized
        ]
        history.insert(
            0,
            {
                "address": normalized,
                "name": str(name or "JSAUX E-INK"),
                "last_seen": timestamp,
            },
        )
        self.settings["device_candidates"] = [
            {
                "address": item["address"],
                "name": str(item.get("name") or "JSAUX E-INK"),
                "last_seen": float(item.get("last_seen") or 0.0),
            }
            for item in history[:MAX_DEVICE_CANDIDATES]
        ]

    def _remember_verified_scan_results(self, results: list) -> None:
        known_addresses = {
            str(item.get("address") or "").strip().upper()
            for item in self._device_candidate_history()
        }
        changed = False
        for result in results:
            if not result.get("verified"):
                continue
            address = str(result.get("address") or "").strip().upper()
            result["new_candidate"] = bool(address and address not in known_addresses)
            self._remember_device_candidate(
                address,
                result.get("name", "JSAUX E-INK"),
                result.get("seen_at"),
            )
            changed = True
        if changed:
            _save_settings(self.settings, changed_keys={"device_candidates"})

    def _build_connection_candidates(
        self, discovered: list, *, include_history: bool = True
    ) -> list:
        history = self._device_candidate_history() if include_history else []
        known_addresses = {item.get("address") for item in history}
        current = self._sort_scan_results(discovered)
        connected = [item for item in current if item.get("connected")]
        live_new_broadcasts = [
            item
            for item in current
            if not item.get("connected")
            and item.get("source") == "bleak"
            and (
                item.get("new_candidate")
                or str(item.get("address") or "").strip().upper() not in known_addresses
            )
        ]
        ordered = [*connected, *live_new_broadcasts, *history]
        deduped = []
        seen = set()
        for item in ordered:
            address = str(item.get("address") or "").strip().upper()
            if not address or address in seen:
                continue
            seen.add(address)
            candidate = dict(item)
            candidate["address"] = address
            deduped.append(candidate)
        return deduped

    def _sort_scan_results(self, results: list) -> list:
        deduped = {}
        for result in results:
            address = result.get("address", "").strip()
            if not address:
                continue
            current = deduped.get(address)
            if current is None:
                deduped[address] = result
                continue

            current_rank = (
                0 if current.get("connected") else 1,
                0 if current.get("nearby") else 1,
                0 if current.get("source") == "bleak" else 1,
                0 if current.get("approx_distance_m") is not None else 1,
                (
                    current.get("approx_distance_m")
                    if current.get("approx_distance_m") is not None
                    else float("inf")
                ),
                -(current.get("rssi") if current.get("rssi") is not None else -999),
            )
            new_rank = (
                0 if result.get("connected") else 1,
                0 if result.get("nearby") else 1,
                0 if result.get("source") == "bleak" else 1,
                0 if result.get("approx_distance_m") is not None else 1,
                (
                    result.get("approx_distance_m")
                    if result.get("approx_distance_m") is not None
                    else float("inf")
                ),
                -(result.get("rssi") if result.get("rssi") is not None else -999),
            )
            if new_rank < current_rank:
                deduped[address] = result

        ordered = sorted(
            deduped.values(),
            key=lambda item: (
                0 if item.get("connected") else 1,
                0 if item.get("nearby") else 1,
                0 if item.get("source") == "bleak" else 1,
                0 if item.get("approx_distance_m") is not None else 1,
                (
                    item.get("approx_distance_m")
                    if item.get("approx_distance_m") is not None
                    else math.inf
                ),
                -(item.get("rssi") if item.get("rssi") is not None else -999),
                item.get("name", ""),
                item.get("address", ""),
            ),
        )
        return ordered

    def _scan_result_for_address(self, address: str) -> Optional[dict]:
        normalized = (address or "").strip().upper()
        if not normalized:
            return None
        for item in self._last_scan_results:
            if (item.get("address") or "").strip().upper() == normalized:
                return item
        return None

    def _parse_bluetoothctl_device_lines(self, output: str, source: str) -> list:
        results = []
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if not line.startswith("Device "):
                continue
            parts = line.split(maxsplit=2)
            if len(parts) < 3:
                continue
            results.append(
                {
                    "address": parts[1].strip(),
                    "name": parts[2].strip(),
                    "source": source,
                }
            )
        return results

    def _read_bluetoothctl_info(self, address: str) -> dict:
        try:
            output = subprocess.check_output(
                ["bluetoothctl", "info", address],
                text=True,
                timeout=8,
            )
        except Exception as exc:
            decky.logger.warning("bluetoothctl info failed for %s: %s", address, exc)
            return {}

        info = {"uuids": []}
        manufacturer_data = bytearray()
        reading_manufacturer_data = False
        for raw_line in output.splitlines():
            line = raw_line.strip()
            if line.startswith("ManufacturerData.Value:"):
                reading_manufacturer_data = True
                continue
            if reading_manufacturer_data:
                match = re.match(r"^((?:[0-9a-fA-F]{2}\s+)+)", line)
                if match:
                    manufacturer_data.extend(bytes.fromhex(match.group(1)))
                    continue
                reading_manufacturer_data = False
            if line.startswith("Name:"):
                info["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Alias:") and not info.get("name"):
                info["name"] = line.split(":", 1)[1].strip()
            elif line.startswith("Connected:"):
                info["connected"] = line.split(":", 1)[1].strip().lower() == "yes"
            elif line.startswith("RSSI:"):
                info["rssi"] = self._parse_int_field(line)
            elif line.startswith("TxPower:"):
                info["tx_power"] = self._parse_int_field(line)
            elif line.startswith("UUID:"):
                match = re.search(r"\(([0-9a-fA-F-]{36})\)", line)
                if match:
                    info["uuids"].append(match.group(1).lower())
        if manufacturer_data:
            info["manufacturer_data"] = bytes(manufacturer_data)
        return info

    def _run_bluetoothctl(self, *args: str, timeout: int = 20) -> tuple[bool, str]:
        command = ["bluetoothctl", *args]
        try:
            output = subprocess.check_output(
                command,
                text=True,
                timeout=timeout,
                stderr=subprocess.STDOUT,
            )
            return True, output
        except subprocess.CalledProcessError as exc:
            return False, exc.output or str(exc)
        except Exception as exc:
            return False, str(exc)

    def _bluez_device_known(self, address: str) -> bool:
        if not address:
            return False
        ok, output = self._run_bluetoothctl("info", address, timeout=5)
        return ok and "DeviceSet" not in output and "not available" not in output

    async def _recover_bluez_discovery(self) -> None:
        decky.logger.warning(
            "BlueZ scan already in progress; requesting discovery stop before retry"
        )
        await asyncio.to_thread(self._run_bluetoothctl, "scan", "off", timeout=8)
        await asyncio.sleep(1.0)

    def _try_system_connect(self, address: str) -> bool:
        ok, output = self._run_bluetoothctl("connect", address, timeout=25)
        cleaned = " ".join(line.strip() for line in output.splitlines() if line.strip())
        if cleaned:
            decky.logger.info("bluetoothctl connect %s -> %s", address, cleaned)
        if "Connection successful" in output:
            return True
        if not ok:
            return False
        return "Failed to connect" not in output

    async def _get_ble_client_target(self, address: str, name: str = "JSAUX E-INK"):
        normalized_address = str(address or "").strip().upper()
        cached_target = getattr(self, "_ble_device_targets", {}).get(normalized_address)
        # Only reuse a real BLEDevice from scan; ignore stale non-device cache entries.
        if isinstance(cached_target, BLEDevice):
            return cached_target
        try:
            manager = await get_global_bluez_manager()
        except Exception as exc:
            decky.logger.warning("BlueZ manager unavailable for %s: %s", address, exc)
            return address

        normalized = normalized_address.replace(":", "_")
        for path, interfaces in manager._properties.items():
            if not path.endswith(f"dev_{normalized}"):
                continue
            props = interfaces.get("org.bluez.Device1")
            if not props:
                continue
            rssi = props.get("RSSI")
            return BLEDevice(
                address,
                props.get("Alias") or props.get("Name") or name,
                {"path": path, "props": props},
                rssi if rssi is not None else -127,
            )

        return address

    async def _rediscover_ble_client_target(self, address: str):
        decky.logger.info("Rediscovering BLE display before foreground send: %s", address)
        try:
            target = await BleakScanner.find_device_by_address(
                address,
                timeout=BLE_SCAN_TIMEOUT_SEC,
            )
        except Exception as exc:
            decky.logger.warning("BLE display rediscovery failed for %s: %s", address, exc)
            return None
        if target is None:
            decky.logger.warning("BLE display rediscovery did not find %s", address)
            return None
        decky.logger.info("BLE display rediscovered for foreground send: %s", address)
        return target

    @staticmethod
    def _ble_failure_needs_rediscovery(error: Exception) -> bool:
        message = f"{type(error).__name__}: {error}".lower()
        return any(
            marker in message
            for marker in (
                "devicenotfound",
                "device was removed",
                "device with address",
                "unknownobject",
                "inprogress",
                "operation already in progress",
            )
        ) or ("device" in message and "not found" in message)

    async def _verify_candidate(self, address: str) -> DeviceInfo:
        target = await self._get_ble_client_target(address)
        try:
            async with BleakClient(target, timeout=15.0) as client:
                return await self._query_device_info(client, DISPLAY_AB)
        except Exception as exc:
            if not self._ble_failure_needs_rediscovery(exc):
                raise
            fresh_target = await self._rediscover_ble_client_target(address)
            if fresh_target is None:
                raise
            self._ble_device_targets[address.strip().upper()] = fresh_target
            async with BleakClient(fresh_target, timeout=15.0) as client:
                return await self._query_device_info(client, DISPLAY_AB)

    def _is_target_display_info(self, info: DeviceInfo) -> bool:
        return (
            info.width == TARGET_SCREEN_W
            and info.height == TARGET_SCREEN_H
            and info.color_mode == TARGET_COLOR_MODE
            and info.is_dual_screen == TARGET_IS_DUAL_SCREEN
        )

    def _describe_device_info(self, info: DeviceInfo) -> str:
        screen_type = "dual" if info.is_dual_screen else "single"
        return f"{info.width}x{info.height}, {screen_type}, battery={info.battery}%"

    async def _filter_target_scan_results(self, results: list) -> list:
        filtered = []
        for result in results:
            address = (result.get("address") or "").strip()
            if not address:
                continue
            try:
                info = await self._verify_candidate(address)
            except Exception as exc:
                decky.logger.warning("Skipping %s: unable to verify display info: %s", address, exc)
                continue

            if not self._is_target_display_info(info):
                decky.logger.info(
                    "Skipping %s: not a supported E-INK display (%s)",
                    address,
                    self._describe_device_info(info),
                )
                continue

            result = dict(result)
            result.update(
                {
                    "width": info.width,
                    "height": info.height,
                    "color_count": info.color_count,
                    "color_mode": info.color_mode,
                    "is_dual_screen": info.is_dual_screen,
                    "battery": info.battery or result.get("battery", 0),
                }
            )
            if address.upper() == str(self.settings.get("device_address") or "").upper():
                self._update_display_battery(result["battery"])
            filtered.append(result)

        return self._sort_scan_results(filtered)

    async def _verify_scan_results(self, results: list) -> list:
        verified = await self._filter_target_scan_results(results)
        if verified:
            for result in verified:
                result["verified"] = True
            self._remember_verified_scan_results(verified)
            return verified

        fallback = []
        for result in results:
            if not result.get("address"):
                continue
            candidate = dict(result)
            candidate["verified"] = False
            fallback.append(candidate)
        return self._sort_scan_results(fallback)

    def _scan_bluetoothctl_devices(self) -> list:
        try:
            connected_out = subprocess.check_output(
                ["bluetoothctl", "devices", "Connected"], text=True, timeout=8
            )
            devices_out = subprocess.check_output(["bluetoothctl", "devices"], text=True, timeout=8)
        except Exception as exc:
            decky.logger.warning("bluetoothctl devices failed: %s", exc)
            return []

        results = []
        candidates = self._parse_bluetoothctl_device_lines(
            connected_out, "bluetoothctl_connected"
        ) + self._parse_bluetoothctl_device_lines(devices_out, "bluetoothctl")
        for candidate in candidates:
            info = self._read_bluetoothctl_info(candidate["address"])
            advertised_info = _parse_device_info_payload(info.get("manufacturer_data", b""))
            if advertised_info is not None and not self._is_target_display_info(advertised_info):
                advertised_info = None
            matched, display_name = self._matches_display_signature(
                info.get("name") or candidate.get("name"),
                candidate.get("name"),
                info.get("uuids"),
            )
            if not matched and advertised_info is None:
                continue
            result = self._make_scan_result(
                name=display_name or "JSAUX E-INK",
                address=candidate["address"],
                source=candidate["source"],
                rssi=info.get("rssi"),
                tx_power=info.get("tx_power"),
                connected=bool(info.get("connected")),
            )
            if advertised_info is not None:
                result.update(
                    {
                        "width": advertised_info.width,
                        "height": advertised_info.height,
                        "color_count": advertised_info.color_count,
                        "color_mode": advertised_info.color_mode,
                        "is_dual_screen": advertised_info.is_dual_screen,
                        "battery": advertised_info.battery,
                    }
                )
                if (
                    candidate["address"].upper()
                    == str(self.settings.get("device_address") or "").upper()
                ):
                    self._update_display_battery(advertised_info.battery)
            results.append(result)
        return self._sort_scan_results(results)

    def _scan_bleak_devices(self, discoveries) -> list:
        if not hasattr(self, "_ble_device_targets"):
            self._ble_device_targets = {}
        results = []
        if isinstance(discoveries, dict):
            iterable = discoveries.values()
        else:
            iterable = [(device, None) for device in discoveries]

        for item in iterable:
            if isinstance(item, tuple) and len(item) == 2:
                device, adv = item
            else:
                device, adv = item, None
            adv_name = getattr(adv, "local_name", None)
            service_uuids = getattr(adv, "service_uuids", None)
            manufacturer_data = getattr(adv, "manufacturer_data", None) or {}
            advertised_info = None
            for raw in manufacturer_data.values():
                candidate_info = _parse_device_info_payload(raw)
                if candidate_info is not None and self._is_target_display_info(candidate_info):
                    advertised_info = candidate_info
                    break
            matched, display_name = self._matches_display_signature(
                getattr(device, "name", None),
                adv_name,
                service_uuids,
            )
            if not matched and advertised_info is None:
                continue
            rssi = getattr(adv, "rssi", None)
            if rssi is None:
                rssi = getattr(device, "rssi", None)
            tx_power = getattr(adv, "tx_power", None)
            result = self._make_scan_result(
                name=display_name or "JSAUX E-INK",
                address=device.address,
                source="bleak",
                rssi=rssi,
                tx_power=tx_power,
                connected=False,
            )
            self._ble_device_targets[device.address.strip().upper()] = device
            if advertised_info is not None:
                result.update(
                    {
                        "width": advertised_info.width,
                        "height": advertised_info.height,
                        "color_count": advertised_info.color_count,
                        "color_mode": advertised_info.color_mode,
                        "is_dual_screen": advertised_info.is_dual_screen,
                        "battery": advertised_info.battery,
                    }
                )
                if device.address.upper() == str(self.settings.get("device_address") or "").upper():
                    self._update_display_battery(advertised_info.battery)
            results.append(result)
        return self._sort_scan_results(results)

    async def scan(self) -> list:
        if self._reject_desktop_owned_ble("scan"):
            await self._emit_status()
            return []

        scan_started_at = time.monotonic()
        scan_priority_token = self._begin_foreground_scan_request()
        try:
            if self._ble_lock is None:
                self._ble_lock = asyncio.Lock()
            try:
                lease_timeout = min(
                    MANUAL_BLE_SCAN_LEASE_TIMEOUT_SEC,
                    _remaining_manual_scan_budget(scan_started_at),
                )
                if lease_timeout <= 0:
                    return await self._return_cached_scan_after_busy("lease budget exhausted")
                async with SharedBleAdapterLease(
                    timeout=lease_timeout,
                    debug_logger=lambda message: decky.logger.info(message),
                ):
                    try:
                        lock_timeout = min(
                            MANUAL_BLE_SCAN_LOCK_TIMEOUT_SEC,
                            _remaining_manual_scan_budget(scan_started_at),
                        )
                        if lock_timeout <= 0:
                            return await self._return_cached_scan_after_busy(
                                "lock budget exhausted"
                            )
                        await asyncio.wait_for(
                            self._ble_lock.acquire(),
                            timeout=lock_timeout,
                        )
                    except asyncio.TimeoutError:
                        return await self._return_cached_scan_after_busy("BLE lock wait timed out")

                    try:
                        scan_timeout = min(
                            MANUAL_BLE_SCAN_TIMEOUT_SEC,
                            _remaining_manual_scan_budget(scan_started_at),
                        )
                        if scan_timeout <= 0:
                            return await self._return_cached_scan_after_busy(
                                "scan budget exhausted"
                            )
                        decky.logger.info(
                            "Scanning BLE advertisements for up to %.1f seconds", scan_timeout
                        )
                        discoveries = await BleakScanner.discover(
                            timeout=scan_timeout,
                            return_adv=True,
                        )
                        results = self._sort_scan_results(self._scan_bleak_devices(discoveries))
                        for result in results:
                            result["verified"] = False
                        self._last_error = ""
                        self._last_scan_results = results
                        decky.logger.info(
                            "Found %d supported E-INK display advertisement(s), %d within %.1fm",
                            len(results),
                            sum(1 for item in results if item.get("nearby")),
                            BLE_NEARBY_DISTANCE_LIMIT_M,
                        )
                        await self._emit_status()
                        return results
                    except Exception as exc:
                        self._last_error = f"Scan failed: {exc}"
                        decky.logger.warning(self._last_error)
                        await self._emit_status()
                        return []
                    finally:
                        self._ble_lock.release()
            except TimeoutError:
                return await self._return_cached_scan_after_busy("shared BLE lease timed out")
        finally:
            self._finish_foreground_scan_request(scan_priority_token)

    async def _return_cached_scan_after_busy(self, detail: str) -> list:
        """Treat a transient shared-adapter collision as a recoverable scan result.

        Automatic refresh and a manual scan can overlap while BlueZ is busy. The
        UI should keep the connection page usable and let the user retry instead
        of displaying a modal error for that expected race.
        """
        decky.logger.warning("Bluetooth scan deferred: %s", detail)
        self._last_error = ""
        await self._emit_status()
        return list(self._last_scan_results or [])

    async def _emit_status(self) -> None:
        await decky.emit("status_update", self._build_status())

    async def _emit_display_state(
        self,
        state: str,
        *,
        progress: Optional[int] = None,
        attempt: Optional[int] = None,
        error: str = "",
        foreground_request: Optional[int] = None,
    ) -> None:
        """Publish a terminal/retry state separate from the numeric progress bar."""
        payload = {
            "state": str(state),
            "progress": None if progress is None else max(0, min(100, int(progress))),
            "attempt": attempt,
            "error": str(error or ""),
            "foreground": foreground_request is not None,
        }
        await decky.emit("display_state", payload)

    def _set_connection_state(
        self,
        connected: bool,
        error: str = "",
        device_info: Optional[DeviceInfo] = None,
        state: Optional[str] = None,
    ) -> None:
        self._device_connected = connected
        self._last_error = error
        if state in (CONNECTION_STATE_OFF, CONNECTION_STATE_CONNECTING, CONNECTION_STATE_ON):
            self._connection_state = state
        elif connected:
            self._connection_state = CONNECTION_STATE_ON
        else:
            self._connection_state = (
                CONNECTION_STATE_CONNECTING if self._connection_enabled() else CONNECTION_STATE_OFF
            )
        if connected:
            if device_info is not None:
                cached_battery = getattr(self, "_display_battery_percent", None)
                if device_info.battery == 0 and cached_battery not in (None, 0):
                    device_info.battery = cached_battery
                else:
                    self._update_display_battery(device_info.battery)
                self.device_info = device_info
        else:
            self.device_info = None

    def _update_display_battery(self, battery: Optional[int]) -> None:
        if battery is None:
            return
        current = max(0, min(100, int(battery)))
        now = time.time()
        previous = getattr(self, "_display_battery_sample", None)
        if previous is not None:
            previous_value, _ = previous
            if current > previous_value:
                self._display_charging_until = now + DISPLAY_CHARGING_HOLD_SEC
                decky.logger.info(
                    "Display charging inferred: %d%% -> %d%%", previous_value, current
                )
            elif current < previous_value:
                self._display_charging_until = 0.0
                decky.logger.info("Display charging cleared: %d%% -> %d%%", previous_value, current)
        previous_cached = getattr(self, "_display_battery_percent", None)
        self._display_battery_percent = current
        self._display_battery_sample = (current, now)
        if previous_cached != current and getattr(self, "settings", None):
            self.settings["display_battery_percent"] = current
            _save_settings(self.settings, changed_keys={"display_battery_percent"})

    def _display_battery_for_render(self) -> int:
        battery = getattr(self, "_display_battery_percent", None)
        if battery is None and self.device_info is not None:
            battery = self.device_info.battery
        return max(0, min(100, int(battery or 0)))

    def _display_charging_for_render(self) -> bool:
        return False

    def _pending_display_battery_state(self):
        battery_known = self._display_battery_percent if self._device_connected else None
        return (
            battery_known,
            self._display_charging_for_render() if battery_known is not None else False,
            time.time() if battery_known is not None else None,
        )

    def _refresh_display_battery_from_bluez_cache(self) -> None:
        address = str(self.settings.get("device_address") or "").strip()
        if not address:
            return
        info = self._read_bluetoothctl_info(address)
        advertised_info = _parse_device_info_payload(info.get("manufacturer_data", b""))
        if advertised_info is not None and self._is_target_display_info(advertised_info):
            self._update_display_battery(advertised_info.battery)

    def _ensure_rendering_ready(self) -> bool:
        try:
            _ensure_pillow()
            if self._last_error.startswith("Rendering unavailable:"):
                self._last_error = ""
            return True
        except RuntimeError as exc:
            self._last_error = f"Rendering unavailable: {exc}"
            decky.logger.error(self._last_error)
            return False

    def _render_bytes(self, mode: str, payload: dict) -> Optional[bytes]:
        payload = render_context(mode, payload, self.settings)
        if self._ensure_rendering_ready():
            try:
                return _render_bytes_locally(mode, payload)
            except Exception as exc:
                self._last_error = f"Local render failed: {exc}"
                decky.logger.error(self._last_error)
                return None

        helper = Path(__file__).with_name("render_subprocess.py")
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", suffix=".json", delete=False
            ) as handle:
                json.dump({"mode": mode, "payload": payload}, handle, ensure_ascii=False)
                input_path = handle.name
            python_bin = _get_render_helper_python()
            env = dict(os.environ)
            env["PYTHONNOUSERSITE"] = "1"
            result = subprocess.run(
                [python_bin, str(helper), input_path],
                capture_output=True,
                env=env,
                timeout=120,
                check=False,
            )
        except Exception as exc:
            self._last_error = f"Render helper failed: {exc}"
            decky.logger.error(self._last_error)
            return None
        finally:
            if "input_path" in locals():
                try:
                    os.unlink(input_path)
                except OSError:
                    pass

        if result.returncode != 0:
            stderr = (
                result.stderr.decode("utf-8", errors="ignore").strip()
                if isinstance(result.stderr, bytes)
                else result.stderr.strip()
            )
            self._last_error = f"Render helper failed: {stderr or result.returncode}"
            decky.logger.error(self._last_error)
            return None

        if self._last_error.startswith("Rendering unavailable:") or self._last_error.startswith(
            "Local render failed:"
        ):
            self._last_error = ""
        return result.stdout

    async def _query_device_info(self, client: BleakClient, display: int) -> DeviceInfo:
        response_event = asyncio.Event()
        response_data = {"value": b""}

        def notify_handler(sender, data: bytearray):
            response_data["value"] = bytes(data)
            response_event.set()

        await client.start_notify(NOTIFY_UUID, notify_handler)
        try:
            response_event.clear()
            query = build_query_info_command(display)
            await client.write_gatt_char(WRITE_UUID, query, response=True)
            await asyncio.wait_for(response_event.wait(), timeout=5.0)
            payload = response_data["value"]
        finally:
            try:
                await client.stop_notify(NOTIFY_UUID)
            except Exception:
                pass

        info = _parse_device_info_payload(payload)
        if info is None:
            raise RuntimeError(f"Unexpected device-info response: {payload.hex()}")
        return info

    @shared_ble_operation
    async def _connect_saved_address_fast(self, address: str) -> bool:
        if self._ble_lock is None:
            self._ble_lock = asyncio.Lock()
        if self._ble_lock.locked():
            return False
        async with self._ble_lock:
            info = await self._verify_candidate(address)
            known_result = self._scan_result_for_address(address)
            if info.battery == 0 and known_result and known_result.get("battery") not in (None, 0):
                info.battery = int(known_result["battery"])
            if not self._is_target_display_info(info):
                return False
            self.settings["device_address"] = address
            self.settings["connection_enabled"] = True
            self._remember_device_candidate(address, (known_result or {}).get("name", "JSAUX E-INK"))
            _save_settings(
                self.settings,
                changed_keys={"connection_enabled", "device_address", "device_candidates"},
            )
            self._set_connection_state(True, device_info=info)
            self._sync_refresh_loop(restart=True)
            await self._emit_status()
            return True

    def _would_replace_connected_device(self, address: str) -> bool:
        if not self._device_connected:
            return False
        current_address = str(self.settings.get("device_address", "") or "").strip().upper()
        requested_address = str(address or "").strip().upper()
        return not current_address or requested_address != current_address

    async def connect(self, address: str) -> bool:
        """Verify and save the closest reachable display."""
        address = str(address or "").strip().upper()
        if not address:
            self._last_error = "Connect failed: no device address supplied"
            await self._emit_status()
            return False
        return await self._connect_after_address_validation(address)

    @shared_ble_operation
    async def _connect_after_address_validation(self, address: str) -> bool:
        if not self._connection_enabled():
            self.settings["connection_enabled"] = True
            _save_settings(self.settings, changed_keys={"connection_enabled"})
        if not self._device_connected:
            self._set_connection_state(False, state=CONNECTION_STATE_CONNECTING)
            await self._emit_status()
        if self._reject_desktop_owned_ble("connect"):
            await self._emit_status()
            return False
        if self._ble_lock is None:
            self._ble_lock = asyncio.Lock()
        try:
            await asyncio.wait_for(
                self._ble_lock.acquire(),
                timeout=FOREGROUND_BLE_WAIT_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            self._last_error = (
                "Bluetooth busy: timed out waiting for the active operation to finish"
            )
            decky.logger.warning(self._last_error)
            await self._emit_status()
            return False

        try:
            return await self._connect_unlocked(address)
        finally:
            self._ble_lock.release()

    async def _connect_unlocked(self, address: str) -> bool:
        candidate = str(address or "").strip().upper()
        if not candidate:
            self._last_error = "Connect failed: no device address supplied"
            await self._emit_status()
            return False
        attempts = [candidate]

        failures = []
        for candidate in attempts:
            known_result = self._scan_result_for_address(candidate)
            try:
                info = await self._verify_candidate(candidate)
                if (
                    info.battery == 0
                    and known_result
                    and known_result.get("battery") not in (None, 0)
                ):
                    info.battery = int(known_result["battery"])
                if not self._is_target_display_info(info):
                    message = f"not a supported E-INK display ({self._describe_device_info(info)})"
                    decky.logger.warning("connect() rejected %s: %s", candidate, message)
                    failures.append(f"{candidate}: {message}")
                    continue
                previous_address = str(self.settings.get("device_address") or "").strip().upper()
                if previous_address and previous_address != candidate:
                    getattr(self, "_ble_device_targets", {}).pop(previous_address, None)
                    self.device_info = None
                self.settings["device_address"] = candidate
                self.settings["connection_enabled"] = True
                self._remember_device_candidate(candidate, (known_result or {}).get("name", "JSAUX E-INK"))
                _save_settings(
                    self.settings,
                    changed_keys={"connection_enabled", "device_address", "device_candidates"},
                )
                self._set_connection_state(True, device_info=info)
                self._sync_refresh_loop(restart=True)
                decky.logger.info("Device verified and address saved: %s", candidate)
                if candidate != address:
                    decky.logger.warning(
                        "Requested %s unavailable, connected to %s instead", address, candidate
                    )
                await self._emit_status()
                return True
            except Exception as exc:
                decky.logger.error("connect() verify failed for %s: %s", candidate, exc)
                getattr(self, "_ble_device_targets", {}).pop(candidate.strip().upper(), None)
                if await asyncio.to_thread(self._try_system_connect, candidate):
                    await asyncio.sleep(1.0)
                    try:
                        info = await self._verify_candidate(candidate)
                        if (
                            info.battery == 0
                            and known_result
                            and known_result.get("battery") not in (None, 0)
                        ):
                            info.battery = int(known_result["battery"])
                        if not self._is_target_display_info(info):
                            message = f"not a supported E-INK display ({
                                self._describe_device_info(info)})"
                            decky.logger.warning(
                                "connect() retry rejected %s: %s", candidate, message
                            )
                            failures.append(f"{candidate}: {message}")
                            continue
                        self.settings["device_address"] = candidate
                        self.settings["connection_enabled"] = True
                        self._remember_device_candidate(
                            candidate, (known_result or {}).get("name", "JSAUX E-INK")
                        )
                        _save_settings(
                            self.settings,
                            changed_keys={
                                "connection_enabled",
                                "device_address",
                                "device_candidates",
                            },
                        )
                        self._set_connection_state(True, device_info=info)
                        self._sync_refresh_loop(restart=True)
                        decky.logger.info("System BLE connect recovered device: %s", candidate)
                        if candidate != address:
                            decky.logger.warning(
                                "Requested %s unavailable, connected to %s instead",
                                address,
                                candidate,
                            )
                        await self._emit_status()
                        return True
                    except Exception as retry_exc:
                        decky.logger.error(
                            "connect() retry after bluetoothctl failed for %s: %s",
                            candidate,
                            retry_exc,
                        )
                        failures.append(f"{candidate}: {retry_exc}")
                        continue
                failures.append(f"{candidate}: {exc}")

        error_msg = "; ".join(failures) if failures else "no scan candidates available"
        self._set_connection_state(False, error=f"Connect failed: {error_msg}")
        await self._emit_status()
        return False

    async def desktop_disconnect(self) -> bool:
        return await self.set_connection_enabled(False)

    async def disconnect(self) -> bool:
        if self._reject_desktop_owned_ble("disconnect"):
            await self._emit_status()
            return False
        return await self.set_connection_enabled(False)

    async def set_connection_enabled(self, enabled: bool) -> bool:
        enabled = bool(enabled)
        address = str(self.settings.get("device_address") or "").strip()
        if enabled and self._device_connected:
            self._set_connection_state(True, device_info=self.device_info)
            await self._emit_status()
            return True
        self.settings["connection_enabled"] = enabled
        if address:
            self.settings["desktop_last_device_address"] = address
        _save_settings(
            self.settings,
            changed_keys={"connection_enabled", "desktop_last_device_address", "device_address"},
        )
        if not enabled:
            await self._cancel_foreground_display_task()
            await self._cancel_background_display_task()
            await self._cancel_connection_tasks()
            old_address = str(self.settings.get("device_address") or "").strip().upper()
            if old_address:
                getattr(self, "_ble_device_targets", {}).pop(old_address, None)
            self.device_info = None
            self._set_connection_state(False, state=CONNECTION_STATE_OFF)
            self._sync_refresh_loop(restart=True)
        elif not self._device_connected:
            self._set_connection_state(False, state=CONNECTION_STATE_CONNECTING)
            startup_task = self._startup_connect_task
            if not startup_task or startup_task.done():
                self._startup_connect_task = asyncio.get_running_loop().create_task(
                    self._run_startup_autoconnect()
                )
        self._sync_refresh_loop(restart=True)
        await self._emit_status()
        return True

    async def get_status(self) -> dict:
        return self._build_status()

    async def get_ui_surface_signals(self) -> dict:
        def process_running(name: str) -> bool:
            try:
                result = subprocess.run(
                    ["pgrep", "-x", name],
                    capture_output=True,
                    text=True,
                    timeout=3,
                )
                return result.returncode == 0
            except Exception:
                return False

        return {
            "sessionDesktop": os.environ.get("XDG_SESSION_DESKTOP", ""),
            "currentDesktop": os.environ.get("XDG_CURRENT_DESKTOP", ""),
            "desktopSession": os.environ.get("DESKTOP_SESSION", ""),
            "hasPlasmaShell": process_running("plasmashell"),
            "hasKWinWayland": process_running("kwin_wayland") or process_running("kwin_x11"),
            "hasGamescope": process_running("gamescope-wl") or process_running("gamescope"),
        }

    def _build_status(self) -> dict:
        addr = self.settings.get("device_address", "")
        info = self.device_info
        helper_available = Path(__file__).with_name("render_subprocess.py").exists()
        return {
            "connected": self._device_connected,
            "connection_enabled": self._connection_enabled(),
            "connection_state": self._connection_state,
            "configured": bool(addr),
            "address": addr,
            "battery": self._display_battery_for_render(),
            "width": info.width if info else 0,
            "height": info.height if info else 0,
            "color_count": info.color_count if info else 0,
            "last_error": self._last_error,
            "last_transfer": (
                dict(self._last_transfer) if isinstance(self._last_transfer, dict) else None
            ),
            "render_ready": helper_available or not bool(_PILLOW_IMPORT_ERROR),
            "agent_status": dict(self._agent_status or {}),
            "codex_status": dict(self._codex_status or {}),
            "agent_active": is_agent_active(self._agent_status, now=time.time()),
        }

    def _build_control_state(self) -> dict:
        module_modes = {
            0: "carousel",
            1: "timeline",
            2: "deck_status",
            3: "weather",
            4: "clock",
            5: "calendar",
            6: "custom",
            AGENT_MODULE_ID: "agent",
        }
        raw_mode = str(self.settings.get("mode", "deck_status") or "deck_status")
        active_module_id = self._get_single_module_id()
        if raw_mode == "dashboard":
            active_module_id = 0
        elif raw_mode in ("clock", "weather", "deck_status", "custom", "agent"):
            active_module_id = {
                "clock": 4,
                "weather": 3,
                "deck_status": 2,
                "custom": 6,
                "agent": AGENT_MODULE_ID,
            }[raw_mode]
        current_display_mode = module_modes.get(active_module_id, raw_mode)
        settings = {
            **{key: self.settings.get(key, default) for key, default in DISPLAY_DEFAULTS.items()},
            "display_preview": with_context({}, self.settings)["_display_context"],
            "weather_auto_city": self.settings.get("city", ""),
            "mode": raw_mode,
            "display_mode": self._get_effective_display_mode(),
            "single_module_id": active_module_id,
            "active_module_id": active_module_id,
            "current_display_mode": current_display_mode,
            "auto_refresh": bool(self.settings.get("auto_refresh", False)),
            "interval_minutes": self.settings.get("interval_minutes", 5),
            "timeline_sec": self.settings.get("timeline_sec", TIMELINE_DEFAULT_SEC),
            "stay_duration": self._get_stay_duration_sec(),
            "module_cycle_ids": list(self._get_cycle_module_ids()),
            "module_switch_interval_minutes": self.settings.get(
                "module_switch_interval_minutes", MODULE_SWITCH_INTERVAL_DEFAULT
            ),
            "module_switch_enabled": bool(self.settings.get("module_switch_enabled", False)),
            "game_time_display_mode": self.settings.get("game_time_display_mode", "auto"),
            "photo_frame_interval_minutes": self.settings.get(
                "photo_frame_interval_minutes", PHOTO_FRAME_INTERVAL_DEFAULT
            ),
            "photo_frame_interval_enabled": bool(
                self.settings.get("photo_frame_interval_enabled", False)
            ),
            "custom_selected_path": str(self.settings.get("custom_selected_path", "") or ""),
            "custom_slideshow_enabled": bool(self.settings.get("custom_slideshow_enabled", False)),
            "agent_status": dict(self._agent_status or {}),
            "codex_status": dict(self._codex_status or {}),
            "agent_active": is_agent_active(self._agent_status, now=time.time()),
        }
        return {"status": self._build_status(), "settings": settings}

    async def get_control_state(self) -> dict:
        """Return the daemon-owned connection and display state for every UI client."""
        self._reload_custom_library_settings()
        await self._refresh_codex_status()
        return self._build_control_state()

    # ── Module data (from SteamOS / Decky JSON) ────
    async def set_module_data(self, module: str, data: dict) -> bool:
        """Update data for one module and optionally refresh."""
        self._module_data[module] = data
        decky.logger.info("Module %s data updated", module)
        if self.settings.get("mode") == "dashboard" and self._display_target_enabled():
            return await self._send_dashboard_internal()
        return True

    async def get_module_data(self) -> dict:
        return self._module_data

    # ── Send actions ──────────────────────────
    def _preempt_automatic_refresh_for_foreground(
        self,
        request_id: int,
        *,
        request_label: str = "Display request",
        request_rediscovery: bool = True,
    ) -> None:
        latest_refresh = self._latest_background_refresh_request
        refresh_key = self._scheduled_refresh_inflight_key
        if refresh_key is None and latest_refresh is not None:
            refresh_key = latest_refresh[0]
        if refresh_key is None:
            refresh_key = self._pending_scheduled_refresh_key
        if refresh_key is not None:
            self._last_scheduled_refresh_key = refresh_key
        self._pending_scheduled_refresh_key = None
        self._latest_background_refresh_request = None

        task = self._background_refresh_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            if request_rediscovery and self._background_ble_active:
                self._foreground_ble_rediscovery_request = request_id
            if self._background_ble_active and request_label != "Scan request":
                # Do not cancel a live GATT transfer. Cancellation can leave
                # BlueZ in an ATT operation-in-progress state, which makes the
                # immediately following foreground request fail or disappear.
                decky.logger.info(
                    "%s %s waiting for automatic refresh key=%s to finish during_ble=True",
                    request_label,
                    request_id,
                    refresh_key,
                )
            else:
                decky.logger.info(
                    "%s %s preempting automatic refresh key=%s during_ble=%s",
                    request_label,
                    request_id,
                    refresh_key,
                    self._background_ble_active,
                )
                task.cancel()

        cycle_task = self._cycle_task
        if (
            cycle_task is not None
            and cycle_task is not asyncio.current_task()
            and not cycle_task.done()
        ):
            decky.logger.info("%s %s preempting automatic carousel", request_label, request_id)
            self._stop_cycle_loop()

        for attribute in ("_startup_connect_task", "_reconnect_task"):
            connection_task = getattr(self, attribute, None)
            if (
                connection_task is not None
                and connection_task is not asyncio.current_task()
                and not connection_task.done()
            ):
                if request_label == "Scan request":
                    decky.logger.info(
                        "%s %s cancelling %s before manual scan",
                        request_label,
                        request_id,
                        attribute,
                    )
                    connection_task.cancel()
                    setattr(self, attribute, None)
                else:
                    decky.logger.info(
                        "%s %s leaving %s active; foreground request will wait for the BLE lock",
                        request_label,
                        request_id,
                        attribute,
                    )

    def _begin_foreground_scan_request(self) -> str:
        self._latest_foreground_scan_request += 1
        request_id = self._latest_foreground_scan_request
        token = f"eink-scan:{request_id}"
        try:
            claim_foreground_ble_priority("eink-scan", request_id)
        except OSError as exc:
            decky.logger.warning("Unable to publish foreground BLE scan priority: %s", exc)
        self._preempt_automatic_refresh_for_foreground(
            request_id,
            request_label="Scan request",
            request_rediscovery=False,
        )
        return token

    def _finish_foreground_scan_request(self, token: str) -> None:
        try:
            clear_foreground_ble_priority(token)
        except OSError as exc:
            decky.logger.warning("Unable to clear foreground BLE scan priority: %s", exc)

    def _begin_foreground_display_request(self) -> Optional[int]:
        current = asyncio.current_task()
        if current in (self._background_refresh_task, self._cycle_task, self._refresh_task):
            return None
        previous = self._foreground_display_task
        self._latest_foreground_display_request += 1
        request_id = self._latest_foreground_display_request
        self._foreground_display_task = current
        try:
            claim_foreground_ble_priority("eink", request_id)
        except OSError as exc:
            decky.logger.warning("Unable to publish foreground BLE priority: %s", exc)
        self._preempt_automatic_refresh_for_foreground(request_id)
        if previous is not None and previous is not current and not previous.done():
            decky.logger.info(
                "Display request %s cancelling stale foreground request",
                request_id,
            )
            previous.cancel()
        return request_id

    def _finish_foreground_display_request(self, request_id: Optional[int]) -> None:
        if request_id is None:
            return
        try:
            clear_foreground_ble_priority(f"eink:{request_id}")
        except OSError as exc:
            decky.logger.warning("Unable to clear foreground BLE priority: %s", exc)
        if (
            request_id == self._latest_foreground_display_request
            and self._foreground_display_task is asyncio.current_task()
        ):
            self._foreground_display_task = None

    async def _run_foreground_display_request(self, operation) -> bool:
        request_id = self._begin_foreground_display_request()
        await self._wait_for_preempted_background_task()
        try:
            return bool(await operation(request_id))
        except asyncio.CancelledError:
            if request_id is not None and request_id != self._latest_foreground_display_request:
                decky.logger.info("Discarded cancelled foreground display request %s", request_id)
                return False
            raise
        finally:
            self._finish_foreground_display_request(request_id)

    async def send_dashboard(self) -> bool:
        async def operation(foreground_request: Optional[int]) -> bool:
            if not self._display_target_enabled():
                return False
            self.settings["mode"] = "dashboard"
            self.settings["display_mode"] = "single"
            _save_settings(self.settings, changed_keys={"mode", "display_mode"})
            self._set_active_module(None)
            return await self._send_dashboard_internal(foreground_request=foreground_request)

        return await self._run_foreground_display_request(operation)

    async def _send_dashboard_internal(self, *, foreground_request: Optional[int] = None) -> bool:
        status = get_deck_status()
        p0 = self._module_data.setdefault("P0", {})
        p0.setdefault("bat", f"{status.get('battery_percent', '--')}%")
        p0.setdefault("bt", status.get("wifi_ssid", "SteamDeck"))
        p0.setdefault("fw", FW_VERSION)
        p1_data, signature = self._compose_game_progress_data(self._module_data.get("P1", {}))
        self._module_data["P1"] = p1_data
        self._last_game_progress_signature = signature
        p2_data, performance_signature = self._compose_performance_data(
            self._module_data.get("P2", {})
        )
        self._module_data["P2"] = p2_data
        self._last_performance_signature = performance_signature
        p3_data, weather_signature = await self._compose_weather_data(
            self._module_data.get("P3", {})
        )
        self._module_data["P3"] = p3_data
        self._last_weather_signature = weather_signature
        p0.update(
            {
                "weather_icon": p3_data.get("icon", "sun"),
                "weather_desc": p3_data.get("desc", ""),
                "weather_city": p3_data.get("city", ""),
            }
        )
        p0_data, status_signature = self._compose_status_bar_data(p0)
        self._module_data["P0"] = p0_data
        self._last_status_bar_signature = status_signature
        p4_data, monohub_signature = await self._compose_monohub_data(
            self._module_data.get("P4", {})
        )
        self._module_data["P4"] = p4_data
        self._last_monohub_signature = monohub_signature
        p0_render_data = _with_display_battery_snapshot(
            p0_data,
            *self._pending_display_battery_state(),
        )
        render_payload = {"P0": p0_render_data}
        data_bytes = self._render_bytes("dashboard", render_payload)
        if data_bytes is None:
            await self._emit_status()
            return False
        return await self._send_prepared_bytes(
            data_bytes,
            foreground_request=foreground_request,
            render_mode="dashboard",
            render_payload=render_payload,
        )

    async def _dispatch_module(
        self,
        module_id: int,
        *,
        set_active: bool = True,
        foreground_request: Optional[int] = None,
    ) -> bool:
        if not self._display_target_enabled():
            return False
        module_id = self._sanitize_module_id(module_id)
        if module_id is None:
            return False
        key = f"P{module_id}"
        data = dict(self._module_data.get(key, {}))
        if module_id == 0:
            data, signature = self._compose_status_bar_data(data)
            self._module_data[key] = data
            self._last_status_bar_signature = signature
        if module_id == 1:
            data = await self._compose_game_time_render_data(data)
            self._module_data[key] = data
            self._last_game_progress_signature = get_game_progress_snapshot(data)[
                "refresh_signature"
            ]
        if module_id == 2:
            data, signature = self._compose_performance_data(data)
            self._module_data[key] = data
            self._last_performance_signature = signature
        if module_id == 3:
            data, signature = await self._compose_weather_data(data)
            self._module_data[key] = data
            self._last_weather_signature = signature
        if module_id == 4:
            data, signature = await self._compose_monohub_data(data)
            self._module_data[key] = data
            self._last_monohub_signature = signature
        if module_id == 5:
            data["calendar_country"] = await self._calendar_country_for_render()
        if module_id == AGENT_MODULE_ID:
            try:
                await self._resolve_ip_location(force=False)
            except Exception as exc:
                decky.logger.info("Agent country lookup unavailable: %s", exc)
            data = self._agent_display_payload()
            self._module_data[key] = dict(data)
        if module_id == 6:
            selected_path = (self.settings.get("custom_selected_path", "") or "").strip()
            if selected_path:
                if not Path(selected_path).exists():
                    self._last_error = f"Custom image not found: {selected_path}"
                    await self._emit_status()
                    return False
                data["file_path"] = selected_path
                data.setdefault("title", Path(selected_path).name)
                self._module_data[key] = data
            elif not (data.get("file_path") or data.get("image") or data.get("body")):
                self._last_error = "No custom image selected"
                await self._emit_status()
                return False
        # P0 Status Bar: 自动填充系统状态
        if module_id == 0:
            status = get_deck_status()
            data.setdefault("bat", f"{status.get('battery_percent', '--')}%")
            data.setdefault("bt", status.get("wifi_ssid", "SteamDeck"))
            data.setdefault("fw", FW_VERSION)
        data = _with_display_battery_snapshot(
            data,
            *self._pending_display_battery_state(),
        )
        render_payload = {"module_id": module_id, "data": data}
        data_bytes = self._render_bytes("module", render_payload)
        if data_bytes is None:
            await self._emit_status()
            return False
        ok = await self._send_prepared_bytes(
            data_bytes,
            foreground_request=foreground_request,
            render_mode="module",
            render_payload=render_payload,
        )
        if ok:
            self._timeline_idx = module_id
            if set_active:
                self.settings["mode"] = "agent" if module_id == AGENT_MODULE_ID else "timeline"
                self.settings["display_mode"] = "single"
                self.settings["single_module_id"] = module_id
                _save_settings(
                    self.settings,
                    changed_keys={"mode", "display_mode", "single_module_id"},
                )
                self._set_active_module(module_id)
            await decky.emit("timeline_idx", module_id)
        return ok

    async def send_module(self, module_id: int) -> bool:
        return await self._run_foreground_display_request(
            lambda foreground_request: self._dispatch_module(
                module_id,
                set_active=True,
                foreground_request=foreground_request,
            )
        )

    async def send_clock(self) -> bool:
        async def operation(foreground_request: Optional[int]) -> bool:
            if not self._display_target_enabled():
                return False
            self.settings["mode"] = "clock"
            self.settings["display_mode"] = "single"
            _save_settings(self.settings, changed_keys={"mode", "display_mode"})
            self._set_active_module(None)
            data, signature = await self._compose_monohub_data(
                self._module_data.get("P4", {}), force=True
            )
            self._module_data["P4"] = data
            self._last_monohub_signature = signature
            render_data = _with_display_battery_snapshot(
                data,
                *self._pending_display_battery_state(),
            )
            render_payload = {"data": render_data}
            data_bytes = self._render_bytes("clock", render_payload)
            if data_bytes is None:
                await self._emit_status()
                return False
            return await self._send_prepared_bytes(
                data_bytes,
                foreground_request=foreground_request,
                render_mode="clock",
                render_payload=render_payload,
            )

        return await self._run_foreground_display_request(operation)

    async def send_weather(self, lat: float, lon: float) -> bool:
        async def operation(foreground_request: Optional[int]) -> bool:
            if not self._display_target_enabled():
                return False
            self.settings["mode"] = "weather"
            self.settings["display_mode"] = "single"
            _save_settings(self.settings, changed_keys={"mode", "display_mode"})
            self._set_active_module(None)
            if lat:
                self.settings["latitude"] = lat
            if lon:
                self.settings["longitude"] = lon
            if lat or lon:
                _save_settings(self.settings, changed_keys={"latitude", "longitude"})
            data, signature = await self._compose_weather_data(
                self._module_data.get("P3", {}), force=True
            )
            self._module_data["P3"] = data
            self._last_weather_signature = signature
            render_data = _with_display_battery_snapshot(
                data,
                *self._pending_display_battery_state(),
            )
            render_payload = {"data": render_data}
            data_bytes = self._render_bytes("weather", render_payload)
            if data_bytes is None:
                await self._emit_status()
                return False
            return await self._send_prepared_bytes(
                data_bytes,
                foreground_request=foreground_request,
                render_mode="weather",
                render_payload=render_payload,
            )

        return await self._run_foreground_display_request(operation)

    async def get_ip_location(self) -> dict:
        """前端调用：获取当前 IP 定位"""
        return await self._resolve_ip_location(force=False)

    async def send_deck_status(self) -> bool:
        async def operation(foreground_request: Optional[int]) -> bool:
            if not self._display_target_enabled():
                return False
            self.settings["mode"] = "deck_status"
            self.settings["display_mode"] = "single"
            _save_settings(self.settings, changed_keys={"mode", "display_mode"})
            self._set_active_module(None)
            data_bytes = self._render_bytes("deck_status", {"data": get_deck_status()})
            if data_bytes is None:
                await self._emit_status()
                return False
            return await self._send_prepared_bytes(
                data_bytes, foreground_request=foreground_request
            )

        return await self._run_foreground_display_request(operation)

    async def send_image(self, path: str) -> bool:
        async def operation(foreground_request: Optional[int]) -> bool:
            if not self._display_target_enabled():
                return False
            self.settings["display_mode"] = "single"
            _save_settings(self.settings, changed_keys={"display_mode"})
            self._set_active_module(None)
            data_bytes = self._render_bytes("image_path", {"path": path})
            if data_bytes is None:
                await self._emit_status()
                return False
            return await self._send_prepared_bytes(
                data_bytes, foreground_request=foreground_request
            )

        return await self._run_foreground_display_request(operation)

    @shared_ble_operation
    async def _send_prepared_bytes(
        self,
        data_bytes: bytes,
        *,
        foreground_request: Optional[int] = None,
        render_mode: Optional[str] = None,
        render_payload: Optional[dict] = None,
    ) -> bool:
        """Send pre-rendered bytes via BLE. Uses lock to prevent concurrent operations."""
        if self._reject_desktop_owned_ble("display update"):
            await self._emit_status()
            return False
        if self._ble_lock is None:
            self._ble_lock = asyncio.Lock()
        if (
            foreground_request is not None
            and foreground_request != self._latest_foreground_display_request
        ):
            decky.logger.info("Discarded stale display request %s", foreground_request)
            return False
        if self._ble_lock.locked():
            if foreground_request is None:
                decky.logger.warning("Background BLE operation already in progress, skipping")
                return False
            decky.logger.info(
                "Display request %s waiting for the active BLE frame",
                foreground_request,
            )
            try:
                await asyncio.wait_for(
                    self._ble_lock.acquire(),
                    timeout=FOREGROUND_BLE_WAIT_TIMEOUT_SEC,
                )
            except asyncio.TimeoutError:
                if foreground_request == self._latest_foreground_display_request:
                    self._last_error = (
                        "Bluetooth busy: timed out waiting for the active frame to finish"
                    )
                    await self._emit_display_state(
                        "failed",
                        progress=0,
                        error=self._last_error,
                        foreground_request=foreground_request,
                    )
                    await decky.emit("progress", 0)
                    await self._emit_status()
                return False
            else:
                self._ble_lock.release()
            if foreground_request != self._latest_foreground_display_request:
                decky.logger.info("Discarded stale display request %s", foreground_request)
                return False
        addr = self.settings.get("device_address", "")
        if not self._connection_enabled() or not addr:
            decky.logger.error("Display connection is OFF or no device address is configured")
            return False

        data_length = len(data_bytes)
        decky.logger.info("Preparing %d bytes for %s", data_length, addr)
        ok = False
        attempt_count = 3 if foreground_request is not None else 2
        async with self._ble_lock:
            if (
                foreground_request is not None
                and foreground_request != self._latest_foreground_display_request
            ):
                decky.logger.info("Discarded stale display request %s", foreground_request)
                return False
            if self._reject_desktop_owned_ble("display update"):
                return False
            await self._emit_display_state(
                "starting",
                progress=5,
                foreground_request=foreground_request,
            )
            await decky.emit("progress", 5)
            recovered_target = None
            if (
                foreground_request is not None
                and foreground_request == self._foreground_ble_rediscovery_request
            ):
                self._foreground_ble_rediscovery_request = None
                await asyncio.sleep(1.0)
                recovered_target = await self._rediscover_ble_client_target(addr)
            for attempt in range(attempt_count):
                transfer_complete = False
                client = None
                try:
                    target = recovered_target or await self._get_ble_client_target(addr)
                    recovered_target = None
                    client = BleakClient(target, timeout=15.0)
                    await client.connect()
                    try:
                        info = await self._query_device_info(client, DISPLAY_A)
                        if info.packet_size <= 0:
                            raise RuntimeError("Device reported an invalid display payload size")
                        packet_size = info.packet_size
                        total_packets = (data_length + packet_size - 1) // packet_size
                        self._set_connection_state(True, device_info=info)
                        # Full-screen layouts are rendered before opening the BLE session.
                        # Reuse the device-info response already obtained for this transfer to
                        # redraw only the pending battery snapshot; no extra BLE read or timer
                        # is introduced and the module's existing refresh schedule is unchanged.
                        if render_mode in DISPLAY_BATTERY_RENDER_MODES and isinstance(
                            render_payload, dict
                        ):
                            payload_key = "P0" if render_mode == "dashboard" else "data"
                            render_data = render_payload.get(payload_key)
                            if isinstance(render_data, dict):
                                sample = getattr(self, "_display_battery_sample", None)
                                updated_at = sample[1] if sample is not None else time.time()
                                render_payload[payload_key] = _with_display_battery_snapshot(
                                    render_data,
                                    info.battery,
                                    self._display_charging_for_render(),
                                    updated_at,
                                )
                                refreshed_bytes = self._render_bytes(render_mode, render_payload)
                                if refreshed_bytes is not None:
                                    data_bytes = refreshed_bytes
                                    data_length = len(data_bytes)
                                    total_packets = (data_length + packet_size - 1) // packet_size
                                    decky.logger.info(
                                        "Refreshed %s frame with device battery=%d%% before send",
                                        render_mode,
                                        info.battery,
                                    )
                        # The device reports its battery only after the BLE link is established.
                        # Refresh the clock frame at this point so this 60-second update carries
                        # the newly detected battery value instead of the previous cache.
                        if render_mode == "clock" and isinstance(render_payload, dict):
                            render_data = render_payload.get("data")
                            if isinstance(render_data, dict):
                                render_data["battery_percent"] = self._display_battery_for_render()
                                render_data["battery_charging"] = (
                                    self._display_charging_for_render()
                                )
                                refreshed_bytes = self._render_bytes(render_mode, render_payload)
                                if refreshed_bytes is not None:
                                    data_bytes = refreshed_bytes
                                    data_length = len(data_bytes)
                                    decky.logger.info(
                                        "Refreshed clock frame with device battery=%d%% before send",
                                        render_data["battery_percent"],
                                    )
                        decky.logger.info(
                            "Device info: %sx%s %s-color, payload=%d, %d packets",
                            info.width,
                            info.height,
                            info.color_count,
                            packet_size,
                            total_packets,
                        )

                        await self._emit_display_state(
                            "sending",
                            progress=10,
                            foreground_request=foreground_request,
                        )
                        await decky.emit("progress", 10)

                        is_background_refresh = (
                            asyncio.current_task() is self._background_refresh_task
                        )
                        ack_event = asyncio.Event()
                        ack_status = {"value": None}
                        data_ack_notifications = None

                        def notify_handler(sender, data: bytearray):
                            status = data_ack_status(data)
                            if status is not DataAckStatus.MISSING:
                                ack_status["value"] = status
                                ack_event.set()

                        await client.start_notify(NOTIFY_UUID, notify_handler)
                        if is_background_refresh:
                            self._background_ble_active = True
                        try:
                            for i in range(total_packets):
                                if self._desktop_owner_active():
                                    raise RuntimeError(
                                        "Desktop controller took BLE ownership during display update"
                                    )
                                start = i * packet_size
                                end = min(start + packet_size, data_length)
                                chunk = data_bytes[start:end]

                                packet = build_display_data_packet(i, chunk, packet_size)
                                if data_ack_notifications is False:
                                    await client.write_gatt_char(WRITE_UUID, packet, response=True)
                                else:
                                    ack_status["value"] = None
                                    ack_event.clear()
                                    await client.write_gatt_char(WRITE_UUID, packet, response=True)
                                    try:
                                        await asyncio.wait_for(
                                            ack_event.wait(),
                                            timeout=0.5 if data_ack_notifications is None else 5.0,
                                        )
                                    except asyncio.TimeoutError:
                                        notification_mode_was_active = (
                                            data_ack_notifications is True
                                        )
                                        data_ack_notifications = False
                                        if notification_mode_was_active:
                                            decky.logger.info(
                                                "Display data ACK notification stopped; using GATT Write responses"
                                            )
                                        else:
                                            decky.logger.info(
                                                "Display does not notify data ACKs; using GATT Write responses"
                                            )
                                    else:
                                        if ack_status["value"] is DataAckStatus.REJECTED:
                                            raise RuntimeError(
                                                f"Display packet {i + 1} was rejected"
                                            )
                                        if ack_status["value"] is DataAckStatus.INVALID:
                                            raise RuntimeError(
                                                f"Display packet {
                                                    i + 1} acknowledgement frame was invalid"
                                            )
                                        if ack_status["value"] is not DataAckStatus.SUCCESS:
                                            raise RuntimeError(
                                                f"Display packet {
                                                    i + 1} acknowledgement was missing"
                                            )
                                        data_ack_notifications = True

                                if (i + 1) % 36 == 0 or i == total_packets - 1:
                                    pct = 10 + int(88 * (i + 1) / total_packets)
                                    await decky.emit("progress", pct)
                        finally:
                            if is_background_refresh:
                                self._background_ble_active = False
                            try:
                                await client.stop_notify(NOTIFY_UUID)
                            except Exception:
                                pass

                        decky.logger.info("Image sent (%d packets)", total_packets)
                        transfer_complete = True
                        if not self._connection_enabled():
                            decky.logger.info(
                                "Discarding completed frame because BLE was turned OFF during transfer"
                            )
                            self._device_connected = False
                            self._set_connection_state(False, state=CONNECTION_STATE_OFF)
                            ok = False
                            break
                        self._last_transfer = {
                            "transport_confirmed": True,
                            "display_apply_confirmed": None,
                            "completed_at": time.time(),
                        }
                        decky.logger.info(
                            "BLE transport complete; panel apply confirmation unavailable"
                        )
                        self._device_connected = True
                        if self._last_error.startswith(
                            "Connect failed:"
                        ) or self._last_error.startswith("BLE send failed:"):
                            self._last_error = ""
                        ok = True
                        break
                    finally:
                        if client is not None:
                            try:
                                if client.is_connected:
                                    await client.disconnect()
                            except Exception as disconnect_exc:
                                if transfer_complete:
                                    decky.logger.warning(
                                        "BLE disconnect after successful send: %s", disconnect_exc
                                    )
                                else:
                                    decky.logger.warning(
                                        "BLE disconnect cleanup failed: %s", disconnect_exc
                                    )
                            # BlueZ can report the old GATT operation as still
                            # active for a short interval after disconnect().
                            # Let that state drain before the next retry.
                            await asyncio.sleep(BLE_DISCONNECT_SETTLE_SEC)
                except Exception as e:
                    if transfer_complete:
                        decky.logger.warning("BLE post-send cleanup issue ignored: %s", e)
                        self._device_connected = True
                        if self._last_error.startswith("BLE send failed:"):
                            self._last_error = ""
                        ok = True
                        break
                    decky.logger.error(
                        "BLE send failed (attempt %d): %s: %r",
                        attempt + 1,
                        type(e).__name__,
                        e,
                    )
                    self._set_connection_state(False, error=f"BLE send failed: {e}")
                    # Stop automatic module/photo refreshes immediately while
                    # the bounded reconnect loop owns recovery. Otherwise a
                    # scheduler tick can start another 5% operation on top of
                    # the same missing peripheral.
                    self._sync_refresh_loop(restart=True)
                    await self._emit_status()
                    if foreground_request is None:
                        self._ensure_reconnect_task()
                    if self._desktop_owner_active():
                        break
                    if attempt + 1 < attempt_count:
                        await self._emit_display_state(
                            "retrying",
                            progress=0,
                            attempt=attempt + 2,
                            error=str(e),
                            foreground_request=foreground_request,
                        )
                        await decky.emit("progress", 0)
                        if self._ble_failure_needs_rediscovery(e):
                            await asyncio.sleep(1.0)
                            recovered_target = await self._rediscover_ble_client_target(addr)
                        if recovered_target is None:
                            # Wait for BlueZ to release before retry
                            await asyncio.sleep(5.0)

        if ok:
            await decky.emit("progress", 100)
            await self._emit_display_state(
                "complete",
                progress=100,
                foreground_request=foreground_request,
            )
        elif foreground_request is not None:
            self._ensure_reconnect_task()
        if not ok:
            await decky.emit("progress", 0)
            await self._emit_display_state(
                "failed",
                progress=0,
                error=self._last_error,
                foreground_request=foreground_request,
            )
        decky.logger.info("Send complete, ok=%s", ok)
        await self._emit_status()
        return ok

    # ── Mode & Settings ───────────────────────
    async def set_mode(self, mode: str, interval: int) -> bool:
        previous_effective_mode = self._get_effective_root_mode()
        self.settings["mode"] = (
            mode
            if mode in (*DISPLAY_MODE_SEQUENCE, "carousel", "custom", "dashboard", "module")
            else "deck_status"
        )
        self.settings["interval_minutes"] = interval
        self.settings["display_mode"] = "multi" if self.settings["mode"] == "carousel" else "single"
        self._active_module_id = None
        if self.settings["mode"] == "carousel":
            effective = (
                previous_effective_mode
                if previous_effective_mode in DISPLAY_MODE_SEQUENCE
                else DISPLAY_MODE_SEQUENCE[0]
            )
            self._cycle_pos = DISPLAY_MODE_SEQUENCE.index(effective)
        else:
            self._sync_cycle_position_from_current()
        _save_settings(
            self.settings,
            changed_keys={"mode", "interval_minutes", "display_mode"},
        )
        self._sync_refresh_loop(restart=True)
        return True

    async def set_auto_refresh(self, enabled: bool) -> bool:
        self.settings["auto_refresh"] = enabled
        _save_settings(self.settings, changed_keys={"auto_refresh"})
        self._sync_refresh_loop(restart=True)
        return True

    async def set_timeline_sec(self, seconds: int) -> bool:
        clamped = self._clamp_stay_duration(int(seconds))
        self.settings["timeline_sec"] = clamped
        self.settings["stay_duration"] = clamped
        _save_settings(self.settings, changed_keys={"timeline_sec", "stay_duration"})
        self._sync_refresh_loop(restart=True)
        return True

    async def set_photo_frame_folder(self, folder_path: str) -> bool:
        folder = _resolve_existing_path_case_insensitive(folder_path)
        if folder is None:
            return False
        if not folder.is_dir():
            return False
        self.settings["photo_frame_folder"] = str(folder)
        self.settings["photo_frame_excluded_paths"] = []
        files = _list_photo_frame_files(str(folder))
        self.settings["custom_selected_path"] = str(files[0]) if files else ""
        _save_settings(
            self.settings,
            changed_keys={
                "photo_frame_folder",
                "photo_frame_excluded_paths",
                "custom_selected_path",
            },
        )
        await self._emit_custom_file_selected(self.settings["custom_selected_path"])
        self._sync_refresh_loop(restart=True)
        return True

    async def import_photo_frame_asset(self, source_path: str) -> dict:
        """Import one image selection into the photo-frame library."""
        source = Path(source_path).expanduser()
        try:
            source = source.resolve(strict=True)
        except (OSError, RuntimeError):
            raise ValueError("Unsupported custom asset")
        suffix = source.suffix.lower()
        if suffix == ".svg":
            temp_path = (
                Path(tempfile.gettempdir()) / f"eink-svg-{source.stem}-{uuid.uuid4().hex}.png"
            )
            try:
                subprocess.run(
                    ["rsvg-convert", str(source), "-o", str(temp_path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
                imported = await self.import_custom_asset(str(temp_path))
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                raise ValueError("Unsupported custom asset") from exc
            finally:
                try:
                    temp_path.unlink()
                except OSError:
                    pass
        else:
            imported = await self.import_custom_asset(str(source))

        destination = Path(str(imported.get("path") or "")).expanduser()
        if not destination.is_file():
            raise ValueError("Unsupported custom asset")
        self.settings["photo_frame_folder"] = str(destination.parent)
        self.settings["photo_frame_excluded_paths"] = []
        files = _list_photo_frame_files(str(destination.parent))
        selected = destination if destination in files else (files[0] if files else destination)
        self.settings["custom_selected_path"] = str(selected)
        _save_settings(
            self.settings,
            changed_keys={
                "photo_frame_folder",
                "photo_frame_excluded_paths",
                "custom_selected_path",
            },
        )
        await self._emit_custom_file_selected(str(selected))
        self._sync_refresh_loop(restart=True)
        result = dict(imported)
        result["path"] = str(selected)
        result["folder"] = str(destination.parent)
        return result

    async def list_photo_frame_files(self) -> list:
        files = _list_photo_frame_files(
            self.settings.get("photo_frame_folder", ""),
            self.settings.get("photo_frame_excluded_paths", []),
        )
        return [self._custom_asset_item(path) for path in files]

    async def exclude_photo_frame_file(self, path: str) -> bool:
        try:
            selected = Path(path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            return False
        files = _list_photo_frame_files(
            self.settings.get("photo_frame_folder", ""),
            self.settings.get("photo_frame_excluded_paths", []),
        )
        if selected not in files:
            return False
        excluded = list(self.settings.get("photo_frame_excluded_paths", []) or [])
        selected_path = str(selected)
        if selected_path not in excluded:
            excluded.append(selected_path)
        self.settings["photo_frame_excluded_paths"] = excluded
        remaining = _list_photo_frame_files(
            self.settings.get("photo_frame_folder", ""),
            excluded,
        )
        if self.settings.get("custom_selected_path") == selected_path:
            self.settings["custom_selected_path"] = str(remaining[0]) if remaining else ""
            await self._emit_custom_file_selected(self.settings["custom_selected_path"])
        _save_settings(
            self.settings,
            changed_keys={"photo_frame_excluded_paths", "custom_selected_path"},
        )
        self._sync_refresh_loop(restart=True)
        return True

    async def set_photo_frame_selected_file(self, path: str) -> bool:
        try:
            selected = Path(path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            return False
        files = _list_photo_frame_files(
            self.settings.get("photo_frame_folder", ""),
            self.settings.get("photo_frame_excluded_paths", []),
        )
        if selected not in files:
            return False
        self.settings["custom_selected_path"] = str(selected)
        _save_settings(self.settings, changed_keys={"custom_selected_path"})
        await self._emit_custom_file_selected(self.settings["custom_selected_path"])
        return True

    async def set_custom_selected_path(self, path: str) -> bool:
        if path and not Path(path).exists():
            return False
        self._reload_custom_library_settings()
        self.settings["custom_selected_path"] = path or ""
        _save_settings(self.settings, changed_keys={"custom_selected_path"})
        await self._emit_custom_file_selected(self.settings["custom_selected_path"])
        return True

    async def set_custom_slideshow_enabled(self, enabled: bool) -> bool:
        self._reload_custom_library_settings()
        self.settings["custom_slideshow_enabled"] = bool(enabled)
        _save_settings(self.settings, changed_keys={"custom_slideshow_enabled"})
        self._sync_refresh_loop(restart=True)
        return True

    async def get_display_options(self) -> dict:
        return display_options(self.settings)

    async def get_weather_location_options(
        self,
        country_code: str = "",
        query: str = "",
        offset: int = 0,
        limit: int = 40,
        language: str = "en",
    ) -> dict:
        return await asyncio.to_thread(
            weather_location_options,
            dict(self.settings),
            country_code,
            query,
            offset,
            limit,
            language,
        )

    async def search_weather_locations(
        self, query: str, language: str = "en", country_code: str = ""
    ) -> list:
        query = str(query).strip()[:100]
        if len(query) < 2:
            return []
        country_code = str(country_code).upper()
        params = {
            "name": query,
            "count": 50,
            "language": "zh" if language.startswith("zh") else language[:2],
            "format": "json",
        }
        if country_code and country_code != "ALL":
            # Use the catalog's country validation before making a remote request.
            weather_location_options(self.settings, country_code, limit=1)
            params["countryCode"] = country_code
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search", params=params
            )
            response.raise_for_status()
            payload = response.json()
        return [
            validate_display_update({"weather_manual_location": item}, self.settings)[
                "weather_manual_location"
            ]
            for item in payload.get("results", [])
            if not country_code or country_code == "ALL" or item.get("country_code") == country_code
        ]

    async def get_settings(self) -> dict:
        self._reload_custom_library_settings()
        settings = dict(self.settings)
        settings["display_mode"] = self._get_effective_display_mode()
        settings["stay_duration"] = self._get_stay_duration_sec()
        settings["timeline_sec"] = int(
            self.settings.get("timeline_sec", TIMELINE_DEFAULT_SEC) or TIMELINE_DEFAULT_SEC
        )
        settings["module_cycle_ids"] = self._get_cycle_module_ids()
        settings["single_module_id"] = self._get_single_module_id()
        settings["current_display_mode"] = self._get_effective_root_mode()
        return settings

    async def save_settings(self, new_settings: dict) -> bool:
        preferences = validate_display_update(new_settings, self.settings)
        new_settings = {
            **{
                key: value for key, value in new_settings.items() if key not in DISPLAY_SETTING_KEYS
            },
            **preferences,
        }
        preferences_changed = any(
            self.settings.get(key, DISPLAY_DEFAULTS.get(key)) != value
            for key, value in preferences.items()
        )
        weather_changed = any(
            key in preferences and self.settings.get(key) != preferences[key]
            for key in WEATHER_SETTING_KEYS
        )
        requested_keys = set(new_settings)
        new_settings = _normalize_settings(new_settings)
        self.settings.update(
            {
                k: v
                for k, v in new_settings.items()
                if k in requested_keys
                and k
                not in (
                    "stay_duration",
                    "timeline_sec",
                    "module_cycle_ids",
                    "single_module_id",
                    "display_mode",
                )
            }
        )
        if "mode" in requested_keys and new_settings["mode"] in (
            *DISPLAY_MODE_SEQUENCE,
            "carousel",
            "custom",
            "dashboard",
            "module",
            "agent",
        ):
            self.settings["mode"] = new_settings["mode"]
        if "display_mode" in requested_keys and new_settings["display_mode"] in ("single", "multi"):
            self.settings["display_mode"] = new_settings["display_mode"]
        if "stay_duration" in requested_keys:
            clamped = self._clamp_stay_duration(int(new_settings["stay_duration"]))
            self.settings["stay_duration"] = clamped
        if "timeline_sec" in requested_keys:
            self.settings["timeline_sec"] = max(
                60, int(new_settings["timeline_sec"] or TIMELINE_DEFAULT_SEC)
            )
        if "brightness" in requested_keys:
            self.settings["brightness"] = max(0, min(100, int(new_settings["brightness"] or 0)))
        if "photo_frame_interval_minutes" in requested_keys:
            self.settings["photo_frame_interval_minutes"] = _clamp_photo_frame_interval_minutes(
                new_settings.get("photo_frame_interval_minutes", PHOTO_FRAME_INTERVAL_DEFAULT)
            )
        if "photo_frame_interval_enabled" in requested_keys:
            photo_enabled = bool(new_settings.get("photo_frame_interval_enabled"))
            self.settings["photo_frame_interval_enabled"] = photo_enabled
            if photo_enabled:
                self.settings["module_switch_enabled"] = False
        if "module_switch_interval_minutes" in requested_keys:
            self.settings["module_switch_interval_minutes"] = _clamp_module_switch_interval_minutes(
                new_settings.get("module_switch_interval_minutes", MODULE_SWITCH_INTERVAL_DEFAULT)
            )
        if "module_switch_enabled" in requested_keys:
            module_enabled = bool(new_settings.get("module_switch_enabled"))
            self.settings["module_switch_enabled"] = module_enabled
            if module_enabled:
                self.settings["photo_frame_interval_enabled"] = False
        if "game_time_display_mode" in requested_keys:
            requested_mode = str(
                new_settings.get("game_time_display_mode", "auto") or "auto"
            ).lower()
            self.settings["game_time_display_mode"] = (
                requested_mode if requested_mode in GAME_TIME_DISPLAY_MODES else "auto"
            )
        if "module_cycle_ids" in requested_keys:
            self.settings["module_cycle_ids"] = [
                module_id
                for module_id in (
                    self._sanitize_module_id(value)
                    for value in (new_settings.get("module_cycle_ids") or [])
                )
                if module_id is not None
            ] or [0, 1, 2, 3, 4, 5, 6]
        if "single_module_id" in requested_keys:
            module_id = self._sanitize_module_id(new_settings["single_module_id"])
            if module_id is not None:
                self.settings["single_module_id"] = module_id
        self._sync_cycle_position_from_current()
        persisted_keys = set(requested_keys)
        if (
            "photo_frame_interval_enabled" in requested_keys
            or "module_switch_enabled" in requested_keys
        ):
            # Persist the automatically disabled counterpart as well. Otherwise
            # another UI client can reload the stale value and re-enable both.
            persisted_keys.update({"photo_frame_interval_enabled", "module_switch_enabled"})
        _save_settings(self.settings, changed_keys=persisted_keys)
        if "custom_selected_path" in requested_keys:
            await self._emit_custom_file_selected(self.settings.get("custom_selected_path", ""))
        if any(
            k in requested_keys
            for k in (
                "auto_refresh",
                "custom_slideshow_enabled",
                "mode",
                "interval_minutes",
                "timeline_sec",
                "stay_duration",
                "display_mode",
                "single_module_id",
                "module_cycle_ids",
                "photo_frame_interval_minutes",
                "photo_frame_interval_enabled",
                "module_switch_interval_minutes",
                "module_switch_enabled",
                "game_time_display_mode",
            )
        ):
            self._sync_refresh_loop(restart=True)
        if preferences_changed:
            self._display_preferences_revision = (
                getattr(self, "_display_preferences_revision", 0) + 1
            )
            if weather_changed:
                self._weather_preferences_revision = (
                    getattr(self, "_weather_preferences_revision", 0) + 1
                )
                self._weather_cache = {}
                self._module_data["P3"] = {}
            self._last_scheduler_observed_at = None
            self._last_scheduled_refresh_key = None
            target = self._get_active_display_target()
            if (
                target
                and self._display_target_enabled()
                and (
                    target[0] in ("dashboard", "clock", "weather")
                    or target[0] == "module"
                    and target[1] in (0, 3, 4, 5, AGENT_MODULE_ID)
                )
            ):
                self._queue_scheduled_refresh(
                    ("preferences", self._display_preferences_revision), target
                )
        return True

    def _custom_asset_dir(self) -> Path:
        return Path(decky.DECKY_PLUGIN_SETTINGS_DIR) / "custom-assets"

    def _reload_custom_library_settings(self) -> None:
        if not Path(_settings_path()).is_file():
            return
        latest = _load_settings()
        defaults = _default_settings()
        for key in CUSTOM_LIBRARY_SETTING_KEYS:
            self.settings[key] = latest.get(key, defaults[key])

    def _custom_asset_item(self, path: Path) -> dict:
        stat = path.stat()
        return {
            "path": str(path),
            "name": path.name,
            "dir": str(path.parent),
            "size": stat.st_size,
            "mtime": stat.st_mtime_ns,
            "thumbnail_png_base64": self._custom_asset_thumbnail(path),
            "color_thumbnail_png_base64": self._custom_asset_color_thumbnail(path),
        }

    def _custom_asset_thumbnail(self, path: Path) -> str:
        try:
            _ensure_pillow()
            pil_image = Image
            if pil_image is None:
                return ""
            frame = _render_bytes_locally(
                "custom_file",
                {"data": {"file_path": str(path), "title": path.name}},
            )
            preview = pil_image.frombytes("1", (SCREEN_W, SCREEN_H), frame).resize(
                (CUSTOM_THUMBNAIL_W, CUSTOM_THUMBNAIL_H),
                pil_image.Resampling.NEAREST,
            )
            output = io.BytesIO()
            preview.save(output, format="PNG", optimize=True)
            return base64.b64encode(output.getvalue()).decode("ascii")
        except Exception as exc:
            decky.logger.warning("Unable to render custom asset thumbnail for %s: %s", path, exc)
            return ""

    def _custom_asset_color_thumbnail(self, path: Path) -> str:
        try:
            _ensure_pillow()
            pil_image = Image
            if pil_image is None:
                return ""
            with pil_image.open(path) as source:
                source.seek(0)
                rgba = source.convert("RGBA")
            preview = pil_image.new("RGB", rgba.size, "white")
            preview.paste(rgba, mask=rgba.getchannel("A"))
            scale = max(
                CUSTOM_THUMBNAIL_W / preview.width,
                CUSTOM_THUMBNAIL_H / preview.height,
            )
            preview = preview.resize(
                (
                    max(1, int(round(preview.width * scale))),
                    max(1, int(round(preview.height * scale))),
                ),
                pil_image.Resampling.LANCZOS,
            )
            left = max(0, (preview.width - CUSTOM_THUMBNAIL_W) // 2)
            top = max(0, (preview.height - CUSTOM_THUMBNAIL_H) // 2)
            preview = preview.crop(
                (
                    left,
                    top,
                    left + CUSTOM_THUMBNAIL_W,
                    top + CUSTOM_THUMBNAIL_H,
                )
            )
            output = io.BytesIO()
            preview.save(output, format="PNG", optimize=True)
            return base64.b64encode(output.getvalue()).decode("ascii")
        except Exception as exc:
            decky.logger.warning(
                "Unable to render color custom asset thumbnail for %s: %s", path, exc
            )
            return ""

    def _managed_custom_asset_path(self, path: str) -> Optional[Path]:
        if not path:
            return None
        asset_dir = self._custom_asset_dir().resolve()
        try:
            candidate = Path(path).resolve(strict=True)
            candidate.relative_to(asset_dir)
        except (FileNotFoundError, OSError, ValueError):
            return None
        return candidate if candidate.is_file() else None

    async def list_custom_assets(self) -> list:
        self._reload_custom_library_settings()
        asset_dir = self._custom_asset_dir()
        asset_dir.mkdir(parents=True, exist_ok=True)
        saved_paths = [str(path) for path in self.settings.get("custom_asset_paths", []) if path]
        legacy_selected = (self.settings.get("custom_selected_path") or "").strip()
        if not saved_paths and legacy_selected:
            legacy_path = Path(legacy_selected).expanduser()
            if legacy_path.is_file() and legacy_path.suffix.lower() in {
                ".jpg",
                ".jpeg",
                ".png",
                ".bmp",
                ".gif",
                ".webp",
            }:
                destination = asset_dir / legacy_path.name
                shutil.copy2(legacy_path, destination)
                destination = destination.resolve()
                saved_paths = [str(destination)]
                self.settings["custom_selected_path"] = str(destination)
        existing = []
        seen = set()
        for saved_path in saved_paths:
            managed = self._managed_custom_asset_path(saved_path)
            if managed is None or str(managed) in seen:
                continue
            seen.add(str(managed))
            existing.append(managed)
        supported_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
        orphans = sorted(
            (
                path.resolve()
                for path in asset_dir.iterdir()
                if path.is_file()
                and path.suffix.lower() in supported_extensions
                and str(path.resolve()) not in seen
            ),
            key=lambda path: path.stat().st_ctime_ns,
            reverse=True,
        )
        existing = (existing + orphans)[:6]
        self.settings["custom_asset_paths"] = [str(path) for path in existing[:6]]
        kept = set(self.settings["custom_asset_paths"])
        source_map = self.settings.get("custom_asset_sources", {})
        self.settings["custom_asset_sources"] = (
            {
                source_path: managed_path
                for source_path, managed_path in source_map.items()
                if managed_path in kept
            }
            if isinstance(source_map, dict)
            else {}
        )
        _save_settings(
            self.settings,
            changed_keys={"custom_selected_path", "custom_asset_paths", "custom_asset_sources"},
        )
        return [self._custom_asset_item(path) for path in existing[:6]]

    async def import_custom_asset(self, source_path: str) -> dict:
        source = Path(source_path).expanduser().resolve(strict=True)
        if not source.is_file() or source.suffix.lower() not in {
            ".jpg",
            ".jpeg",
            ".png",
            ".bmp",
            ".gif",
            ".webp",
        }:
            raise ValueError("Unsupported custom asset")
        asset_dir = self._custom_asset_dir()
        asset_dir.mkdir(parents=True, exist_ok=True)
        self._reload_custom_library_settings()
        source_key = str(source)
        source_map = self.settings.get("custom_asset_sources", {})
        if not isinstance(source_map, dict):
            source_map = {}
        source_destination = self._managed_custom_asset_path(str(source_map.get(source_key, "")))
        existing = [
            Path(path).resolve()
            for path in self.settings.get("custom_asset_paths", [])
            if path and self._managed_custom_asset_path(str(path)) is not None
        ]
        matching = next((path for path in existing if path.name == source.name), None)
        if source_destination is not None:
            destination = source_destination
            shutil.copy2(source, destination)
        elif matching is None:
            destination = asset_dir / source.name
            shutil.copy2(source, destination)
        elif matching.read_bytes() == source.read_bytes():
            destination = matching
            os.utime(destination, None)
        else:
            destination = asset_dir / f"{source.stem}-{uuid.uuid4().hex}{source.suffix.lower()}"
            shutil.copy2(source, destination)
        destination = destination.resolve()
        source_map[source_key] = str(destination)
        ordered = [str(destination)] + [
            str(path)
            for path in self.settings.get("custom_asset_paths", [])
            if path and str(Path(path)) != str(destination)
        ]
        evicted = ordered[6:]
        self.settings["custom_asset_paths"] = ordered[:6]
        for evicted_path in evicted:
            managed = self._managed_custom_asset_path(evicted_path)
            if managed is not None:
                try:
                    managed.unlink()
                except OSError:
                    pass
        kept = set(self.settings["custom_asset_paths"])
        self.settings["custom_asset_sources"] = {
            source_path: managed_path
            for source_path, managed_path in source_map.items()
            if managed_path in kept
        }
        _save_settings(
            self.settings,
            changed_keys={"custom_asset_paths", "custom_asset_sources"},
        )
        return self._custom_asset_item(destination)

    async def delete_custom_asset(self, path: str) -> bool:
        self._reload_custom_library_settings()
        managed = self._managed_custom_asset_path(path)
        if managed is None:
            return False
        managed.unlink()
        removed = str(managed)
        self.settings["custom_asset_paths"] = [
            str(item)
            for item in self.settings.get("custom_asset_paths", [])
            if str(Path(item).resolve()) != removed
        ]
        source_map = self.settings.get("custom_asset_sources", {})
        self.settings["custom_asset_sources"] = (
            {
                source_path: managed_path
                for source_path, managed_path in source_map.items()
                if managed_path != removed
            }
            if isinstance(source_map, dict)
            else {}
        )
        if self.settings.get("custom_selected_path") == removed:
            self.settings["custom_selected_path"] = ""
            await self._emit_custom_file_selected("")
        _save_settings(
            self.settings,
            changed_keys={"custom_selected_path", "custom_asset_paths", "custom_asset_sources"},
        )
        return True

    async def list_user_files(self, directory: str = "") -> list:
        """列出受管素材；显式目录参数保留为兼容扫描入口。"""
        if not directory:
            return await self.list_custom_assets()
        IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
        p = Path(directory)
        if not p.exists():
            return []
        results = []
        try:
            for f in sorted(p.iterdir(), key=lambda item: item.stat().st_mtime_ns, reverse=True):
                if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                    results.append(self._custom_asset_item(f))
        except Exception:
            pass
        return results[:6]

    async def _send_custom_file_internal(
        self,
        path: str,
        title: str = "",
        *,
        set_active: bool = True,
        foreground_request: Optional[int] = None,
    ) -> bool:
        """发送本地图片文件到墨水屏"""
        if not self._display_target_enabled():
            return False
        if set_active:
            self.settings["mode"] = "custom"
            self.settings["display_mode"] = "single"
            self.settings["single_module_id"] = 6
            _save_settings(
                self.settings,
                changed_keys={"mode", "display_mode", "single_module_id"},
            )
            self._set_active_module(None)
        if not Path(path).exists():
            decky.logger.error("File not found: %s", path)
            return False
        data = {"file_path": path, "title": title or Path(path).name}
        data_bytes = self._render_bytes("custom_file", {"data": data})
        if data_bytes is None:
            await self._emit_status()
            return False
        ok = await self._send_prepared_bytes(data_bytes, foreground_request=foreground_request)
        if ok:
            self._module_data["P6"] = dict(data)
            self.settings["custom_selected_path"] = path
            if set_active:
                self.settings["single_module_id"] = 6
            changed_keys = {"custom_selected_path"}
            if set_active:
                changed_keys.add("single_module_id")
            _save_settings(self.settings, changed_keys=changed_keys)
            self._timeline_idx = 6
            if set_active:
                self._set_active_module(6)
            await decky.emit("timeline_idx", 6)
            await self._emit_custom_file_selected(path)
        return ok

    async def send_custom_file(self, path: str, title: str = "") -> bool:
        return await self._run_foreground_display_request(
            lambda foreground_request: self._send_custom_file_internal(
                path,
                title,
                set_active=True,
                foreground_request=foreground_request,
            )
        )

    async def send_next_photo_frame_file(self) -> bool:
        files = await self.list_photo_frame_files()
        if not files:
            self._last_error = "No photo-frame images found"
            await self._emit_status()
            return False

        current_path = self.settings.get("custom_selected_path", "")
        file_paths = [item["path"] for item in files]
        if current_path in file_paths:
            next_idx = (file_paths.index(current_path) + 1) % len(file_paths)
        else:
            next_idx = 0
        next_file = files[next_idx]
        return await self._send_custom_file_internal(
            next_file["path"],
            next_file["name"],
            set_active=True,
        )

    async def send_next_custom_file(self) -> bool:
        if self.settings.get("photo_frame_folder"):
            return await self.send_next_photo_frame_file()
        files = await self.list_user_files("")
        if not files:
            self._last_error = "No custom images found"
            await self._emit_status()
            return False

        current_path = self.settings.get("custom_selected_path", "")
        file_paths = [item["path"] for item in files]
        if current_path in file_paths:
            next_idx = (file_paths.index(current_path) + 1) % len(file_paths)
        else:
            next_idx = 0

        next_file = files[next_idx]
        return await self._send_custom_file_internal(
            next_file["path"],
            next_file["name"],
            set_active=self._get_effective_display_mode() != "multi",
        )

    async def refresh_now(self) -> bool:
        return await self._do_refresh()

    # ── Auto-refresh loop ─────────────────────
    def _start_refresh_loop(self):
        self._refresh_task = asyncio.get_event_loop().create_task(self._refresh_loop())

    def _stop_refresh_loop(self):
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            self._refresh_task = None

    def _queue_scheduled_refresh(
        self,
        refresh_key: tuple[int, int, int, int, int],
        target: tuple[str, Optional[int]],
    ) -> None:
        self._latest_background_refresh_request = (refresh_key, target)
        task = self._background_refresh_task
        if task is not None and not task.done():
            if not self._background_ble_active:
                task.cancel()
            return
        self._start_background_refresh_worker()

    def _start_background_refresh_worker(self) -> None:
        if self._background_refresh_stopping:
            return
        task = asyncio.get_running_loop().create_task(self._background_refresh_worker())
        self._background_refresh_task = task
        task.add_done_callback(self._background_refresh_finished)

    def _background_refresh_finished(self, task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            decky.logger.error("Background refresh worker failed: %s", exc)
        if self._background_refresh_task is task:
            self._background_refresh_task = None
        if (
            self._latest_background_refresh_request is not None
            and not self._background_refresh_stopping
        ):
            self._start_background_refresh_worker()

    async def _background_refresh_worker(self) -> None:
        while not self._background_refresh_stopping:
            request = self._latest_background_refresh_request
            if request is None:
                return
            self._latest_background_refresh_request = None
            refresh_key, target = request
            self._scheduled_refresh_inflight_key = refresh_key
            ok = False
            try:
                decky.logger.info(
                    "Background refresh started key=%s target=%s", refresh_key, target
                )
                ok = await self._refresh_active_display(target)
            except asyncio.CancelledError:
                # Cancellation is the ownership handoff signal. Never swallow
                # it here: doing so can keep the BLE lock alive after a
                # foreground module request or explicit disconnect.
                decky.logger.info(
                    "Cancelled background refresh key=%s target=%s", refresh_key, target
                )
                raise
            except Exception as exc:
                decky.logger.error("Scheduled refresh failed: %s", exc)
            finally:
                if self._scheduled_refresh_inflight_key == refresh_key:
                    self._scheduled_refresh_inflight_key = None
            if ok:
                self._last_scheduled_refresh_key = refresh_key
                if self._pending_scheduled_refresh_key == refresh_key:
                    self._pending_scheduled_refresh_key = None

    async def _stop_background_refresh_queue(self) -> None:
        self._background_refresh_stopping = True
        self._latest_background_refresh_request = None
        task = self._background_refresh_task
        if task is not None and not task.done():
            if self._background_ble_active:
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            else:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._background_refresh_task = None
        self._scheduled_refresh_inflight_key = None
        self._background_ble_active = False

    def _start_cycle_loop(self):
        self._cycle_task = asyncio.get_event_loop().create_task(self._cycle_loop())

    def _stop_cycle_loop(self):
        if self._cycle_task and not self._cycle_task.done():
            self._cycle_task.cancel()
            self._cycle_task = None

    def _start_photo_frame_loop(self):
        self._photo_frame_task = asyncio.get_event_loop().create_task(self._photo_frame_loop())

    def _stop_photo_frame_loop(self):
        if self._photo_frame_task and not self._photo_frame_task.done():
            self._photo_frame_task.cancel()
            self._photo_frame_task = None

    def _current_module_switch_id(self) -> int:
        mode = self._get_effective_root_mode()
        if mode == "dashboard":
            return 0
        if mode == "clock":
            return 4
        if mode == "weather":
            return 3
        if mode == "deck_status":
            return 2
        if mode == "timeline":
            module_id = self._get_single_module_id()
            if module_id in MODULE_SWITCH_MODULE_IDS:
                return module_id
        return 0

    async def _send_module_switch_target(self, module_id: int) -> bool:
        if module_id == 0:
            return await self.send_dashboard()
        if module_id == 4:
            return await self.send_clock()
        if module_id == 3:
            return await self.send_weather(
                self.settings.get("latitude", 0.0),
                self.settings.get("longitude", 0.0),
            )
        return await self.send_module(module_id)

    async def _refresh_loop(self):
        try:
            while True:
                if self._desktop_owner_active():
                    self._desktop_owner_seen = True
                    await asyncio.sleep(0.2)
                    continue
                if self._desktop_owner_seen:
                    self._desktop_owner_seen = False
                    self._reload_settings_after_desktop_handoff()
                    # The desktop client owns BLE while it is open.  Its
                    # lease can cover the moment a game starts, so the
                    # scheduler's previous wall-clock sample may still be
                    # from before the handoff.  Treat the first tick after
                    # release as a fresh observation and render the current
                    # game poster immediately instead of waiting for the
                    # next five-minute bucket.
                    self._last_scheduler_observed_at = None
                    self._last_scheduled_refresh_key = None
                    self._pending_scheduled_refresh_key = None
                await self._scheduled_refresh_tick(display_now(with_context({}, self.settings)))
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            pass

    async def _scheduled_refresh_tick(self, now: datetime) -> bool:
        previous_observed_at = getattr(self, "_last_scheduler_observed_at", None)
        self._last_scheduler_observed_at = now
        if not self._should_run_refresh_loop():
            return False
        target = self._get_active_display_target()
        if target is None or not self._is_scheduled_refresh_target(target):
            return False
        cadence_sec = _target_refresh_cadence(target)
        refresh_key = _target_refresh_key(target, now)
        pending_match = (
            refresh_key is not None and self._pending_scheduled_refresh_key == refresh_key
        )
        if (
            cadence_sec is None
            or refresh_key is None
            or (not pending_match and not _target_refresh_is_due(target, now, previous_observed_at))
        ):
            if not pending_match:
                self._pending_scheduled_refresh_key = None
            return False
        if now.second < 1:
            return False
        if refresh_key == self._last_scheduled_refresh_key:
            self._pending_scheduled_refresh_key = None
            return False
        if refresh_key == self._scheduled_refresh_inflight_key:
            return False
        latest_request = self._latest_background_refresh_request
        if latest_request is not None and latest_request[0] == refresh_key:
            return False
        due_observed = pending_match or _target_refresh_is_due(target, now, previous_observed_at)
        if not due_observed:
            return False
        self._pending_scheduled_refresh_key = refresh_key
        if self._ble_lock is not None and self._ble_lock.locked():
            return False
        decky.logger.info(
            "Scheduled refresh due at %s cadence=%ds target=%s",
            now.isoformat(timespec="seconds"),
            cadence_sec,
            target,
        )
        self._queue_scheduled_refresh(refresh_key, target)
        return True

    async def _cycle_loop(self):
        try:
            while True:
                await asyncio.sleep(
                    _clamp_module_switch_interval_minutes(
                        self.settings.get(
                            "module_switch_interval_minutes", MODULE_SWITCH_INTERVAL_DEFAULT
                        )
                    )
                    * 60
                )
                if not self._should_run_module_switch_loop():
                    continue
                next_module_id = _next_module_switch_id(self._current_module_switch_id())
                decky.logger.info("Automatic module switch to module_id=%d", next_module_id)
                await self._send_module_switch_target(next_module_id)
        except asyncio.CancelledError:
            pass

    async def _photo_frame_loop(self):
        try:
            while True:
                await asyncio.sleep(
                    _clamp_photo_frame_interval_minutes(
                        self.settings.get(
                            "photo_frame_interval_minutes", PHOTO_FRAME_INTERVAL_DEFAULT
                        )
                    )
                    * 60
                )
                if not self._should_run_photo_frame_loop():
                    continue
                await self.send_next_photo_frame_file()
        except asyncio.CancelledError:
            pass

    async def _do_refresh(self) -> bool:
        try:
            target = self._get_active_display_target()
            if target is not None:
                return await self._refresh_active_display(target)
        except Exception as e:
            decky.logger.error("Refresh failed: %s", e)
        return False


# Backward-compatible alias used by older unit tests / secondary-dev snippets.
MonoInkCore = EInkCore


class Plugin(DaemonPluginBridge):
    """Decky-facing bridge. The daemon owns BLE, settings, scheduling, and rendering."""

    pass
