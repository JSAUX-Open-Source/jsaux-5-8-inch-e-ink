#!/bin/sh
set -eu
APPLICATION_DIR="$HOME/.local/share/applications"
rm -f "$APPLICATION_DIR/jsaux-eink.desktop" "$APPLICATION_DIR/jsaux-eink-uninstall.desktop" "$HOME/Desktop/JSAUX E-INK.desktop"
rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/jsaux-eink.svg" "$HOME/.local/share/icons/hicolor/256x256/apps/jsaux-eink.png"
