#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import queue
import subprocess
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any, Callable, Optional

from ble_lease import DesktopLease
from daemon_client import AsyncDaemonClient, request_daemon_start
from desktop_controller import (
    NAV_SECTIONS,
    DesktopNavigationState,
    InputGate,
    RawGamepadInput,
    RawPuckInput,
    RawTouchEvent,
    RawTouchInput,
    activate_existing_window,
    center_managed_frame_position,
    center_window_position,
    map_steam_deck_touch_to_screen,
    parse_frame_extents,
    reduce_desktop_navigation,
    select_managed_window_id,
)
from desktop_i18n import detect_system_language, translate
from desktop_preferences import DesktopPreferencesMixin

APP_TITLE = "JSAUX E-INK"
APP_ID = "jsaux-eink"
WINDOW_ICON = "jsaux-eink.png"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("jsaux-eink-desktop")
WINDOW_W = 960
WINDOW_H = 680
MIN_WINDOW_W = WINDOW_W
MIN_WINDOW_H = WINDOW_H
SIDEBAR_W = 275
CONTENT_W = 685
ACTION_BAR_H = 100
CUSTOM_GRID_Y = ACTION_BAR_H + 12
CUSTOM_UPLOAD_Y = ACTION_BAR_H + (WINDOW_H - ACTION_BAR_H - 48) // 2
MODULE_CARD_W = 155
MODULE_CARD_H = 141
MODULE_CARD_RADIUS = 12
MODULE_CARD_X = 74
MODULE_CARD_Y = 85
MODULE_CARD_GAP_X = 37
MODULE_CARD_GAP_Y = 43
CONTROL_ROW_X = 130
CONTROL_ROW_RIGHT = 130
CONTROL_ICON_SIZE = 36
TOGGLE_W = 72
TOGGLE_H = 35
INTERVAL_TOGGLE_FONT = ("Noto Sans CJK SC", -10, "normal")
# Effective device-row geometry used by the local desktop application.
CANDIDATE_SWITCH_TRACK_W = 36
CANDIDATE_SWITCH_TRACK_H = 21
CANDIDATE_SWITCH_PADDING = 2
CANDIDATE_SWITCH_KNOB = 17
CANDIDATE_SWITCH_RIGHT_INSET = 36
CANDIDATE_STATUS_GAP = 6
CONNECTION_ON_ANIMATION_MS = 800
CONNECTION_SPINNER_FRAME_MS = 80
CONNECTION_SPINNER_STEP_DEGREES = 36.0
CONNECTION_HEADER_H = 76
CONNECTION_CANDIDATE_H = 72
ASSET_CARD_W = 215
ASSET_CARD_H = 166
EXIT_OVERLAY_W = 480
EXIT_OVERLAY_H = 230
PURPLE = "#7B00FF"
PURPLE_BRIGHT = "#8900FF"
RED = "#D53B3B"
BACKGROUND = "#0A1118"
SIDEBAR_BG = "#090F16"
CARD_BG = "#0D141C"
NAV_DIVIDER = "#202936"
BOTTOM_DIVIDER = "#26313D"
CARD_BORDER = "#2C3540"
CONTROL_DIVIDER = "#39414B"
BUTTON_BG = "#434A55"
FOCUS_ROW_BG = "#252B33"
MUTED = "#969DA7"
MODULE_MUTED = "#89929B"
CONTROL_MUTED = "#68747E"
SUBTLE = "#7E8794"
WHITE = "#FFFFFF"
PHOTO_FRAME_INTERVAL_VALUES = list(range(1, 61))
MODULE_SWITCH_INTERVAL_VALUES = list(range(5, 61, 5))
CURRENT_FW = "V1.2"
LATEST_FW = "V1.2"
PRODUCT_NAME = "JSAUX E-INK"
GAME_TIME_MODE_TITLES = {
    k: v[0]
    for k, v in {
        "ar": "وضع العرض",
        "pt-br": "MODO DE EXIBIÇÃO",
        "bg": "РЕЖИМ НА ЕКРАНА",
        "cs": "REŽIM ZOBRAZENÍ",
        "da": "VISNINGSTIL",
        "nl": "WEERGAVEMODUS",
        "en": "DISPLAY MODE",
        "fi": "NÄYTTÖTILA",
        "fr": "MODE D’AFFICHAGE",
        "de": "ANZEIGEMODUS",
        "el": "ΛΕΙΤΟΥΡΓΙΑ ΠΡΟΒΟΛΗΣ",
        "hu": "MEGJELENÍTÉSI MÓD",
        "id": "MODE TAMPILAN",
        "it": "MODALITÀ DI VISUALIZZAZIONE",
        "ja": "表示モード",
        "ko": "표시 모드",
        "es-419": "MODO DE VISUALIZACIÓN",
        "ms": "MOD PAPARAN",
        "no": "VISNINGSMODUS",
        "pl": "TRYB WYŚWIETLANIA",
        "pt": "MODO DE EXIBIÇÃO",
        "ro": "MOD AFIȘARE",
        "ru": "РЕЖИМ ОТОБРАЖЕНИЯ",
        "zh": "显示模式",
        "es": "MODO DE VISUALIZACIÓN",
        "sv": "VISNINGSLÄGE",
        "zh-tw": "顯示模式",
        "th": "โหมดการแสดงผล",
        "tr": "GÖRÜNTÜLEME MODU",
        "uk": "РЕЖИМ ВІДОБРАЖЕННЯ",
        "vi": "CHẾ ĐỘ HIỂN THỊ",
    }.items()
}
GAME_TIME_MODE_LABELS = {
    "ar": {"time": "الوقت", "poster": "الملصق", "auto": "تلقائي"},
    "pt-br": {"time": "Hora", "poster": "Pôster", "auto": "Automático"},
    "bg": {"time": "Време", "poster": "Плакат", "auto": "Автоматично"},
    "cs": {"time": "Čas", "poster": "Plakát", "auto": "Automaticky"},
    "da": {"time": "Tid", "poster": "Plakat", "auto": "Automatisk"},
    "nl": {"time": "Tijd", "poster": "Poster", "auto": "Automatisch"},
    "en": {"time": "Time", "poster": "Poster", "auto": "Auto"},
    "fi": {"time": "Aika", "poster": "Juliste", "auto": "Automaattinen"},
    "fr": {"time": "Heure", "poster": "Affiche", "auto": "Auto"},
    "de": {"time": "Zeit", "poster": "Poster", "auto": "Auto"},
    "el": {"time": "Ώρα", "poster": "Αφίσα", "auto": "Αυτόματο"},
    "hu": {"time": "Idő", "poster": "Poszter", "auto": "Automatikus"},
    "id": {"time": "Waktu", "poster": "Poster", "auto": "Otomatis"},
    "it": {"time": "Ora", "poster": "Poster", "auto": "Auto"},
    "ja": {"time": "時刻", "poster": "ポスター", "auto": "自動"},
    "ko": {"time": "시간", "poster": "포스터", "auto": "자동"},
    "es-419": {"time": "Hora", "poster": "Póster", "auto": "Automático"},
    "ms": {"time": "Masa", "poster": "Poster", "auto": "Automatik"},
    "no": {"time": "Tid", "poster": "Plakat", "auto": "Automatisk"},
    "pl": {"time": "Czas", "poster": "Plakat", "auto": "Automatycznie"},
    "pt": {"time": "Hora", "poster": "Pôster", "auto": "Automático"},
    "ro": {"time": "Ora", "poster": "Poster", "auto": "Automat"},
    "ru": {"time": "Время", "poster": "Постер", "auto": "Авто"},
    "zh": {"time": "时间", "poster": "海报", "auto": "自动"},
    "es": {"time": "Hora", "poster": "Póster", "auto": "Automático"},
    "sv": {"time": "Tid", "poster": "Affisch", "auto": "Automatiskt"},
    "zh-tw": {"time": "時間", "poster": "海報", "auto": "自動"},
    "th": {"time": "เวลา", "poster": "โปสเตอร์", "auto": "อัตโนมัติ"},
    "tr": {"time": "Zaman", "poster": "Poster", "auto": "Otomatik"},
    "uk": {"time": "Час", "poster": "Постер", "auto": "Авто"},
    "vi": {"time": "Thời gian", "poster": "Áp phích", "auto": "Tự động"},
}
MODULES = [
    ("module_composite", 0, "carousel"),
    ("module_agent", 7, "agent"),
    ("module_clock", 4, "clock"),
    ("module_weather", 3, "weather"),
    ("module_game_time", 1, "timeline"),
    ("module_performance", 2, "deck_status"),
    ("module_calendar", 5, "calendar"),
    ("module_custom", 6, "custom"),
]

# The desktop UI is authored on a 960x680 design surface. Keep the design
# values in one place and derive live metrics from the client area so a user
# resize scales the complete UI instead of leaving a fixed-size island inside
# a larger window.
DESIGN_WINDOW_W = WINDOW_W
DESIGN_WINDOW_H = WINDOW_H
UI_SCALE_X = 1.0
UI_SCALE_Y = 1.0
UI_SCALE = 1.0
_LAYOUT_X = (
    "WINDOW_W",
    "SIDEBAR_W",
    "CONTENT_W",
    "CUSTOM_GRID_Y",
    "MODULE_CARD_W",
    "MODULE_CARD_X",
    "MODULE_CARD_GAP_X",
    "CONTROL_ROW_X",
    "CONTROL_ROW_RIGHT",
    "CONTROL_ICON_SIZE",
    "TOGGLE_W",
    "CANDIDATE_SWITCH_TRACK_W",
    "CANDIDATE_SWITCH_PADDING",
    "CANDIDATE_SWITCH_KNOB",
    "CANDIDATE_SWITCH_RIGHT_INSET",
    "CANDIDATE_STATUS_GAP",
    "CONNECTION_HEADER_H",
    "ASSET_CARD_W",
    "EXIT_OVERLAY_W",
)
_LAYOUT_Y = (
    "WINDOW_H",
    "ACTION_BAR_H",
    "CUSTOM_GRID_Y",
    "CUSTOM_UPLOAD_Y",
    "MODULE_CARD_H",
    "MODULE_CARD_Y",
    "MODULE_CARD_GAP_Y",
    "CONTROL_ICON_SIZE",
    "TOGGLE_H",
    "CANDIDATE_SWITCH_TRACK_H",
    "CONNECTION_HEADER_H",
    "CONNECTION_CANDIDATE_H",
    "ASSET_CARD_H",
    "EXIT_OVERLAY_H",
)
_LAYOUT_UNIFORM = ("MODULE_CARD_RADIUS",)
_BASE_LAYOUT = {name: globals()[name] for name in set(_LAYOUT_X + _LAYOUT_Y + _LAYOUT_UNIFORM)}


def _sx(value: float) -> int:
    return max(1, round(float(value) * UI_SCALE_X))


def _sy(value: float) -> int:
    return max(1, round(float(value) * UI_SCALE_Y))


def _scaled_font(size: int, weight: str = "normal") -> tuple[str, int, str]:
    return ("Noto Sans CJK SC", -max(1, round(size * UI_SCALE)), weight)


def _set_layout_scale(scale_x: float, scale_y: float) -> None:
    """Update the live design metrics used by all Tk placements and widgets."""
    global UI_SCALE_X, UI_SCALE_Y, UI_SCALE, INTERVAL_TOGGLE_FONT
    UI_SCALE_X = max(1.0, float(scale_x))
    UI_SCALE_Y = max(1.0, float(scale_y))
    UI_SCALE = min(UI_SCALE_X, UI_SCALE_Y)
    for name in _LAYOUT_X:
        globals()[name] = max(1, round(_BASE_LAYOUT[name] * UI_SCALE_X))
    for name in _LAYOUT_Y:
        globals()[name] = max(1, round(_BASE_LAYOUT[name] * UI_SCALE_Y))
    for name in _LAYOUT_UNIFORM:
        globals()[name] = max(1, round(_BASE_LAYOUT[name] * UI_SCALE))
    INTERVAL_TOGGLE_FONT = _scaled_font(10)


def _draw_desktop_icon(
    canvas: tk.Canvas,
    name: str,
    cx: float,
    cy: float,
    size: float,
    color: str,
    width: float = 2.0,
) -> None:
    scale = size / 24.0

    def point(x: float, y: float) -> tuple[float, float]:
        return cx + (x - 12.0) * scale, cy + (y - 12.0) * scale

    def line(*coords: float, **kwargs: Any) -> None:
        mapped: list[float] = []
        for index in range(0, len(coords), 2):
            px, py = point(coords[index], coords[index + 1])
            mapped.extend((px, py))
        canvas.create_line(
            *mapped,
            fill=color,
            width=width,
            capstyle=tk.ROUND,
            joinstyle=tk.ROUND,
            tags="icon",
            **kwargs,
        )

    def oval(x1: float, y1: float, x2: float, y2: float, **kwargs: Any) -> None:
        left, top = point(x1, y1)
        right, bottom = point(x2, y2)
        canvas.create_oval(
            left,
            top,
            right,
            bottom,
            outline=color,
            width=width,
            tags="icon",
            **kwargs,
        )

    def rounded_rect(x1: float, y1: float, x2: float, y2: float, radius: float = 2.0) -> None:
        left, top = point(x1, y1)
        right, bottom = point(x2, y2)
        canvas.create_polygon(
            RoundedModuleCard._rounded_points(left, top, right, bottom, radius * scale),
            fill="",
            outline=color,
            width=width,
            smooth=True,
            splinesteps=24,
            tags="icon",
        )

    if name == "carousel":
        rounded_rect(3, 3, 10, 21, 1.7)
        rounded_rect(13, 3, 21, 11, 1.7)
        rounded_rect(13, 14, 21, 21, 1.7)
    elif name == "clock":
        oval(3, 3, 21, 21)
        line(12, 7, 12, 12, 16, 15)
    elif name == "weather":
        oval(6, 4, 15, 13)
        for ray in (
            (10.5, 0.5, 10.5, 2.5),
            (5.0, 2.0, 6.4, 3.4),
            (15.0, 2.0, 13.6, 3.4),
            (1.5, 5.8, 3.5, 5.8),
            (17.5, 5.8, 19.5, 5.8),
        ):
            line(*ray)
        line(5, 19, 18, 19)
        line(5, 19, 3.8, 18.5, 3, 17, 3, 15.2, 4.2, 13.8, 6, 13.5)
        line(6, 13.5, 7.2, 10.7, 10, 9.7, 12.8, 10.7, 14, 13.2)
        line(14, 13.2, 16.2, 13, 18.2, 14.4, 18.5, 16.5, 18, 18, 17, 19)
    elif name == "timeline":
        oval(2, 2, 15, 15)
        line(8.5, 5, 8.5, 9, 5.8, 11)
        rounded_rect(12, 10, 21, 22, 1.6)
        line(15, 14, 18, 14)
        line(15, 18, 18, 18)
    elif name == "deck_status":
        oval(3, 3, 21, 21)
        line(5.5, 16.5, 7.5, 10.5, 12, 8.5, 16.5, 10.5, 18.5, 16.5)
        line(12, 12, 12, 6)
        oval(10.5, 10.5, 13.5, 13.5)
    elif name == "calendar":
        rounded_rect(3, 5, 21, 21, 1.8)
        line(7, 2, 7, 8)
        line(17, 2, 17, 8)
        line(3, 10, 21, 10)
        line(7, 14, 12, 14)
        line(7, 18, 17, 18)
    elif name == "custom":
        rounded_rect(3, 3, 21, 21, 1.8)
        oval(6, 6, 9, 9)
        line(5, 18, 9.5, 13, 13, 16, 16, 12.5, 20, 18)
    elif name == "agent":
        rounded_rect(4, 5, 20, 19, 3)
        oval(7, 9, 10, 12)
        oval(14, 9, 17, 12)
        line(8, 15, 16, 15)
        line(12, 5, 12, 3)
    elif name == "power":
        line(12, 2, 12, 11)
        left, top = point(3.5, 4.5)
        right, bottom = point(20.5, 21.5)
        canvas.create_arc(
            left,
            top,
            right,
            bottom,
            start=135,
            extent=270,
            style=tk.ARC,
            outline=color,
            width=width,
            tags="icon",
        )
    elif name == "brightness":
        oval(8.5, 8.5, 15.5, 15.5)
        for ray in (
            (12, 1, 12, 4),
            (12, 20, 12, 23),
            (1, 12, 4, 12),
            (20, 12, 23, 12),
            (4.2, 4.2, 6.3, 6.3),
            (17.7, 17.7, 19.8, 19.8),
            (19.8, 4.2, 17.7, 6.3),
            (6.3, 17.7, 4.2, 19.8),
        ):
            line(*ray)
    elif name == "refresh":
        line(19.5, 8, 19.5, 3.5, 15, 3.5)
        line(19, 4.5, 16.5, 2.5, 12, 2.5, 7.8, 4.5, 5.2, 8)
        line(4.5, 16, 4.5, 20.5, 9, 20.5)
        line(5, 19.5, 7.5, 21.5, 12, 21.5, 16.2, 19.5, 18.8, 16)


def _normalize_eink_address(value: Any) -> str:
    return str(value or "").strip().upper()


def merge_eink_candidates(
    candidates: list[dict[str, Any]],
    *,
    connected_address: str = "",
    connected: bool = False,
) -> list[dict[str, Any]]:
    current_address = _normalize_eink_address(connected_address) if connected else ""
    merged: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        name = str(candidate.get("name") or "").strip()
        address = _normalize_eink_address(candidate.get("address"))
        if not address or PRODUCT_NAME.lower() not in name.lower():
            continue
        try:
            signal_strength = (
                int(candidate.get("rssi")) if candidate.get("rssi") is not None else None
            )
        except (TypeError, ValueError):
            signal_strength = None
        raw_battery = candidate.get("battery")
        try:
            battery = max(0, min(100, int(raw_battery))) if raw_battery is not None else None
        except (TypeError, ValueError):
            battery = None
        item = {"name": name, "address": address, "rssi": signal_strength, "battery": battery}
        current = merged.get(address)
        if current is None or (
            signal_strength is not None
            and (current.get("rssi") is None or signal_strength > int(current["rssi"]))
        ):
            if current is not None and item.get("battery") is None:
                item["battery"] = current.get("battery")
            merged[address] = item
        elif current.get("battery") is None and item.get("battery") is not None:
            current["battery"] = item["battery"]
    if current_address:
        connected_item = merged.get(
            current_address, {"name": PRODUCT_NAME, "address": current_address, "rssi": None}
        )
        connected_item["name"] = str(connected_item.get("name") or PRODUCT_NAME)
        merged[current_address] = connected_item
    return sorted(
        merged.values(),
        key=lambda item: (
            0 if item["address"] == current_address else 1,
            0 if item.get("rssi") is not None else 1,
            -int(item["rssi"]) if item.get("rssi") is not None else 0,
            str(item["name"]).lower(),
            str(item["address"]),
        ),
    )


def resolve_shared_settings_dir(plugin_root: Path) -> Path:
    override = os.environ.get("JSAUX_EINK_SETTINGS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / "homebrew" / "settings" / "jsaux-eink-display"


class DotSlider(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        from_: float,
        to: float,
        value: float,
        step: float,
        command: Callable[[float], None],
        enabled: bool = True,
        segmented: bool = False,
        segment_count: int = 0,
    ) -> None:
        super().__init__(
            parent,
            bg=str(parent.cget("bg")),
            bd=0,
            highlightbackground=PURPLE,
            highlightcolor=WHITE,
            highlightthickness=0,
            cursor="hand2" if enabled else "arrow",
            state="normal" if enabled else "disabled",
        )
        self._from = from_
        self._to = to
        self._step = step
        self._command = command
        self._enabled = bool(enabled)
        self._segmented = segmented
        self._segment_count = segment_count
        self._focus_background = str(parent.cget("bg"))
        self._value = from_
        self._committed_value = from_
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", self._begin_pointer)
        self.bind("<B1-Motion>", self._drag_pointer)
        self.bind("<ButtonRelease-1>", self._end_pointer)
        self.set(value, notify=False)
        self._committed_value = self._value

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.configure(
            state="normal" if self._enabled else "disabled",
            cursor="hand2" if self._enabled else "arrow",
        )

    def set_focus_background(self, background: str) -> None:
        """Update only the focus background item; never rebuild the slider."""
        self._focus_background = str(background)
        if not self.winfo_exists():
            return
        try:
            self.itemconfigure("focus-background", fill=self._focus_background)
        except tk.TclError:
            pass

    def set(self, value: float, *, notify: bool = False) -> None:
        clamped = max(self._from, min(self._to, float(value)))
        steps = round((clamped - self._from) / self._step)
        self._value = max(self._from, min(self._to, self._from + steps * self._step))
        self._draw()
        if notify and self._command is not None and self._value != self._committed_value:
            self._committed_value = self._value
            self._command(self._value)

    def _track_bounds(self) -> tuple[float, float, float]:
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        return 14.0, max(15.0, float(width - 14)), height / 2.0

    def _value_x(self) -> float:
        left, right, _center_y = self._track_bounds()
        ratio = (self._value - self._from) / max(1.0, self._to - self._from)
        return left + (right - left) * ratio

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("focus-background")
        self.delete("slider")
        left, right, center_y = self._track_bounds()
        self.create_rectangle(
            0,
            0,
            max(1, self.winfo_width()),
            max(1, self.winfo_height()),
            fill=self._focus_background,
            outline="",
            tags="focus-background",
        )
        track_width = _sx(10)
        self.create_line(
            left,
            center_y,
            right,
            center_y,
            fill=BUTTON_BG,
            width=track_width,
            capstyle=tk.ROUND,
            tags="slider",
        )
        if self._value_x() > left:
            self.create_line(
                left,
                center_y,
                self._value_x(),
                center_y,
                fill=PURPLE,
                width=track_width,
                capstyle=tk.ROUND,
                tags="slider",
            )
        if self._segmented and self._segment_count > 1:
            spacing = (right - left) / (self._segment_count - 1)
            for index in range(1, self._segment_count - 1):
                tick_x = left + index * spacing
                self.create_line(
                    tick_x,
                    center_y - track_width / 2,
                    tick_x,
                    center_y + track_width / 2,
                    fill=BACKGROUND,
                    width=1,
                    tags="slider",
                )
        dot_x = self._value_x()
        radius = _sx(17)
        self.create_oval(
            dot_x - radius,
            center_y - radius,
            dot_x + radius,
            center_y + radius,
            fill=WHITE,
            outline=WHITE,
            width=0,
            tags="slider",
        )

    def _set_from_x(self, x: float, *, notify: bool) -> None:
        left, right, _center_y = self._track_bounds()
        ratio = max(0.0, min(1.0, (x - left) / max(1.0, right - left)))
        self.set(self._from + (self._to - self._from) * ratio, notify=notify)

    def _begin_pointer(self, event: tk.Event) -> None:
        if not self._enabled:
            return
        self.focus_set()
        self._set_from_x(event.x, notify=False)

    def _drag_pointer(self, event: tk.Event) -> None:
        if not self._enabled:
            return
        self._set_from_x(event.x, notify=False)

    def _end_pointer(self, event: tk.Event) -> None:
        if not self._enabled:
            return
        self._set_from_x(event.x, notify=True)


class CapsuleToggle(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        enabled: bool,
        busy: bool,
        spinning: bool = False,
        status_font: tuple[str, int, str] = ("Noto Sans CJK SC", -10, "bold"),
        command: Callable[[], None],
    ) -> None:
        super().__init__(
            parent,
            bg=str(parent.cget("bg")),
            bd=0,
            highlightthickness=0,
            cursor="arrow" if busy else "hand2",
            takefocus=True,
            state="disabled" if busy else "normal",
        )
        self._enabled = enabled
        self._busy = busy
        self._spinning = spinning
        self._status_font = status_font
        self._command = command
        self._controller_focused = False
        self._focus_background = str(parent.cget("bg"))
        self._spinner_angle = 0.0
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", lambda _event: self.invoke())

    def invoke(self) -> None:
        if str(self.cget("state")) == "disabled":
            return
        self.focus_set()
        self._command()

    def set_controller_focus(self, focused: bool) -> None:
        self._controller_focused = focused
        self._draw()

    def set_focus_background(self, background: str) -> None:
        """Update only the focus background item; never rebuild the toggle."""
        self._focus_background = str(background)
        if not self.winfo_exists():
            return
        try:
            self.itemconfigure("focus-background", fill=self._focus_background)
        except tk.TclError:
            pass

    def set_state(self, *, enabled: bool, busy: bool = False, spinning: bool = False) -> None:
        self._enabled = bool(enabled)
        self._busy = bool(busy)
        self._spinning = bool(spinning)
        self.configure(
            state="disabled" if self._busy else "normal", cursor="arrow" if self._busy else "hand2"
        )
        self._draw()

    def set_spinner_angle(self, angle: float) -> None:
        self._spinner_angle = float(angle) % 360.0
        if self._spinning:
            self._draw()

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("focus-background")
        self.delete("toggle")
        width = max(TOGGLE_W, self.winfo_width())
        height = max(TOGGLE_H, self.winfo_height())
        self.create_rectangle(
            0,
            0,
            width,
            height,
            fill=self._focus_background,
            outline="",
            tags="focus-background",
        )
        center_y = height / 2
        track_left = width - CANDIDATE_SWITCH_TRACK_W
        track_top = (height - CANDIDATE_SWITCH_TRACK_H) / 2
        track_right = width
        track_radius = CANDIDATE_SWITCH_TRACK_H / 2
        track_color = PURPLE if self._enabled or self._spinning else BUTTON_BG
        self.create_line(
            track_left + track_radius,
            center_y,
            track_right - track_radius,
            center_y,
            fill=track_color,
            width=CANDIDATE_SWITCH_TRACK_H,
            capstyle=tk.ROUND,
            tags="toggle",
        )
        if self._spinning:
            spinner_radius = 6.0
            spinner_x = track_left + CANDIDATE_SWITCH_TRACK_W / 2
            for index in range(8):
                angle = math.radians(self._spinner_angle + index * 45.0)
                inner = spinner_radius * 0.48
                brightness = 96 + index * 20
                color = f"#{brightness:02x}{brightness:02x}{brightness:02x}"
                self.create_line(
                    spinner_x + math.cos(angle) * inner,
                    center_y + math.sin(angle) * inner,
                    spinner_x + math.cos(angle) * spinner_radius,
                    center_y + math.sin(angle) * spinner_radius,
                    fill=color,
                    width=_sx(2),
                    capstyle=tk.ROUND,
                    tags="toggle",
                )
        else:
            knob_left = (
                track_right - CANDIDATE_SWITCH_PADDING - CANDIDATE_SWITCH_KNOB
                if self._enabled
                else track_left + CANDIDATE_SWITCH_PADDING
            )
            knob_top = track_top + CANDIDATE_SWITCH_PADDING
            self.create_oval(
                knob_left,
                knob_top,
                knob_left + CANDIDATE_SWITCH_KNOB,
                knob_top + CANDIDATE_SWITCH_KNOB,
                fill=WHITE,
                outline=WHITE,
                width=0,
                tags="toggle",
            )
        self.create_text(
            track_left - CANDIDATE_STATUS_GAP,
            center_y,
            text="ON" if self._enabled else "OFF",
            fill=WHITE,
            anchor="e",
            font=self._status_font,
            tags="toggle",
        )


class ConnectionStatusIndicator(tk.Canvas):
    def __init__(self, parent: tk.Misc, *, connected: bool, label: str, background: str) -> None:
        super().__init__(parent, bg=background, bd=0, highlightthickness=0, takefocus=0)
        self._connected = connected
        self._label = label
        self.bind("<Configure>", lambda _event: self._draw())

    def _draw(self) -> None:
        self.delete("status")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        color = PURPLE if self._connected else CONTROL_MUTED
        dot_size = _sx(12)
        dot_x = _sx(4)
        dot_y = (height - dot_size) / 2
        self.create_oval(
            dot_x,
            dot_y,
            dot_x + dot_size,
            dot_y + dot_size,
            fill=color,
            outline=color,
            tags="status",
        )
        self.create_text(
            dot_x + dot_size + _sx(9),
            height / 2,
            text=self._label,
            fill=WHITE,
            anchor="w",
            font=self._fit_label_font(width - dot_size - 13),
            tags="status",
        )
        self.configure(width=width, height=height)

    def _fit_label_font(self, available_width: int) -> tuple[str, int, str]:
        for size in range(12, 9, -1):
            font = tkfont.Font(
                root=self,
                family="Noto Sans CJK SC",
                size=-max(1, round(size * UI_SCALE)),
                weight="normal",
            )
            if font.measure(self._label) <= available_width:
                return _scaled_font(size)
        return _scaled_font(9)


class ConnectionSignalIndicator(tk.Canvas):
    def __init__(self, parent: tk.Misc, *, rssi: Optional[int], background: str) -> None:
        super().__init__(parent, bg=background, bd=0, highlightthickness=0, takefocus=0)
        self._rssi = rssi
        self.bind("<Configure>", lambda _event: self._draw())

    @staticmethod
    def _bar_count(rssi: Optional[int]) -> int:
        if rssi is None:
            return 0
        if rssi >= -50:
            return 4
        if rssi >= -60:
            return 3
        if rssi >= -70:
            return 2
        return 1

    def _draw(self) -> None:
        self.delete("signal")
        baseline = _sy(43)
        active_count = self._bar_count(self._rssi)
        for index in range(4):
            bar_height = _sy(7 + index * 6)
            left = _sx(6 + index * 8)
            color = PURPLE if index < active_count else CONTROL_DIVIDER
            self.create_rectangle(
                left,
                baseline - bar_height,
                left + _sx(5),
                baseline,
                fill=color,
                outline=color,
                tags="signal",
            )
        label = "-- dBm" if self._rssi is None else f"{int(self._rssi)} dBm"
        self.create_text(
            max(1, self.winfo_width()) / 2,
            _sy(59),
            text=label,
            fill=SUBTLE,
            anchor="center",
            font=_scaled_font(8),
            tags="signal",
        )


class ConnectionHeaderButton(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        icon: str,
        command: Callable[[], None],
        background: str,
        spinning: bool = False,
    ) -> None:
        super().__init__(parent, bg=background, bd=0, highlightthickness=0, takefocus=1)
        self._icon = icon
        self._command = command
        self._spinning = spinning
        self._spinner_angle = 0.0
        self._controller_focused = False
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", lambda _event: self.invoke())

    def invoke(self) -> None:
        if str(self.cget("state")) != "disabled":
            self._command()

    def set_controller_focus(self, focused: bool) -> None:
        self._controller_focused = focused
        self._draw()

    def set_spinner_angle(self, angle: float) -> None:
        self._spinner_angle = float(angle) % 360.0
        if self._spinning:
            self._draw()

    def _draw(self) -> None:
        self.delete("connection-header")
        # The shared icon renderer uses the generic "icon" tag. Remove it
        # before redrawing so focus/spinner updates cannot leave a gray icon
        # underneath the current purple icon.
        self.delete("icon")
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        color = PURPLE if self._controller_focused else WHITE
        if self._controller_focused:
            self.create_oval(
                1,
                1,
                width - 1,
                height - 1,
                outline=PURPLE,
                width=2,
                tags="connection-header",
            )
        if self._spinning:
            center_x = width / 2
            center_y = height / 2
            radius = min(width, height) * 0.30
            for index in range(8):
                angle = math.radians(self._spinner_angle + index * 45.0)
                inner = radius * 0.48
                brightness = 96 + index * 20
                segment_color = f"#{brightness:02x}{brightness:02x}{brightness:02x}"
                self.create_line(
                    center_x + math.cos(angle) * inner,
                    center_y + math.sin(angle) * inner,
                    center_x + math.cos(angle) * radius,
                    center_y + math.sin(angle) * radius,
                    fill=segment_color,
                    width=2,
                    capstyle=tk.ROUND,
                    tags="connection-header",
                )
            return
        if self._icon == "back":
            center_y = height / 2
            self.create_line(
                width * 0.64,
                height * 0.25,
                width * 0.36,
                center_y,
                width * 0.64,
                height * 0.75,
                fill=color,
                width=_sx(2.6),
                capstyle=tk.ROUND,
                joinstyle=tk.ROUND,
                tags="connection-header",
            )
        else:
            _draw_desktop_icon(
                self, "refresh", width / 2, height / 2, min(width, height) * 0.72, color, _sx(2.2)
            )


class RoundedModuleCard(tk.Canvas):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        mode: str,
        label: str,
        command: Callable[[], None],
    ) -> None:
        super().__init__(
            parent,
            bg=BACKGROUND,
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            takefocus=True,
        )
        self._mode = mode
        self._label = label
        self._command = command
        self._hovered = False
        self._controller_focused = False
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Enter>", lambda _event: self._set_hovered(True))
        self.bind("<Leave>", lambda _event: self._set_hovered(False))
        self.bind("<Button-1>", lambda _event: self.invoke())

    @staticmethod
    def _rounded_points(x1: float, y1: float, x2: float, y2: float, radius: float) -> list[float]:
        return [
            x1 + radius,
            y1,
            x2 - radius,
            y1,
            x2 - radius,
            y1,
            x2,
            y1,
            x2,
            y1 + radius,
            x2,
            y2 - radius,
            x2,
            y2 - radius,
            x2,
            y2,
            x2 - radius,
            y2,
            x1 + radius,
            y2,
            x1 + radius,
            y2,
            x1,
            y2,
            x1,
            y2 - radius,
            x1,
            y1 + radius,
            x1,
            y1 + radius,
            x1,
            y1,
            x1 + radius,
            y1,
        ]

    def invoke(self) -> None:
        self._command()

    def set_controller_focus(self, focused: bool) -> None:
        self._controller_focused = focused
        self._draw()

    def _set_hovered(self, hovered: bool) -> None:
        self._hovered = hovered
        self._draw()

    def _draw(self) -> None:
        if not self.winfo_exists():
            return
        self.delete("card")
        width = max(2, self.winfo_width())
        height = max(2, self.winfo_height())
        fill_color = PURPLE if self._controller_focused else CARD_BG
        self.create_polygon(
            self._rounded_points(0, 0, width - 1, height - 1, MODULE_CARD_RADIUS),
            fill=fill_color if self._controller_focused else CARD_BORDER,
            outline="",
            smooth=True,
            splinesteps=36,
            tags="card",
        )
        if not self._controller_focused:
            inset = 1
            self.create_polygon(
                self._rounded_points(
                    inset,
                    inset,
                    width - 1 - inset,
                    height - 1 - inset,
                    max(2, MODULE_CARD_RADIUS - inset),
                ),
                fill=fill_color,
                outline="",
                smooth=True,
                splinesteps=36,
                tags="card",
            )
        icon_color = WHITE if self._controller_focused else MODULE_MUTED
        _draw_desktop_icon(
            self,
            self._mode,
            width / 2,
            height * 0.36,
            _sx(44.0),
            icon_color,
            _sx(3.0),
        )
        self.create_text(
            width / 2,
            height * 0.75,
            text=self._label,
            fill=WHITE,
            font=self._fit_label_font(width - 18),
            width=max(40, width - 18),
            justify="center",
            tags="card",
        )

    def _fit_label_font(self, available_width: int) -> tuple[str, int, str]:
        for size in range(13, 8, -1):
            font = tkfont.Font(
                root=self,
                family="Noto Sans CJK SC",
                size=-max(1, round(size * UI_SCALE)),
                weight="bold",
            )
            if font.measure(self._label) <= available_width:
                return _scaled_font(size, "bold")
        return _scaled_font(9, "bold")


class QueueLogger:
    def __init__(self, sink: queue.Queue[str]) -> None:
        self._sink = sink

    def _log(self, level: str, message: str, *args: Any) -> None:
        self._sink.put(f"[{level}] {message % args if args else message}")

    def info(self, message: str, *args: Any) -> None:
        self._log("INFO", message, *args)

    def warning(self, message: str, *args: Any) -> None:
        self._log("WARN", message, *args)

    def error(self, message: str, *args: Any) -> None:
        self._log("ERROR", message, *args)


class DesktopAlreadyRunningError(RuntimeError):
    pass


class DesktopBackend:
    def __init__(self, plugin_root: Path, *, language: str = "en") -> None:
        self.plugin_root = plugin_root
        self.language = language
        self.settings_dir = resolve_shared_settings_dir(plugin_root)
        self.settings_dir.mkdir(parents=True, exist_ok=True)
        self.event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.log_queue: queue.Queue[str] = queue.Queue()
        self._logger = QueueLogger(self.log_queue)
        self._lease = DesktopLease()
        if not self._lease.acquire():
            raise DesktopAlreadyRunningError(self._t("already_running"))
        request_daemon_start()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        try:
            self.plugin = AsyncDaemonClient()
            self._call(self._initialize_client(), timeout=15)
        except Exception:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=2)
            self._lease.release()
            raise

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _t(self, key: str, **values: object) -> str:
        return translate(key, getattr(self, "language", "en"), **values)

    async def _initialize_client(self) -> None:
        await self.plugin.wait_until_ready(timeout=15)
        await self.plugin.start_events(self._receive_event)

    async def _receive_event(self, event: str, payload: Any = None) -> None:
        self.event_queue.put((event, payload))

    def _call(self, coro, timeout: float = 120):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except TimeoutError as error:
            if not future.done():
                future.cancel()
            raise TimeoutError(self._t("operation_timeout", seconds=timeout)) from error

    def shutdown(self) -> None:
        try:
            self._call(self.plugin.close(), timeout=10)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=2)
        self._lease.release()

    def poll_events(self) -> list[tuple[str, Any]]:
        result: list[tuple[str, Any]] = []
        while True:
            try:
                result.append(self.event_queue.get_nowait())
            except queue.Empty:
                return result

    def get_status(self) -> dict[str, Any]:
        return self._call(self.plugin.get_status())

    def get_control_state(self) -> dict[str, Any]:
        return self._call(self.plugin.get_control_state())

    def get_display_options(self) -> dict[str, Any]:
        return self._call(self.plugin.get_display_options())

    def get_weather_location_options(
        self,
        country_code: str = "",
        query: str = "",
        offset: int = 0,
        limit: int = 40,
        language: str = "en",
    ) -> dict:
        return self._call(
            self.plugin.get_weather_location_options(country_code, query, offset, limit, language)
        )

    def search_weather_locations(
        self, query: str, language: str = "en", country_code: str = ""
    ) -> list:
        return self._call(
            self.plugin.search_weather_locations(query, language, country_code), timeout=20
        )

    def get_settings(self) -> dict[str, Any]:
        return self._call(self.plugin.get_settings())

    def get_agent_status(self) -> dict[str, Any]:
        return self._call(self.plugin.get_agent_status(), timeout=10)

    def set_agent_status(self, event: dict[str, Any]) -> dict[str, Any]:
        return self._call(self.plugin.set_agent_status(event), timeout=30)

    def clear_agent_status(self) -> bool:
        return self._call(self.plugin.clear_agent_status(), timeout=30)

    def save_settings(self, values: dict[str, Any]) -> bool:
        return self._call(self.plugin.save_settings(values), timeout=30)

    def scan(self) -> list[dict[str, Any]]:
        # The daemon's bounded BLE scan is 12 seconds.  Keep the desktop
        # control responsive if an older BlueZ/Decky runtime does not return
        # the RPC promptly; the operation can be retried from the page.
        return self._call(self.plugin.scan(), timeout=20)

    def connect(self, address: str) -> dict[str, Any]:
        self._call(self.plugin.connect(address), timeout=30)
        return self.get_status()

    def scan_and_connect(self) -> dict[str, Any]:
        return self.enable_connection()

    def enable_connection(self) -> dict[str, Any]:
        self._call(self.plugin.set_connection_enabled(True), timeout=30)
        return self.get_status()

    def disconnect(self) -> dict[str, Any]:
        self._call(self.plugin.set_connection_enabled(False), timeout=30)
        return self.get_status()

    def send_module(self, module_id: int) -> bool:
        return self._call(self.plugin.send_module(module_id), timeout=180)

    def send_layout(self, mode: str, module_id: int) -> bool:
        if mode == "carousel":
            return self._call(self.plugin.send_dashboard(), timeout=180)
        if mode == "clock":
            return self._call(self.plugin.send_clock(), timeout=180)
        if mode == "weather":
            return self._call(self.plugin.send_weather(0, 0), timeout=180)
        return self.send_module(module_id)

    def set_photo_frame_folder(self, folder_path: str) -> bool:
        return self._call(self.plugin.set_photo_frame_folder(folder_path), timeout=30)

    def import_photo_frame_asset(self, source_path: str) -> dict[str, Any]:
        return self._call(self.plugin.import_photo_frame_asset(source_path), timeout=60)

    def list_photo_frame_files(self) -> list[dict[str, Any]]:
        return self._call(self.plugin.list_photo_frame_files(), timeout=30)

    def exclude_photo_frame_file(self, path: str) -> bool:
        return self._call(self.plugin.exclude_photo_frame_file(path), timeout=30)

    def set_photo_frame_selected_file(self, path: str) -> bool:
        return self._call(self.plugin.set_photo_frame_selected_file(path), timeout=30)

    def send_custom_file(self, path: str) -> bool:
        return self._call(self.plugin.send_custom_file(path, Path(path).name), timeout=180)

    def self_test(self, include_device: bool = False) -> dict[str, Any]:
        result = {
            "language": self.language,
            "settings_dir": str(self.settings_dir),
            "status": self.get_status(),
            "settings": self.get_settings(),
            "images": self.list_photo_frame_files(),
        }
        if include_device:
            result["device"] = self.scan_and_connect()
        return result


class DesktopApp(DesktopPreferencesMixin):
    def __init__(self, root: tk.Tk, backend: DesktopBackend) -> None:
        self.root = root
        self.backend = backend
        self.language = backend.language
        self._init_preferences()
        self.root.title(APP_TITLE)
        icon_path = self.backend.plugin_root / "assets" / WINDOW_ICON
        self._window_icon: Optional[tk.PhotoImage] = None
        try:
            icon = tk.PhotoImage(file=str(icon_path))
            # Tk/Xwayland may publish an empty _NET_WM_ICON for oversized
            # 256px source images. Keep the launcher artwork unchanged, but
            # use a taskbar-safe 64px window icon.
            max_dimension = max(icon.width(), icon.height())
            if max_dimension > 64:
                scale = max(1, (max_dimension + 63) // 64)
                icon = icon.subsample(scale, scale)
            self._window_icon = icon
            self.root.iconphoto(True, self._window_icon)
        except (OSError, tk.TclError) as error:
            LOGGER.warning("unable to load desktop window icon %s: %s", icon_path, error)
        self.root.update_idletasks()
        try:
            display_width, display_height = map(
                int,
                subprocess.check_output(
                    ["xdotool", "getdisplaygeometry"],
                    text=True,
                    timeout=2,
                ).split(),
            )
        except (FileNotFoundError, subprocess.SubprocessError, ValueError):
            display_width = self.root.winfo_screenwidth()
            display_height = self.root.winfo_screenheight()
        window_x, window_y = center_window_position(
            display_width,
            display_height,
            WINDOW_W,
            WINDOW_H,
        )
        self._center_position = (window_x, window_y)
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}+0+0")
        self.root.minsize(MIN_WINDOW_W, MIN_WINDOW_H)
        self.root.resizable(True, True)
        self.root.overrideredirect(False)
        self.root.configure(bg=BACKGROUND)
        self.root.protocol("WM_DELETE_WINDOW", self._request_close)
        self._fullscreen = False
        self._windowed_geometry: Optional[str] = None
        self._shell: Optional[tk.Frame] = None
        self._sidebar: Optional[tk.Frame] = None
        self._sidebar_divider: Optional[tk.Frame] = None
        self._layout_refresh_pending = False
        self._live_place_baseline: dict[tk.Misc, tuple[float, float, float, float]] = {}
        self._live_pack_baseline: dict[tk.Misc, tuple[float, float]] = {}
        self._live_font_baseline: dict[tk.Misc, tuple[Any, ...]] = {}
        self._live_canvas_baseline: dict[
            tk.Canvas, dict[int, tuple[list[float], Optional[float], Optional[tuple[Any, ...]]]]
        ] = {}

        self.section = "screen"
        self.custom_open = False
        self.connection_state = "off"
        self.connected = False
        self.connected_address = ""
        self.scanning = False
        self.devices_scanning = False
        self.disconnecting = False
        self._connection_command_pending = False
        self._connection_action_address = ""
        self.connection_page = False
        self.connection_candidates: list[dict[str, str]] = []
        self.sending = False
        self.photo_frame_interval = 5
        self.photo_frame_interval_enabled = False
        self.module_switch_interval = 5
        self.module_switch_enabled = False
        self.mode = "deck_status"
        self.game_time_display_mode = "auto"
        self.progress = 0
        self._display_progress_state = ""
        self._module_request_id = 0
        self.images: list[dict[str, Any]] = []
        self._custom_thumbnail_images: list[tk.PhotoImage] = []
        self.selected_image = ""
        self.selected_custom_index = -1
        self._custom_action_return_control = "custom:0"
        self._custom_action: Optional[str] = None
        self._closed = False
        self._connection_spinner_angle = 0.0
        self._connection_spinner_scheduled = False
        self._connection_animation_started_at = 0.0
        self._connection_status_generation = 0
        self._control_state_epoch = ""
        self._control_state_revision = -1
        self._connection_scroll_canvas: Optional[tk.Canvas] = None
        self._custom_scroll_canvas: Optional[tk.Canvas] = None
        self._last_connection_failure = ""
        self._content: Optional[tk.Frame] = None
        self._nav_buttons: dict[str, tk.Button] = {}
        self._control_widgets: dict[str, Any] = {}
        self._screen_rows: dict[str, tk.Frame] = {}
        self._screen_focus_surfaces: dict[str, tk.Canvas] = {}
        self._screen_focus_backgrounds: dict[str, str] = {}
        self._screen_value_labels: dict[str, tk.Label] = {}
        self._connection_rows: dict[str, tk.Frame] = {}
        self._module_progress_label: Optional[tk.Label] = None
        self._module_progress_canvas: Optional[tk.Canvas] = None
        self._custom_progress_label: Optional[tk.Label] = None
        self._custom_progress_canvas: Optional[tk.Canvas] = None
        self._controller_queue: queue.Queue[tuple[str, float]] = queue.Queue()
        self._touch_queue: queue.Queue[RawTouchEvent] = queue.Queue()
        self._controller_gate = InputGate()
        self._gamepad = RawGamepadInput(self._controller_queue)
        self._controller = RawPuckInput(self._controller_queue)
        self._touch = RawTouchInput(self._touch_queue)
        self._touch_target: Optional[tk.Misc] = None
        self._navigation = DesktopNavigationState()
        self._exit_overlay: Optional[tk.Frame] = None
        self._exit_buttons: dict[str, tk.Button] = {}

        self._build_shell()
        self.root.bind("<Configure>", self._on_window_configure)
        self.root.bind_all("<F11>", lambda _event: self._toggle_fullscreen())
        self.root.after_idle(self._recenter_window)
        self.root.after(250, self._move_managed_frame)
        self.root.bind_all("<Up>", lambda _event: self._queue_controller_action("up"))
        self.root.bind_all("<Right>", lambda _event: self._queue_controller_action("right"))
        self.root.bind_all("<Down>", lambda _event: self._queue_controller_action("down"))
        self.root.bind_all("<Left>", lambda _event: self._queue_controller_action("left"))
        self.root.bind_all("<Return>", lambda _event: self._queue_controller_action("activate"))
        self.root.bind_all("<space>", lambda _event: self._queue_controller_action("activate"))
        self.root.bind_all("<Escape>", self._handle_escape)
        self.root.bind_all("<BackSpace>", lambda _event: self._queue_controller_action("back"))
        self.root.bind_all("<MouseWheel>", self._content_mousewheel)
        self.root.bind_all("<Button-4>", self._content_mousewheel)
        self.root.bind_all("<Button-5>", self._content_mousewheel)
        self._gamepad.start()
        self._controller.start()
        self._touch.start()
        self._load_initial_state()
        self._poll_backend()
        self._poll_controller()
        self._poll_touch()

    def _on_window_configure(self, _event: tk.Event) -> None:
        if self._closed:
            return
        self._layout_window_shell()

    def _layout_sidebar(self) -> None:
        if self._sidebar is None:
            return
        self._sidebar.configure(width=SIDEBAR_W, height=WINDOW_H)
        self._sidebar.place(x=0, y=0, width=SIDEBAR_W, height=WINDOW_H)
        nav_h = WINDOW_H // 3
        buttons = list(self._nav_buttons.values())
        for index, button in enumerate(buttons):
            item_y = index * nav_h
            item_h = WINDOW_H - item_y if index == 2 else nav_h
            label = str(button.cget("text"))
            button.configure(font=self._fit_font(label, SIDEBAR_W - _sx(32), 18, minimum=12))
            button.place(x=0, y=item_y, width=SIDEBAR_W - 1, height=item_h)
        separators = [child for child in self._sidebar.winfo_children() if child not in buttons]
        for index, separator in enumerate(separators[:2]):
            separator.place(x=0, y=(index + 1) * nav_h - 1, width=SIDEBAR_W, height=1)
        if self._sidebar_divider is not None:
            self._sidebar_divider.place(x=SIDEBAR_W - 1, y=0, width=1, height=WINDOW_H)

    def _font_baseline(self, widget: tk.Misc) -> Optional[tuple[Any, ...]]:
        try:
            spec = widget.cget("font")
            if not spec:
                return None
            font = tkfont.Font(root=self.root, font=spec)
            configured = font.configure()
            size = int(configured["size"])
            if size == 0:
                return None
            base_size = int(round(size / UI_SCALE))
            if base_size == 0:
                base_size = -1 if size < 0 else 1
            return (
                configured["family"],
                base_size,
                configured["weight"],
                configured["slant"],
                configured["underline"],
                configured["overstrike"],
            )
        except (tk.TclError, TypeError, ValueError, KeyError):
            return None

    def _capture_live_layout(self) -> None:
        if self._shell is None:
            return
        place_baseline: dict[tk.Misc, tuple[float, float, float, float]] = {}
        pack_baseline: dict[tk.Misc, tuple[float, float]] = {}
        font_baseline: dict[tk.Misc, tuple[Any, ...]] = {}
        canvas_baseline: dict[
            tk.Canvas, dict[int, tuple[list[float], Optional[float], Optional[tuple[Any, ...]]]]
        ] = {}

        def walk(widget: tk.Misc) -> None:
            if widget is not self._shell:
                manager = widget.winfo_manager()
                if manager == "place":
                    try:
                        info = widget.place_info()
                        if not info.get("relx") and not info.get("rely"):
                            place_baseline[widget] = tuple(
                                float(info.get(key, 0) or 0) / UI_SCALE
                                for key in ("x", "y", "width", "height")
                            )
                    except (tk.TclError, ValueError):
                        pass
                elif manager == "pack":
                    try:
                        pack_baseline[widget] = (
                            max(1, widget.winfo_width()) / UI_SCALE,
                            max(1, widget.winfo_height()) / UI_SCALE,
                        )
                    except tk.TclError:
                        pass
                font = self._font_baseline(widget)
                if font is not None:
                    font_baseline[widget] = font
            if isinstance(widget, tk.Canvas):
                items: dict[int, tuple[list[float], Optional[float], Optional[tuple[Any, ...]]]] = (
                    {}
                )
                for item in widget.find_all():
                    try:
                        coords = [float(value) / UI_SCALE for value in widget.coords(item)]
                        width_value = widget.itemcget(item, "width")
                        item_width = float(width_value) / UI_SCALE if width_value else None
                        item_font: Optional[tuple[Any, ...]] = None
                        font_spec = widget.itemcget(item, "font")
                        if font_spec:
                            font = tkfont.Font(root=self.root, font=font_spec)
                            configured = font.configure()
                            item_size = int(configured["size"])
                            item_font = (
                                configured["family"],
                                int(round(item_size / UI_SCALE)),
                                configured["weight"],
                                configured["slant"],
                                configured["underline"],
                                configured["overstrike"],
                            )
                        items[item] = (coords, item_width, item_font)
                    except (tk.TclError, TypeError, ValueError, KeyError):
                        pass
                if items:
                    canvas_baseline[widget] = items
            for child in widget.winfo_children():
                walk(child)

        walk(self._shell)
        self._live_place_baseline = place_baseline
        self._live_pack_baseline = pack_baseline
        self._live_font_baseline = font_baseline
        self._live_canvas_baseline = canvas_baseline

    def _scale_live_content(self) -> None:
        if self._shell is None:
            return
        custom_canvases = (
            DotSlider,
            CapsuleToggle,
            ConnectionStatusIndicator,
            ConnectionSignalIndicator,
            ConnectionHeaderButton,
            RoundedModuleCard,
        )
        for widget, (x, y, width, height) in list(self._live_place_baseline.items()):
            try:
                if widget.winfo_exists():
                    widget.place(
                        x=_sx(x),
                        y=_sy(y),
                        width=_sx(width),
                        height=_sy(height),
                    )
            except tk.TclError:
                pass
        for widget, (width, height) in list(self._live_pack_baseline.items()):
            try:
                if widget.winfo_exists():
                    widget.configure(width=_sx(width), height=_sy(height))
            except tk.TclError:
                pass
        for widget, baseline in list(self._live_font_baseline.items()):
            try:
                if widget.winfo_exists():
                    family, size, weight, slant, underline, overstrike = baseline
                    widget.configure(
                        font=(
                            family,
                            (
                                _scaled_font(abs(int(size)))[1]
                                if int(size) < 0
                                else max(1, round(int(size) * UI_SCALE))
                            ),
                            weight,
                            slant,
                            underline,
                            overstrike,
                        )
                    )
            except (tk.TclError, TypeError, ValueError):
                pass
        for canvas, items in list(self._live_canvas_baseline.items()):
            try:
                if not canvas.winfo_exists():
                    continue
                if isinstance(canvas, custom_canvases):
                    canvas.event_generate("<Configure>")
                    continue
                for item, (coords, item_width, item_font) in items.items():
                    if item not in canvas.find_all():
                        continue
                    canvas.coords(
                        item,
                        *[
                            value * (UI_SCALE_X if index % 2 == 0 else UI_SCALE_Y)
                            for index, value in enumerate(coords)
                        ],
                    )
                    options: dict[str, Any] = {}
                    if item_width is not None:
                        options["width"] = _sx(item_width)
                    if item_font is not None:
                        family, size, weight, slant, underline, overstrike = item_font
                        options["font"] = (
                            family,
                            (
                                _scaled_font(abs(int(size)))[1]
                                if int(size) < 0
                                else max(1, round(int(size) * UI_SCALE))
                            ),
                            weight,
                            slant,
                            underline,
                            overstrike,
                        )
                    if options:
                        canvas.itemconfigure(item, **options)
            except tk.TclError:
                pass

    def _layout_window_shell(self) -> None:
        if self._shell is None:
            return
        width = max(MIN_WINDOW_W, int(self.root.winfo_width() or MIN_WINDOW_W))
        height = max(MIN_WINDOW_H, int(self.root.winfo_height() or MIN_WINDOW_H))
        scale_x = max(1.0, width / DESIGN_WINDOW_W)
        scale_y = max(1.0, height / DESIGN_WINDOW_H)
        changed = abs(scale_x - UI_SCALE_X) > 0.001 or abs(scale_y - UI_SCALE_Y) > 0.001
        if changed:
            _set_layout_scale(scale_x, scale_y)
        # Match native layout behavior: the content surface fills
        # the complete client area in both axes during a live resize.
        self._shell.place(
            x=0,
            y=0,
            width=WINDOW_W,
            height=WINDOW_H,
        )
        self._layout_sidebar()
        if self._content is not None:
            self._content.configure(width=CONTENT_W, height=WINDOW_H)
            self._content.place(x=SIDEBAR_W, y=0, width=CONTENT_W, height=WINDOW_H)
        if self._sidebar_divider is not None:
            self._sidebar_divider.place(x=SIDEBAR_W - 1, y=0, width=1, height=WINDOW_H)
        if changed:
            self._scale_live_content()

    def _handle_escape(self, _event: tk.Event) -> str:
        if self._fullscreen:
            self._toggle_fullscreen()
            return "break"
        self._queue_controller_action("back")
        return "break"

    def _toggle_fullscreen(self) -> str:
        if self._fullscreen:
            self.root.attributes("-fullscreen", False)
            self._fullscreen = False
            if self._windowed_geometry:
                self.root.geometry(self._windowed_geometry)
            self.root.minsize(MIN_WINDOW_W, MIN_WINDOW_H)
            self.root.resizable(True, True)
        else:
            self._windowed_geometry = self.root.geometry()
            self._fullscreen = True
            self.root.attributes("-fullscreen", True)
        self.root.after_idle(self._layout_window_shell)
        return "break"

    def _font(self, size: int, weight: str = "normal") -> tuple[str, int, str]:
        return _scaled_font(size, weight)

    def _fit_font(
        self, text: str, width: int, size: int, weight: str = "normal", minimum: int = 9
    ) -> tuple[str, int, str]:
        """Keep existing geometry: reduce only a label that exceeds its fixed width."""
        for candidate in range(size, minimum - 1, -1):
            font = tkfont.Font(
                root=self.root,
                family="Noto Sans CJK SC",
                size=-max(1, round(candidate * UI_SCALE)),
                weight=weight,
            )
            if font.measure(text.replace("\n", " ")) <= width:
                return self._font(candidate, weight)
        return self._font(minimum, weight)

    def _t(self, key: str, **values: object) -> str:
        return translate(key, getattr(self, "language", "en"), **values)

    def _recenter_window(self) -> None:
        if self._closed:
            return
        try:
            display_width, display_height = map(
                int,
                subprocess.check_output(
                    ["xdotool", "getdisplaygeometry"],
                    text=True,
                    timeout=2,
                ).split(),
            )
        except (FileNotFoundError, subprocess.SubprocessError, ValueError):
            display_width = self.root.winfo_screenwidth()
            display_height = self.root.winfo_screenheight()
        undecorated_position = center_window_position(
            display_width,
            display_height,
            WINDOW_W,
            WINDOW_H,
        )
        self.root.geometry(f"+{undecorated_position[0]}+{undecorated_position[1]}")

    def _move_managed_frame(self) -> None:
        if self._closed:
            return
        try:
            display_width, display_height = map(
                int,
                subprocess.check_output(
                    ["xdotool", "getdisplaygeometry"],
                    text=True,
                    timeout=2,
                ).split(),
            )
        except (FileNotFoundError, subprocess.SubprocessError, ValueError):
            return
        try:
            fallback_window_id = self.root.winfo_id()
            search_output = subprocess.check_output(
                ["xdotool", "search", "--onlyvisible", "--name", f"^{APP_TITLE}$"],
                text=True,
                timeout=2,
            )
            window_id = select_managed_window_id(search_output, fallback_window_id)
            output = subprocess.check_output(
                ["xprop", "-id", str(window_id), "_NET_FRAME_EXTENTS"],
                text=True,
                timeout=2,
            )
            frame_extents = parse_frame_extents(output)
        except (FileNotFoundError, subprocess.SubprocessError, ValueError):
            return
        undecorated_position = center_window_position(
            display_width, display_height, WINDOW_W, WINDOW_H
        )
        frame_x, frame_y = center_managed_frame_position(
            display_width,
            display_height,
            WINDOW_W,
            WINDOW_H,
            frame_extents,
            undecorated_position,
        )
        try:
            subprocess.run(
                ["xdotool", "windowmove", "--sync", str(window_id), str(frame_x), str(frame_y)],
                check=True,
                timeout=2,
            )
        except (FileNotFoundError, subprocess.SubprocessError):
            return

    def _build_shell(self) -> None:
        self._shell = tk.Frame(
            self.root,
            width=WINDOW_W,
            height=WINDOW_H,
            bg=BACKGROUND,
            bd=0,
            highlightthickness=0,
        )
        self._shell.pack_propagate(False)
        self._layout_window_shell()
        sidebar = tk.Frame(
            self._shell,
            width=SIDEBAR_W,
            height=WINDOW_H,
            bg=SIDEBAR_BG,
            highlightbackground=NAV_DIVIDER,
            highlightthickness=1,
        )
        sidebar.place(x=0, y=0)
        sidebar.pack_propagate(False)
        self._sidebar = sidebar
        labels = [
            ("screen", self._t("nav_screen")),
            ("layout", self._t("nav_layout")),
            ("settings", self._pt("settings")),
        ]
        nav_h = WINDOW_H // 3
        for index, (key, label) in enumerate(labels):
            item_y = index * nav_h
            item_h = WINDOW_H - item_y if index == len(labels) - 1 else nav_h
            button = tk.Button(
                sidebar,
                text=label,
                command=lambda value=key: self._select_section(value),
                fg=WHITE,
                bg=SIDEBAR_BG,
                activebackground=SIDEBAR_BG,
                activeforeground=WHITE,
                bd=0,
                relief="flat",
                font=self._fit_font(label, SIDEBAR_W - 32, 18, minimum=12),
                cursor="hand2",
            )
            button.place(x=0, y=item_y, width=SIDEBAR_W - 1, height=item_h)
            if index < len(labels) - 1:
                tk.Frame(sidebar, bg=NAV_DIVIDER).place(
                    x=0, y=item_y + item_h - 1, width=SIDEBAR_W, height=1
                )
            self._nav_buttons[key] = button
            self._control_widgets[key] = button

        self._content = tk.Frame(self._shell, width=CONTENT_W, height=WINDOW_H, bg=BACKGROUND)
        self._content.place(x=SIDEBAR_W, y=0)
        self._content.pack_propagate(False)

        sidebar_divider = tk.Frame(self._shell, bg=NAV_DIVIDER)
        sidebar_divider.place(x=SIDEBAR_W - 1, y=0, width=1, height=WINDOW_H)
        sidebar_divider.lift()
        self._sidebar_divider = sidebar_divider
        self._render()

    def _clear_content(self) -> None:
        if self._content is None:
            return
        self._settings_note_widget = None
        for child in self._content.winfo_children():
            child.destroy()
        self._module_progress_label = None
        self._module_progress_canvas = None
        self._custom_progress_label = None
        self._custom_progress_canvas = None
        self._custom_action_bar = None
        self._connection_scroll_canvas = None
        self._custom_scroll_canvas = None
        self._screen_rows.clear()
        self._screen_focus_surfaces.clear()
        self._screen_focus_backgrounds.clear()
        self._screen_value_labels.clear()
        self._connection_rows.clear()

    def _refresh_sidebar_focus(self) -> None:
        for key, button in self._nav_buttons.items():
            focused = self._navigation.region == "nav" and self._navigation.control == key
            button.configure(
                bg=PURPLE if focused else SIDEBAR_BG,
                activebackground=PURPLE if focused else SIDEBAR_BG,
                highlightthickness=0,
            )

    def _render(self) -> None:
        if self._preference_picker and not getattr(self, "_preferences_render_requested", False):
            return
        if not self._navigation.exit_confirming and self._exit_overlay is not None:
            self._hide_exit_confirmation()
        if self._refresh_settings():
            self._refresh_sidebar_focus()
            self._apply_controller_focus()
            if self._navigation.exit_confirming:
                if self._exit_overlay is None:
                    self._render_exit_confirmation()
                else:
                    self._refresh_exit_confirmation_focus()
            self._capture_live_layout()
            return
        for control_id in [key for key in self._control_widgets if key not in NAV_SECTIONS]:
            self._control_widgets.pop(control_id, None)
        self._refresh_sidebar_focus()
        self._clear_content()
        if self.section == "screen":
            self._render_screen()
        elif self.section == "settings":
            self._render_settings()
        elif self.custom_open:
            self._render_custom()
        elif self._navigation.game_time_page:
            self._render_game_time()
        else:
            self._render_modules()
        self._apply_controller_focus()
        if self._navigation.exit_confirming:
            self._render_exit_confirmation()
        self._capture_live_layout()

    def _render_screen(self) -> None:
        if self.connection_page:
            self._render_connection_page()
            return
        self._control_row(0, "power", self._t("task_connect"), self._connection_entry_widget)
        self._control_row(
            1, "custom", self._t("control_brightness"), self._photo_frame_interval_widget
        )
        self._control_row(
            2, "refresh", self._t("control_refresh"), self._module_switch_interval_widget
        )
        # Apply the selected-row background to labels and interval controls on
        # the initial render as well as during later focus movement.
        self._refresh_screen_focus()

    def _screen_control_row_background(self, control: str) -> str:
        focused = (
            self._navigation.region == "content"
            and self._navigation.section == "screen"
            and self._navigation.control == control
        )
        return FOCUS_ROW_BG if focused else BACKGROUND

    def _refresh_screen_focus(self) -> None:
        for control, row in self._screen_rows.items():
            if not row.winfo_exists():
                continue
            background = self._screen_control_row_background(control)
            if self._screen_focus_backgrounds.get(control) == background:
                continue
            self._screen_focus_backgrounds[control] = background
            surface = self._screen_focus_surfaces.get(control)
            if surface is not None and surface.winfo_exists():
                try:
                    surface.itemconfigure("focus-background", fill=background)
                except tk.TclError:
                    pass
            for child in row.winfo_children():
                if child is surface:
                    continue
                set_focus_background = getattr(child, "set_focus_background", None)
                if callable(set_focus_background):
                    # Slider/Toggle focus is updated through one Canvas item;
                    # changing the Canvas widget background would repaint the
                    # control and recreate the visible flash.
                    set_focus_background(background)
                    continue
                try:
                    child.configure(bg=background)
                except (tk.TclError, AttributeError):
                    pass
                # Focus movement must only change the row/control background.
                # Calling Canvas._draw() here deletes and recreates every
                # slider/toggle item on each joystick step, which produces a
                # visible flash.  The interval controls keep their track and
                # ON/OFF state until an actual value/toggle change, where the
                # existing local update path redraws only that control.
        self._apply_controller_focus()

    def _control_row(
        self, index: int, icon: str, label: str, builder: Callable[[tk.Frame], None]
    ) -> None:
        if self._content is None:
            return
        row_h = WINDOW_H // 3
        row_y = index * row_h
        actual_h = WINDOW_H - row_y if index == 2 else row_h
        control = ("connection", "photo-frame", "module-switch")[index]
        row_bg = self._screen_control_row_background(control)
        row = tk.Frame(self._content, width=CONTENT_W, height=actual_h, bg=BACKGROUND)
        row.place(x=0, y=row_y)
        row.pack_propagate(False)
        self._screen_rows[control] = row
        focus_surface = tk.Canvas(
            row,
            width=CONTENT_W,
            height=actual_h,
            bg=BACKGROUND,
            bd=0,
            highlightthickness=0,
            takefocus=0,
        )
        focus_surface.place(x=0, y=0, width=CONTENT_W, height=actual_h)
        focus_surface.create_rectangle(
            0,
            0,
            CONTENT_W,
            actual_h,
            fill=row_bg,
            outline="",
            tags="focus-background",
        )
        self._screen_focus_surfaces[control] = focus_surface
        # Force the first focus pass to update every child created in the row;
        # the focus surface itself already has the initial row color.
        self._screen_focus_backgrounds[control] = ""
        label_y = _sy(91 if index == 0 else 43)
        icon_canvas = tk.Canvas(
            row,
            bg=BACKGROUND,
            bd=0,
            highlightthickness=0,
        )
        icon_canvas.place(
            x=CONTROL_ROW_X,
            y=label_y,
            width=CONTROL_ICON_SIZE,
            height=CONTROL_ICON_SIZE,
        )
        _draw_desktop_icon(
            icon_canvas,
            icon,
            CONTROL_ICON_SIZE / 2,
            CONTROL_ICON_SIZE / 2,
            _sx(34.0),
            CONTROL_MUTED,
            _sx(2.5),
        )
        title = tk.Label(
            row,
            text=label,
            fg=WHITE,
            bg=BACKGROUND,
            anchor="w",
            font=self._fit_font(label, 220, 13, "bold"),
        )
        title.place(x=CONTROL_ROW_X + _sx(47), y=label_y, width=_sx(220), height=_sy(36))
        builder(row)
        if control == "connection":
            for target in (row, icon_canvas, title):
                target.bind("<Button-1>", lambda _event: self._open_connection_page())
        if index < 2:
            tk.Frame(row, bg=CONTROL_DIVIDER).place(
                x=0,
                y=actual_h - 1,
                width=CONTENT_W,
                height=1,
            )

    def _connection_entry_widget(self, row: tk.Frame) -> None:
        indicator = ConnectionStatusIndicator(
            row,
            connected=self.connected,
            label=self._t("connection_connected" if self.connected else "connection_disconnected"),
            background=str(row.cget("bg")),
        )
        indicator.place(
            x=CONTENT_W - CONTROL_ROW_RIGHT - _sx(132),
            y=_sy(91),
            width=_sx(132),
            height=TOGGLE_H,
        )
        self._control_widgets["connection"] = indicator

    def _render_connection_page(self) -> None:
        if self._content is None:
            return
        header = tk.Frame(self._content, width=CONTENT_W, height=CONNECTION_HEADER_H, bg=BACKGROUND)
        header.place(x=0, y=0)
        header.pack_propagate(False)
        back = ConnectionHeaderButton(
            header,
            icon="back",
            command=self._close_connection_page,
            background=BACKGROUND,
        )
        back.place(x=_sx(28), y=_sy(18), width=_sx(40), height=_sy(40))
        back_label = tk.Label(
            header,
            text=self._t("back"),
            fg=WHITE,
            bg=BACKGROUND,
            anchor="w",
            font=self._fit_font(self._t("back"), 90, 14, minimum=10),
        )
        back_label.place(x=_sx(72), y=_sy(18), width=_sx(90), height=_sy(40))
        back_label.bind("<Button-1>", lambda _event: self._close_connection_page())
        title = tk.Label(
            header,
            text=self._t("task_connect"),
            fg=WHITE,
            bg=BACKGROUND,
            anchor="center",
            font=self._fit_font(self._t("task_connect"), 220, 17, minimum=11),
        )
        title.place(x=_sx(165), y=_sy(18), width=CONTENT_W - _sx(330), height=_sy(40))
        refresh = ConnectionHeaderButton(
            header,
            icon="refresh",
            command=self._refresh_connection_candidates,
            background=BACKGROUND,
            spinning=self.devices_scanning,
        )
        refresh.place(x=CONTENT_W - _sx(68), y=_sy(18), width=_sx(40), height=_sy(40))
        tk.Frame(header, bg=CONTROL_DIVIDER).place(
            x=0, y=CONNECTION_HEADER_H - 1, width=CONTENT_W, height=1
        )
        self._control_widgets["connection:back"] = back
        self._control_widgets["connection:refresh"] = refresh
        if self.devices_scanning:
            refresh.set_spinner_angle(self._connection_spinner_angle)
            self._start_connection_spinner()
        viewport_height = WINDOW_H - CONNECTION_HEADER_H
        viewport_width = CONTENT_W - 14
        canvas = tk.Canvas(self._content, bg=BACKGROUND, bd=0, highlightthickness=0)
        canvas.place(x=0, y=CONNECTION_HEADER_H, width=viewport_width, height=viewport_height)
        scrollbar = tk.Scrollbar(
            self._content,
            orient="vertical",
            command=canvas.yview,
            width=14,
            bg=CONTROL_MUTED,
            troughcolor=BACKGROUND,
            activebackground=PURPLE,
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        scrollbar.place(x=viewport_width, y=CONNECTION_HEADER_H, width=14, height=viewport_height)
        canvas.configure(yscrollcommand=scrollbar.set)
        frame = tk.Frame(canvas, bg=BACKGROUND, width=viewport_width)
        window_id = canvas.create_window((0, 0), window=frame, anchor="nw", width=viewport_width)
        frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        self._connection_scroll_canvas = canvas
        connection_in_progress = self.disconnecting or self._connection_command_pending
        for index, candidate in enumerate(self.connection_candidates):
            row = tk.Frame(
                frame,
                width=viewport_width,
                height=CONNECTION_CANDIDATE_H,
                bg=self._connection_candidate_background(index),
            )
            row.pack(fill="x")
            row.pack_propagate(False)
            self._connection_rows[f"connection:device:{index}"] = row
            row_bg = str(row.cget("bg"))
            raw_rssi = candidate.get("rssi")
            try:
                rssi = int(raw_rssi) if raw_rssi is not None else None
            except (TypeError, ValueError):
                rssi = None
            signal = ConnectionSignalIndicator(row, rssi=rssi, background=row_bg)
            signal.place(x=_sx(16), y=0, width=_sx(58), height=CONNECTION_CANDIDATE_H)
            tk.Label(
                row,
                text=str(candidate.get("name") or PRODUCT_NAME),
                fg=WHITE,
                bg=row_bg,
                anchor="w",
                font=self._font(10, "bold"),
            ).place(x=_sx(88), y=_sy(8), width=_sx(220), height=_sy(28))
            tk.Label(
                row,
                text=str(candidate.get("address") or ""),
                fg=SUBTLE,
                bg=row_bg,
                anchor="w",
                font=self._font(10),
            ).place(x=_sx(88), y=_sy(36), width=_sx(290), height=_sy(24))
            raw_battery = candidate.get("battery")
            try:
                battery = max(0, min(100, int(raw_battery))) if raw_battery is not None else None
            except (TypeError, ValueError):
                battery = None
            tk.Label(
                row,
                text="--%" if battery is None else f"{battery}%",
                fg=SUBTLE,
                bg=row_bg,
                anchor="w",
                font=self._font(9),
            ).place(x=_sx(390), y=_sy(36), width=_sx(55), height=_sy(24))
            address = _normalize_eink_address(candidate.get("address"))
            candidate_connected = self.connected and address == self.connected_address
            candidate_action_in_progress = (
                connection_in_progress and address == self._connection_action_address
            )
            switching_blocked = self.connected and not candidate_connected
            busy = (
                self.devices_scanning or connection_in_progress or self.sending or switching_blocked
            )
            toggle = CapsuleToggle(
                row,
                enabled=candidate_connected,
                busy=busy,
                spinning=candidate_action_in_progress,
                command=lambda value=index: self._toggle_connection_candidate(value),
            )
            toggle.place(
                x=viewport_width - CANDIDATE_SWITCH_RIGHT_INSET - TOGGLE_W - _sx(14),
                y=(CONNECTION_CANDIDATE_H - TOGGLE_H) // 2,
                width=TOGGLE_W + _sx(14),
                height=TOGGLE_H,
            )
            self._control_widgets[f"connection:device:{index}"] = toggle
            tk.Frame(row, bg=CONTROL_DIVIDER).place(
                x=0,
                y=CONNECTION_CANDIDATE_H - 1,
                width=CONTENT_W,
                height=1,
            )

    def _content_mousewheel(self, event: tk.Event) -> str:
        scroll_canvas = (
            self._connection_scroll_canvas
            if self.connection_page
            else self._custom_scroll_canvas if self.custom_open else None
        )
        if scroll_canvas is not None:
            delta = getattr(event, "delta", 0)
            if delta:
                scroll_canvas.yview_scroll(-1 if delta > 0 else 1, "units")
            elif getattr(event, "num", None) == 4:
                scroll_canvas.yview_scroll(-3, "units")
            elif getattr(event, "num", None) == 5:
                scroll_canvas.yview_scroll(3, "units")
            return "break"
        return ""

    def _connection_candidate_background(self, index: int) -> str:
        control = f"connection:device:{index}"
        if (
            self._navigation.region == "content"
            and self._navigation.connection_page
            and self._navigation.control == control
        ):
            return FOCUS_ROW_BG
        return BACKGROUND

    def _refresh_connection_focus(self) -> None:
        for key, widget in self._control_widgets.items():
            if not key.startswith("connection:") or not widget.winfo_exists():
                continue
            setter = getattr(widget, "set_controller_focus", None)
            if callable(setter):
                setter(key == self._navigation.control)
        for key, row in self._connection_rows.items():
            if not row.winfo_exists():
                continue
            background = FOCUS_ROW_BG if key == self._navigation.control else BACKGROUND
            try:
                row.configure(bg=background)
            except tk.TclError:
                pass
            for child in row.winfo_children():
                try:
                    child.configure(bg=background)
                except (tk.TclError, AttributeError):
                    pass
                redraw = getattr(child, "_draw", None)
                if callable(redraw):
                    try:
                        redraw()
                    except tk.TclError:
                        pass
        current = self._control_widgets.get(self._navigation.control)
        if current is not None:
            try:
                current.focus_set()
            except tk.TclError:
                pass

    def _refresh_connection_state_visuals(self) -> None:
        connection_in_progress = self.disconnecting or self._connection_command_pending
        for index, candidate in enumerate(self.connection_candidates):
            widget = self._control_widgets.get(f"connection:device:{index}")
            if widget is None or not widget.winfo_exists():
                continue
            address = _normalize_eink_address(candidate.get("address"))
            candidate_connected = self.connected and address == self.connected_address
            switching_blocked = self.connected and not candidate_connected
            busy = (
                self.devices_scanning or connection_in_progress or self.sending or switching_blocked
            )
            candidate_action_in_progress = (
                connection_in_progress and address == self._connection_action_address
            )
            setter = getattr(widget, "set_state", None)
            if callable(setter):
                setter(
                    enabled=candidate_connected, busy=busy, spinning=candidate_action_in_progress
                )
        self._refresh_connection_focus()

    def _start_connection_spinner(self) -> None:
        if self._closed or not self.devices_scanning or self._connection_spinner_scheduled:
            return
        self._connection_spinner_scheduled = True
        self.root.after(CONNECTION_SPINNER_FRAME_MS, self._advance_connection_spinner)

    def _advance_connection_spinner(self) -> None:
        self._connection_spinner_scheduled = False
        if self._closed or not self.devices_scanning:
            return
        self._connection_spinner_angle = (
            self._connection_spinner_angle + CONNECTION_SPINNER_STEP_DEGREES
        ) % 360.0
        refresh = self._control_widgets.get("connection:refresh")
        set_spinner_angle = getattr(refresh, "set_spinner_angle", None)
        if refresh is not None and refresh.winfo_exists() and callable(set_spinner_angle):
            set_spinner_angle(self._connection_spinner_angle)
        self._start_connection_spinner()

    def _photo_frame_interval_widget(self, row: tk.Frame) -> None:
        row_bg = str(row.cget("bg"))
        value_label = tk.Label(
            row,
            text=self._t("minutes_short", value=self.photo_frame_interval),
            fg=WHITE,
            bg=row_bg,
            anchor="e",
            font=self._font(12),
        )
        value_label.place(
            x=CONTENT_W - CONTROL_ROW_RIGHT - _sx(225), y=_sy(43), width=_sx(105), height=_sy(36)
        )
        self._screen_value_labels["photo-frame"] = value_label
        toggle = CapsuleToggle(
            row,
            enabled=self.photo_frame_interval_enabled,
            busy=False,
            status_font=INTERVAL_TOGGLE_FONT,
            command=self._toggle_photo_frame_interval_enabled,
        )
        toggle.place(
            x=CONTENT_W - CONTROL_ROW_RIGHT - TOGGLE_W,
            y=_sy(43),
            width=TOGGLE_W,
            height=TOGGLE_H,
        )
        slider = DotSlider(
            row,
            from_=1,
            to=60,
            value=self.photo_frame_interval,
            step=1,
            command=self._photo_frame_interval_changed,
            enabled=self.photo_frame_interval_enabled,
        )
        slider.place(
            x=CONTROL_ROW_X,
            y=_sy(119),
            width=CONTENT_W - CONTROL_ROW_X - CONTROL_ROW_RIGHT,
            height=_sy(52),
        )
        self._control_widgets["photo-frame"] = slider
        self._control_widgets["photo-frame-toggle"] = toggle

    def _module_switch_interval_widget(self, row: tk.Frame) -> None:
        row_bg = str(row.cget("bg"))
        value_label = tk.Label(
            row,
            text=self._t("minutes_short", value=self.module_switch_interval),
            fg=WHITE,
            bg=row_bg,
            anchor="e",
            font=self._font(12),
        )
        value_label.place(
            x=CONTENT_W - CONTROL_ROW_RIGHT - _sx(225), y=_sy(43), width=_sx(105), height=_sy(36)
        )
        self._screen_value_labels["module-switch"] = value_label
        toggle = CapsuleToggle(
            row,
            enabled=self.module_switch_enabled,
            busy=False,
            status_font=INTERVAL_TOGGLE_FONT,
            command=self._toggle_module_switch_enabled,
        )
        toggle.place(
            x=CONTENT_W - CONTROL_ROW_RIGHT - TOGGLE_W,
            y=_sy(43),
            width=TOGGLE_W,
            height=TOGGLE_H,
        )
        slider = DotSlider(
            row,
            from_=5,
            to=60,
            value=self.module_switch_interval,
            step=5,
            command=self._module_switch_interval_changed,
            enabled=self.module_switch_enabled,
            segmented=True,
            segment_count=len(MODULE_SWITCH_INTERVAL_VALUES),
        )
        slider.place(
            x=CONTROL_ROW_X,
            y=_sy(119),
            width=CONTENT_W - CONTROL_ROW_X - CONTROL_ROW_RIGHT,
            height=_sy(52),
        )
        self._control_widgets["module-switch"] = slider
        self._control_widgets["module-switch-toggle"] = toggle

    def _select_game_time_mode(self, mode: str) -> None:
        if mode not in ("time", "poster", "auto"):
            return
        self.game_time_display_mode = mode
        self.backend.save_settings({"game_time_display_mode": mode})
        item = next((item for item in MODULES if item[2] == "timeline"), None)
        if item is not None:
            self._navigation = DesktopNavigationState(
                region="content", control="module:timeline", section="layout"
            )
            self.custom_open = False
            self._open_module(item, open_game_time_page=False)

    def _render_game_time(self) -> None:
        if self._content is None:
            return
        title = tk.Label(
            self._content,
            text=self._t("module_game_time"),
            fg=WHITE,
            bg=BACKGROUND,
            font=self._font(16, "bold"),
        )
        title.place(x=_sx(36), y=_sy(26), width=CONTENT_W - _sx(72), height=_sy(34))
        labels = GAME_TIME_MODE_LABELS.get(self.language, GAME_TIME_MODE_LABELS["en"])
        options = tuple((mode, labels[mode]) for mode in ("time", "poster", "auto"))
        for index, (mode, label) in enumerate(options):
            control = f"game-time:{mode}"
            selected = self.game_time_display_mode == mode
            focused = self._navigation.region == "content" and self._navigation.control == control
            button = tk.Button(
                self._content,
                text=("● " if selected else "○ ") + label,
                command=lambda value=mode: self._select_game_time_mode(value),
                fg=WHITE,
                bg=PURPLE if focused else BUTTON_BG,
                activebackground=PURPLE,
                activeforeground=WHITE,
                highlightbackground=PURPLE if focused else BUTTON_BG,
                highlightcolor=PURPLE if focused else BUTTON_BG,
                highlightthickness=0,
                bd=0,
                relief="flat",
                font=self._font(14, "bold" if selected else "normal"),
                anchor="w",
                padx=_sx(18),
            )
            button.place(
                x=_sx(64), y=_sy(140 + index * 58), width=CONTENT_W - _sx(128), height=_sy(44)
            )
            self._control_widgets[control] = button
        back = tk.Button(
            self._content,
            text="‹ " + self._t("back"),
            command=lambda: self._handle_controller_action("back"),
            fg=SUBTLE,
            bg=BACKGROUND,
            activebackground=BACKGROUND,
            activeforeground=WHITE,
            bd=0,
            relief="flat",
            font=self._font(12),
            anchor="w",
        )
        back.place(x=_sx(24), y=WINDOW_H - _sy(52), width=_sx(160), height=_sy(32))
        self._control_widgets["game-time:back"] = back

    def _render_modules(self) -> None:
        if self._content is None:
            return
        for index, (label_key, module_id, mode) in enumerate(MODULES):
            row, col = divmod(index, 3)
            if mode == "custom":
                row, col = 2, 1
            card = RoundedModuleCard(
                self._content,
                mode=mode,
                label=self._t(label_key),
                command=lambda item=(label_key, module_id, mode): self._open_module_from_pointer(
                    item
                ),
            )
            card.place(
                x=MODULE_CARD_X + col * (MODULE_CARD_W + MODULE_CARD_GAP_X),
                y=MODULE_CARD_Y + row * (MODULE_CARD_H + MODULE_CARD_GAP_Y),
                width=MODULE_CARD_W,
                height=MODULE_CARD_H,
            )
            self._control_widgets[f"module:{mode}"] = card
        if self.sending:
            self._render_module_progress()

    def _render_module_progress(self) -> None:
        if self._content is None:
            return
        progress = max(0, min(100, int(self.progress)))
        bar_x = _sx(78)
        bar_w = CONTENT_W - bar_x * 2
        if self._module_progress_label is None or not self._module_progress_label.winfo_exists():
            self._module_progress_label = tk.Label(
                self._content,
                fg=WHITE,
                bg=BACKGROUND,
                font=self._font(13, "bold"),
            )
            self._module_progress_label.place(x=bar_x, y=_sy(596), width=bar_w, height=_sy(26))
        if self._display_progress_state == "retrying":
            label = "正在重新连接设备…" if self.language.startswith("zh") else "Reconnecting…"
        elif self._display_progress_state == "starting":
            label = "正在连接设备…" if self.language.startswith("zh") else "Connecting…"
        else:
            label = self._t("switching_screen", progress=progress)
        self._module_progress_label.configure(text=label)
        if self._module_progress_canvas is None or not self._module_progress_canvas.winfo_exists():
            self._module_progress_canvas = tk.Canvas(
                self._content,
                width=bar_w,
                height=_sy(22),
                bg=BACKGROUND,
                bd=0,
                highlightthickness=0,
            )
            self._module_progress_canvas.place(x=bar_x, y=_sy(626), width=bar_w, height=_sy(22))
        canvas = self._module_progress_canvas
        canvas.delete("progress")
        canvas.create_line(
            _sx(8),
            _sy(11),
            bar_w - _sx(8),
            _sy(11),
            fill=BUTTON_BG,
            width=_sx(8),
            capstyle=tk.ROUND,
            tags="progress",
        )
        if progress:
            progress_x = _sx(8) + (bar_w - _sx(16)) * progress / 100
            canvas.create_line(
                _sx(8),
                _sy(11),
                progress_x,
                _sy(11),
                fill=PURPLE,
                width=_sx(8),
                capstyle=tk.ROUND,
                tags="progress",
            )

    def _hide_module_progress(self) -> None:
        if self._module_progress_label is not None and self._module_progress_label.winfo_exists():
            self._module_progress_label.destroy()
        if self._module_progress_canvas is not None and self._module_progress_canvas.winfo_exists():
            self._module_progress_canvas.destroy()
        self._module_progress_label = None
        self._module_progress_canvas = None

    def _refresh_module_focus(self, previous_control: str) -> None:
        previous_card = self._control_widgets.get(previous_control)
        clear_focus = getattr(previous_card, "set_controller_focus", None)
        if callable(clear_focus):
            clear_focus(False)
        self._apply_controller_focus()

    def _refresh_custom_action_focus(self, previous_control: str) -> None:
        for control in (previous_control, self._navigation.control):
            if control not in ("custom:apply", "custom:delete"):
                continue
            widget = self._control_widgets.get(control)
            if widget is None:
                continue
            background = self._custom_control_background(control)
            try:
                widget.configure(
                    bg=background,
                    activebackground=background,
                    highlightbackground=background,
                    highlightcolor=background,
                    highlightthickness=0,
                )
            except tk.TclError:
                pass
        current = self._control_widgets.get(self._navigation.control)
        try:
            if current is not None and str(current.cget("state")) != "disabled":
                current.focus_set()
        except tk.TclError:
            pass

    def _open_module_from_pointer(self, item: tuple[str, int, str]) -> None:
        _label_key, _module_id, mode = item
        previous_control = self._navigation.control
        if mode == "custom":
            self._navigation = DesktopNavigationState(
                region="content",
                control="custom:add" if not self.images else "custom:0",
                section="layout",
                custom_open=True,
            )
            self.section = "layout"
            self.custom_open = True
        elif mode == "timeline":
            self._navigation = DesktopNavigationState(
                region="content",
                control=f"game-time:{self.game_time_display_mode}",
                section="layout",
                game_time_page=True,
            )
            self.section = "layout"
            self.custom_open = False
        else:
            self._navigation = DesktopNavigationState(
                region="content",
                control=f"module:{mode}",
                section="layout",
            )
            self.section = "layout"
            self.custom_open = False
            self._refresh_sidebar_focus()
            self._refresh_module_focus(previous_control)
        self._open_module(item)

    def _open_module(self, item: tuple[str, int, str], *, open_game_time_page: bool = True) -> None:
        _label_key, module_id, mode = item
        if mode == "timeline" and open_game_time_page:
            self._navigation = DesktopNavigationState(
                region="content",
                control=f"game-time:{self.game_time_display_mode}",
                section="layout",
                game_time_page=True,
            )
            self.custom_open = False
            self.section = "layout"
            self._render()
            return
        if mode == "custom":
            self.custom_open = True
            suffix = (
                self._navigation.control.split(":", 1)[1]
                if self._navigation.control.startswith("custom:")
                else ""
            )
            self.selected_custom_index = int(suffix) if suffix.isdigit() else -1
            if 0 <= self.selected_custom_index < len(self.images):
                self.selected_image = self.images[self.selected_custom_index]["path"]
            self._render()
            return
        self._module_request_id += 1
        request_id = self._module_request_id
        self.mode = mode
        self.sending = True
        self.progress = 0
        self._display_progress_state = "starting"
        if self.section == "layout" and not self.custom_open:
            self._render_module_progress()
        else:
            self._render()
        self._run_task(
            self._t("task_apply_layout"),
            lambda: self.backend.send_layout(mode, module_id),
            self._module_applied(request_id),
            lambda error: self._module_failed(request_id, error),
        )

    def _module_applied(self, request_id: int) -> Callable[[Any], None]:
        def callback(ok: Any) -> None:
            if request_id != self._module_request_id:
                return
            self.sending = False
            if ok:
                self.progress = 100
                self._display_progress_state = "complete"
            else:
                self.progress = 0
                self._display_progress_state = "failed"
            if self.section == "layout" and not self.custom_open:
                self._hide_module_progress()
            else:
                self._render()

        return callback

    def _module_failed(self, request_id: int, error: Exception) -> None:
        if request_id != self._module_request_id:
            return
        self.sending = False
        self.progress = 0
        self._display_progress_state = "failed"
        self._hide_module_progress()
        self._task_failed(self._t("task_apply_layout"), error)

    def _render_custom(self) -> None:
        if self._content is None:
            return
        self._custom_thumbnail_images = []
        visible = self.images
        if visible:
            selected_index = next(
                (
                    index
                    for index, item in enumerate(visible)
                    if item.get("path") == self.selected_image
                ),
                -1,
            )
            if selected_index >= 0:
                self.selected_custom_index = selected_index
            elif not (0 <= self.selected_custom_index < len(visible)):
                self.selected_custom_index = -1
        action_bar = self._create_action_bar(top=True)
        self._custom_action_bar = action_bar
        delete_enabled = 0 <= self.selected_custom_index < len(visible)
        apply_enabled = delete_enabled
        if self._custom_action is not None:
            self._render_custom_progress(action_bar)
        else:
            apply_button = self._create_action_button(
                action_bar,
                self._t("action_apply"),
                self._apply_selected,
                32,
                apply_enabled,
                primary=True,
                focused=self._navigation.control == "custom:apply",
            )
            delete_button = self._create_action_button(
                action_bar,
                self._t("action_delete"),
                self._delete_selected,
                CONTENT_W - 32 - 108,
                delete_enabled,
                primary=False,
                destructive=True,
                focused=self._navigation.control == "custom:delete",
            )
            self._control_widgets["custom:delete"] = delete_button
            self._control_widgets["custom:apply"] = apply_button

        viewport_y = ACTION_BAR_H
        viewport_height = WINDOW_H - viewport_y
        viewport_width = CONTENT_W - 14
        canvas = tk.Canvas(self._content, bg=BACKGROUND, bd=0, highlightthickness=0)
        canvas.place(x=0, y=viewport_y, width=viewport_width, height=viewport_height)
        scrollbar = tk.Scrollbar(
            self._content,
            orient="vertical",
            command=canvas.yview,
            width=14,
            bg=CONTROL_MUTED,
            troughcolor=BACKGROUND,
            activebackground=PURPLE,
            bd=0,
            highlightthickness=0,
            relief="flat",
        )
        scrollbar.place(x=viewport_width, y=viewport_y, width=14, height=viewport_height)
        canvas.configure(yscrollcommand=scrollbar.set)
        frame = tk.Frame(canvas, bg=BACKGROUND, width=viewport_width)
        window_id = canvas.create_window((0, 0), window=frame, anchor="nw", width=viewport_width)
        frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        self._custom_scroll_canvas = canvas
        if not visible:
            upload_background = self._custom_control_background("custom:add")
            button = tk.Button(
                frame,
                text=self._t("upload_local"),
                command=self._pick_photo_frame_folder,
                fg=WHITE,
                bg=upload_background,
                activebackground=PURPLE,
                activeforeground=WHITE,
                bd=0,
                relief="flat",
                font=self._fit_font(self._t("upload_local"), 300, 16, minimum=11),
                cursor="hand2",
                highlightbackground=upload_background,
                highlightthickness=0,
            )
            button.place(
                x=(viewport_width - _sx(318)) // 2,
                y=(viewport_height - _sy(48)) // 2,
                width=_sx(318),
                height=_sy(48),
            )
            frame.configure(height=viewport_height)
            self._control_widgets["custom:add"] = button
            back_button = tk.Button(
                frame,
                text=self._t("back"),
                command=lambda: self._handle_controller_action("back"),
                fg=WHITE if self._custom_control_background("custom:back") == PURPLE else SUBTLE,
                bg=self._custom_control_background("custom:back"),
                activebackground=PURPLE,
                activeforeground=WHITE,
                bd=0,
                relief="flat",
                font=self._fit_font(self._t("back"), 120, 14, minimum=10),
                cursor="hand2",
            )
            back_button.place(
                x=_sx(24), y=viewport_height - _sy(52), width=_sx(120), height=_sy(36)
            )
            self._control_widgets["custom:back"] = back_button
            return
        card_x = (viewport_width - ASSET_CARD_W * 2 - _sx(70)) // 2
        for index, image in enumerate(visible):
            row, col = divmod(index, 2)
            selected = index == self.selected_custom_index
            thumbnail_data = str(
                image.get("color_thumbnail_png_base64") or image.get("thumbnail_png_base64") or ""
            )
            thumbnail = None
            if thumbnail_data:
                try:
                    thumbnail = tk.PhotoImage(data=thumbnail_data)
                    self._custom_thumbnail_images.append(thumbnail)
                except tk.TclError:
                    thumbnail = None
            button = tk.Button(
                frame,
                text="" if thumbnail is not None else self._t("thumbnail"),
                image=thumbnail if thumbnail is not None else "",
                compound="center",
                command=lambda value=index: self._select_custom(value),
                fg=WHITE if selected else SUBTLE,
                bg=CARD_BG,
                activebackground=CARD_BG,
                activeforeground=WHITE,
                highlightbackground=PURPLE if selected else CARD_BORDER,
                highlightcolor=PURPLE if selected else CARD_BORDER,
                highlightthickness=3 if selected else 1,
                bd=0,
                relief="flat",
                font=self._fit_font(self._t("thumbnail"), ASSET_CARD_W - 10, 17, minimum=11),
                cursor="hand2",
                padx=2,
                pady=2,
            )
            button.place(
                x=card_x + col * (ASSET_CARD_W + _sx(70)),
                y=_sy(12) + row * (ASSET_CARD_H + _sy(19)),
                width=ASSET_CARD_W,
                height=ASSET_CARD_H,
            )
            self._control_widgets[f"custom:{index}"] = button
        row_count = math.ceil(len(visible) / 2)
        upload_y = _sy(12) + row_count * (ASSET_CARD_H + _sy(19)) + _sy(12)
        upload_background = self._custom_control_background("custom:add")
        add_button = tk.Button(
            frame,
            text=self._t("upload_local"),
            command=self._pick_photo_frame_folder,
            fg=WHITE if upload_background == PURPLE else SUBTLE,
            bg=upload_background,
            activebackground=PURPLE,
            activeforeground=WHITE,
            highlightbackground=upload_background,
            highlightcolor=upload_background,
            highlightthickness=0,
            bd=0,
            relief="flat",
            font=self._fit_font(self._t("upload_local"), 300, 16, minimum=11),
            cursor="hand2",
        )
        add_button.place(
            x=(viewport_width - _sx(318)) // 2, y=upload_y, width=_sx(318), height=_sy(48)
        )
        frame.configure(height=max(viewport_height, upload_y + 60))
        self._control_widgets["custom:add"] = add_button
        back_button = tk.Button(
            frame,
            text=self._t("back"),
            command=lambda: self._handle_controller_action("back"),
            fg=WHITE if self._custom_control_background("custom:back") == PURPLE else SUBTLE,
            bg=self._custom_control_background("custom:back"),
            activebackground=PURPLE,
            activeforeground=WHITE,
            highlightbackground=self._custom_control_background("custom:back"),
            highlightcolor=self._custom_control_background("custom:back"),
            highlightthickness=0,
            bd=0,
            relief="flat",
            font=self._fit_font(self._t("back"), 120, 14, minimum=10),
            cursor="hand2",
        )
        back_button.place(x=_sx(24), y=upload_y + _sy(62), width=_sx(120), height=_sy(36))
        frame.configure(height=max(viewport_height, upload_y + _sy(108)))
        self._control_widgets["custom:back"] = back_button

    def _custom_control_background(self, control: str) -> str:
        if control == "custom:add":
            return (
                PURPLE
                if self._navigation.region == "content" and self._navigation.control == control
                else BUTTON_BG
            )
        if self._navigation.region != "content" or self._navigation.control != control:
            return BUTTON_BG
        return RED if control == "custom:delete" else PURPLE

    def _render_custom_progress(self, parent: Optional[tk.Frame] = None) -> None:
        progress = max(0, min(100, int(self.progress)))
        bar_x = _sx(32)
        bar_w = CONTENT_W - bar_x * 2
        if parent is not None and (
            self._custom_progress_label is None or not self._custom_progress_label.winfo_exists()
        ):
            self._custom_progress_label = tk.Label(
                parent,
                fg=WHITE,
                bg=BACKGROUND,
                font=self._font(13, "bold"),
            )
            self._custom_progress_label.place(x=bar_x, y=_sy(8), width=bar_w, height=_sy(26))
        if parent is not None and (
            self._custom_progress_canvas is None or not self._custom_progress_canvas.winfo_exists()
        ):
            self._custom_progress_canvas = tk.Canvas(
                parent,
                width=bar_w,
                height=_sy(22),
                bg=BACKGROUND,
                bd=0,
                highlightthickness=0,
            )
            self._custom_progress_canvas.place(x=bar_x, y=_sy(44), width=bar_w, height=_sy(22))
        if self._custom_progress_label is None or self._custom_progress_canvas is None:
            return
        action_key = "action_delete" if self._custom_action == "delete" else "action_apply"
        self._custom_progress_label.configure(text=f"{self._t(action_key)} {progress}%")
        canvas = self._custom_progress_canvas
        canvas.delete("progress")
        canvas.create_line(
            _sx(8),
            _sy(11),
            bar_w - _sx(8),
            _sy(11),
            fill=BUTTON_BG,
            width=_sx(8),
            capstyle=tk.ROUND,
            tags="progress",
        )
        if progress:
            progress_x = _sx(8) + (bar_w - _sx(16)) * progress / 100
            canvas.create_line(
                _sx(8),
                _sy(11),
                progress_x,
                _sy(11),
                fill=PURPLE,
                width=_sx(8),
                capstyle=tk.ROUND,
                tags="progress",
            )

    def _render_firmware(self) -> None:
        if self._content is None:
            return
        tk.Label(
            self._content,
            text=self._t("firmware_current"),
            fg=MUTED,
            bg=BACKGROUND,
            font=self._fit_font(self._t("firmware_current"), 200, 13),
        ).place(x=(CONTENT_W - _sx(200)) // 2, y=_sy(170), width=_sx(200), height=_sy(36))
        tk.Label(
            self._content,
            text=CURRENT_FW,
            fg=MUTED,
            bg=BACKGROUND,
            highlightbackground=CARD_BORDER,
            highlightthickness=1,
            font=self._font(13),
        ).place(x=(CONTENT_W - _sx(150)) // 2, y=_sy(216), width=_sx(150), height=_sy(40))
        action_bar = self._create_action_bar()
        firmware_button = self._create_action_button(
            action_bar,
            self._t("no_updates"),
            lambda: None,
            (CONTENT_W - 108) // 2,
            False,
            primary=True,
        )
        self._control_widgets["firmware"] = firmware_button

    def _create_action_bar(self, *, top: bool = False) -> tk.Frame:
        if self._content is None:
            raise RuntimeError("Desktop content has not been created")
        bar = tk.Frame(self._content, width=CONTENT_W, height=ACTION_BAR_H, bg=BACKGROUND)
        bar.place(x=0, y=0 if top else WINDOW_H - ACTION_BAR_H)
        bar.pack_propagate(False)
        tk.Frame(bar, bg=BOTTOM_DIVIDER).place(
            x=0, y=ACTION_BAR_H - 1 if top else 0, width=CONTENT_W, height=1
        )
        return bar

    def _create_action_button(
        self,
        parent: tk.Frame,
        text: str,
        command: Callable[[], None],
        x: int,
        enabled: bool,
        primary: bool,
        destructive: bool = False,
        focused: bool = False,
    ) -> tk.Button:
        background = (
            RED
            if destructive and enabled and focused
            else PURPLE if primary and enabled and focused else BUTTON_BG
        )
        active_background = (
            RED if destructive and enabled else PURPLE_BRIGHT if primary and enabled else BUTTON_BG
        )
        button = tk.Button(
            parent,
            text=text,
            command=command,
            state="normal" if enabled else "disabled",
            fg=WHITE,
            disabledforeground=SUBTLE,
            bg=background,
            activebackground=active_background,
            activeforeground=WHITE,
            bd=0,
            relief="flat",
            font=self._fit_font(text, 100, 14, minimum=9),
            cursor="hand2",
            highlightbackground=background,
            highlightcolor=background,
            highlightthickness=0,
        )
        button.place(x=x, y=_sy(32), width=_sx(108), height=_sy(36))
        return button

    def _select_section(self, section: str) -> None:
        self._preference_picker = ""
        self._preference_generation += 1
        self.section = section
        self.custom_open = False
        self.connection_page = False
        self.selected_custom_index = -1
        self._navigation = DesktopNavigationState(region="nav", control=section, section=section)
        self._render()

    def _open_connection_page(self) -> None:
        if self.section != "screen":
            return
        self.connection_page = True
        self._navigation = DesktopNavigationState(
            region="content",
            control="connection:back",
            section="screen",
            connection_page=True,
        )
        self._render()

    def _close_connection_page(self) -> None:
        self.connection_page = False
        self._navigation = DesktopNavigationState(
            region="content", control="connection", section="screen"
        )
        self._render()

    def _toggle_connection(self) -> None:
        self._open_connection_page()

    def _refresh_connection_candidates(self) -> None:
        if (
            not self.connection_page
            or self.devices_scanning
            or self.disconnecting
            or self._connection_command_pending
            or self.sending
        ):
            return
        self.devices_scanning = True
        self._connection_spinner_angle = 0.0
        self._refresh_connection_state_visuals()
        refresh = self._control_widgets.get("connection:refresh")
        if refresh is not None:
            refresh._spinning = True
            refresh.set_spinner_angle(0.0)
            self._start_connection_spinner()
        self._run_task(
            self._t("task_refresh_status"),
            self.backend.scan,
            self._connection_scan_complete,
        )

    def _connection_scan_complete(self, result: Any) -> None:
        self.devices_scanning = False
        raw_candidates = result if isinstance(result, list) else []
        self.connection_candidates = merge_eink_candidates(
            raw_candidates,
            connected_address=self.connected_address,
            connected=self.connected,
        )
        self._render()
        self._run_task(
            self._t("task_refresh_status"),
            self.backend.get_status,
            self._connection_scan_status_complete,
        )

    def _connection_scan_status_complete(self, status: dict[str, Any]) -> None:
        self._apply_status(status)
        error = str(status.get("last_error") or "").strip()
        if (
            not self.connection_candidates
            and error
            and not error.lower().startswith("bluetooth busy:")
        ):
            messagebox.showwarning(APP_TITLE, error)

    def _toggle_connection_candidate(self, index: int) -> None:
        if (
            self.devices_scanning
            or self.disconnecting
            or self._connection_command_pending
            or self.sending
            or not (0 <= index < len(self.connection_candidates))
        ):
            return
        address = _normalize_eink_address(self.connection_candidates[index].get("address"))
        if not address:
            return
        if self.connected:
            if address != self.connected_address:
                return
            self.disconnecting = True
            self._connection_command_pending = True
            self._connection_action_address = address
            self._refresh_connection_state_visuals()
            self._run_task(
                self._t("task_disconnect"), self.backend.disconnect, self._disconnect_complete
            )
            return
        self._connection_command_pending = True
        self._connection_action_address = address
        self._connection_animation_started_at = time.monotonic()
        self._refresh_connection_state_visuals()
        self._run_task(
            self._t("task_connect"),
            lambda: self.backend.connect(address),
            self._connection_complete,
        )

    def _connection_complete(self, result: Any) -> None:
        self._connection_command_pending = False
        self._connection_action_address = ""
        if isinstance(result, dict):
            result_state = self._status_connection_state(result)
            if not (
                getattr(self, "connection_state", "off") == "on" and result_state == "connecting"
            ):
                self._apply_status(result)
                return
        self._reload_status()

    def _finish_connection(self, result: Any) -> None:
        self._connection_complete(result)

    def _disconnect_complete(self, result: Any) -> None:
        self._connection_command_pending = False
        self._connection_action_address = ""
        self.disconnecting = False
        if isinstance(result, dict):
            self._apply_status(result)
        else:
            self._reload_status()

    def _photo_frame_interval_changed(self, value: float) -> None:
        self.photo_frame_interval = max(1, min(60, int(float(value))))
        self.backend.save_settings({"photo_frame_interval_minutes": self.photo_frame_interval})
        label = self._screen_value_labels.get("photo-frame")
        if label is not None and label.winfo_exists():
            label.configure(text=self._t("minutes_short", value=self.photo_frame_interval))

    def _toggle_photo_frame_interval_enabled(self) -> None:
        self.photo_frame_interval_enabled = not self.photo_frame_interval_enabled
        if self.photo_frame_interval_enabled:
            self.module_switch_enabled = False
        self.backend.save_settings(
            {
                "photo_frame_interval_enabled": self.photo_frame_interval_enabled,
                "module_switch_enabled": self.module_switch_enabled,
            }
        )
        self._refresh_screen_switches()

    def _module_switch_interval_changed(self, value: float) -> None:
        self.module_switch_interval = max(5, min(60, int(float(value)) // 5 * 5))
        self.backend.save_settings({"module_switch_interval_minutes": self.module_switch_interval})
        label = self._screen_value_labels.get("module-switch")
        if label is not None and label.winfo_exists():
            label.configure(text=self._t("minutes_short", value=self.module_switch_interval))

    def _toggle_module_switch_enabled(self) -> None:
        self.module_switch_enabled = not self.module_switch_enabled
        if self.module_switch_enabled:
            self.photo_frame_interval_enabled = False
        self.backend.save_settings(
            {
                "module_switch_enabled": self.module_switch_enabled,
                "photo_frame_interval_enabled": self.photo_frame_interval_enabled,
            }
        )
        self._refresh_screen_switches()

    def _refresh_screen_switches(self) -> None:
        for key, enabled in (
            ("photo-frame-toggle", self.photo_frame_interval_enabled),
            ("module-switch-toggle", self.module_switch_enabled),
        ):
            widget = self._control_widgets.get(key)
            if widget is not None and widget.winfo_exists():
                widget._enabled = bool(enabled)
                widget._draw()
        for key, enabled in (
            ("photo-frame", self.photo_frame_interval_enabled),
            ("module-switch", self.module_switch_enabled),
        ):
            widget = self._control_widgets.get(key)
            setter = getattr(widget, "set_enabled", None)
            if callable(setter):
                setter(enabled)
        self._refresh_screen_focus()

    def _refresh_screen_interval_state(self) -> None:
        for key, value in (
            ("photo-frame", self.photo_frame_interval),
            ("module-switch", self.module_switch_interval),
        ):
            label = self._screen_value_labels.get(key)
            if label is not None and label.winfo_exists():
                label.configure(text=self._t("minutes_short", value=value))
            slider = self._control_widgets.get(key)
            setter = getattr(slider, "set", None)
            if callable(setter):
                setter(value, notify=False)
        self._refresh_screen_switches()

    def _refresh_custom_selection_visuals(self) -> None:
        """Update selection visuals in place without rebuilding the page."""
        selected_index = self.selected_custom_index
        for index, _image in enumerate(self.images):
            widget = self._control_widgets.get(f"custom:{index}")
            if widget is None or not widget.winfo_exists():
                continue
            selected = index == selected_index
            try:
                widget.configure(
                    fg=WHITE if selected else SUBTLE,
                    highlightbackground=PURPLE if selected else CARD_BORDER,
                    highlightcolor=PURPLE if selected else CARD_BORDER,
                    highlightthickness=3 if selected else 1,
                )
            except tk.TclError:
                continue
        enabled = 0 <= selected_index < len(self.images) and self._custom_action is None
        for control in ("custom:apply", "custom:delete"):
            widget = self._control_widgets.get(control)
            if widget is None or not widget.winfo_exists():
                continue
            try:
                widget.configure(state=tk.NORMAL if enabled else tk.DISABLED)
            except tk.TclError:
                pass
        self._apply_controller_focus()

    def _select_custom(self, index: int, enter_actions: bool = False) -> None:
        self.selected_custom_index = index
        if index < len(self.images):
            self.selected_image = self.images[index]["path"]
            if not enter_actions:
                self._navigation = DesktopNavigationState(
                    region="content",
                    control=f"custom:{index}",
                    section="layout",
                    custom_open=True,
                )
            self._run_task(
                self._t("task_select_asset"),
                lambda: self.backend.set_photo_frame_selected_file(self.selected_image),
            )
            if enter_actions:
                self._custom_action_return_control = f"custom:{index}"
                self._navigation = DesktopNavigationState(
                    region="content",
                    control="custom:apply",
                    section="layout",
                    custom_open=True,
                )
        self._refresh_custom_selection_visuals()

    def _pick_native_photo_folder(self) -> Optional[str]:
        """Open KDE's native folder picker for the photo-frame folder."""
        initial_dir = str(Path.home() / "Pictures")
        title = f"{self._t('task_import_asset')} — {APP_TITLE}"
        env = os.environ.copy()
        # The app can be launched from Steam/Decky with an inherited X11 Qt
        # platform. Force the KDE Wayland backend so a
        # transient launch context cannot silently fall back to Tk.
        env["QT_QPA_PLATFORM"] = "wayland"
        env["QT_QPA_PLATFORMTHEME"] = "kde"
        try:
            result = subprocess.run(
                [
                    "kdialog",
                    "--title",
                    title,
                    "--getexistingdirectory",
                    initial_dir,
                ],
                capture_output=True,
                text=True,
                env=env,
                timeout=300,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError) as error:
            LOGGER.warning("KDE native file picker unavailable: %s", error)
            return None
        if result.returncode != 0:
            return ""
        return result.stdout.strip()

    def _pick_photo_frame_folder(self) -> None:
        path = self._pick_native_photo_folder()
        if path is None:
            path = filedialog.askdirectory(
                title=self._t("upload_local"),
                initialdir=str(Path.home() / "Pictures"),
            )
        if not path:
            return
        self._run_task(
            self._t("task_import_asset"),
            lambda: self.backend.set_photo_frame_folder(path),
            self._photo_frame_folder_selected,
        )

    def _photo_frame_folder_selected(self, result: Any) -> None:
        select_first = result is True
        if isinstance(result, dict):
            selected_path = str(result.get("path") or "")
            if selected_path:
                self.selected_image = selected_path
        self._reload_images(select_first=select_first)

    def _delete_selected(self) -> None:
        if self._custom_action is not None or not (
            0 <= self.selected_custom_index < len(self.images)
        ):
            return
        deleted_index = self.selected_custom_index
        path = self.images[self.selected_custom_index]["path"]
        self._begin_custom_action("delete")
        self._run_task(
            self._t("task_delete_asset"),
            lambda: self.backend.exclude_photo_frame_file(path),
            lambda ok: self._custom_delete_removed(ok, deleted_index),
            lambda error: self._custom_action_failed(self._t("task_delete_asset"), error),
        )

    def _apply_selected(self) -> None:
        if self._custom_action is not None:
            return
        if not (0 <= self.selected_custom_index < len(self.images)):
            return
        path = self.images[self.selected_custom_index]["path"]
        self._begin_custom_action("apply")
        self._run_task(
            self._t("task_apply_asset"),
            lambda: self.backend.send_custom_file(path),
            lambda ok: self._custom_applied(path, ok),
            lambda error: self._custom_action_failed(self._t("task_apply_asset"), error),
        )

    def _begin_custom_action(self, action: str) -> None:
        self._custom_action = action
        self.sending = action == "apply"
        self.progress = 0
        if action == "delete" and self._custom_action_bar is not None:
            self._render_custom_progress(self._custom_action_bar)
            self._refresh_custom_selection_visuals()
            return
        self._render()

    def _custom_delete_removed(self, ok: Any, deleted_index: int) -> None:
        if not ok:
            self._custom_action = None
            self.progress = 0
            self._render()
            return
        self.progress = 50
        self._render_custom_progress()
        self._run_task(
            self._t("task_load_assets"),
            self.backend.list_photo_frame_files,
            lambda items: self._custom_delete_reloaded(items, deleted_index),
            lambda error: self._custom_action_failed(self._t("task_load_assets"), error),
        )

    def _custom_delete_reloaded(self, items: list[dict[str, Any]], deleted_index: int) -> None:
        self.progress = 100
        self._render_custom_progress()
        self.root.after_idle(lambda: self._finish_custom_delete(items, deleted_index))

    def _finish_custom_delete(self, items: list[dict[str, Any]], deleted_index: int) -> None:
        self._custom_action = None
        self._apply_images(items, False, focus_index=deleted_index)

    def _custom_applied(self, path: str, ok: Any) -> None:
        self.progress = 100 if ok else 0
        if ok:
            self._render_custom_progress()
            self.root.after_idle(lambda: self._finish_custom_apply(path))
            return
        self.sending = False
        self._custom_action = None
        self._render()

    def _finish_custom_apply(self, path: str) -> None:
        self.sending = False
        self._custom_action = None
        self.selected_image = path
        self.mode = "custom"
        control = self._custom_action_return_control
        if not control.startswith("custom:") or not control.split(":", 1)[1].isdigit():
            control = f"custom:{max(0, self.selected_custom_index)}"
        self._navigation = DesktopNavigationState(
            region="content",
            control=control,
            section="layout",
            custom_open=True,
        )
        self._render()

    def _custom_action_failed(self, label: str, error: Exception) -> None:
        self._custom_action = None
        self.progress = 0
        self._task_failed(label, error)

    def _run_task(
        self,
        label: str,
        func: Callable[[], Any],
        callback: Optional[Callable[[Any], None]] = None,
        error_callback: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        def worker() -> None:
            try:
                result = func()
                self.root.after(0, lambda value=result: callback(value) if callback else None)
            except Exception as error:
                self.root.after(
                    0,
                    lambda caught=error: (
                        error_callback(caught)
                        if error_callback
                        else self._task_failed(label, caught)
                    ),
                )

        threading.Thread(target=worker, daemon=True).start()

    def _task_failed(self, label: str, error: Exception) -> None:
        self._connection_command_pending = False
        self._connection_action_address = ""
        self.devices_scanning = False
        self.disconnecting = False
        self.sending = False
        self._render()
        connection_task_labels = {
            self._t("task_connect"),
            self._t("task_disconnect"),
            self._t("task_refresh_status"),
        }
        if not self._closed and label not in connection_task_labels:
            messagebox.showerror(APP_TITLE, self._t("task_failed", label=label, error=error))

    def _load_initial_state(self) -> None:
        self._run_task(
            self._t("task_load_status"), self.backend.get_control_state, self._apply_control_state
        )
        self._reload_images()

    def _reload_status(self) -> None:
        self._run_task(self._t("task_refresh_status"), self.backend.get_status, self._apply_status)

    def _reload_images(self, select_first: bool = False, focus_index: Optional[int] = None) -> None:
        self._run_task(
            self._t("task_load_assets"),
            self.backend.list_photo_frame_files,
            lambda items: self._apply_images(items, select_first, focus_index),
        )

    def _apply_control_state(self, snapshot: dict[str, Any]) -> None:
        if not isinstance(snapshot, dict):
            return
        epoch = str(snapshot.get("epoch") or "")
        try:
            revision = int(snapshot.get("revision", -1))
        except (TypeError, ValueError):
            revision = -1
        if epoch and epoch != getattr(self, "_control_state_epoch", ""):
            self._control_state_epoch = epoch
            self._control_state_revision = -1
        if epoch and revision <= getattr(self, "_control_state_revision", -1):
            return
        if epoch and revision >= 0:
            self._control_state_revision = revision
        previous_status_signature = (
            self.connection_state,
            self.connected,
            self.connected_address,
            self.scanning,
            self.devices_scanning,
            self.disconnecting,
        )
        status = snapshot.get("status")
        if isinstance(status, dict):
            self._apply_status(status, render=False)
        if isinstance(snapshot.get("agent_status"), dict):
            self.agent_status = dict(snapshot.get("agent_status") or {})
        settings = snapshot.get("settings")
        if isinstance(settings, dict):
            self._apply_settings(settings, render=False)
        current_status_signature = (
            self.connection_state,
            self.connected,
            self.connected_address,
            self.scanning,
            self.devices_scanning,
            self.disconnecting,
        )
        if (
            self.section == "screen"
            and not self.connection_page
            and not self.custom_open
            and current_status_signature == previous_status_signature
        ):
            # Saving an interval value publishes a control_state_update.  The
            # screen is already built, so update only its controls; rebuilding
            # the content would clear it and create a visible flash.
            self._refresh_screen_interval_state()
            return
        if self.custom_open:
            self._refresh_custom_selection_visuals()
        else:
            self._render()

    def _apply_status(self, status: dict[str, Any], *, render: bool = True) -> None:
        next_state = self._status_connection_state(status)
        if next_state == "off" and self.sending:
            # The daemon reports a lost link before its bounded retry loop
            # returns. Never leave the pre-connect 5% marker on screen.
            self._display_progress_state = "retrying"
            self.progress = 0
        previous_state = getattr(
            self,
            "connection_state",
            (
                "connecting"
                if getattr(self, "scanning", False)
                else ("on" if getattr(self, "connected", False) else "off")
            ),
        )
        self._connection_status_generation = getattr(self, "_connection_status_generation", 0) + 1
        generation = self._connection_status_generation
        if next_state == "connecting" and previous_state != "connecting":
            if not getattr(self, "_connection_command_pending", False):
                self._connection_animation_started_at = time.monotonic()
        if (
            next_state == "on"
            and previous_state == "connecting"
            and not getattr(self, "_closed", False)
        ):
            started_at = float(getattr(self, "_connection_animation_started_at", 0.0) or 0.0)
            elapsed_ms = (
                int((time.monotonic() - started_at) * 1000)
                if started_at
                else CONNECTION_ON_ANIMATION_MS
            )
            remaining_ms = max(0, CONNECTION_ON_ANIMATION_MS - elapsed_ms)
            if remaining_ms:
                self.root.after(
                    remaining_ms,
                    lambda value=dict(status), token=generation: self._apply_deferred_status(
                        value, token
                    ),
                )
                return
        self._commit_status(status, next_state, previous_state, render=render)

    def _apply_deferred_status(self, status: dict[str, Any], generation: int) -> None:
        if generation != self._connection_status_generation or getattr(self, "_closed", False):
            return
        previous_state = getattr(self, "connection_state", "off")
        self._commit_status(status, self._status_connection_state(status), previous_state)

    def _commit_status(
        self,
        status: dict[str, Any],
        next_state: str,
        previous_state: str,
        *,
        render: bool = True,
    ) -> None:
        self.connection_state = next_state
        self.connected = next_state == "on"
        self.connected_address = (
            _normalize_eink_address(status.get("address")) if self.connected else ""
        )
        if isinstance(status.get("agent_status"), dict):
            self.agent_status = dict(status.get("agent_status") or {})
        self.connection_candidates = merge_eink_candidates(
            self.connection_candidates,
            connected_address=self.connected_address,
            connected=self.connected,
        )
        self.scanning = next_state == "connecting"
        if self.scanning:
            self._last_connection_failure = ""
        else:
            self._connection_animation_started_at = 0.0
        if render:
            self._render()
        elif self.custom_open:
            self._refresh_custom_selection_visuals()

    @staticmethod
    def _status_connection_state(status: dict[str, Any]) -> str:
        state = str(status.get("connection_state") or "").strip().lower()
        if state in ("off", "connecting", "on"):
            return state
        return "on" if status.get("connected") else "off"

    @staticmethod
    def _status_is_enabled(status: dict[str, Any]) -> bool:
        return DesktopApp._status_connection_state(status) == "on"

    def _apply_settings(self, settings: dict[str, Any], *, render: bool = True) -> None:
        self._apply_preferences(settings)
        raw_photo_frame_interval = settings.get("photo_frame_interval_minutes", 5)
        try:
            parsed_photo_frame_interval = int(raw_photo_frame_interval)
        except (TypeError, ValueError):
            parsed_photo_frame_interval = 5
        self.photo_frame_interval = max(1, min(60, parsed_photo_frame_interval))
        self.photo_frame_interval_enabled = bool(
            settings.get("photo_frame_interval_enabled", False)
        )
        raw_module_switch_interval = settings.get("module_switch_interval_minutes", 5)
        try:
            parsed_module_switch_interval = int(raw_module_switch_interval)
        except (TypeError, ValueError):
            parsed_module_switch_interval = 5
        self.module_switch_interval = max(5, min(60, parsed_module_switch_interval // 5 * 5))
        self.module_switch_enabled = bool(settings.get("module_switch_enabled", False))
        if self.photo_frame_interval_enabled:
            self.module_switch_enabled = False
        elif self.module_switch_enabled:
            self.photo_frame_interval_enabled = False
        configured_game_time_mode = str(
            settings.get("game_time_display_mode", "auto") or "auto"
        ).lower()
        self.game_time_display_mode = (
            configured_game_time_mode
            if configured_game_time_mode in ("time", "poster", "auto")
            else "auto"
        )
        raw_mode = str(settings.get("mode", "deck_status") or "deck_status")
        try:
            active_module_id = int(
                settings.get("active_module_id", settings.get("single_module_id", -1)) or -1
            )
        except (TypeError, ValueError):
            active_module_id = -1
        module_mode = {
            0: "carousel",
            1: "timeline",
            2: "deck_status",
            3: "weather",
            4: "clock",
            5: "calendar",
            6: "custom",
            7: "agent",
        }.get(active_module_id)
        if raw_mode in ("dashboard", "carousel"):
            self.mode = "carousel"
        elif module_mode:
            self.mode = module_mode
        elif raw_mode in ("clock", "weather", "deck_status", "timeline"):
            self.mode = raw_mode
        else:
            self.mode = "deck_status"
        self.selected_image = str(settings.get("custom_selected_path", "") or "")
        if render and not self.custom_open:
            self._render()
        elif self.custom_open:
            self._refresh_custom_selection_visuals()

    def _apply_images(
        self,
        items: list[dict[str, Any]],
        select_first: bool,
        focus_index: Optional[int] = None,
    ) -> None:
        self.images = list(items or [])
        if focus_index is not None:
            if self.images:
                self.selected_custom_index = max(0, min(focus_index, len(self.images) - 1))
                self.selected_image = self.images[self.selected_custom_index]["path"]
                self.backend.set_photo_frame_selected_file(self.selected_image)
                self._custom_action_return_control = f"custom:{self.selected_custom_index}"
            else:
                self.selected_custom_index = -1
                self.selected_image = ""
                self._custom_action_return_control = "custom:add"
            self._navigation = DesktopNavigationState(
                region="content",
                control=self._custom_action_return_control,
                section="layout",
                custom_open=True,
            )
        elif select_first and self.images:
            self.selected_custom_index = 0
            self.selected_image = self.images[0]["path"]
            self.backend.set_photo_frame_selected_file(self.selected_image)
        else:
            self.selected_custom_index = next(
                (
                    i
                    for i, item in enumerate(self.images)
                    if item.get("path") == self.selected_image
                ),
                -1,
            )
        self._render()

    def _poll_backend(self) -> None:
        if self._closed:
            return
        for event, payload in self.backend.poll_events():
            if event == "control_state_update" and isinstance(payload, dict):
                self._apply_control_state(payload)
            elif event == "status_update" and isinstance(payload, dict):
                self._apply_status(payload)
            elif event == "agent_status_update" and isinstance(payload, dict):
                self.agent_status = dict(payload)
                self._render()
            elif event == "display_state" and isinstance(payload, dict):
                # Background module refreshes use the same daemon as the
                # desktop UI. Only their numeric progress is shared; a failed
                # background transfer must not cancel a newer user request.
                state = str(payload.get("state") or "")
                if payload.get("foreground") or not self.sending:
                    self._display_progress_state = state
                    if payload.get("progress") is not None:
                        self.progress = max(0, min(100, int(payload["progress"])))
                    if state == "failed":
                        self.sending = False
                        self.progress = 0
                        if self._custom_action == "apply":
                            self._custom_action = None
                        self._hide_module_progress()
                        self._render()
                    elif self.sending and self.section == "layout" and not self.custom_open:
                        self._render_module_progress()
            elif event == "progress":
                custom_action = getattr(self, "_custom_action", None)
                if custom_action == "delete":
                    continue
                self.progress = max(0, min(100, int(payload or 0)))
                if custom_action == "apply" and self.custom_open:
                    self._render_custom_progress()
                elif self.sending:
                    if self.section == "layout" and not self.custom_open:
                        self._render_module_progress()
                    else:
                        self._render()
            elif event == "custom_file_selected" and isinstance(payload, dict):
                self.selected_image = str(payload.get("path") or "")
                self.selected_custom_index = next(
                    (
                        index
                        for index, item in enumerate(self.images)
                        if item.get("path") == self.selected_image
                    ),
                    -1,
                )
                if self.custom_open:
                    self._refresh_custom_selection_visuals()
        self.root.after(250, self._poll_backend)

    def _request_close(self) -> None:
        if self._closed or self._navigation.exit_confirming:
            return
        self._navigation = DesktopNavigationState(
            region=self._navigation.region,
            control=self._navigation.control,
            section=self._navigation.section,
            custom_open=self._navigation.custom_open,
            connection_page=self._navigation.connection_page,
            game_time_page=self._navigation.game_time_page,
            exit_confirming=True,
            exit_choice="cancel",
        )
        self._render_exit_confirmation()

    def _queue_controller_action(self, action: str) -> str:
        if (
            self._preference_picker
            and self.root.focus_get() == getattr(self, "_preference_entry", None)
            and action in ("left", "right", "back", "activate")
        ):
            return ""
        self._controller_queue.put((action, time.monotonic() * 1000.0))
        return "break"

    def _poll_controller(self) -> None:
        if self._closed:
            return
        while True:
            try:
                action, captured_at_ms = self._controller_queue.get_nowait()
            except queue.Empty:
                break
            if self._controller_gate.accept(action, captured_at_ms):
                self._handle_controller_action(action)
        self.root.after(30, self._poll_controller)

    def _poll_touch(self) -> None:
        if self._closed:
            return
        while True:
            try:
                event = self._touch_queue.get_nowait()
            except queue.Empty:
                break
            self._dispatch_touch_event(event)
        self.root.after(8, self._poll_touch)

    def _dispatch_touch_event(self, event: RawTouchEvent) -> None:
        screen_x, screen_y = map_steam_deck_touch_to_screen(
            event.x,
            event.y,
            self.root.winfo_screenwidth(),
            self.root.winfo_screenheight(),
        )
        if event.kind == "down":
            self._touch_target = self.root.winfo_containing(screen_x, screen_y)
        target = self._touch_target
        if target is None:
            return
        try:
            if not target.winfo_exists():
                self._touch_target = None
                return
            local_x = screen_x - target.winfo_rootx()
            local_y = screen_y - target.winfo_rooty()
            if event.kind == "down":
                target.event_generate("<ButtonPress-1>", x=local_x, y=local_y)
            elif event.kind == "move":
                target.event_generate("<B1-Motion>", x=local_x, y=local_y, state=0x0100)
            elif event.kind == "up":
                target.event_generate("<ButtonRelease-1>", x=local_x, y=local_y)
                self._touch_target = None
        except tk.TclError:
            self._touch_target = None

    def _handle_controller_action(self, action: str) -> None:
        if self._handle_preference_action(action):
            return
        LOGGER.info(
            "controller action=%s region=%s control=%s section=%s",
            action,
            self._navigation.region,
            self._navigation.control,
            self._navigation.section,
        )
        if self._navigation.exit_confirming:
            if action == "activate":
                if self._navigation.exit_choice == "exit":
                    self._on_close()
                else:
                    self._navigation = reduce_desktop_navigation(
                        self._navigation,
                        "back",
                        len(self.images),
                        len(self.connection_candidates),
                    )
                    self._hide_exit_confirmation()
                return
            previous_choice = self._navigation.exit_choice
            self._navigation = reduce_desktop_navigation(
                self._navigation,
                action,
                len(self.images),
                len(self.connection_candidates),
            )
            if not self._navigation.exit_confirming:
                self._hide_exit_confirmation()
            elif self._navigation.exit_choice != previous_choice:
                self._refresh_exit_confirmation_focus()
            return
        if (
            action == "back"
            and self._navigation.custom_open
            and self._navigation.control in ("custom:delete", "custom:apply")
        ):
            self._navigation = DesktopNavigationState(
                region="content",
                control=self._custom_action_return_control,
                section="layout",
                custom_open=True,
            )
            self._render()
            return
        if action == "activate":
            self._activate_controller_focus()
            return
        if action in ("left", "right") and self._navigation.control == "photo-frame":
            if not self.photo_frame_interval_enabled:
                return
            self.photo_frame_interval = max(
                1, min(60, self.photo_frame_interval + (-1 if action == "left" else 1))
            )
            self.backend.save_settings({"photo_frame_interval_minutes": self.photo_frame_interval})
            label = self._screen_value_labels.get("photo-frame")
            if label is not None and label.winfo_exists():
                label.configure(text=self._t("minutes_short", value=self.photo_frame_interval))
            return
        if action in ("left", "right") and self._navigation.control == "module-switch":
            if not self.module_switch_enabled:
                return
            index = (
                MODULE_SWITCH_INTERVAL_VALUES.index(self.module_switch_interval)
                if self.module_switch_interval in MODULE_SWITCH_INTERVAL_VALUES
                else 0
            )
            index = max(
                0,
                min(
                    len(MODULE_SWITCH_INTERVAL_VALUES) - 1, index + (-1 if action == "left" else 1)
                ),
            )
            self.module_switch_interval = MODULE_SWITCH_INTERVAL_VALUES[index]
            self.backend.save_settings(
                {"module_switch_interval_minutes": self.module_switch_interval}
            )
            label = self._screen_value_labels.get("module-switch")
            if label is not None and label.winfo_exists():
                label.configure(text=self._t("minutes_short", value=self.module_switch_interval))
            return
        previous = self._navigation
        self._navigation = reduce_desktop_navigation(
            self._navigation,
            action,
            len(self.images),
            len(self.connection_candidates),
        )
        self.section = self._navigation.section
        self.custom_open = self._navigation.custom_open
        self.connection_page = self._navigation.connection_page
        if self._navigation.game_time_page:
            self.section = "layout"
        if self.custom_open and self._navigation.control.startswith("custom:"):
            suffix = self._navigation.control.split(":", 1)[1]
            if suffix.isdigit():
                index = int(suffix)
                if 0 <= index < len(self.images):
                    self.selected_custom_index = index
                    self.selected_image = self.images[index]["path"]
        if previous != self._navigation:
            custom_image_focus_only = (
                previous.region == "content"
                and self._navigation.region == "content"
                and previous.section == "layout"
                and self._navigation.section == "layout"
                and previous.custom_open
                and self._navigation.custom_open
                and (
                    previous.control == "custom:add"
                    or self._navigation.control == "custom:add"
                    or previous.control.startswith("custom:")
                    and previous.control.split(":", 1)[1].isdigit()
                    or self._navigation.control.startswith("custom:")
                    and self._navigation.control.split(":", 1)[1].isdigit()
                )
            )
            root_focus_only = (
                previous.region == "nav"
                and self._navigation.region == "nav"
                and previous.section == self._navigation.section
                and not previous.exit_confirming
                and not self._navigation.exit_confirming
            )
            module_focus_only = (
                previous.region == "content"
                and self._navigation.region == "content"
                and previous.section == "layout"
                and self._navigation.section == "layout"
                and not previous.custom_open
                and not self._navigation.custom_open
                and previous.control.startswith("module:")
                and self._navigation.control.startswith("module:")
            )
            custom_action_focus_only = (
                previous.region == "content"
                and self._navigation.region == "content"
                and previous.section == "layout"
                and self._navigation.section == "layout"
                and previous.custom_open
                and self._navigation.custom_open
                and previous.control in ("custom:apply", "custom:delete")
                and self._navigation.control in ("custom:apply", "custom:delete")
            )
            if custom_image_focus_only:
                # Navigation-only updates stay in place: rebuilding the Tk
                # canvas on every D-pad step causes visible flicker and resets
                # the custom scroll position.
                self._refresh_custom_selection_visuals()
            elif root_focus_only:
                self._refresh_sidebar_focus()
                self._apply_controller_focus()
            elif module_focus_only:
                self._refresh_module_focus(previous.control)
            elif (
                previous.region == "content"
                and self._navigation.region == "content"
                and previous.section == "screen"
                and self._navigation.section == "screen"
                and previous.connection_page
                and self._navigation.connection_page
            ):
                self._refresh_connection_focus()
            elif (
                previous.region == "content"
                and self._navigation.region == "content"
                and previous.section == "screen"
                and self._navigation.section == "screen"
                and not previous.connection_page
                and not self._navigation.connection_page
            ):
                self._refresh_screen_focus()
            elif custom_action_focus_only:
                self._refresh_custom_action_focus(previous.control)
            else:
                self._render()

    def _activate_controller_focus(self) -> None:
        if self._navigation.region == "nav":
            self._navigation = reduce_desktop_navigation(
                self._navigation,
                "activate",
                len(self.images),
                len(self.connection_candidates),
            )
            self.section = self._navigation.section
            self.custom_open = self._navigation.custom_open
            self.connection_page = self._navigation.connection_page
            self._render()
            return
        control = self._navigation.control
        if control.startswith("settings:"):
            self._open_preference(control.split(":", 1)[1])
            return
        if control == "connection":
            self._open_connection_page()
            return
        if control == "photo-frame":
            self._toggle_photo_frame_interval_enabled()
            return
        if control == "module-switch":
            self._toggle_module_switch_enabled()
            return
        if control == "connection:back":
            self._close_connection_page()
            return
        if control == "connection:refresh":
            self._refresh_connection_candidates()
            return
        if control.startswith("connection:device:"):
            suffix = control.rsplit(":", 1)[-1]
            if suffix.isdigit():
                self._toggle_connection_candidate(int(suffix))
            return
        if control.startswith("game-time:"):
            selected_mode = control.split(":", 1)[1]
            if selected_mode == "back":
                self._navigation = reduce_desktop_navigation(
                    self._navigation, "back", len(self.images), len(self.connection_candidates)
                )
                self.section = self._navigation.section
                self.custom_open = self._navigation.custom_open
                self._render()
                return
            if selected_mode in ("time", "poster", "auto"):
                self._select_game_time_mode(selected_mode)
            return
        if control.startswith("module:"):
            mode = control.split(":", 1)[1]
            item = next((item for item in MODULES if item[2] == mode), None)
            if item is not None:
                if mode == "custom":
                    self._navigation = DesktopNavigationState(
                        region="content",
                        control="custom:add" if not self.images else "custom:0",
                        section="layout",
                        custom_open=True,
                    )
                self._open_module(item)
            return
        if control.startswith("custom:"):
            suffix = control.split(":", 1)[1]
            if suffix.isdigit():
                self._select_custom(int(suffix), enter_actions=True)
            elif suffix == "add":
                self._pick_photo_frame_folder()
            elif suffix == "delete":
                self._delete_selected()
            elif suffix == "apply":
                self._apply_selected()
            elif suffix == "back":
                self._handle_controller_action("back")
            return
        widget = self._control_widgets.get(control)
        if widget is None:
            return
        invoke = getattr(widget, "invoke", None)
        if callable(invoke) and str(widget.cget("state")) != "disabled":
            invoke()

    def _ensure_custom_control_visible(self, control: str, widget: tk.Misc) -> None:
        canvas = self._custom_scroll_canvas
        if canvas is None or not canvas.winfo_exists() or not widget.winfo_exists():
            return
        try:
            canvas.update_idletasks()
            if control == "custom:add":
                canvas.yview_moveto(1.0)
                return
            bbox = canvas.bbox("all")
            if not bbox:
                return
            viewport_height = max(1, canvas.winfo_height())
            content_height = max(viewport_height, int(bbox[3] - bbox[1]))
            max_offset = max(1, content_height - viewport_height)
            current_offset = float(canvas.canvasy(0))
            item_top = float(widget.winfo_y())
            item_bottom = item_top + max(1, widget.winfo_height())
            target_offset = current_offset
            if item_top < current_offset:
                target_offset = item_top
            elif item_bottom > current_offset + viewport_height:
                target_offset = item_bottom - viewport_height
            if target_offset != current_offset:
                canvas.yview_moveto(max(0.0, min(1.0, target_offset / max_offset)))
        except tk.TclError:
            pass

    def _apply_controller_focus(self) -> None:
        control = self._navigation.control
        widget = self._control_widgets.get(control)
        if widget is None:
            return
        try:
            if str(widget.cget("state")) == "disabled":
                return
            # The interval screen uses the row background as its focus cue.
            # Do not ask its Canvas controls to redraw when the joystick only
            # moves focus: CapsuleToggle.set_controller_focus() rebuilds all
            # of its items and causes a visible flash.  The existing value and
            # toggle handlers still redraw the single control when its state
            # actually changes.
            interval_focus_control = self._navigation.section == "screen" and control in {
                "photo-frame",
                "photo-frame-toggle",
                "module-switch",
                "module-switch-toggle",
            }
            set_controller_focus = getattr(widget, "set_controller_focus", None)
            if callable(set_controller_focus) and not interval_focus_control:
                set_controller_focus(True)
            elif control in ("custom:add", "custom:apply", "custom:delete", "custom:back"):
                background = self._custom_control_background(control)
                widget.configure(
                    bg=background,
                    activebackground=background,
                    highlightbackground=background,
                    highlightcolor=background,
                    highlightthickness=0,
                )
            elif control.startswith("custom:") and control.split(":", 1)[1].isdigit():
                # Focus is navigation-only; only the selected asset owns the purple border.
                focused_index = int(control.split(":", 1)[1])
                focused_color = (
                    PURPLE if focused_index == self.selected_custom_index else CARD_BORDER
                )
                focused_thickness = 3 if focused_index == self.selected_custom_index else 1
                widget.configure(
                    highlightbackground=focused_color,
                    highlightcolor=focused_color,
                    highlightthickness=focused_thickness,
                )
            elif self._navigation.section == "screen":
                pass
            else:
                widget.configure(
                    highlightbackground=PURPLE, highlightcolor=PURPLE, highlightthickness=3
                )
            # Keyboard/gamepad events are bound at the root.  The interval
            # rows already expose focus through their row/background items;
            # moving Tk's native focus into a Canvas causes an extra repaint
            # on some SteamOS themes, so leave native focus untouched there.
            if not interval_focus_control:
                widget.focus_set()
            if control.startswith("custom:"):
                self._ensure_custom_control_visible(control, widget)
        except tk.TclError:
            pass

    def _hide_exit_confirmation(self) -> None:
        if self._exit_overlay is not None:
            self._exit_overlay.destroy()
        self._exit_overlay = None
        self._exit_buttons = {}

    def _refresh_exit_confirmation_focus(self) -> None:
        for choice, button in self._exit_buttons.items():
            background = PURPLE if choice == self._navigation.exit_choice else BUTTON_BG
            button.configure(
                bg=background,
                activebackground=background,
                highlightbackground=background,
            )

    def _render_exit_confirmation(self) -> None:
        if self._exit_overlay is not None:
            self._exit_overlay.destroy()
        self._exit_buttons = {}
        overlay = tk.Frame(
            self._shell or self.root, bg="#101820", highlightbackground=PURPLE, highlightthickness=2
        )
        overlay.place(
            x=(WINDOW_W - EXIT_OVERLAY_W) // 2,
            y=(WINDOW_H - EXIT_OVERLAY_H) // 2,
            width=EXIT_OVERLAY_W,
            height=EXIT_OVERLAY_H,
        )
        tk.Label(
            overlay,
            text=self._t("exit_title"),
            fg=WHITE,
            bg="#101820",
            font=self._font(22, "bold"),
        ).place(x=_sx(20), y=_sy(35), width=EXIT_OVERLAY_W - _sx(40), height=_sy(45))
        tk.Label(
            overlay,
            text=self._t("exit_hint"),
            fg=SUBTLE,
            bg="#101820",
            font=self._font(13),
        ).place(x=_sx(20), y=_sy(85), width=EXIT_OVERLAY_W - _sx(40), height=_sy(30))
        exit_focused = self._navigation.exit_choice == "exit"
        exit_button = tk.Button(
            overlay,
            text=self._t("exit"),
            command=self._on_close,
            fg=WHITE,
            bg=PURPLE if exit_focused else BUTTON_BG,
            activebackground=PURPLE if exit_focused else BUTTON_BG,
            activeforeground=WHITE,
            highlightbackground=PURPLE if exit_focused else BUTTON_BG,
            highlightthickness=0,
            bd=0,
            relief="flat",
            font=self._font(14),
        )
        exit_button.place(x=_sx(75), y=_sy(145), width=_sx(130), height=_sy(44))
        cancel_button = tk.Button(
            overlay,
            text=self._t("cancel"),
            command=lambda: self._handle_controller_action("back"),
            fg=WHITE,
            bg=PURPLE if not exit_focused else BUTTON_BG,
            activebackground=PURPLE if not exit_focused else BUTTON_BG,
            activeforeground=WHITE,
            highlightbackground=PURPLE if not exit_focused else BUTTON_BG,
            highlightthickness=0,
            bd=0,
            relief="flat",
            font=self._font(14),
        )
        cancel_button.place(x=_sx(275), y=_sy(145), width=_sx(130), height=_sy(44))
        self._exit_buttons = {"exit": exit_button, "cancel": cancel_button}
        self._exit_overlay = overlay

    def _on_close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._gamepad.close()
            self._controller.close()
            self._touch.close()
            self.backend.shutdown()
        finally:
            self.root.destroy()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=APP_TITLE)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--with-device", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    plugin_root = Path(__file__).resolve().parent
    language = detect_system_language()
    if not args.self_test and activate_existing_window(APP_TITLE):
        return 0
    try:
        backend = DesktopBackend(plugin_root, language=language)
    except DesktopAlreadyRunningError:
        activate_existing_window(APP_TITLE, wait_timeout=5.0)
        return 0
    except Exception as error:
        if args.self_test:
            raise
        root = tk.Tk(className=APP_ID)
        root.withdraw()
        messagebox.showerror(APP_TITLE, str(error))
        root.destroy()
        return 1
    try:
        if args.self_test:
            print(
                json.dumps(
                    backend.self_test(include_device=args.with_device), ensure_ascii=False, indent=2
                )
            )
            return 0
        root = tk.Tk(className=APP_ID)
        DesktopApp(root, backend)
        root.mainloop()
        return 0
    finally:
        if args.self_test:
            backend.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
