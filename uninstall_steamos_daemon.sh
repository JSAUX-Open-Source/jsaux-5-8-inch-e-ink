#!/bin/sh
set -eu
SERVICE_NAME="jsaux-eink-daemon.service"
systemctl --user disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
rm -f "$HOME/.config/systemd/user/$SERVICE_NAME"
systemctl --user daemon-reload
