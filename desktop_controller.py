from __future__ import annotations

import logging
import os
import queue
import re
import selectors
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

EV_KEY = 1
EV_ABS = 3
EV_SYN = 0
SYN_REPORT = 0
KEY_ESC = 1
KEY_BACKSPACE = 14
KEY_ENTER = 28
KEY_SPACE = 57
KEY_KPENTER = 96
KEY_UP = 103
KEY_LEFT = 105
KEY_RIGHT = 106
KEY_DOWN = 108
ABS_X = 0
ABS_Y = 1
ABS_HAT0X = 16
ABS_HAT0Y = 17
ABS_MT_SLOT = 47
ABS_MT_POSITION_X = 53
ABS_MT_POSITION_Y = 54
ABS_MT_TRACKING_ID = 57
BTN_SOUTH = 304
BTN_EAST = 305
BTN_TOUCH = 330
INPUT_EVENT = struct.Struct("llHHi")
PUCK_KEYBOARD_NAME = "Valve Software Steam Controller Puck Keyboard"
MICROSOFT_XBOX_PAD_PREFIX = "Microsoft X-Box 360 pad"
STEAM_DECK_TOUCH_MAX_X = 800
STEAM_DECK_TOUCH_MAX_Y = 1280


def _touchscreen_names() -> set[str]:
    """Host touchscreen names, overridable via JSAUX_TOUCHSCREEN_NAME."""
    names: set[str] = set()
    override = os.environ.get("JSAUX_TOUCHSCREEN_NAME", "").strip()
    if override:
        names.add(override)
    try:
        from device_identity import TOUCHSCREEN_NAMES

        names.update(str(item) for item in TOUCHSCREEN_NAMES)
    except ImportError:
        pass
    return names


LOGGER = logging.getLogger("jsaux-eink-controller")
RAW_KEY_ACTIONS = {
    KEY_UP: "up",
    KEY_RIGHT: "right",
    KEY_DOWN: "down",
    KEY_LEFT: "left",
    KEY_ENTER: "activate",
    KEY_KPENTER: "activate",
    KEY_SPACE: "activate",
    KEY_ESC: "back",
    KEY_BACKSPACE: "back",
}
NAV_SECTIONS = ("screen", "layout", "settings")
MODULE_MODES = (
    "carousel",
    "agent",
    "clock",
    "weather",
    "timeline",
    "deck_status",
    "calendar",
    "custom",
)


def center_window_position(
    screen_w: int, screen_h: int, window_w: int, window_h: int
) -> tuple[int, int]:
    return max(0, (screen_w - window_w) // 2), max(0, (screen_h - window_h) // 2)


def center_managed_frame_position(
    screen_w: int,
    screen_h: int,
    window_w: int,
    window_h: int,
    frame_extents: tuple[int, int, int, int],
    undecorated_position: tuple[int, int],
) -> tuple[int, int]:
    left, right, top, bottom = frame_extents
    undecorated_x, undecorated_y = undecorated_position
    return (
        max(0, undecorated_x - left),
        max(0, undecorated_y - (top + bottom) // 2),
    )


def parse_frame_extents(output: str) -> tuple[int, int, int, int]:
    values = [int(value) for value in re.findall(r"-?\d+", output.split("=", 1)[-1])]
    return tuple(values[:4]) if len(values) >= 4 else (0, 0, 0, 0)  # type: ignore[return-value]


def select_managed_window_id(output: str, fallback: int) -> int:
    window_ids = [int(value) for value in output.split() if value.isdigit()]
    return window_ids[-1] if window_ids else fallback


def activate_existing_window(title: str, *, wait_timeout: float = 0.0) -> bool:
    deadline = time.monotonic() + max(0.0, float(wait_timeout))
    pattern = f"^{re.escape(title)}$"
    while True:
        try:
            output = subprocess.check_output(
                ["xdotool", "search", "--name", pattern],
                text=True,
                timeout=2.0,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            output = ""
        window_id = select_managed_window_id(output, 0)
        if window_id:
            activated = False
            for command in (
                ["xdotool", "windowmap", str(window_id)],
                ["xdotool", "windowactivate", "--sync", str(window_id)],
                ["xdotool", "windowraise", str(window_id)],
            ):
                try:
                    result = subprocess.run(
                        command,
                        check=False,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=2.0,
                    )
                    if command[1] == "windowactivate":
                        activated = result.returncode == 0
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    return False
            return activated
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)


def map_raw_key(code: int, value: int) -> Optional[str]:
    action = RAW_KEY_ACTIONS.get(int(code))
    if action in ("activate", "back") and value != 1:
        return None
    if action in ("up", "right", "down", "left") and value not in (1, 2):
        return None
    return action


@dataclass(frozen=True)
class RawTouchEvent:
    kind: str
    x: int
    y: int
    captured_at_ms: float


def map_steam_deck_touch_to_screen(
    raw_x: int,
    raw_y: int,
    screen_width: int,
    screen_height: int,
) -> tuple[int, int]:
    """Map the Deck panel's portrait touch axes to its right-rotated desktop."""
    normalized_x = max(0.0, min(1.0, raw_x / STEAM_DECK_TOUCH_MAX_X))
    normalized_y = max(0.0, min(1.0, raw_y / STEAM_DECK_TOUCH_MAX_Y))
    return (
        int(round((1.0 - normalized_y) * max(0, screen_width - 1))),
        int(round(normalized_x * max(0, screen_height - 1))),
    )


class TouchInputState:
    def __init__(self) -> None:
        self.slot = 0
        self.x = 0
        self.y = 0
        self.have_x = False
        self.have_y = False
        self.active = False
        self.down_sent = False
        self.down_pending = False
        self.up_pending = False
        self.position_changed = False

    def update_event(self, event_type: int, code: int, value: int) -> list[tuple[str, int, int]]:
        if event_type == EV_ABS:
            if code == ABS_MT_SLOT:
                self.slot = value
            elif self.slot == 0 and code in (ABS_MT_POSITION_X, ABS_X):
                self.x = value
                self.have_x = True
                self.position_changed = True
            elif self.slot == 0 and code in (ABS_MT_POSITION_Y, ABS_Y):
                self.y = value
                self.have_y = True
                self.position_changed = True
            elif self.slot == 0 and code == ABS_MT_TRACKING_ID:
                if value >= 0:
                    self.active = True
                    self.down_pending = not self.down_sent
                    self.up_pending = False
                else:
                    self.active = False
                    self.up_pending = self.down_sent
        elif event_type == EV_KEY and code == BTN_TOUCH:
            if value == 1:
                self.active = True
                self.down_pending = not self.down_sent
                self.up_pending = False
            elif value == 0:
                self.active = False
                self.up_pending = self.down_sent
        if event_type != EV_SYN or code != SYN_REPORT:
            return []
        return self._flush_frame()

    def _flush_frame(self) -> list[tuple[str, int, int]]:
        if self.down_pending and self.have_x and self.have_y:
            self.down_pending = False
            self.down_sent = True
            self.position_changed = False
            return [("down", self.x, self.y)]
        if self.up_pending:
            self.up_pending = False
            self.down_pending = False
            if self.down_sent:
                self.down_sent = False
                self.position_changed = False
                return [("up", self.x, self.y)]
        if self.active and self.down_sent and self.position_changed:
            self.position_changed = False
            return [("move", self.x, self.y)]
        self.position_changed = False
        return []


class InputGate:
    def __init__(self, duplicate_ms: float = 80.0, direction_lock_ms: float = 90.0) -> None:
        self.duplicate_ms = duplicate_ms
        self.direction_lock_ms = direction_lock_ms
        self._last_by_action: dict[str, float] = {}
        self._last_direction_at = float("-inf")

    def accept(self, action: str, captured_at_ms: float) -> bool:
        previous = self._last_by_action.get(action, float("-inf"))
        if captured_at_ms - previous < self.duplicate_ms:
            return False
        if action in ("up", "right", "down", "left"):
            if captured_at_ms - self._last_direction_at < self.direction_lock_ms:
                return False
            self._last_direction_at = captured_at_ms
        self._last_by_action[action] = captured_at_ms
        return True


class GamepadInputState:
    def __init__(
        self, dead_zone: int = 16000, initial_repeat_ms: int = 320, repeat_ms: int = 125
    ) -> None:
        self.dead_zone = dead_zone
        self.initial_repeat_ms = initial_repeat_ms
        self.repeat_ms = repeat_ms
        self.axis_x = 0
        self.axis_y = 0
        self.hat_x = 0
        self.hat_y = 0
        self._direction: Optional[str] = None
        self._next_repeat_ms = 0.0
        self._pressed: set[int] = set()

    def update_event(self, event_type: int, code: int, value: int) -> list[str]:
        if event_type == EV_ABS:
            if code == ABS_X:
                self.axis_x = value
            elif code == ABS_Y:
                self.axis_y = value
            elif code == ABS_HAT0X:
                self.hat_x = value
            elif code == ABS_HAT0Y:
                self.hat_y = value
            return []
        if event_type != EV_KEY or code not in (BTN_SOUTH, BTN_EAST):
            return []
        if value == 0:
            self._pressed.discard(code)
            return []
        if value != 1 or code in self._pressed:
            return []
        self._pressed.add(code)
        return ["activate" if code == BTN_SOUTH else "back"]

    def poll(self, now_ms: float) -> list[str]:
        direction = self._current_direction()
        if direction != self._direction:
            self._direction = direction
            self._next_repeat_ms = now_ms + self.initial_repeat_ms
            return [direction] if direction else []
        if direction and now_ms >= self._next_repeat_ms:
            self._next_repeat_ms = now_ms + self.repeat_ms
            return [direction]
        return []

    def _current_direction(self) -> Optional[str]:
        if self.hat_y < 0:
            return "up"
        if self.hat_y > 0:
            return "down"
        if self.hat_x < 0:
            return "left"
        if self.hat_x > 0:
            return "right"
        if max(abs(self.axis_x), abs(self.axis_y)) < self.dead_zone:
            return None
        if abs(self.axis_x) > abs(self.axis_y):
            return "left" if self.axis_x < 0 else "right"
        return "up" if self.axis_y < 0 else "down"


def decode_gamepad_events(data: bytes, state: GamepadInputState) -> tuple[list[str], bytes]:
    complete = len(data) - len(data) % INPUT_EVENT.size
    actions: list[str] = []
    for offset in range(0, complete, INPUT_EVENT.size):
        _sec, _usec, event_type, code, value = INPUT_EVENT.unpack_from(data, offset)
        actions.extend(state.update_event(event_type, code, value))
    return actions, data[complete:]


@dataclass(frozen=True)
class DesktopNavigationState:
    region: str = "nav"
    control: str = "screen"
    section: str = "screen"
    custom_open: bool = False
    connection_page: bool = False
    game_time_page: bool = False
    exit_confirming: bool = False
    exit_choice: str = "cancel"


def section_controls(
    state: DesktopNavigationState,
    image_count: int,
    connection_candidate_count: int = 0,
) -> list[str]:
    if state.section == "screen":
        if state.connection_page:
            return [
                "connection:back",
                "connection:refresh",
                *[
                    f"connection:device:{index}"
                    for index in range(max(0, connection_candidate_count))
                ],
            ]
        return ["connection", "photo-frame", "module-switch"]
    if state.game_time_page:
        return ["game-time:back", "game-time:time", "game-time:poster", "game-time:auto"]
    if state.section == "settings":
        return [
            "settings:timezone",
            "settings:units",
            "settings:format",
            "settings:dst",
            "settings:weather",
        ]
    if state.custom_open:
        controls = [f"custom:{index}" for index in range(max(0, image_count))]
        controls.append("custom:add")
        controls.append("custom:back")
        if image_count > 0:
            controls.extend(["custom:apply", "custom:delete"])
        return controls
    return [f"module:{mode}" for mode in MODULE_MODES]


def reduce_desktop_navigation(
    state: DesktopNavigationState,
    action: str,
    image_count: int,
    connection_candidate_count: int = 0,
) -> DesktopNavigationState:
    if state.exit_confirming:
        if action in ("left", "right"):
            return replace(state, exit_choice="exit" if state.exit_choice == "cancel" else "cancel")
        if action == "back":
            return replace(state, exit_confirming=False, exit_choice="cancel")
        return state
    if action == "back":
        if state.connection_page:
            return DesktopNavigationState(region="content", control="connection", section="screen")
        if state.game_time_page:
            return DesktopNavigationState(
                region="content", control="module:timeline", section="layout"
            )
        if state.custom_open:
            return DesktopNavigationState(region="nav", control="layout", section="layout")
        if state.region == "content":
            return replace(state, region="nav", control=state.section)
        return replace(state, exit_confirming=True, exit_choice="cancel")
    if state.region == "nav":
        index = NAV_SECTIONS.index(state.control) if state.control in NAV_SECTIONS else 0
        if action == "up":
            index = (index - 1) % len(NAV_SECTIONS)
        elif action == "down":
            index = (index + 1) % len(NAV_SECTIONS)
        elif action == "activate":
            section = state.control if state.control in NAV_SECTIONS else state.section
            selected = replace(
                state,
                section=section,
                custom_open=False,
                connection_page=False,
                game_time_page=False,
            )
            return replace(
                selected,
                region="content",
                control=section_controls(selected, image_count, connection_candidate_count)[0],
            )
        else:
            return state
        return replace(state, control=NAV_SECTIONS[index])
    controls = section_controls(state, image_count, connection_candidate_count)
    if not controls:
        return replace(state, region="nav", control=state.section)
    if state.game_time_page:
        if state.control != "game-time:back" and action == "left":
            return replace(state, control="game-time:back")
        if state.control == "game-time:back" and action == "right":
            return replace(state, control="game-time:time")
        index = controls.index(state.control) if state.control in controls else 0
        if action in ("up", "down"):
            index = max(0, min(len(controls) - 1, index + (-1 if action == "up" else 1)))
        return replace(state, control=controls[index])
    if state.connection_page:
        # Header actions sit side by side; discovered devices are a vertical
        # list below them.
        if state.control == "connection:back" and action == "right":
            return replace(state, control="connection:refresh")
        if state.control == "connection:refresh" and action == "left":
            return replace(state, control="connection:back")
        devices = [control for control in controls if control.startswith("connection:device:")]
        if action in ("up", "down"):
            if state.control in ("connection:back", "connection:refresh"):
                return replace(
                    state, control=devices[0] if action == "down" and devices else state.control
                )
            if state.control in devices:
                index = devices.index(state.control) + (1 if action == "down" else -1)
                if index < 0:
                    return replace(state, control="connection:refresh")
                return replace(state, control=devices[min(index, len(devices) - 1)])
        return state
    if state.custom_open and state.control in ("custom:delete", "custom:apply"):
        if action == "left" and "custom:apply" in controls:
            return replace(state, control="custom:apply")
        if action == "right" and "custom:delete" in controls:
            return replace(state, control="custom:delete")
        return state
    if state.custom_open:
        if state.control == "custom:back":
            if action == "up":
                return replace(state, control="custom:add")
            return state
        if state.control == "custom:add" and action == "down":
            return replace(state, control="custom:back")
        grid_controls = [
            control
            for control in controls
            if control not in ("custom:apply", "custom:delete", "custom:back")
        ]
        if state.control not in grid_controls:
            return replace(state, control=grid_controls[0]) if grid_controls else state
        index = grid_controls.index(state.control)
        if action == "up":
            if index >= 2:
                return replace(state, control=grid_controls[index - 2])
        elif action == "down":
            if index + 2 < len(grid_controls):
                return replace(state, control=grid_controls[index + 2])
            # The last row may have only one image. Make the upload action
            # reachable from either column instead of trapping focus on the card.
            if "custom:add" in grid_controls and state.control != "custom:add":
                return replace(state, control="custom:add")
        elif action == "left" and index % 2 == 1:
            return replace(state, control=grid_controls[index - 1])
        elif action == "right" and index % 2 == 0 and index + 1 < len(grid_controls):
            return replace(state, control=grid_controls[index + 1])
        return state
    if action == "left" and state.section in ("screen", "settings"):
        return replace(state, region="nav", control=state.section)
    index = controls.index(state.control) if state.control in controls else 0
    if state.section == "layout" and not state.custom_open and state.control.startswith("module:"):
        if action in ("left", "right"):
            index = max(0, min(len(controls) - 1, index + (-1 if action == "left" else 1)))
        elif action in ("up", "down"):
            index = max(0, min(len(controls) - 1, index + (-3 if action == "up" else 3)))
    elif action in ("up", "left"):
        index = (index - 1) % len(controls)
    elif action in ("down", "right"):
        index = (index + 1) % len(controls)
    return replace(state, control=controls[index])


class RawPuckInput:
    def __init__(self, sink: queue.Queue[tuple[str, float]]) -> None:
        self._sink = sink
        self._selector = selectors.DefaultSelector()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._paths: dict[int, Path] = {}

    def start(self) -> None:
        LOGGER.info("starting raw puck input")
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        for fd in list(self._paths):
            try:
                self._selector.unregister(fd)
            except Exception:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
        self._paths.clear()
        self._selector.close()
        LOGGER.info("raw puck input closed")

    @staticmethod
    def discover() -> list[Path]:
        result: list[Path] = []
        for event in sorted(Path("/dev/input").glob("event*")):
            try:
                name = (Path("/sys/class/input") / event.name / "device/name").read_text().strip()
            except OSError:
                continue
            if name == PUCK_KEYBOARD_NAME:
                result.append(event)
        return result

    def _refresh(self) -> None:
        wanted = set(self.discover())
        active = set(self._paths.values())
        for path in wanted - active:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                self._selector.register(fd, selectors.EVENT_READ)
                self._paths[fd] = path
                LOGGER.info("opened %s", path)
            except OSError:
                pass
        for fd, path in list(self._paths.items()):
            if path in wanted:
                continue
            try:
                self._selector.unregister(fd)
            except Exception:
                pass
            try:
                os.close(fd)
            except OSError:
                pass
            self._paths.pop(fd, None)

    def _run(self) -> None:
        buffers: dict[int, bytes] = {}
        next_refresh = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_refresh:
                self._refresh()
                next_refresh = now + 1.0
            for key, _mask in self._selector.select(timeout=0.05):
                fileobj = key.fileobj
                fd = fileobj if isinstance(fileobj, int) else fileobj.fileno()
                try:
                    chunk = os.read(fd, INPUT_EVENT.size * 32)
                except BlockingIOError:
                    continue
                except OSError:
                    chunk = b""
                if not chunk:
                    try:
                        self._selector.unregister(fd)
                    except Exception:
                        pass
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    self._paths.pop(fd, None)
                    buffers.pop(fd, None)
                    continue
                data = buffers.get(fd, b"") + chunk
                complete = len(data) - len(data) % INPUT_EVENT.size
                buffers[fd] = data[complete:]
                for offset in range(0, complete, INPUT_EVENT.size):
                    _sec, _usec, event_type, code, value = INPUT_EVENT.unpack_from(data, offset)
                    if event_type != EV_KEY:
                        continue
                    action = map_raw_key(code, value)
                    if action:
                        LOGGER.info(
                            "action=%s source=%s code=%s", action, self._paths.get(fd, fd), code
                        )
                        self._sink.put((action, time.monotonic() * 1000.0))


class RawGamepadInput:
    def __init__(self, sink: queue.Queue[tuple[str, float]]) -> None:
        self._sink = sink
        self._selector = selectors.DefaultSelector()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._paths: dict[int, Path] = {}
        self._states: dict[int, GamepadInputState] = {}

    def start(self) -> None:
        LOGGER.info("starting raw gamepad input")
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        for fd in list(self._paths):
            self._close_fd(fd)
        self._selector.close()
        LOGGER.info("raw gamepad input closed")

    @staticmethod
    def discover(
        input_root: Path = Path("/dev/input"),
        sysfs_root: Path = Path("/sys/class/input"),
    ) -> list[Path]:
        result: list[Path] = []
        for event in sorted(input_root.glob("event*")):
            try:
                name = (sysfs_root / event.name / "device/name").read_text().strip()
            except OSError:
                continue
            if name.startswith(MICROSOFT_XBOX_PAD_PREFIX):
                result.append(event)
        return result

    def _refresh(self) -> None:
        wanted = set(self.discover())
        active = set(self._paths.values())
        for path in wanted - active:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                self._selector.register(fd, selectors.EVENT_READ)
                self._paths[fd] = path
                self._states[fd] = GamepadInputState()
                LOGGER.info("opened gamepad %s", path)
            except OSError:
                pass
        for fd, path in list(self._paths.items()):
            if path not in wanted:
                self._close_fd(fd)

    def _close_fd(self, fd: int) -> None:
        try:
            self._selector.unregister(fd)
        except Exception:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        self._paths.pop(fd, None)
        self._states.pop(fd, None)

    def _run(self) -> None:
        buffers: dict[int, bytes] = {}
        next_refresh = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_refresh:
                self._refresh()
                next_refresh = now + 1.0
            for key, _mask in self._selector.select(timeout=0.02):
                fd = key.fileobj if isinstance(key.fileobj, int) else key.fileobj.fileno()
                try:
                    chunk = os.read(fd, INPUT_EVENT.size * 32)
                except BlockingIOError:
                    continue
                except OSError:
                    chunk = b""
                if not chunk:
                    self._close_fd(fd)
                    buffers.pop(fd, None)
                    continue
                data = buffers.get(fd, b"") + chunk
                state = self._states.get(fd)
                if state is None:
                    continue
                actions, buffers[fd] = decode_gamepad_events(data, state)
                for action in actions:
                    self._emit(action, fd)
            captured_at_ms = time.monotonic() * 1000.0
            for fd, state in list(self._states.items()):
                for action in state.poll(captured_at_ms):
                    self._emit(action, fd, captured_at_ms)

    def _emit(self, action: str, fd: int, captured_at_ms: Optional[float] = None) -> None:
        timestamp = captured_at_ms if captured_at_ms is not None else time.monotonic() * 1000.0
        LOGGER.info("action=%s source=%s", action, self._paths.get(fd, fd))
        self._sink.put((action, timestamp))


class RawTouchInput:
    def __init__(self, sink: queue.Queue[RawTouchEvent]) -> None:
        self._sink = sink
        self._selector = selectors.DefaultSelector()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._paths: dict[int, Path] = {}
        self._states: dict[int, TouchInputState] = {}
        self._permission_warnings: set[Path] = set()

    def start(self) -> None:
        LOGGER.info("starting raw touchscreen input")
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)
        for fd in list(self._paths):
            self._close_fd(fd)
        self._selector.close()
        LOGGER.info("raw touchscreen input closed")

    @staticmethod
    def discover(
        input_root: Path = Path("/dev/input"),
        sysfs_root: Path = Path("/sys/class/input"),
    ) -> list[Path]:
        result: list[Path] = []
        for event in sorted(input_root.glob("event*")):
            try:
                name = (sysfs_root / event.name / "device/name").read_text().strip()
            except OSError:
                continue
            if name in _touchscreen_names():
                result.append(event)
        return result

    def _refresh(self) -> None:
        wanted = set(self.discover())
        active = set(self._paths.values())
        for path in wanted - active:
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                self._selector.register(fd, selectors.EVENT_READ)
                self._paths[fd] = path
                self._states[fd] = TouchInputState()
                self._permission_warnings.discard(path)
                LOGGER.info("opened touchscreen %s", path)
            except PermissionError:
                if path not in self._permission_warnings:
                    LOGGER.warning(
                        "touchscreen access denied for %s; reinstall the desktop shortcut", path
                    )
                    self._permission_warnings.add(path)
            except OSError:
                pass
        for fd, path in list(self._paths.items()):
            if path not in wanted:
                self._close_fd(fd)

    def _close_fd(self, fd: int) -> None:
        try:
            self._selector.unregister(fd)
        except Exception:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        self._paths.pop(fd, None)
        self._states.pop(fd, None)

    def _run(self) -> None:
        buffers: dict[int, bytes] = {}
        next_refresh = 0.0
        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_refresh:
                self._refresh()
                next_refresh = now + 1.0
            for key, _mask in self._selector.select(timeout=0.01):
                fd = key.fileobj if isinstance(key.fileobj, int) else key.fileobj.fileno()
                try:
                    chunk = os.read(fd, INPUT_EVENT.size * 64)
                except BlockingIOError:
                    continue
                except OSError:
                    chunk = b""
                if not chunk:
                    self._close_fd(fd)
                    buffers.pop(fd, None)
                    continue
                data = buffers.get(fd, b"") + chunk
                complete = len(data) - len(data) % INPUT_EVENT.size
                buffers[fd] = data[complete:]
                state = self._states.get(fd)
                if state is None:
                    continue
                for offset in range(0, complete, INPUT_EVENT.size):
                    _sec, _usec, event_type, code, value = INPUT_EVENT.unpack_from(data, offset)
                    for kind, x, y in state.update_event(event_type, code, value):
                        event = RawTouchEvent(kind, x, y, time.monotonic() * 1000.0)
                        LOGGER.debug(
                            "touch=%s x=%s y=%s source=%s", kind, x, y, self._paths.get(fd, fd)
                        )
                        self._sink.put(event)
