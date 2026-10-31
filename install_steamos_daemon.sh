#!/bin/sh
set -eu
SERVICE_NAME="jsaux-eink-daemon.service"
systemctl --user daemon-reload
systemctl --user enable --now "$SERVICE_NAME"
