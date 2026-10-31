#!/usr/bin/env bash
# Single-authentication frontend for installation and removal.
# The only privileged process is the one Python worker launched below.
set -uo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-}"
PACKAGE_ROOT="${2:-}"
case "$ACTION" in install|uninstall) ;; *) exit 2 ;; esac
if [ "$(id -u)" -eq 0 ]; then
  printf '%s\n' 'Run this entry as the Steam Machine / SteamOS user, not root.' >&2
  exit 1
fi
if [ -z "$PACKAGE_ROOT" ]; then
  PACKAGE_ROOT="$SCRIPT_DIR"
fi
PACKAGE_ROOT="$(cd -- "$PACKAGE_ROOT" 2>/dev/null && pwd)" || {
  printf '%s\n' 'Installer package directory is unavailable.' >&2
  exit 1
}
PAYLOAD_ROOT="$PACKAGE_ROOT/payload/jsaux-eink-display"
export PATH=/usr/local/bin:/usr/bin:/bin
unset JSAUX_EINK_POLKIT_AUTH JSAUX_EINK_AUTH_PRECHECK
APP_NAME='JSAUX E-INK'
LOG_DIR="$HOME/Desktop"
mkdir -p "$LOG_DIR" 2>/dev/null || LOG_DIR="$HOME"
LOG_FILE="$LOG_DIR/JSAUX-E-INK-${ACTION}.log"
UI_SCRIPT="$SCRIPT_DIR/installer_ui.sh"
[ -f "$UI_SCRIPT" ] || UI_SCRIPT="$PAYLOAD_ROOT/installer_ui.sh"
[ -f "$UI_SCRIPT" ] && . "$UI_SCRIPT"
JSAUX_EINK_RUNTIME_OVERLAY=""
cleanup() {
  ui_close || true
  if [ -n "$JSAUX_EINK_RUNTIME_OVERLAY" ] && [ -d "$JSAUX_EINK_RUNTIME_OVERLAY" ]; then
    rm -rf -- "$JSAUX_EINK_RUNTIME_OVERLAY"
  fi
}
trap cleanup EXIT
trap 'exit 130' HUP INT TERM
perform() {
  if [ "$ACTION" = install ]; then
    [ -f "$PACKAGE_ROOT/SHA256SUMS" ] || return 1
    printf '%s\n' 'Verifying offline payload...'
    (cd -- "$PACKAGE_ROOT" && sha256sum --quiet -c SHA256SUMS) || return 1
    ui_open '正在检查运行环境 / Checking SteamOS runtime'
    [ -f "$PAYLOAD_ROOT/python_compatibility.sh" ] || return 1
    # shellcheck disable=SC1091
    . "$PAYLOAD_ROOT/python_compatibility.sh"
    jsaux_ensure_python_compatibility "$PAYLOAD_ROOT" "$LOG_DIR/JSAUX-E-INK-python-compat.log" || {
      ui_close || true
      return 1
    }
  else
    ui_open '正在准备卸载 / Preparing uninstall'
  fi
  ui_set 25 '等待管理员授权 / Waiting for administrator authorization'
  printf '%s\n' 'Requesting one administrator session for the complete operation.'
  local command_line=()
  if command -v pkexec >/dev/null 2>&1; then
    command_line=(/usr/bin/pkexec)
  elif command -v sudo >/dev/null 2>&1; then
    command_line=(/usr/bin/sudo)
  else
    printf '%s\n' 'Administrator authorization is unavailable.' >&2
    ui_close || true
    return 1
  fi
  # One root worker performs the whole transaction. It never invokes sudo or
  # pkexec itself, so no child operation can open another authentication UI.
  "${command_line[@]}" /usr/bin/python3 -I "$SCRIPT_DIR/installer_privileged.py" \
    "$ACTION" "$(id -u)" "$PACKAGE_ROOT" "$JSAUX_EINK_RUNTIME_OVERLAY" |
  while IFS= read -r line; do
    printf '%s\n' "$line"
    if [[ "$line" == JSAUX_PROGRESS\ * ]]; then
      local rest="${line#JSAUX_PROGRESS }"
      ui_set "${rest%% *}" "${rest#* }"
    fi
  done
  local operation_status="${PIPESTATUS[0]}"
  # perform() runs in the tee pipeline's subshell, which owns the kdialog
  # handle returned by ui_open(). Close it here before the parent shell waits
  # for the user to press Enter in the terminal.
  ui_close || true
  if [ -n "$JSAUX_EINK_RUNTIME_OVERLAY" ] && [ -d "$JSAUX_EINK_RUNTIME_OVERLAY" ]; then
    rm -rf -- "$JSAUX_EINK_RUNTIME_OVERLAY"
    JSAUX_EINK_RUNTIME_OVERLAY=""
  fi
  return "$operation_status"
}
perform 2>&1 | tee "$LOG_FILE"
status=${PIPESTATUS[0]}
cleanup
trap - EXIT
if [ "$status" -eq 0 ]; then
  printf 'JSAUX E-INK %s completed successfully.\n' "$ACTION"
else
  printf 'Operation failed or authorization was cancelled (exit %s). Log: %s\n' "$status" "$LOG_FILE"
fi
if [ -t 0 ]; then
  printf '%s' 'Press Enter to close / 按回车关闭...'
  read -r _ || true
fi
exit "$status"
