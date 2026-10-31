"""Shared display preferences. Never changes the host clock or process TZ."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

DEFAULTS = {
    "display_timezone": "system",
    "display_time_format": "24",
    "display_auto_dst": True,
    "display_standard_offset_seconds": None,
    "weather_location_mode": "auto",
    "weather_temperature_unit": "celsius",
    "weather_manual_location": None,
    "weather_recent_locations": [],
}
SETTING_KEYS = frozenset(DEFAULTS)
TIME_KEYS = frozenset(key for key in DEFAULTS if key.startswith("display_"))
WEATHER_KEYS = frozenset(("weather_location_mode", "weather_manual_location"))
COMMON_ZONES = {
    "Asia/Shanghai": "北京 / Shanghai",
    "Asia/Hong_Kong": "香港 / Hong Kong",
    "Asia/Taipei": "台北 / Taipei",
    "Asia/Tokyo": "东京 / Tokyo",
    "Asia/Seoul": "首尔 / Seoul",
    "Asia/Singapore": "新加坡 / Singapore",
    "America/New_York": "纽约 / New York",
    "America/Los_Angeles": "洛杉矶 / Los Angeles",
    "Europe/London": "伦敦 / London",
    "Europe/Paris": "巴黎 / Paris",
    "Europe/Berlin": "柏林 / Berlin",
    "Australia/Sydney": "悉尼 / Sydney",
    "Asia/Kolkata": "印度 / Kolkata",
    "Asia/Kathmandu": "尼泊尔 / Kathmandu",
    "UTC": "UTC",
}


def system_zone():
    try:
        resolved = str(Path("/etc/localtime").resolve())
        if "/zoneinfo/" in resolved:
            return ZoneInfo(resolved.split("/zoneinfo/", 1)[1])
        text = Path("/etc/timezone").read_text().strip()
        return ZoneInfo(text)
    except (OSError, ValueError, ZoneInfoNotFoundError):
        return datetime.now().astimezone().tzinfo or timezone.utc


def offset_label(seconds):
    minutes = int(seconds // 60)
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"UTC{sign}{hours:02d}:{rest:02d}"


def resolve_zone(settings):
    name = settings.get("display_timezone", "system")
    return system_zone() if name == "system" else ZoneInfo(name)


def normalize_location(value):
    if not isinstance(value, dict) or not str(value.get("name") or "").strip():
        raise ValueError("Choose a weather city / 请选择天气城市")
    coordinates = []
    for key, limit in (("latitude", 90), ("longitude", 180)):
        raw = value.get(key)
        if isinstance(raw, bool):
            raise ValueError("Invalid coordinates")
        try:
            number = float(raw)
        except (TypeError, ValueError):
            raise ValueError("Invalid coordinates") from None
        if not math.isfinite(number) or abs(number) > limit:
            raise ValueError("Invalid coordinates")
        coordinates.append(number)
    zone = str(value.get("timezone") or "UTC")
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Invalid city timezone") from None
    return {
        "id": str(value.get("id") or "")[:64],
        "name": str(value["name"]).strip()[:100],
        "admin1": str(value.get("admin1") or "")[:100],
        "country": str(value.get("country") or "")[:100],
        "country_code": str(value.get("country_code") or "").upper()[:2],
        "latitude": coordinates[0],
        "longitude": coordinates[1],
        "timezone": zone,
    }


def validate_update(values, current):
    result = {key: value for key, value in values.items() if key in SETTING_KEYS}
    if "display_timezone" in result:
        name = str(result["display_timezone"])
        try:
            if name != "system":
                ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Invalid timezone / 无效时区") from None
        result["display_timezone"] = name
    if "display_time_format" in result:
        if result["display_time_format"] not in ("12", "24"):
            raise ValueError("Time format must be 12 or 24")
    if "weather_temperature_unit" in result and result["weather_temperature_unit"] not in (
        "celsius",
        "fahrenheit",
    ):
        raise ValueError("Temperature unit must be celsius or fahrenheit")
    if "display_auto_dst" in result and not isinstance(result["display_auto_dst"], bool):
        raise ValueError("DST setting must be a boolean")
    if "weather_location_mode" in result and result["weather_location_mode"] not in (
        "auto",
        "manual",
    ):
        raise ValueError("Invalid weather location mode")
    if "weather_manual_location" in result:
        result["weather_manual_location"] = normalize_location(result["weather_manual_location"])
        recent = [result["weather_manual_location"]]
        for item in current.get("weather_recent_locations", []):
            try:
                item = normalize_location(item)
            except ValueError:
                continue
            if (item["latitude"], item["longitude"]) not in {
                (entry["latitude"], entry["longitude"]) for entry in recent
            }:
                recent.append(item)
        result["weather_recent_locations"] = recent[:8]
    else:
        result.pop("weather_recent_locations", None)  # Backend owns this list.
    merged = {**DEFAULTS, **current, **result}
    if merged["weather_location_mode"] == "manual":
        normalize_location(merged.get("weather_manual_location"))
    # Record the exact standard offset when disabling DST or choosing a zone.
    result.pop("display_standard_offset_seconds", None)
    if {"display_auto_dst", "display_timezone"} & set(result):
        if merged["display_auto_dst"]:
            result["display_standard_offset_seconds"] = None
        else:
            local = datetime.now(timezone.utc).astimezone(resolve_zone(merged))
            result["display_standard_offset_seconds"] = int(
                (local.utcoffset() - (local.dst() or timedelta())).total_seconds()
            )
    return result


def preference_now(settings, instant=None):
    instant = instant or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("UTC instant must include a timezone")
    local = instant.astimezone(resolve_zone(settings))
    if settings.get("display_auto_dst", True):
        return local
    seconds = (
        settings.get("display_standard_offset_seconds")
        if settings.get("display_timezone") != "system"
        else None
    )
    if seconds is None:
        seconds = int((local.utcoffset() - (local.dst() or timedelta())).total_seconds())
    return instant.astimezone(timezone(timedelta(seconds=int(seconds))))


def make_context(settings, instant=None):
    now = preference_now(settings, instant)
    fmt = settings.get("display_time_format", "24")
    return {
        "now": now.isoformat(),
        "format": fmt,
        "clock": now.strftime("%I:%M" if fmt == "12" else "%H:%M"),
        "ampm": now.strftime("%p") if fmt == "12" else "",
        "timezone": settings.get("display_timezone", "system"),
        "temperature_unit": settings.get("weather_temperature_unit", "celsius"),
        "offset": offset_label(now.utcoffset().total_seconds()),
    }


def with_context(data, settings, instant=None):
    return {**dict(data or {}), "_display_context": make_context(settings, instant)}


def display_now(data=None):
    raw = (data or {}).get("_display_context", {}).get("now")
    return datetime.fromisoformat(raw) if raw else datetime.now().astimezone()


def clock_parts(data=None):
    context = (data or {}).get("_display_context", {})
    now = display_now(data)
    fmt = context.get("format", "24")
    return now.strftime("%I:%M" if fmt == "12" else "%H:%M"), (
        now.strftime("%p") if fmt == "12" else ""
    )


def weather_now(data=None):
    data = data or {}
    instant = display_now(data)
    name = data.get("_weather_timezone") or data.get("timezone")
    if name:
        try:
            return instant.astimezone(ZoneInfo(name))
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return instant


def render_context(mode, payload, settings):
    result = dict(payload)
    instant = datetime.now(timezone.utc)
    if mode == "dashboard":
        for key in (f"P{index}" for index in range(7)):
            if key in result:
                result[key] = with_context(result[key], settings, instant)
    elif "data" in result:
        result["data"] = with_context(result["data"], settings, instant)
    return result


def options(settings):
    from weather_locations import location_options

    now = datetime.now(timezone.utc)
    zones = []
    for name in sorted(available_timezones()):
        if name.startswith(("Etc/", "posix/", "right/")):
            continue
        local = now.astimezone(ZoneInfo(name))
        label = COMMON_ZONES.get(name, name.replace("_", " "))
        zones.append(
            {"id": name, "label": label, "offset": offset_label(local.utcoffset().total_seconds())}
        )
    zones.sort(
        key=lambda item: (
            item["id"] not in COMMON_ZONES,
            list(COMMON_ZONES).index(item["id"]) if item["id"] in COMMON_ZONES else item["id"],
        )
    )
    return {
        "zones": zones,
        "preview": make_context(settings),
        "weather_locations": location_options(settings),
    }
