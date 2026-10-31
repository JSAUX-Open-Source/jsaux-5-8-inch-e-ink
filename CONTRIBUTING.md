# Contributing

Thanks for helping improve the **JSAUX E-Ink Faceplate for Steam Machine** host App.

Public development happens on GitHub:
[JSAUX-Open-Source/JSAUX-E-INK](https://github.com/JSAUX-Open-Source/JSAUX-E-INK).
Open a branch and pull request there. Maintainers aim to reply within about a week.

## What you can change

- Display layouts, modules, fonts, and data sources in Python (`main.py` and related modules)
- Desktop Mode (`desktop_app.py` and helpers)
- Host BLE connect / device-info / image-transfer used by the App (`eink_display.py`)
- Docs, install helpers, tests

Game Mode panel UI currently ships as a prebuilt `dist/` bundle (TypeScript `src/` is not in this tree yet). Panel-only PRs that require rebuilding `dist/` are not practical until sources are restored.

## What we do not accept

- Chip firmware, OTA flashing, silicon / PCBA / panel-driver materials (see [PROPRIETARY.md](./PROPRIETARY.md))
- Reordering the `sys.path` bootstrap at the top of `main.py` / `eink_daemon.py`
- Secrets, internal factory docs, private emails, or internal network addresses in commits / Issues / PRs

## Develop and test

1. Prefer a Steam Machine / SteamOS host (vendored wheels target SteamOS ABI).
2. Run checks:

```bash
npm test
```

(`npm test` runs `python3 -m unittest discover -s tests -v`.)

3. Install a local build for manual checks — see **Developer install** in [README.md](./README.md).

`npm run build` / `watch` are not available without frontend sources; use the shipped `dist/`.

## Pull requests

- One PR, one concern
- Describe what changed and how you tested it
- If the change affects on-device UI or e-ink layouts, attach screenshots or photos
- Do not force-push shared branches; keep history linear when possible

Use the repository pull request template when opening a PR.
