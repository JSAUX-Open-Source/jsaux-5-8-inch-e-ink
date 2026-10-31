"""Host-side device identity helpers for JSAUX E-INK.

Touchscreen matching is for the host panel input device used by the desktop
UI. BLE panel geometry constants mirror ``eink_display``.

Chip / MCU / flash / PCBA identifiers and firmware flashing are not part of
this module.
"""

from __future__ import annotations

from eink_display import TARGET_COLOR_MODE as TARGET_COLOR_MODE
from eink_display import TARGET_HEIGHT as TARGET_HEIGHT
from eink_display import TARGET_IS_DUAL_SCREEN as TARGET_IS_DUAL_SCREEN
from eink_display import TARGET_WIDTH as TARGET_WIDTH
from eink_display import TOUCHSCREEN_NAMES as TOUCHSCREEN_NAMES

# Aliases used by main.py panel matching
TARGET_SCREEN_W = TARGET_WIDTH
TARGET_SCREEN_H = TARGET_HEIGHT
DISPLAY_QUERY_FACE = 0x02  # DISPLAY_AB

__all__ = [
    "TARGET_COLOR_MODE",
    "TARGET_HEIGHT",
    "TARGET_IS_DUAL_SCREEN",
    "TARGET_WIDTH",
    "TARGET_SCREEN_W",
    "TARGET_SCREEN_H",
    "TOUCHSCREEN_NAMES",
    "DISPLAY_QUERY_FACE",
]
