#!/usr/bin/env bash
# Runtime compatibility helper for SteamOS Stable/Beta/Preview.
# The payload contains native extensions, so they must match the Python ABI
# used by the current SteamOS image.  We first use the offline payload and
# only bootstrap matching wheels into a temporary overlay when the offline
# probe fails.  The overlay is copied into the staged install tree; the
# extracted package and its SHA256 manifest are never modified.

jsaux_python_probe() {
  local payload_root="$1"
  local python_bin="${JSAUX_EINK_PYTHON:-python3}"
  local overlay_root="${JSAUX_EINK_RUNTIME_OVERLAY:-}"
  local python_path="$payload_root/py_modules:$payload_root"
  if [ -n "$overlay_root" ] && [ -d "$overlay_root/py_modules" ]; then
    python_path="$overlay_root/py_modules:$python_path"
  fi
  PYTHONNOUSERSITE=1 PYTHONPATH="$python_path" "$python_bin" - "$payload_root" <<'PY'
import importlib
import sys
import sysconfig
import tkinter

root = sys.argv[1]
print("Python:", sys.version.replace("\n", " "))
print("Cache tag:", getattr(sys.implementation, "cache_tag", ""))
print("SOABI:", sysconfig.get_config_var("SOABI") or "")
print("Payload:", root)
for name in ("aiohttp", "bleak", "httpx", "dbus_fast", "PIL"):
    module = importlib.import_module(name)
    print("{}: {}".format(name, getattr(module, "__file__", "")))
from PIL import Image, _imaging
print("Pillow:", getattr(Image, "__version__", ""))
print("Pillow core:", getattr(_imaging, "__file__", ""))
print("tkinter: ok")
PY
}

jsaux_ensure_python_compatibility() {
  local payload_root="$1"
  local report_file="$2"
  local python_bin="${JSAUX_EINK_PYTHON:-python3}"
  local probe_output=""
  local probe_status=0
  local pip_log=""
  local cache_tag=""
  local abi_tag=""
  local wheel_root=""
  local overlay_root=""
  local wheel_files=()

  JSAUX_EINK_RUNTIME_OVERLAY=""

  mkdir -p "$(dirname "$report_file")" 2>/dev/null || true
  if probe_output=$(jsaux_python_probe "$payload_root" 2>&1); then
    printf '%s\n' "$probe_output" | tee "$report_file"
    return 0
  else
    probe_status=$?
  fi

  {
    printf 'Offline bundled dependency probe failed (exit %s).\n' "$probe_status"
    printf '%s\n' "$probe_output"
    printf '\nAttempting ABI-matched wheel bootstrap in the extracted package directory.\n'
  } | tee "$report_file"

  cache_tag=$(PYTHONNOUSERSITE=1 "$python_bin" -c 'import sys; print(getattr(sys.implementation, "cache_tag", ""))' 2>/dev/null || true)
  abi_tag="cp${cache_tag#cpython-}"
  overlay_root=$(mktemp -d "${TMPDIR:-/tmp}/jsaux-eink-runtime-${abi_tag}.XXXXXX")
  JSAUX_EINK_RUNTIME_OVERLAY="$overlay_root"
  wheel_root="$payload_root/runtime_wheels/$abi_tag"
  if [ -f "$payload_root/runtime_wheel_extract.py" ] && [ -d "$wheel_root" ]; then
    wheel_files=("$wheel_root"/*.whl)
    if [ -f "${wheel_files[0]}" ]; then
      printf '\nUsing offline ABI-matched wheels for %s.\n' "$abi_tag" | tee -a "$report_file"
      mkdir -p "$overlay_root/py_modules"
      if PYTHONNOUSERSITE=1 "$python_bin" "$payload_root/runtime_wheel_extract.py" \
          "$overlay_root/py_modules" "${wheel_files[@]}" >>"$report_file" 2>&1; then
        if probe_output=$(jsaux_python_probe "$payload_root" 2>&1); then
          printf '\nABI-matched offline dependency probe passed after wheel extraction:\n%s\n' "$probe_output" | tee -a "$report_file"
          return 0
        fi
        printf '\nDependency probe still fails after offline wheel extraction:\n%s\n' "$probe_output" | tee -a "$report_file"
      else
        printf '%s\n' 'Offline wheel extraction failed.' | tee -a "$report_file"
      fi
    fi
  fi

  if ! "$python_bin" -m pip --version >>"$report_file" 2>&1; then
    printf '%s\n' "pip is unavailable for $python_bin; no compatible wheel bootstrap is possible." | tee -a "$report_file"
    return 1
  fi

  pip_log=$(mktemp "${TMPDIR:-/tmp}/jsaux-eink-pip.XXXXXX")
  mkdir -p "$overlay_root/py_modules"
  if ! PYTHONNOUSERSITE=1 "$python_bin" -m pip install \
      --disable-pip-version-check --no-input --no-cache-dir \
      --only-binary=:all: --upgrade --upgrade-strategy eager \
      --target "$overlay_root/py_modules" \
      'Pillow>=11.3,<13' 'aiohttp>=3.12,<4' 'bleak>=0.22,<2' \
      'httpx>=0.28,<1' 'dbus-fast>=2,<3' >"$pip_log" 2>&1; then
    printf '%s\n' 'ABI-matched wheel bootstrap failed:' | tee -a "$report_file"
    cat "$pip_log" | tee -a "$report_file"
    rm -f "$pip_log"
    return 1
  fi
  cat "$pip_log" | tee -a "$report_file"
  rm -f "$pip_log"

  if probe_output=$(jsaux_python_probe "$payload_root" 2>&1); then
    printf '\nABI-matched dependency probe passed after bootstrap:\n%s\n' "$probe_output" | tee -a "$report_file"
    return 0
  fi
  printf '\nDependency probe still fails after bootstrap:\n%s\n' "$probe_output" | tee -a "$report_file"
  rm -rf "$overlay_root"
  JSAUX_EINK_RUNTIME_OVERLAY=""
  return 1
}
