# Third-party licenses and attributions

This plugin vendors offline Python wheels under `py_modules/` and
`runtime_wheels/`, and ships a prebuilt Game Mode bundle in `dist/`.
Upstream license texts generally remain next to each package
(`py_modules/*-dist-info/`, including any `NOTICE` files).

## Bundled / inlined

| Component | License | Notes |
|-----------|---------|--------|
| `@decky/api` 1.1.3 (inlined in `dist/index.js`) | LGPL-2.1 | Source: [SteamDeckHomebrew/loader-api](https://github.com/SteamDeckHomebrew/loader-api). Compatible use: unobfuscated, replaceable. |
| Pillow / PIL | MIT-CMU (+ bundled libs) | FreeType (FTL) and Independent JPEG Group libjpeg acknowledgments are quoted below. Full vendor texts remain in `py_modules/pillow-*-dist-info/licenses/LICENSE`. |
| `py_modules/xml/` | PSF-2.0 (CPython stdlib copy) | Used for SteamOS interpreter compatibility; see [PSF License](https://docs.python.org/3/license.html). |
| aiohttp / aiosignal / frozenlist / multidict / propcache / yarl | Apache-2.0 (and MIT where dual) | Keep package `NOTICE` files under dist-info. |
| bleak / dbus-fast / anyio / attrs / h11 / sniffio | MIT (or MIT OR Apache-2.0) | — |
| httpx / httpcore / idna | BSD-3-Clause | — |
| certifi | MPL-2.0 | File-level copyleft; CA bundle unmodified. |
| aiohappyeyeballs / typing_extensions | PSF-2.0 | — |
| GeoNames-derived city catalog (`assets/weather-cities.json.gz`) | CC BY 4.0 | See `assets/weather-cities-LICENSE.txt`. |

## Runtime services (not vendored)

| Service | License / terms | Use in this plugin |
|---------|-----------------|--------------------|
| [Open-Meteo](https://open-meteo.com/) forecast & geocoding | CC BY 4.0 | Weather layouts show an on-panel “Open-Meteo” credit. Free tier is generally non-commercial—confirm the correct plan/terms before commercial shipping. |
| [ipwho.is](https://ipwho.is/) | Provider terms | Used only when weather location mode is `auto` (default). Sends the user’s public IP. Switch to manual city selection to disable. |
| Steam CDN artwork URLs | Valve | Fetches cover art for the current Steam AppID. |

## Host runtime (not packaged)

| Component | License | Notes |
|-----------|---------|--------|
| Decky Loader | GPL-2.0 | Host process for Game Mode plugins; MIT plugins are normal in this ecosystem. |

## Required acknowledgments (Pillow bundled libs)

### FreeType (FTL)

This product uses FreeType via Pillow. Preferred credit form from the FreeType
Project LICENSE:

> Portions of this software are copyright © 2024 The FreeType
> Project (www.freetype.org).  All rights reserved.

### Independent JPEG Group (libjpeg)

This product uses libjpeg via Pillow. Required documentation statement:

> This software is based in part on the work of the Independent JPEG Group.

## Trademark

**JSAUX** and product names/logos are trademarks of their owners. The MIT
license for this repository does not grant trademark rights.
