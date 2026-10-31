#!/bin/sh
set -eu
SCRIPT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec /usr/bin/env bash "$SCRIPT_ROOT/installer_entry.sh" uninstall "$SCRIPT_ROOT"
