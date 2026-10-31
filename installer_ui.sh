#!/usr/bin/env bash

# Lightweight KDE progress UI used by the offline installer and uninstaller.
# It deliberately has no dependency beyond the tools already present on
# SteamOS (kdialog and qdbus/qdbus6).

UI_SERVICE=""
UI_PATH=""
UI_ACTIVE=0

ui_open() {
  UI_ACTIVE=0
  if ! command -v kdialog >/dev/null 2>&1 || [ -z "${DISPLAY:-}" ]; then
    return 0
  fi
  local result
  result=$(kdialog --title "${APP_NAME:-JSAUX E-INK}" --progressbar "$1" 100 2>/dev/null || true)
  UI_SERVICE=$(printf '%s\n' "$result" | awk 'NR == 1 {print $1}')
  UI_PATH=$(printf '%s\n' "$result" | awk 'NR == 1 {print $2}')
  if [ -n "$UI_SERVICE" ] && [ -n "$UI_PATH" ]; then
    UI_ACTIVE=1
  fi
}

ui_set() {
  local progress="$1"
  local label="$2"
  [ "$UI_ACTIVE" -eq 1 ] || return 0
  local qdbus_bin=qdbus6
  command -v "$qdbus_bin" >/dev/null 2>&1 || qdbus_bin=qdbus
  "$qdbus_bin" "$UI_SERVICE" "$UI_PATH" setLabelText "$label" >/dev/null 2>&1 || true
  "$qdbus_bin" "$UI_SERVICE" "$UI_PATH" org.freedesktop.DBus.Properties.Set org.kde.kdialog.ProgressDialog value "$progress" >/dev/null 2>&1 || true
}

ui_close() {
  [ "$UI_ACTIVE" -eq 1 ] || return 0
  local qdbus_bin=qdbus6
  command -v "$qdbus_bin" >/dev/null 2>&1 || qdbus_bin=qdbus
  "$qdbus_bin" "$UI_SERVICE" "$UI_PATH" close >/dev/null 2>&1 || true
  UI_ACTIVE=0
}

