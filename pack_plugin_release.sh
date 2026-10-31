#!/usr/bin/env bash
# Build a manual-install zip for GitHub Releases (plugin directory layout).
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
VERSION="$(python3 -c 'import json; print(json.load(open("'"$ROOT"'/plugin.json"))["version"])')"
PLUGIN_DIR="jsaux-eink-display"
OUT_DIR="${1:-$ROOT/release}"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/jsaux-eink-pack.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$OUT_DIR" "$STAGE/$PLUGIN_DIR"

# Paths needed to run as a Decky plugin + desktop helpers (no node_modules / git).
INCLUDE=(
  LICENSE
  PROPRIETARY.md
  README.md
  README-zh.md
  THIRD_PARTY_LICENSES.md
  CONTRIBUTING.md
  SECURITY.md
  package.json
  plugin.json
  agent_status.py
  ble_lease.py
  daemon_client.py
  desktop_app.py
  desktop_app_launcher.sh
  desktop_controller.py
  desktop_i18n.py
  desktop_preferences.py
  device_identity.py
  display_preferences.py
  eink_daemon.py
  eink_display.py
  install_steamos_daemon.sh
  install_steamos_desktop_app.sh
  install_steamos_desktop_shortcut.sh
  installer_entry.sh
  installer_privileged.py
  installer_ui.sh
  main.py
  python_compatibility.sh
  render_subprocess.py
  runtime_wheel_extract.py
  setup.cfg
  pyproject.toml
  uninstall_steamos_app.sh
  uninstall_steamos_daemon.sh
  uninstall_steamos_desktop_shortcut.sh
  weather_locations.py
  assets
  dist
  py_modules
  runtime_wheels
  systemd
  udev
  preview
)

for path in "${INCLUDE[@]}"; do
  src="$ROOT/$path"
  if [ ! -e "$src" ]; then
    continue
  fi
  rsync -a --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' \
    "$src" "$STAGE/$PLUGIN_DIR/"
done

ZIP_NAME="jsaux-eink-display-${VERSION}.zip"
(
  cd "$STAGE"
  rm -f "$OUT_DIR/$ZIP_NAME"
  zip -qr "$OUT_DIR/$ZIP_NAME" "$PLUGIN_DIR"
)
(
  cd "$OUT_DIR"
  shasum -a 256 "$ZIP_NAME" > "${ZIP_NAME}.sha256"
)

echo "Wrote $OUT_DIR/$ZIP_NAME"
echo "SHA256: $(cut -d' ' -f1 "$OUT_DIR/${ZIP_NAME}.sha256")"
