"""Offline city selection, keyed by named timezone rather than UTC offset."""

from __future__ import annotations

import gzip
import json
import unicodedata
from functools import lru_cache
from pathlib import Path
from zoneinfo import available_timezones


@lru_cache(maxsize=1)
def catalog():
    with gzip.open(
        Path(__file__).with_name("assets") / "weather-cities.json.gz", "rt", encoding="utf-8"
    ) as source:
        data = json.load(source)
    valid = available_timezones()
    rows = []
    for row in data["cities"]:
        zone = row[8]
        seen = set()
        canonical = zone
        while canonical in data["aliases"] and canonical not in seen:
            seen.add(canonical)
            canonical = data["aliases"][canonical]
        if zone not in valid:
            if canonical not in valid:
                continue
            row[8] = canonical
        row.append(fold(" ".join(str(row[index]) for index in (1, 2, 3, 4, 5))))
        row.append(canonical)
        rows.append(row)
    data["cities"] = rows
    return data


def canonical_zone(name):
    aliases = catalog()["aliases"]
    seen = set()
    while name in aliases and name not in seen:
        seen.add(name)
        name = aliases[name]
    return name


def effective_zone(settings):
    from display_preferences import resolve_zone

    zone = resolve_zone(settings)
    return getattr(zone, "key", "UTC")


def countries():
    data = catalog()
    available_codes = {row[5] for row in data["cities"]}
    # Do not expose legacy/territory codes that have no geocodable city row;
    # selecting one would otherwise open an empty weather picker forever.
    values = [
        {"code": code, "name": value["en"], "name_zh": value["zh"]}
        for code, value in data["countries"].items()
        if code in available_codes
    ]
    return sorted(values, key=lambda item: item["name"])


def default_country(settings):
    zone = effective_zone(settings)
    data = catalog()
    available_codes = {row[5] for row in data["cities"]}
    matching = [
        code
        for code in (
            data.get("named_zones", {}).get(zone) or data["zones"].get(canonical_zone(zone), {})
        ).get("countries", [])
        if code in available_codes
    ]
    if matching:
        return matching[0]
    selected = settings.get("weather_manual_location") or {}
    for value in (selected.get("country_code"), settings.get("country")):
        code = str(value or "").upper()
        if code in data["countries"]:
            return code
    return "ALL"


def fold(text):
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", str(text)).casefold()
        if not unicodedata.combining(character)
    )


def location_options(settings, country_code="", query="", offset=0, limit=40, language="en"):
    data = catalog()
    zone = effective_zone(settings)
    canonical = canonical_zone(zone)
    country_code = str(country_code or default_country(settings)).upper()
    if country_code != "ALL" and country_code not in data["countries"]:
        raise ValueError("Invalid country / 无效国家或地区")
    offset, limit = max(0, int(offset)), max(1, min(100, int(limit)))
    query = fold(str(query).strip()[:100])
    matching = [
        row
        for row in data["cities"]
        if (country_code == "ALL" or row[5] == country_code) and (not query or query in row[10])
    ]
    matching.sort(
        key=lambda row: (0 if row[8] == zone else 1 if row[11] == canonical else 2, -row[9])
    )
    principal = data.get("named_zones", {}).get(zone) or data["zones"].get(canonical)
    if (
        not query
        and principal
        and country_code in ("ALL", *principal["countries"])
        and not any(row[11] == canonical for row in matching)
    ):
        code = principal["countries"][0]
        name = zone.rsplit("/", 1)[-1].replace("_", " ")
        matching.insert(
            0,
            [
                "tz:" + zone,
                name,
                name,
                "",
                "",
                code,
                *principal["point"],
                zone,
                0,
                fold(name),
                canonical,
            ],
        )
    result = []
    for row in matching[offset: offset + limit]:
        country = data["countries"][row[5]]
        result.append(
            {
                "id": row[0],
                "name": row[3] if language.startswith("zh") and row[3] else row[1],
                "name_en": row[1],
                "name_zh": row[3],
                "admin1": row[4],
                "country_code": row[5],
                "country": country["zh"] if language.startswith("zh") else country["en"],
                "latitude": row[6],
                "longitude": row[7],
                "timezone": row[8],
                "recommended": row[11] == canonical,
            }
        )
    return {
        "timezone": zone,
        "country_code": country_code,
        "countries": countries(),
        "cities": result,
        "total": len(matching) or len(result),
        "offset": offset,
        "next_offset": offset + limit if offset + limit < len(matching) else None,
    }
