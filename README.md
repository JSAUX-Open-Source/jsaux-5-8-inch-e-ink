# JSAUX E-INK

[中文说明](./README-zh.md)

Decky Loader plugin and SteamOS desktop companion for the **JSAUX E-Ink Faceplate for Steam Machine**.

This public tree opens the **host App**: UI, rendering, local daemon, installers, and offline dependency packs. **Chip firmware / OTA flashing is not included**. See [PROPRIETARY.md](./PROPRIETARY.md).

Current plugin version: **1.2**

Public source of truth:
[github.com/JSAUX-Open-Source/JSAUX-E-INK](https://github.com/JSAUX-Open-Source/JSAUX-E-INK)

## Official links

- Installation guide: [jsaux.com — Steam Machine Faceplate App installation](https://jsaux.com/pages/steam-machine-faceplate-app-installation-guide)
- Product / support: [jsaux.com](https://jsaux.com/)
- Issues / feature requests: use GitHub Issues (templates provided)
- Contributing: [CONTRIBUTING.md](./CONTRIBUTING.md)
- Security: [SECURITY.md](./SECURITY.md) (GitHub Private vulnerability reporting — do not open a public Issue)

## Features

- Game Mode (Decky) and Desktop Mode entry points
- Clock, weather, calendar, game progress, performance, and custom image layouts
- Local daemon / WebSocket bridge for SteamOS
- Offline city catalog for weather location picking
- SteamOS installer / uninstaller helpers

## What's open and what isn't

**Open in this repository (the host App):**

- Game Mode and Desktop UI surfaces (Game Mode ships as a prebuilt `dist/` bundle; TypeScript `src/` is not included yet)
- Local rendering, daemon, and SteamOS install helpers
- Host-side BLE connect / device-info / image-transfer code used by the App (`eink_display.py`)
- Optional on-device Agent layout helpers (`agent_status.py` only; no cloud usage client and no local HTTP agent ingest)

**Not provided:**

- Chip firmware binaries or chip firmware / OTA flashing
- Factory silicon / PCBA / panel-driver IC programming materials
- A cloud Codex / ChatGPT usage client
- Local HTTP agent ingest (`/v1/agent/events`), agent bridge LAN bind, or `agent_token` issuance

With this App tree alone you can install, connect over BLE, query the accessory, and update the display. In-app firmware flashing is unavailable.

## Requirements

- [Steam Machine](https://store.steampowered.com/steammachine) / SteamOS with [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
- Python 3.11+ (SteamOS bundled interpreters; ABI-matched wheels are vendored)
- BlueZ (Steam Machine / SteamOS Bluetooth stack for BLE)

## Developer install

Use this when you changed Python / assets in a clone and want to run them under Decky without the full privileged installer.

1. On Steam Machine / SteamOS, ensure [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) is installed.
2. Copy this repository (or an unpacked Release zip) into:

   `~/homebrew/plugins/jsaux-eink-display/`

   The folder name must be **`jsaux-eink-display`** (same as the official installer).
3. Restart Decky Loader (or reboot), then open **JSAUX E-INK** in Game Mode.
4. Plugin logs: `~/homebrew/logs/jsaux-eink-display/` (or the matching Decky log folder for this plugin).

End-user installs should still follow the [official installation guide](https://jsaux.com/pages/steam-machine-faceplate-app-installation-guide) or a GitHub Release zip when published.

## Privileged install (what it does)

Installers under `installer_*.sh` / `installer_privileged.py` request **one** administrator session via `pkexec` (or `sudo` if `pkexec` is unavailable). The root worker:

- Installs the Decky plugin files and Desktop Mode launcher pieces
- Installs the user systemd unit for `jsaux-eink-daemon` (local WebSocket bridge)
- Installs a udev rule so Desktop Mode can use the Steam Machine touchscreen input device
- Does **not** create or change user account passwords, write password files, or leave a root listener running

You will be prompted for an existing administrator password when SteamOS requires it. If your account has no password configured, authorize with whatever method your SteamOS image already uses for `pkexec`/`sudo`—this installer does not set one for you.

## Privacy: weather location

- Default weather location mode is **`auto`**: the App may call [ipwho.is](https://ipwho.is/) once (and on refresh) to estimate city/coordinates from your public IP.
- To avoid that request, set weather location to **manual** in the App and pick a city from the offline catalog / search UI (`weather_location_mode=manual`).
- Forecast and geocoding use [Open-Meteo](https://open-meteo.com/) (CC BY 4.0). The fullscreen weather layout shows an **Open-Meteo** credit; see also [THIRD_PARTY_LICENSES.md](./THIRD_PARTY_LICENSES.md).
- **Commercial use:** Open-Meteo’s free API is generally limited to non-commercial use—confirm the right plan/terms with legal before shipping a commercial product that depends on it. Confirm ipwho.is terms the same way.

## Layout (high level)

| Path | Role |
|------|------|
| `main.py` | Decky backend, renderers, connection orchestration |
| `desktop_app.py` | Desktop Mode Tk UI |
| `eink_display.py` | Host BLE link + display image framing used by the App (no chip OTA) |
| `eink_daemon.py` / `daemon_client.py` | Local daemon + client |
| `dist/` | Prebuilt Game Mode UI bundle |
| `py_modules/` / `runtime_wheels/` | Vendored Python dependencies / wheels |
| `installer_*.sh` / `install_steamos_*.sh` / `udev/` / `systemd/` | SteamOS install helpers and host rules/units |
| `pack_plugin_release.sh` | Builds a manual-install Release zip |

## Development notes

- This snapshot publishes the Game Mode UI as a **prebuilt** `dist/index.js` bundle (TypeScript app sources are not included in this tree yet). `npm run build` / `watch` exit with a message; use the shipped `dist/`.
- Run checks with `npm test` (Python `unittest` under `tests/`). Prefer Steam Machine / SteamOS hosts: vendored wheels target SteamOS ABI, not macOS.
- Do not reorder the `sys.path` bootstrap at the top of `main.py` / `eink_daemon.py`.
- Weather city catalog licensing: `assets/weather-cities-LICENSE.txt` (GeoNames CC BY 4.0 and related notices).
- Third-party notices: [THIRD_PARTY_LICENSES.md](./THIRD_PARTY_LICENSES.md).

## Releases

Maintainers publish GitHub Releases (for example `v1.2`) with a zip you can unpack into `~/homebrew/plugins/jsaux-eink-display/`. To build that zip from a clean tree:

```bash
./pack_plugin_release.sh
```

## License

This open-source tree is released under the [MIT License](./LICENSE).

**JSAUX** and related logos are trademarks; the MIT license does not grant trademark rights.

Unavailable components listed in [PROPRIETARY.md](./PROPRIETARY.md) are not distributed with this repository.
