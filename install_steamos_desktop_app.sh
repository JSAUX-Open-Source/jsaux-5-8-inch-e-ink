#!/bin/sh
set -e

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_ROOT="${1:-$SCRIPT_DIR}"
LAUNCHER="$APP_ROOT/desktop_app_launcher.sh"
APP_ID="jsaux-eink-desktop"
APP_NAME="JSAUX E-INK"
DESKTOP_FILE="$HOME/.local/share/applications/${APP_ID}.desktop"
DESKTOP_SHORTCUT="$HOME/Desktop/${APP_NAME}.desktop"

mkdir -p "$HOME/.local/share/applications"

chmod +x "$LAUNCHER"
sh "$APP_ROOT/install_steamos_daemon.sh" "$APP_ROOT"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=${APP_NAME}
Comment=Desktop controller for JSAUX E-INK
Exec=${LAUNCHER}
Path=${APP_ROOT}
Icon=preferences-system
Terminal=false
Categories=Utility;
StartupNotify=true
X-AppVersion=V1.2
EOF

cp "$DESKTOP_FILE" "$DESKTOP_SHORTCUT"
chmod +x "$DESKTOP_FILE" "$DESKTOP_SHORTCUT"

echo "Installed ${APP_NAME}"
echo "Application file: $DESKTOP_FILE"
echo "Desktop shortcut: $DESKTOP_SHORTCUT"
