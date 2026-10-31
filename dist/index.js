const manifest = {"name":"JSAUX E-INK"};
const API_VERSION = 2;
const internalAPIConnection = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
    throw new Error('[@decky/api]: Failed to connect to the loader as as the loader API was not initialized. This is likely a bug in Decky Loader.');
}
let api;
try {
    api = internalAPIConnection.connect(API_VERSION, manifest.name);
}
catch {
    api = internalAPIConnection.connect(1, manifest.name);
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version 1. Some features may not work.`);
}
if (api._version != API_VERSION) {
    console.warn(`[@decky/api] Requested API version ${API_VERSION} but the running loader only supports version ${api._version}. Some features may not work.`);
}
const callable = api.callable;
const addEventListener = api.addEventListener;
const removeEventListener = api.removeEventListener;
const toaster = api.toaster;
const openFilePicker = api.openFilePicker;
const definePlugin = (fn) => {
    return (...args) => {
        return fn(...args);
    };
};

// The gaming-mode cards are a four-row, two-column grid:
// Composite | AI Agent
// Clock     | Weather
// Performance | Calendar
// Game Time | Photo Frame
// Keep vertical paths and horizontal pairs in that same geometry. The old
// paths mixed DOM order with columns, which made left/right jump to a different
// row and sent up/down to the interval controls.
const MODULE_VERTICAL_BRANCHES = {
    left: ["carousel", "clock", "deck_status", "timeline"],
    right: ["agent", "weather", "calendar", "custom"],
};
const MODULE_HORIZONTAL_PAIRS = [
    ["carousel", "agent"],
    ["clock", "weather"],
    ["deck_status", "calendar"],
    ["timeline", "custom"],
];
const MAIN_GAMEPAD_PATHS = {
    left: [
        "connection-page-entry",
        "connection",
        "photo-frame",
        "module-switch",
        "module:carousel",
        "module:clock",
        "module:deck_status",
        "module:timeline",
        "settings-entry",
    ],
    right: [
        "connection-page-entry",
        "connection",
        "photo-frame",
        "module-switch",
        "module:agent",
        "module:weather",
        "module:calendar",
        "module:custom",
        "settings-entry",
    ],
};
function resolveGamepadModuleBranch(id, currentBranch = "left") {
    const mode = id.startsWith("module:") ? id.slice("module:".length) : id;
    if (["clock", "deck_status", "timeline"].includes(mode))
        return "left";
    if (["agent", "weather", "calendar", "custom"].includes(mode))
        return "right";
    return currentBranch;
}
function resolveGamepadFocusIndex(ids, focusedId, activeId, fallbackIndex) {
    const focusedIndex = ids.indexOf(focusedId);
    if (focusedIndex >= 0)
        return focusedIndex;
    const activeIndex = ids.indexOf(activeId);
    if (activeIndex >= 0)
        return activeIndex;
    if (fallbackIndex >= 0 && fallbackIndex < ids.length)
        return fallbackIndex;
    const connectionPageEntryIndex = ids.indexOf("connection-page-entry");
    if (connectionPageEntryIndex >= 0)
        return connectionPageEntryIndex;
    const connectionIndex = ids.indexOf("connection");
    return connectionIndex >= 0 ? connectionIndex : (ids.length > 0 ? 0 : -1);
}
function resolveGamepadNavigationState(ids, state, activeId, direction) {
    const currentIndex = resolveGamepadFocusIndex(ids, state.focusedId, activeId, state.focusedIndex);
    const currentId = ids[currentIndex] ?? "";
    const currentBranch = resolveGamepadModuleBranch(currentId, state.moduleBranch);
    const nextIndex = findGamepadNavigationIndex(ids, currentIndex, direction, currentBranch);
    if (nextIndex < 0) {
        return {
            focusedId: currentId,
            focusedIndex: currentIndex,
            moduleBranch: currentBranch,
        };
    }
    const nextId = ids[nextIndex];
    let nextBranch = resolveGamepadModuleBranch(nextId, currentBranch);
    if (direction === "left" && nextId === "module:carousel")
        nextBranch = "left";
    if (direction === "right" && nextId === "module:clock")
        nextBranch = "right";
    return {
        focusedId: nextId,
        focusedIndex: nextIndex,
        moduleBranch: nextBranch,
    };
}
function findModuleNavigationIndex(modes, currentIndex, direction, branch = "left") {
    const currentMode = modes[currentIndex];
    if (direction === "up" || direction === "down") {
        const effectiveBranch = resolveGamepadModuleBranch(currentMode ?? "", branch);
        const verticalPath = MODULE_VERTICAL_BRANCHES[effectiveBranch];
        const verticalIndex = verticalPath.indexOf(currentMode);
        if (verticalIndex < 0)
            return -1;
        const step = direction === "down" ? 1 : -1;
        const nextMode = verticalPath[verticalIndex + step];
        if (!nextMode)
            return -1;
        return modes.indexOf(nextMode);
    }
    const pair = MODULE_HORIZONTAL_PAIRS.find((items) => items.includes(currentMode));
    if (!pair)
        return -1;
    const nextMode = direction === "right" ? pair[1] : pair[0];
    if (nextMode === currentMode)
        return -1;
    return modes.indexOf(nextMode);
}
function findCustomNavigationIndex(ids, currentIndex, direction) {
    const currentId = ids[currentIndex];
    if (!currentId)
        return ids.length > 0 ? 0 : -1;
    const firstAvailable = (...candidates) => {
        for (const candidate of candidates) {
            const index = ids.indexOf(candidate);
            if (index >= 0)
                return index;
        }
        return currentIndex;
    };
    const itemIds = ids.filter((id) => id.startsWith("custom:item:"));
    const itemIndex = itemIds.indexOf(currentId);
    const lastCustom = itemIds.at(-1) ?? "custom:upload";
    if (itemIndex >= 0) {
        if (direction === "left" && itemIndex % 2 === 1)
            return ids.indexOf(itemIds[itemIndex - 1]);
        if (direction === "right" && itemIndex % 2 === 0 && itemIds[itemIndex + 1])
            return ids.indexOf(itemIds[itemIndex + 1]);
        if (direction === "up")
            return firstAvailable(itemIds[itemIndex - 2] ?? itemIds[itemIndex]);
        if (direction === "down") {
            const nextItem = itemIds[itemIndex + 2];
            if (nextItem)
                return firstAvailable(nextItem);
            return firstAvailable("custom:upload");
        }
        return currentIndex;
    }
    if (currentId === "custom:upload") {
        if (direction === "up")
            return firstAvailable(lastCustom);
        return currentIndex;
    }
    if (currentId === "custom:select") {
        if (direction === "right")
            return firstAvailable("custom:delete");
        return currentIndex;
    }
    if (currentId === "custom:delete") {
        if (direction === "left")
            return firstAvailable("custom:select");
        return currentIndex;
    }
    return currentIndex;
}
function findGamepadNavigationIndex(ids, currentIndex, direction, branch = "left") {
    if (ids.length === 0)
        return -1;
    const currentId = ids[currentIndex];
    if (!currentId)
        return ids.length > 0 ? 0 : -1;
    if (ids.some((id) => id.startsWith("custom:"))) {
        return findCustomNavigationIndex(ids, currentIndex, direction);
    }
    if (direction === "up" || direction === "down") {
        const effectiveBranch = resolveGamepadModuleBranch(currentId, branch);
        const availablePath = MAIN_GAMEPAD_PATHS[effectiveBranch].filter((id) => ids.includes(id));
        const pathIndex = availablePath.indexOf(currentId);
        if (pathIndex >= 0) {
            const step = direction === "down" ? 1 : -1;
            const nextId = availablePath[Math.max(0, Math.min(availablePath.length - 1, pathIndex + step))];
            return ids.indexOf(nextId);
        }
    }
    if (currentId.startsWith("game-time")) {
        const modeIds = ids.filter((id) => id.startsWith("game-time-mode:"));
        const modeIndex = modeIds.indexOf(currentId);
        if (modeIndex >= 0 && (direction === "up" || direction === "down")) {
            const nextIndex = Math.max(0, Math.min(modeIds.length - 1, modeIndex + (direction === "down" ? 1 : -1)));
            return ids.indexOf(modeIds[nextIndex]);
        }
        if (currentId !== "game-time:back" && direction === "left")
            return ids.indexOf("game-time:back");
        if (currentId === "game-time:back" && direction === "right")
            return ids.indexOf(modeIds[0] ?? currentId);
        return currentIndex;
    }
    if (!currentId.startsWith("module:"))
        return -1;
    const moduleIndexes = [];
    const moduleModes = [];
    ids.forEach((id, index) => {
        if (!id.startsWith("module:"))
            return;
        moduleIndexes.push(index);
        moduleModes.push(id.slice("module:".length));
    });
    const currentModuleIndex = moduleIndexes.indexOf(currentIndex);
    const nextModuleIndex = findModuleNavigationIndex(moduleModes, currentModuleIndex, direction, branch);
    return nextModuleIndex >= 0 ? moduleIndexes[nextModuleIndex] : -1;
}
function shouldActivateGamepadInput(activationArmed, alreadyPressed, now, activationReadyAt) {
    return activationArmed && !alreadyPressed && now >= activationReadyAt;
}
function shouldHandleGamepadActivation(lastHandledAt, now, dedupeMs) {
    return now - lastHandledAt >= dedupeMs;
}
function shouldActivateGamepadTarget(id, activatable) {
    return activatable && id !== "back";
}
function didGamepadPanelBecomeVisible(wasVisible, isVisible) {
    return !wasVisible && isVisible;
}
function shouldScrollGamepadTargetToTop(id) {
    return id === "connection" || id === "connection-page-entry";
}
function mapSteamControllerButton(button) {
    return {
        0: "activate",
        1: "cancel",
        4: "up",
        5: "right",
        6: "down",
        7: "left",
        9: "up",
        10: "down",
        11: "left",
        12: "right",
        20: "up",
        21: "down",
        22: "left",
        23: "right",
    }[button] ?? null;
}
function mapDeckyGamepadButton(button) {
    return {
        9: "up",
        10: "down",
        11: "left",
        12: "right",
        20: "up",
        21: "down",
        22: "left",
        23: "right",
    }[button] ?? null;
}
function shouldHandleGamepadDirection(direction, lastHandledAt, lastDirection, now, dedupeMs) {
    return direction !== lastDirection || now - lastHandledAt >= dedupeMs;
}

const h$1 = SP_REACT.createElement;
const svgProps = (name, props = {}) => ({
    viewBox: "0 0 24 24",
    width: props.size ?? 24,
    height: props.size ?? 24,
    fill: "none",
    stroke: props.color ?? "currentColor",
    strokeWidth: props.strokeWidth ?? 1.8,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    "aria-hidden": "true",
    "data-icon": name,
});
function EInkMark({ size = 24, color = "currentColor" }) {
    return h$1("svg", { ...svgProps("eink-brand", { size, color, strokeWidth: 1.9 }) }, [
        h$1("path", { key: "corners", d: "M3.5 8V3.5H8M16 3.5h4.5V8M20.5 16v4.5H16M8 20.5H3.5V16" }),
        h$1("rect", { key: "screen", x: 7.5, y: 7.5, width: 9, height: 9, rx: 1.3 }),
    ]);
}
const iconPaths = {
    carousel: [
        h$1("rect", { key: "a", x: 3, y: 4, width: 6, height: 16, rx: 1.5 }),
        h$1("rect", { key: "b", x: 12, y: 4, width: 9, height: 7, rx: 1.5 }),
        h$1("rect", { key: "c", x: 12, y: 14, width: 9, height: 6, rx: 1.5 }),
    ],
    clock: [
        h$1("circle", { key: "a", cx: 12, cy: 12, r: 8.5 }),
        h$1("path", { key: "b", d: "M12 7.5V12l3.2 2.1" }),
    ],
    weather: [
        h$1("path", { key: "a", d: "M6.3 14.7a4 4 0 1 1 1.2-7.8 5.8 5.8 0 0 1 10.8 3.4 3.3 3.3 0 0 1-.5 6.6H7.1a3.2 3.2 0 0 1-.8-6.3" }),
        h$1("path", { key: "b", d: "M6.2 3.5V2M2.9 6.1 1.8 5M10 5l1.1-1.1" }),
    ],
    deck_status: [
        h$1("path", { key: "a", d: "M4 17a8 8 0 1 1 16 0" }),
        h$1("path", { key: "b", d: "m12 13 4-4" }),
        h$1("circle", { key: "c", cx: 12, cy: 17, r: 1.2 }),
        h$1("path", { key: "d", d: "M6.5 14h1M16.5 14h1M8.3 10.3l.7.7M15 11l.7-.7" }),
    ],
    calendar: [
        h$1("rect", { key: "a", x: 4, y: 5.5, width: 16, height: 14, rx: 2 }),
        h$1("path", { key: "b", d: "M8 3.5v4M16 3.5v4M4 9.5h16M8 13h8M8 16h5" }),
    ],
    timeline: [
        h$1("circle", { key: "a", cx: 9.5, cy: 11, r: 6.5 }),
        h$1("path", { key: "b", d: "M9.5 7.5V11l2.7 1.8" }),
        h$1("rect", { key: "c", x: 14, y: 13, width: 6.5, height: 7.5, rx: 1.4 }),
        h$1("path", { key: "d", d: "M16.3 17h1.9" }),
    ],
    custom: [
        h$1("rect", { key: "a", x: 3.5, y: 4.5, width: 17, height: 15, rx: 2 }),
        h$1("circle", { key: "b", cx: 8.2, cy: 9.2, r: 1.4 }),
        h$1("path", { key: "c", d: "m5.5 17 4.2-4.3 3.2 3 2.2-2.1 3.4 3.4" }),
    ],
    agent: [
        h$1("rect", { key: "a", x: 4, y: 5, width: 16, height: 14, rx: 3 }),
        h$1("circle", { key: "b", cx: 9, cy: 11, r: 1.4 }),
        h$1("circle", { key: "c", cx: 15, cy: 11, r: 1.4 }),
        h$1("path", { key: "d", d: "M8 15h8M12 5V3" }),
    ],
    power: [h$1("path", { key: "a", d: "M12 3v8M7.1 5.8a8 8 0 1 0 9.8 0" })],
    brightness: [
        h$1("circle", { key: "a", cx: 12, cy: 12, r: 3.5 }),
        h$1("path", { key: "b", d: "M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M18.7 5.3l-1.4 1.4M6.7 17.3l-1.4 1.4" }),
    ],
    refresh: [h$1("path", { key: "a", d: "M20 7v5h-5M4 17v-5h5M18.3 12A6.5 6.5 0 0 0 7.1 7.5L4 12M5.7 12a6.5 6.5 0 0 0 11.2 4.5L20 12" })],
    plus: [h$1("path", { key: "a", d: "M12 5v14M5 12h14" })],
    close: [h$1("path", { key: "a", d: "m6 6 12 12M18 6 6 18" })],
    check: [h$1("path", { key: "a", d: "m5 12.5 4.3 4.2L19 7" })],
};
function ModuleIcon({ mode, size = 24, color = "currentColor", strokeWidth = 1.8 }) {
    return h$1("svg", { ...svgProps(`module-${mode}`, { size, color, strokeWidth }) }, iconPaths[mode] ?? iconPaths.custom);
}
function ControlIcon({ name, size = 20, color = "currentColor", strokeWidth = 1.8 }) {
    return h$1("svg", { ...svgProps(`control-${name}`, { size, color, strokeWidth }) }, iconPaths[name]);
}
function EInkTitle() {
    return h$1("div", { style: { display: "flex", alignItems: "center", gap: "7px", fontSize: "15px", fontWeight: 700 } }, [
        h$1(EInkMark, { key: "mark", size: 18, color: "#7b00ff" }),
        h$1("span", { key: "label" }, "JSAUX E-INK"),
    ]);
}
function PdfRange({ id, value, min, max, step, discrete = 0, onChange, actionProps = {}, disabled = false, compact = false, large = false }) {
    const span = Math.max(1, max - min);
    const pct = Math.max(0, Math.min(100, ((value - min) / span) * 100));
    const height = large ? 29 : compact ? 18 : 23;
    const trackTop = large ? 10 : compact ? 7 : 8;
    const trackHeight = large ? 8 : compact ? 4 : 7;
    const thumbSize = large ? 29 : compact ? 16 : 23;
    const thumbTop = large ? 0 : compact ? 1 : 0;
    return h$1("div", { style: { position: "relative", width: "100%", height: `${height}px` }, "data-pdf-range": id }, [
        h$1("div", { key: "track", style: { position: "absolute", left: 0, right: 0, top: `${trackTop}px`, height: `${trackHeight}px`, borderRadius: "999px", background: large ? "#3b404a" : "#454c57", overflow: "hidden" } }, [
            h$1("span", { key: "fill", style: { display: "block", width: `${pct}%`, height: "100%", background: "linear-gradient(90deg,#6e00ff,#9400ff)" } }),
            discrete > 1 ? h$1("span", { key: "ticks", style: { position: "absolute", inset: 0, display: "grid", gridTemplateColumns: `repeat(${discrete - 1}, 1fr)`, pointerEvents: "none" } }, Array.from({ length: discrete - 1 }, (_, index) => h$1("i", { key: index, style: { borderRight: "1px solid #151b22" } }))) : null,
        ]),
        h$1("span", { key: "thumb", style: { position: "absolute", left: `${pct}%`, top: `${thumbTop}px`, width: `${thumbSize}px`, height: `${thumbSize}px`, transform: "translateX(-50%)", borderRadius: "50%", background: "#fff", pointerEvents: "none" } }),
        h$1("input", {
            ...actionProps,
            key: "input",
            type: "range",
            min,
            max,
            step,
            value,
            disabled,
            onChange: (event) => onChange(Number(event.target.value)),
            style: { position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0, cursor: "pointer", margin: 0 },
            "aria-label": id,
        }),
    ]);
}

function normalizeVersion(version) {
    return `V${String(version).trim().replace(/^v/i, "")}`;
}
function resolveFirmwareUi(currentVersion, latestVersion, updateSupported, labels) {
    const current = normalizeVersion(currentVersion);
    const latest = normalizeVersion(latestVersion);
    const upToDate = current === latest;
    return {
        currentVersion: current,
        actionLabel: upToDate ? labels.upToDate : labels.updateNow,
        actionEnabled: !upToDate && updateSupported,
    };
}

const _local_SP_REACT = SP_REACT;
// --- Backend callables ---
const scanDevices = callable("scan");
const connectDevice = callable("connect");
const disconnect = callable("disconnect");
const setConnectionEnabledFn = callable("set_connection_enabled");
const getStatus = callable("get_status");
const getControlState = callable("get_control_state");
const getSettings = callable("get_settings");
const saveSettings = callable("save_settings");
callable("set_timeline_sec");
const refreshNow = callable("refresh_now");
const sendModuleFn = callable("send_module");
const sendDashboardFn = callable("send_dashboard");
const sendClockFn = callable("send_clock");
const sendWeatherFn = callable("send_weather");
const sendCustomFile = callable("send_custom_file");
const setPhotoFrameFolder = callable("set_photo_frame_folder");
const importPhotoFrameAsset = callable("import_photo_frame_asset");
const listPhotoFrameFiles = callable("list_photo_frame_files");
const excludePhotoFrameFile = callable("exclude_photo_frame_file");
const setPhotoFrameSelectedFile = callable("set_photo_frame_selected_file");
const getIpLocation = callable("get_ip_location");
const getDisplayOptions = callable("get_display_options");
const searchWeatherLocations = callable("search_weather_locations");
const callWithTimeout = (promise, timeoutMs, label) => Promise.race([
    promise,
    new Promise((_, reject) => setTimeout(() => reject(new Error(`${label} timed out`)), timeoutMs)),
]);
const getWeatherLocationOptions = callable("get_weather_location_options");
const getAgentStatus = callable("get_agent_status");
const setAgentStatus = callable("set_agent_status");
// --- Constants ---
const PRODUCT_NAME = "JSAUX E-INK";
const UI_TEXT = {
    en: {
        screenSwitch: "Device Connection",
        brightness: "Brightness",
        refreshRate: "Refresh",
        composite: "Composite",
        clock: "Clock",
        weather: "Weather",
        performance: "Performance",
        calendar: "Calendar",
        gameTime: "Game Time",
        custom: "Custom",
        upload: "Upload GIF/Image",
        scanning: "Scanning...",
        connecting: "Connecting",
        connectionConnected: "Connected",
        connectionDisconnected: "Disconnected",
        connectionStatus: "Connection status",
        minutesSuffix: " min",
        disconnectCurrentDevice: "Disconnect the current EInk device before connecting another device",
        sendFailed: "Send failed.",
        folderUnavailable: "Unable to use this folder",
        deleteFailed: "Delete failed.",
        errorMessage: "Error: {error}",
        connectionFailed: "Unable to connect to device",
        delete: "Delete",
        apply: "Push",
        applying: "Pushing",
        add: "Add",
        slideshow: "Auto slideshow",
        firmware: "Firmware",
        latestVersion: "V1.2  Latest",
        updateNow: "Update Now",
        upToDate: "Up to date",
        syncing: "Syncing screen",
        thumbnail: "GIF/Image thumbnail",
    },
    zh: {
        screenSwitch: "设备连接",
        brightness: "屏幕亮度",
        refreshRate: "刷新频率",
        composite: "综合布局",
        clock: "时间模块",
        weather: "天气模块",
        performance: "性能模块",
        calendar: "月历模块",
        gameTime: "游戏时间",
        custom: "个性自定义",
        upload: "上传本地 GIF/图片",
        scanning: "扫描中...",
        connecting: "连接中",
        connectionConnected: "已连接",
        connectionDisconnected: "未连接",
        connectionStatus: "连接状态",
        minutesSuffix: "分钟",
        disconnectCurrentDevice: "请先断开当前 EInk 设备，再连接其他设备",
        sendFailed: "发送失败。",
        folderUnavailable: "无法使用此文件夹",
        deleteFailed: "删除失败。",
        errorMessage: "错误：{error}",
        connectionFailed: "无法连接到设备",
        delete: "删除",
        apply: "推送",
        applying: "推送中",
        add: "添加",
        slideshow: "自动轮播素材",
        firmware: "固件版本",
        latestVersion: "V1.2  最新版本",
        updateNow: "现在更新",
        upToDate: "已是最新",
        syncing: "正在同步屏幕",
        thumbnail: "GIF/图片 缩略图",
    },
    "zh-tw": {
        screenSwitch: "裝置連線",
        brightness: "螢幕亮度",
        refreshRate: "重新整理頻率",
        composite: "綜合版面",
        clock: "時間模組",
        weather: "天氣模組",
        performance: "效能模組",
        calendar: "月曆模組",
        gameTime: "遊戲時間",
        custom: "個性自訂",
        upload: "上傳本機 GIF/圖片",
        scanning: "掃描中...",
        connecting: "連線中",
        connectionConnected: "已連線",
        connectionDisconnected: "未連線",
        connectionStatus: "連線狀態",
        minutesSuffix: "分鐘",
        disconnectCurrentDevice: "請先中斷目前的 EInk 裝置，再連線其他裝置",
        sendFailed: "傳送失敗。",
        folderUnavailable: "無法使用此資料夾",
        deleteFailed: "刪除失敗。",
        errorMessage: "錯誤：{error}",
        connectionFailed: "無法連線到裝置",
        delete: "刪除",
        apply: "推送",
        applying: "推送中",
        add: "新增",
        slideshow: "自動輪播素材",
        firmware: "韌體版本",
        latestVersion: "V1.2  最新版本",
        updateNow: "立即更新",
        upToDate: "已是最新",
        syncing: "正在同步螢幕",
        thumbnail: "GIF/圖片縮圖",
    },
    ja: {
        screenSwitch: "デバイス接続",
        brightness: "画面の明るさ",
        refreshRate: "更新頻度",
        composite: "総合レイアウト",
        clock: "時計モジュール",
        weather: "天気モジュール",
        performance: "性能モジュール",
        calendar: "カレンダー",
        gameTime: "ゲーム時間",
        custom: "カスタム",
        upload: "GIF/画像をアップロード",
        scanning: "スキャン中...",
        connecting: "接続中",
        connectionConnected: "接続済み",
        connectionDisconnected: "未接続",
        connectionStatus: "接続状態",
        minutesSuffix: "分",
        disconnectCurrentDevice: "別のデバイスに接続する前に、現在の EInk デバイスを切断してください。",
        sendFailed: "送信に失敗しました。",
        folderUnavailable: "このフォルダーを使用できません",
        deleteFailed: "削除に失敗しました。",
        errorMessage: "エラー: {error}",
        connectionFailed: "デバイスに接続できません",
        delete: "削除",
        apply: "選択",
        applying: "選択中",
        add: "追加",
        slideshow: "自動スライドショー",
        firmware: "ファームウェア",
        latestVersion: "V1.2  最新版",
        updateNow: "今すぐ更新",
        upToDate: "最新版",
        syncing: "画面を同期中",
        thumbnail: "GIF/画像サムネイル",
    },
    ko: {
        screenSwitch: "기기 연결",
        brightness: "화면 밝기",
        refreshRate: "새로고침 주기",
        composite: "통합 레이아웃",
        clock: "시간 모듈",
        weather: "날씨 모듈",
        performance: "성능 모듈",
        calendar: "달력 모듈",
        gameTime: "게임 시간",
        custom: "사용자 지정",
        upload: "GIF/이미지 업로드",
        scanning: "스캔 중...",
        connecting: "연결 중",
        connectionConnected: "연결됨",
        connectionDisconnected: "연결 안 됨",
        connectionStatus: "연결 상태",
        minutesSuffix: "분",
        disconnectCurrentDevice: "다른 기기를 연결하기 전에 현재 EInk 기기의 연결을 해제하세요.",
        sendFailed: "전송에 실패했습니다.",
        folderUnavailable: "이 폴더를 사용할 수 없습니다",
        deleteFailed: "삭제하지 못했습니다.",
        errorMessage: "오류: {error}",
        connectionFailed: "기기에 연결할 수 없습니다",
        delete: "삭제",
        apply: "선택",
        applying: "선택 중",
        add: "추가",
        slideshow: "자동 슬라이드쇼",
        firmware: "펌웨어",
        latestVersion: "V1.2  최신",
        updateNow: "지금 업데이트",
        upToDate: "최신 상태",
        syncing: "화면 동기화 중",
        thumbnail: "GIF/이미지 썸네일",
    },
    de: {
        screenSwitch: "Geraet verbinden",
        brightness: "Helligkeit",
        refreshRate: "Aktualisierung",
        composite: "Gesamtlayout",
        clock: "Zeitmodul",
        weather: "Wettermodul",
        performance: "Leistung",
        calendar: "Kalender",
        gameTime: "Spielzeit",
        custom: "Anpassen",
        upload: "GIF/Bild hochladen",
        scanning: "Suche...",
        connecting: "Verbindung...",
        connectionConnected: "Verbunden",
        connectionDisconnected: "Nicht verbunden",
        connectionStatus: "Verbindungsstatus",
        minutesSuffix: " Min.",
        disconnectCurrentDevice: "Trennen Sie das aktuelle EInk-Gerät, bevor Sie ein anderes Gerät verbinden.",
        sendFailed: "Senden fehlgeschlagen.",
        folderUnavailable: "Dieser Ordner kann nicht verwendet werden",
        deleteFailed: "Löschen fehlgeschlagen.",
        errorMessage: "Fehler: {error}",
        connectionFailed: "Keine Verbindung zum Gerät möglich",
        delete: "Löschen",
        apply: "Auswählen",
        applying: "Wird ausgewählt",
        add: "Hinzufügen",
        slideshow: "Auto-Diashow",
        firmware: "Firmware",
        latestVersion: "V1.2  Aktuell",
        updateNow: "Jetzt aktualisieren",
        upToDate: "Aktuell",
        syncing: "Bildschirm wird synchronisiert",
        thumbnail: "GIF/Bild-Vorschau",
    },
    fr: {
        screenSwitch: "Connexion appareil",
        brightness: "Luminosite",
        refreshRate: "Actualisation",
        composite: "Disposition",
        clock: "Heure",
        weather: "Meteo",
        performance: "Performances",
        calendar: "Calendrier",
        gameTime: "Temps de jeu",
        custom: "Personnaliser",
        upload: "Importer GIF/image",
        scanning: "Analyse...",
        connecting: "Connexion...",
        connectionConnected: "Connecté",
        connectionDisconnected: "Non connecté",
        connectionStatus: "État de la connexion",
        minutesSuffix: " min",
        disconnectCurrentDevice: "Déconnectez l’appareil EInk actuel avant d’en connecter un autre.",
        sendFailed: "Échec de l’envoi.",
        folderUnavailable: "Ce dossier ne peut pas être utilisé",
        deleteFailed: "Échec de la suppression.",
        errorMessage: "Erreur : {error}",
        connectionFailed: "Impossible de connecter l’appareil",
        delete: "Supprimer",
        apply: "Sélectionner",
        applying: "Sélection",
        add: "Ajouter",
        slideshow: "Diaporama auto",
        firmware: "Firmware",
        latestVersion: "V1.2  Derniere",
        updateNow: "Mettre à jour",
        upToDate: "A jour",
        syncing: "Synchronisation ecran",
        thumbnail: "Miniature GIF/image",
    },
    es: {
        screenSwitch: "Conexion del dispositivo",
        brightness: "Brillo",
        refreshRate: "Actualizacion",
        composite: "Diseno general",
        clock: "Hora",
        weather: "Clima",
        performance: "Rendimiento",
        calendar: "Calendario",
        gameTime: "Tiempo de juego",
        custom: "Personalizado",
        upload: "Subir GIF/imagen",
        scanning: "Buscando...",
        connecting: "Conectando...",
        connectionConnected: "Conectado",
        connectionDisconnected: "Desconectado",
        connectionStatus: "Estado de conexión",
        minutesSuffix: " min",
        disconnectCurrentDevice: "Desconecta el dispositivo EInk actual antes de conectar otro.",
        sendFailed: "Error al enviar.",
        folderUnavailable: "No se puede usar esta carpeta",
        deleteFailed: "Error al eliminar.",
        errorMessage: "Error: {error}",
        connectionFailed: "No se pudo conectar al dispositivo",
        delete: "Eliminar",
        apply: "Seleccionar",
        applying: "Seleccionando",
        add: "Agregar",
        slideshow: "Presentacion auto",
        firmware: "Firmware",
        latestVersion: "V1.2  Ultima",
        updateNow: "Actualizar ahora",
        upToDate: "Actualizado",
        syncing: "Sincronizando pantalla",
        thumbnail: "Miniatura GIF/imagen",
    },
    ru: {
        screenSwitch: "Подключение устройства",
        brightness: "Яркость",
        refreshRate: "Обновление",
        composite: "Общий макет",
        clock: "Время",
        weather: "Погода",
        performance: "Производительность",
        calendar: "Календарь",
        gameTime: "Игровое время",
        custom: "Настройка",
        upload: "Загрузить GIF/изображение",
        scanning: "Сканирование...",
        connecting: "Подключение...",
        connectionConnected: "Подключено",
        connectionDisconnected: "Не подключено",
        connectionStatus: "Состояние подключения",
        minutesSuffix: " мин",
        disconnectCurrentDevice: "Перед подключением другого устройства отключите текущее устройство EInk.",
        sendFailed: "Не удалось отправить данные.",
        folderUnavailable: "Невозможно использовать эту папку",
        deleteFailed: "Не удалось удалить.",
        errorMessage: "Ошибка: {error}",
        connectionFailed: "Не удалось подключиться к устройству",
        delete: "Удалить",
        apply: "Выбрать",
        applying: "Выбор",
        add: "Добавить",
        slideshow: "Автослайд-шоу",
        firmware: "Прошивка",
        latestVersion: "V1.2  Последняя",
        updateNow: "Обновить сейчас",
        upToDate: "Актуально",
        syncing: "Синхронизация экрана",
        thumbnail: "Миниатюра GIF/изображения",
    },
};
const PHOTO_FRAME_TEXT = {
    en: { imageSwitchInterval: "Image Switch Interval", moduleSwitchInterval: "Module Switch Interval", custom: "Photo Frame", upload: "Upload Local Folder" },
    zh: { imageSwitchInterval: "\u56fe\u7247\u5207\u6362\u95f4\u9694", moduleSwitchInterval: "\u6a21\u5757\u5207\u6362\u95f4\u9694", custom: "\u7535\u5b50\u76f8\u6846", upload: "\u4e0a\u4f20\u672c\u5730\u6587\u4ef6\u5939" },
    "zh-tw": { imageSwitchInterval: "\u5716\u7247\u5207\u63db\u9593\u9694", moduleSwitchInterval: "\u6a21\u7d44\u5207\u63db\u9593\u9694", custom: "\u96fb\u5b50\u76f8\u6846", upload: "\u4e0a\u50b3\u672c\u6a5f\u8cc7\u6599\u593e" },
    ja: { imageSwitchInterval: "\u753b\u50cf\u5207\u308a\u66ff\u3048\u9593\u9694", moduleSwitchInterval: "\u30e2\u30b8\u30e5\u30fc\u30eb\u5207\u308a\u66ff\u3048\u9593\u9694", custom: "\u30d5\u30a9\u30c8\u30d5\u30ec\u30fc\u30e0", upload: "\u30ed\u30fc\u30ab\u30eb\u30d5\u30a9\u30eb\u30c0\u30fc\u3092\u9078\u629e" },
    ko: { imageSwitchInterval: "\uc774\ubbf8\uc9c0 \uc804\ud658 \uac04\uaca9", moduleSwitchInterval: "\ubaa8\ub4c8 \uc804\ud658 \uac04\uaca9", custom: "\uc804\uc790 \uc561\uc790 \ud504\ub808\uc784", upload: "\ub85c\uceec \ud3f4\ub354 \uc5c5\ub85c\ub4dc" },
    de: { imageSwitchInterval: "Bildwechselintervall", moduleSwitchInterval: "Modulwechselintervall", custom: "Fotorahmen", upload: "Lokalen Ordner auswählen" },
    fr: { imageSwitchInterval: "Intervalle de changement d'image", moduleSwitchInterval: "Intervalle de changement de module", custom: "Cadre photo", upload: "Choisir un dossier local" },
    es: { imageSwitchInterval: "Intervalo de cambio de imagen", moduleSwitchInterval: "Intervalo de cambio de módulo", custom: "Marco de fotos", upload: "Elegir carpeta local" },
    ru: { imageSwitchInterval: "Интервал смены изображений", moduleSwitchInterval: "Интервал смены модулей", custom: "Фоторамка", upload: "Выбрать локальную папку" },
};
Object.entries(PHOTO_FRAME_TEXT).forEach(([language, text]) => Object.assign(UI_TEXT[language], text));
for (const [language, label] of Object.entries({ en: "AI Agent", zh: "AI Agent", "zh-tw": "AI Agent" })) {
    if (UI_TEXT[language])
        UI_TEXT[language].agent = label;
}

const SUPPORTED_GAME_LANGUAGES = Object.freeze(["ar", "pt-br", "bg", "cs", "da", "nl", "en", "fi", "fr", "de", "el", "hu", "id", "it", "ja", "ko", "es-419", "ms", "no", "pl", "pt", "ro", "ru", "zh", "es", "sv", "zh-tw", "th", "tr", "uk", "vi"]);
const STEAM_LANGUAGE_ALIASES = Object.freeze({
    "arabic": "ar", "ar": "ar", "brazilian": "pt-br", "pt-br": "pt-br", "bulgarian": "bg", "bg": "bg", "czech": "cs", "cs": "cs", "danish": "da", "da": "da", "dutch": "nl", "nl": "nl",
    "english": "en", "en": "en", "finnish": "fi", "fi": "fi", "french": "fr", "fr": "fr", "german": "de", "de": "de", "greek": "el", "el": "el", "hungarian": "hu", "hu": "hu",
    "indonesian": "id", "id": "id", "italian": "it", "it": "it", "japanese": "ja", "ja": "ja", "koreana": "ko", "korean": "ko", "ko": "ko", "latam": "es-419", "es-419": "es-419",
    "malay": "ms", "ms": "ms", "norwegian": "no", "no": "no", "nb": "no", "nn": "no", "polish": "pl", "pl": "pl", "portuguese": "pt", "pt": "pt", "romanian": "ro", "ro": "ro",
    "russian": "ru", "ru": "ru", "schinese": "zh", "spanish": "es", "es": "es", "swedish": "sv", "sv": "sv", "tchinese": "zh-tw", "thai": "th", "th": "th", "turkish": "tr", "tr": "tr", "ukrainian": "uk", "uk": "uk", "vietnamese": "vi", "vi": "vi",
});
const EXTENDED_UI_TEXT = {
    ar: { screenSwitch: "اتصال الجهاز", brightness: "فاصل تبديل الصور", refreshRate: "فاصل تبديل الوحدات", composite: "تخطيط مركب", clock: "الوقت", weather: "الطقس", performance: "الأداء", calendar: "التقويم", gameTime: "وقت اللعب", custom: "إطار الصور", upload: "رفع مجلد محلي", scanning: "جارٍ البحث...", connecting: "جارٍ الاتصال", connectionConnected: "متصل", connectionDisconnected: "غير متصل", connectionStatus: "حالة الاتصال", minutesSuffix: " د", delete: "حذف", apply: "تحديد", applying: "جارٍ التحديد", add: "إضافة", slideshow: "عرض شرائح تلقائي", firmware: "البرنامج الثابت", updateNow: "تحديث الآن", upToDate: "محدّث", syncing: "جارٍ مزامنة الشاشة", thumbnail: "صورة GIF/صورة مصغرة", imageSwitchInterval: "فاصل تبديل الصور", moduleSwitchInterval: "فاصل تبديل الوحدات" },
    "pt-br": { screenSwitch: "Conexão do dispositivo", brightness: "Intervalo de imagens", refreshRate: "Intervalo de módulos", composite: "Layout composto", clock: "Relógio", weather: "Clima", performance: "Desempenho", calendar: "Calendário", gameTime: "Tempo de jogo", custom: "Porta-retratos", upload: "Enviar pasta local", scanning: "Procurando...", connecting: "Conectando", connectionConnected: "Conectado", connectionDisconnected: "Desconectado", connectionStatus: "Status da conexão", minutesSuffix: " min", delete: "Excluir", apply: "Selecionar", applying: "Selecionando", add: "Adicionar", slideshow: "Apresentação automática", firmware: "Firmware", updateNow: "Atualizar agora", upToDate: "Atualizado", syncing: "Sincronizando tela", thumbnail: "Miniatura GIF/imagem", imageSwitchInterval: "Intervalo de imagens", moduleSwitchInterval: "Intervalo de módulos" },
    bg: { screenSwitch: "Свързване на устройство", brightness: "Интервал на снимките", refreshRate: "Интервал на модулите", composite: "Комбинирано оформление", clock: "Часовник", weather: "Време", performance: "Производителност", calendar: "Календар", gameTime: "Време за игра", custom: "Фото рамка", upload: "Качване на локална папка", scanning: "Търсене...", connecting: "Свързване", connectionConnected: "Свързано", connectionDisconnected: "Прекъснато", connectionStatus: "Състояние на връзката", minutesSuffix: " мин", delete: "Изтриване", apply: "Избор", applying: "Избиране", add: "Добавяне", slideshow: "Автоматично слайдшоу", firmware: "Фърмуер", updateNow: "Актуализирай", upToDate: "Актуално", syncing: "Синхронизиране на екрана", thumbnail: "Миниатюра GIF/изображение", imageSwitchInterval: "Интервал на снимките", moduleSwitchInterval: "Интервал на модулите" },
    cs: { screenSwitch: "Připojení zařízení", brightness: "Interval obrázků", refreshRate: "Interval modulů", composite: "Složené rozvržení", clock: "Hodiny", weather: "Počasí", performance: "Výkon", calendar: "Kalendář", gameTime: "Herní čas", custom: "Fotorámeček", upload: "Nahrát místní složku", scanning: "Vyhledávání...", connecting: "Připojování", connectionConnected: "Připojeno", connectionDisconnected: "Odpojeno", connectionStatus: "Stav připojení", minutesSuffix: " min", delete: "Odstranit", apply: "Vybrat", applying: "Vybírání", add: "Přidat", slideshow: "Automatická prezentace", firmware: "Firmware", updateNow: "Aktualizovat", upToDate: "Aktuální", syncing: "Synchronizace obrazovky", thumbnail: "Náhled GIF/obrázku", imageSwitchInterval: "Interval obrázků", moduleSwitchInterval: "Interval modulů" },
    da: { screenSwitch: "Enhedsforbindelse", brightness: "Billedinterval", refreshRate: "Modulinterval", composite: "Samlet layout", clock: "Ur", weather: "Vejr", performance: "Ydeevne", calendar: "Kalender", gameTime: "Spilletid", custom: "Fotoramme", upload: "Upload lokal mappe", scanning: "Søger...", connecting: "Tilslutter", connectionConnected: "Tilsluttet", connectionDisconnected: "Ikke tilsluttet", connectionStatus: "Forbindelsesstatus", minutesSuffix: " min", delete: "Slet", apply: "Vælg", applying: "Vælger", add: "Tilføj", slideshow: "Automatisk diasshow", firmware: "Firmware", updateNow: "Opdater nu", upToDate: "Opdateret", syncing: "Synkroniserer skærm", thumbnail: "GIF/billede-miniature", imageSwitchInterval: "Billedinterval", moduleSwitchInterval: "Modulinterval" },
    nl: { screenSwitch: "Apparaatverbinding", brightness: "Afbeeldingsinterval", refreshRate: "Module-interval", composite: "Samengestelde indeling", clock: "Klok", weather: "Weer", performance: "Prestaties", calendar: "Kalender", gameTime: "Speeltijd", custom: "Fotolijst", upload: "Lokale map uploaden", scanning: "Zoeken...", connecting: "Verbinden", connectionConnected: "Verbonden", connectionDisconnected: "Niet verbonden", connectionStatus: "Verbindingsstatus", minutesSuffix: " min", delete: "Verwijderen", apply: "Selecteren", applying: "Selecteren", add: "Toevoegen", slideshow: "Automatische diavoorstelling", firmware: "Firmware", updateNow: "Nu bijwerken", upToDate: "Bijgewerkt", syncing: "Scherm synchroniseren", thumbnail: "GIF/afbeelding-miniatuur", imageSwitchInterval: "Afbeeldingsinterval", moduleSwitchInterval: "Module-interval" },
    fi: { screenSwitch: "Laiteyhteys", brightness: "Kuvaväli", refreshRate: "Moduuliväli", composite: "Yhdistelmäasettelu", clock: "Kello", weather: "Sää", performance: "Suorituskyky", calendar: "Kalenteri", gameTime: "Peliaika", custom: "Valokuvakehys", upload: "Lataa paikallinen kansio", scanning: "Haetaan...", connecting: "Yhdistetään", connectionConnected: "Yhdistetty", connectionDisconnected: "Ei yhdistetty", connectionStatus: "Yhteyden tila", minutesSuffix: " min", delete: "Poista", apply: "Valitse", applying: "Valitaan", add: "Lisää", slideshow: "Automaattinen diaesitys", firmware: "Laiteohjelmisto", updateNow: "Päivitä nyt", upToDate: "Ajan tasalla", syncing: "Näyttöä synkronoidaan", thumbnail: "GIF/kuvan esikatselu", imageSwitchInterval: "Kuvaväli", moduleSwitchInterval: "Moduuliväli" },
    el: { screenSwitch: "Σύνδεση συσκευής", brightness: "Διάστημα εικόνων", refreshRate: "Διάστημα μονάδων", composite: "Σύνθετη διάταξη", clock: "Ρολόι", weather: "Καιρός", performance: "Απόδοση", calendar: "Ημερολόγιο", gameTime: "Χρόνος παιχνιδιού", custom: "Κορνίζα φωτογραφιών", upload: "Μεταφόρτωση τοπικού φακέλου", scanning: "Αναζήτηση...", connecting: "Σύνδεση", connectionConnected: "Συνδέθηκε", connectionDisconnected: "Δεν συνδέθηκε", connectionStatus: "Κατάσταση σύνδεσης", minutesSuffix: " λ.", delete: "Διαγραφή", apply: "Επιλογή", applying: "Επιλογή", add: "Προσθήκη", slideshow: "Αυτόματη παρουσίαση", firmware: "Υλικολογισμικό", updateNow: "Ενημέρωση τώρα", upToDate: "Ενημερωμένο", syncing: "Συγχρονισμός οθόνης", thumbnail: "Μικρογραφία GIF/εικόνας", imageSwitchInterval: "Διάστημα εικόνων", moduleSwitchInterval: "Διάστημα μονάδων" },
    hu: { screenSwitch: "Eszközkapcsolat", brightness: "Képváltási idő", refreshRate: "Modulváltási idő", composite: "Összetett elrendezés", clock: "Óra", weather: "Időjárás", performance: "Teljesítmény", calendar: "Naptár", gameTime: "Játékidő", custom: "Digitális képkeret", upload: "Helyi mappa feltöltése", scanning: "Keresés...", connecting: "Csatlakozás", connectionConnected: "Csatlakozva", connectionDisconnected: "Nincs csatlakoztatva", connectionStatus: "Kapcsolat állapota", minutesSuffix: " perc", delete: "Törlés", apply: "Kiválasztás", applying: "Kiválasztás", add: "Hozzáadás", slideshow: "Automatikus diavetítés", firmware: "Firmware", updateNow: "Frissítés", upToDate: "Naprakész", syncing: "Képernyő szinkronizálása", thumbnail: "GIF/kép bélyegkép", imageSwitchInterval: "Képváltási idő", moduleSwitchInterval: "Modulváltási idő" },
    id: { screenSwitch: "Koneksi perangkat", brightness: "Interval gambar", refreshRate: "Interval modul", composite: "Tata letak gabungan", clock: "Jam", weather: "Cuaca", performance: "Performa", calendar: "Kalender", gameTime: "Waktu bermain", custom: "Bingkai foto", upload: "Unggah folder lokal", scanning: "Mencari...", connecting: "Menghubungkan", connectionConnected: "Terhubung", connectionDisconnected: "Tidak terhubung", connectionStatus: "Status koneksi", minutesSuffix: " mnt", delete: "Hapus", apply: "Pilih", applying: "Memilih", add: "Tambah", slideshow: "Tayangan slide otomatis", firmware: "Firmware", updateNow: "Perbarui sekarang", upToDate: "Terkini", syncing: "Menyinkronkan layar", thumbnail: "Gambar mini GIF/gambar", imageSwitchInterval: "Interval gambar", moduleSwitchInterval: "Interval modul" },
    it: { screenSwitch: "Connessione dispositivo", brightness: "Intervallo immagini", refreshRate: "Intervallo moduli", composite: "Layout combinato", clock: "Orologio", weather: "Meteo", performance: "Prestazioni", calendar: "Calendario", gameTime: "Tempo di gioco", custom: "Cornice foto", upload: "Carica cartella locale", scanning: "Ricerca...", connecting: "Connessione", connectionConnected: "Connesso", connectionDisconnected: "Disconnesso", connectionStatus: "Stato connessione", minutesSuffix: " min", delete: "Elimina", apply: "Seleziona", applying: "Selezione", add: "Aggiungi", slideshow: "Presentazione automatica", firmware: "Firmware", updateNow: "Aggiorna ora", upToDate: "Aggiornato", syncing: "Sincronizzazione schermo", thumbnail: "Miniatura GIF/immagine", imageSwitchInterval: "Intervallo immagini", moduleSwitchInterval: "Intervallo moduli" },
    "es-419": { screenSwitch: "Conexión del dispositivo", brightness: "Intervalo de imágenes", refreshRate: "Intervalo de módulos", composite: "Diseño combinado", clock: "Reloj", weather: "Clima", performance: "Rendimiento", calendar: "Calendario", gameTime: "Tiempo de juego", custom: "Marco de fotos", upload: "Subir carpeta local", scanning: "Buscando...", connecting: "Conectando", connectionConnected: "Conectado", connectionDisconnected: "Desconectado", connectionStatus: "Estado de conexión", minutesSuffix: " min", delete: "Eliminar", apply: "Seleccionar", applying: "Seleccionando", add: "Agregar", slideshow: "Presentación automática", firmware: "Firmware", updateNow: "Actualizar ahora", upToDate: "Actualizado", syncing: "Sincronizando pantalla", thumbnail: "Miniatura GIF/imagen", imageSwitchInterval: "Intervalo de imágenes", moduleSwitchInterval: "Intervalo de módulos" },
    ms: { screenSwitch: "Sambungan peranti", brightness: "Selang imej", refreshRate: "Selang modul", composite: "Susun atur gabungan", clock: "Jam", weather: "Cuaca", performance: "Prestasi", calendar: "Kalendar", gameTime: "Masa permainan", custom: "Bingkai foto", upload: "Muat naik folder tempatan", scanning: "Mencari...", connecting: "Menyambung", connectionConnected: "Bersambung", connectionDisconnected: "Tidak bersambung", connectionStatus: "Status sambungan", minutesSuffix: " min", delete: "Padam", apply: "Pilih", applying: "Memilih", add: "Tambah", slideshow: "Tayangan slaid automatik", firmware: "Perisian tegar", updateNow: "Kemas kini sekarang", upToDate: "Terkini", syncing: "Menyegerakkan skrin", thumbnail: "Imej kecil GIF/imej", imageSwitchInterval: "Selang imej", moduleSwitchInterval: "Selang modul" },
    no: { screenSwitch: "Enhetsforbindelse", brightness: "Bildeintervall", refreshRate: "Modulintervall", composite: "Kombinert oppsett", clock: "Klokke", weather: "Vær", performance: "Ytelse", calendar: "Kalender", gameTime: "Spilletid", custom: "Fotoramme", upload: "Last opp lokal mappe", scanning: "Søker...", connecting: "Kobler til", connectionConnected: "Tilkoblet", connectionDisconnected: "Ikke tilkoblet", connectionStatus: "Tilkoblingsstatus", minutesSuffix: " min", delete: "Slett", apply: "Velg", applying: "Velger", add: "Legg til", slideshow: "Automatisk lysbildefremvisning", firmware: "Fastvare", updateNow: "Oppdater nå", upToDate: "Oppdatert", syncing: "Synkroniserer skjerm", thumbnail: "GIF/bilde-miniatyr", imageSwitchInterval: "Bildeintervall", moduleSwitchInterval: "Modulintervall" },
    pl: { screenSwitch: "Połączenie urządzenia", brightness: "Interwał obrazów", refreshRate: "Interwał modułów", composite: "Układ łączony", clock: "Zegar", weather: "Pogoda", performance: "Wydajność", calendar: "Kalendarz", gameTime: "Czas gry", custom: "Ramka na zdjęcia", upload: "Prześlij folder lokalny", scanning: "Wyszukiwanie...", connecting: "Łączenie", connectionConnected: "Połączono", connectionDisconnected: "Rozłączono", connectionStatus: "Stan połączenia", minutesSuffix: " min", delete: "Usuń", apply: "Wybierz", applying: "Wybieranie", add: "Dodaj", slideshow: "Automatyczny pokaz slajdów", firmware: "Oprogramowanie", updateNow: "Aktualizuj", upToDate: "Aktualne", syncing: "Synchronizacja ekranu", thumbnail: "Miniatura GIF/obrazu", imageSwitchInterval: "Interwał obrazów", moduleSwitchInterval: "Interwał modułów" },
    pt: { screenSwitch: "Ligação do dispositivo", brightness: "Intervalo de imagens", refreshRate: "Intervalo de módulos", composite: "Esquema composto", clock: "Relógio", weather: "Meteorologia", performance: "Desempenho", calendar: "Calendário", gameTime: "Tempo de jogo", custom: "Moldura digital", upload: "Carregar pasta local", scanning: "A procurar...", connecting: "A ligar", connectionConnected: "Ligado", connectionDisconnected: "Desligado", connectionStatus: "Estado da ligação", minutesSuffix: " min", delete: "Eliminar", apply: "Selecionar", applying: "A selecionar", add: "Adicionar", slideshow: "Apresentação automática", firmware: "Firmware", updateNow: "Atualizar agora", upToDate: "Atualizado", syncing: "A sincronizar ecrã", thumbnail: "Miniatura GIF/imagem", imageSwitchInterval: "Intervalo de imagens", moduleSwitchInterval: "Intervalo de módulos" },
    ro: { screenSwitch: "Conexiune dispozitiv", brightness: "Interval imagini", refreshRate: "Interval module", composite: "Aspect combinat", clock: "Ceas", weather: "Vreme", performance: "Performanță", calendar: "Calendar", gameTime: "Timp de joc", custom: "Ramă foto", upload: "Încarcă dosar local", scanning: "Căutare...", connecting: "Se conectează", connectionConnected: "Conectat", connectionDisconnected: "Deconectat", connectionStatus: "Stare conexiune", minutesSuffix: " min", delete: "Șterge", apply: "Selectează", applying: "Selectare", add: "Adaugă", slideshow: "Prezentare automată", firmware: "Firmware", updateNow: "Actualizează", upToDate: "Actualizat", syncing: "Se sincronizează ecranul", thumbnail: "Miniatură GIF/imagine", imageSwitchInterval: "Interval imagini", moduleSwitchInterval: "Interval module" },
    sv: { screenSwitch: "Enhetsanslutning", brightness: "Bildintervall", refreshRate: "Modulintervall", composite: "Kombinerad layout", clock: "Klocka", weather: "Väder", performance: "Prestanda", calendar: "Kalender", gameTime: "Speltid", custom: "Fotoram", upload: "Ladda upp lokal mapp", scanning: "Söker...", connecting: "Ansluter", connectionConnected: "Ansluten", connectionDisconnected: "Inte ansluten", connectionStatus: "Anslutningsstatus", minutesSuffix: " min", delete: "Ta bort", apply: "Välj", applying: "Väljer", add: "Lägg till", slideshow: "Automatiskt bildspel", firmware: "Firmware", updateNow: "Uppdatera nu", upToDate: "Uppdaterad", syncing: "Synkroniserar skärm", thumbnail: "GIF/bild-miniatyr", imageSwitchInterval: "Bildintervall", moduleSwitchInterval: "Modulintervall" },
    th: { screenSwitch: "การเชื่อมต่ออุปกรณ์", brightness: "ช่วงเปลี่ยนรูปภาพ", refreshRate: "ช่วงสลับโมดูล", composite: "เค้าโครงรวม", clock: "นาฬิกา", weather: "สภาพอากาศ", performance: "ประสิทธิภาพ", calendar: "ปฏิทิน", gameTime: "เวลาเล่นเกม", custom: "กรอบรูป", upload: "อัปโหลดโฟลเดอร์ในเครื่อง", scanning: "กำลังค้นหา...", connecting: "กำลังเชื่อมต่อ", connectionConnected: "เชื่อมต่อแล้ว", connectionDisconnected: "ไม่ได้เชื่อมต่อ", connectionStatus: "สถานะการเชื่อมต่อ", minutesSuffix: " นาที", delete: "ลบ", apply: "เลือก", applying: "กำลังเลือก", add: "เพิ่ม", slideshow: "สไลด์โชว์อัตโนมัติ", firmware: "เฟิร์มแวร์", updateNow: "อัปเดตตอนนี้", upToDate: "เป็นปัจจุบัน", syncing: "กำลังซิงค์หน้าจอ", thumbnail: "ภาพขนาดย่อ GIF/รูปภาพ", imageSwitchInterval: "ช่วงเปลี่ยนรูปภาพ", moduleSwitchInterval: "ช่วงสลับโมดูล" },
    tr: { screenSwitch: "Aygıt bağlantısı", brightness: "Görüntü aralığı", refreshRate: "Modül aralığı", composite: "Birleşik düzen", clock: "Saat", weather: "Hava durumu", performance: "Performans", calendar: "Takvim", gameTime: "Oyun süresi", custom: "Fotoğraf çerçevesi", upload: "Yerel klasörü yükle", scanning: "Aranıyor...", connecting: "Bağlanıyor", connectionConnected: "Bağlandı", connectionDisconnected: "Bağlı değil", connectionStatus: "Bağlantı durumu", minutesSuffix: " dk", delete: "Sil", apply: "Seç", applying: "Seçiliyor", add: "Ekle", slideshow: "Otomatik slayt gösterisi", firmware: "Bellenim", updateNow: "Şimdi güncelle", upToDate: "Güncel", syncing: "Ekran eşitleniyor", thumbnail: "GIF/görüntü küçük resmi", imageSwitchInterval: "Görüntü aralığı", moduleSwitchInterval: "Modül aralığı" },
    uk: { screenSwitch: "Підключення пристрою", brightness: "Інтервал зображень", refreshRate: "Інтервал модулів", composite: "Комбінований макет", clock: "Годинник", weather: "Погода", performance: "Продуктивність", calendar: "Календар", gameTime: "Ігровий час", custom: "Фоторамка", upload: "Завантажити локальну папку", scanning: "Пошук...", connecting: "Підключення", connectionConnected: "Підключено", connectionDisconnected: "Не підключено", connectionStatus: "Стан підключення", minutesSuffix: " хв", delete: "Видалити", apply: "Вибрати", applying: "Вибір", add: "Додати", slideshow: "Автоматичне слайд-шоу", firmware: "Прошивка", updateNow: "Оновити", upToDate: "Актуально", syncing: "Синхронізація екрана", thumbnail: "Мініатюра GIF/зображення", imageSwitchInterval: "Інтервал зображень", moduleSwitchInterval: "Інтервал модулів" },
    vi: { screenSwitch: "Kết nối thiết bị", brightness: "Khoảng chuyển ảnh", refreshRate: "Khoảng chuyển mô-đun", composite: "Bố cục tổng hợp", clock: "Đồng hồ", weather: "Thời tiết", performance: "Hiệu năng", calendar: "Lịch", gameTime: "Thời gian chơi", custom: "Khung ảnh", upload: "Tải thư mục cục bộ", scanning: "Đang tìm...", connecting: "Đang kết nối", connectionConnected: "Đã kết nối", connectionDisconnected: "Chưa kết nối", connectionStatus: "Trạng thái kết nối", minutesSuffix: " phút", delete: "Xóa", apply: "Chọn", applying: "Đang chọn", add: "Thêm", slideshow: "Trình chiếu tự động", firmware: "Phần mềm", updateNow: "Cập nhật ngay", upToDate: "Đã cập nhật", syncing: "Đang đồng bộ màn hình", thumbnail: "Hình thu nhỏ GIF/ảnh", imageSwitchInterval: "Khoảng chuyển ảnh", moduleSwitchInterval: "Khoảng chuyển mô-đun" },
};
Object.entries(EXTENDED_UI_TEXT).forEach(([language, text]) => {
    UI_TEXT[language] = { ...UI_TEXT.en, ...text };
});
const EXTENDED_UI_MESSAGES = {
    ar: { latestVersion: "V1.2 الأحدث", disconnectCurrentDevice: "افصل جهاز EInk الحالي قبل توصيل جهاز آخر", sendFailed: "فشل الإرسال.", folderUnavailable: "لا يمكن استخدام هذا المجلد", deleteFailed: "فشل الحذف.", errorMessage: "خطأ: {error}", connectionFailed: "تعذر الاتصال بالجهاز" },
    "pt-br": { latestVersion: "V1.2 Mais recente", disconnectCurrentDevice: "Desconecte o EInk atual antes de conectar outro dispositivo", sendFailed: "Falha no envio.", folderUnavailable: "Não é possível usar esta pasta", deleteFailed: "Falha ao excluir.", errorMessage: "Erro: {error}", connectionFailed: "Não foi possível conectar ao dispositivo" },
    bg: { latestVersion: "V1.2 Последна", disconnectCurrentDevice: "Прекъснете текущото EInk устройство, преди да свържете друго", sendFailed: "Изпращането е неуспешно.", folderUnavailable: "Тази папка не може да се използва", deleteFailed: "Изтриването е неуспешно.", errorMessage: "Грешка: {error}", connectionFailed: "Неуспешно свързване с устройството" },
    cs: { latestVersion: "V1.2 Nejnovější", disconnectCurrentDevice: "Před připojením jiného zařízení odpojte aktuální EInk", sendFailed: "Odeslání se nezdařilo.", folderUnavailable: "Tuto složku nelze použít", deleteFailed: "Odstranění se nezdařilo.", errorMessage: "Chyba: {error}", connectionFailed: "Zařízení nelze připojit" },
    da: { latestVersion: "V1.2 Seneste", disconnectCurrentDevice: "Afbryd den aktuelle EInk-enhed, før du tilslutter en anden", sendFailed: "Afsendelse mislykkedes.", folderUnavailable: "Denne mappe kan ikke bruges", deleteFailed: "Sletning mislykkedes.", errorMessage: "Fejl: {error}", connectionFailed: "Kan ikke oprette forbindelse til enheden" },
    nl: { latestVersion: "V1.2 Nieuwste", disconnectCurrentDevice: "Ontkoppel het huidige EInk-apparaat voordat u een ander apparaat verbindt", sendFailed: "Verzenden mislukt.", folderUnavailable: "Deze map kan niet worden gebruikt", deleteFailed: "Verwijderen mislukt.", errorMessage: "Fout: {error}", connectionFailed: "Kan geen verbinding maken met het apparaat" },
    fi: { latestVersion: "V1.2 Uusin", disconnectCurrentDevice: "Katkaise nykyisen EInk-laitteen yhteys ennen toisen laitteen yhdistämistä", sendFailed: "Lähetys epäonnistui.", folderUnavailable: "Tätä kansiota ei voi käyttää", deleteFailed: "Poisto epäonnistui.", errorMessage: "Virhe: {error}", connectionFailed: "Laitteeseen ei voi muodostaa yhteyttä" },
    el: { latestVersion: "V1.2 Τελευταία", disconnectCurrentDevice: "Αποσυνδέστε την τρέχουσα συσκευή EInk πριν συνδέσετε άλλη", sendFailed: "Η αποστολή απέτυχε.", folderUnavailable: "Δεν είναι δυνατή η χρήση αυτού του φακέλου", deleteFailed: "Η διαγραφή απέτυχε.", errorMessage: "Σφάλμα: {error}", connectionFailed: "Αδυναμία σύνδεσης με τη συσκευή" },
    hu: { latestVersion: "V1.2 Legújabb", disconnectCurrentDevice: "Másik eszköz csatlakoztatása előtt válassza le a jelenlegi EInk eszközt", sendFailed: "Küldés sikertelen.", folderUnavailable: "Ez a mappa nem használható", deleteFailed: "Törlés sikertelen.", errorMessage: "Hiba: {error}", connectionFailed: "Nem lehet csatlakozni az eszközhöz" },
    id: { latestVersion: "V1.2 Terbaru", disconnectCurrentDevice: "Putuskan EInk saat ini sebelum menghubungkan perangkat lain", sendFailed: "Pengiriman gagal.", folderUnavailable: "Folder ini tidak dapat digunakan", deleteFailed: "Penghapusan gagal.", errorMessage: "Kesalahan: {error}", connectionFailed: "Tidak dapat menghubungkan perangkat" },
    it: { latestVersion: "V1.2 Più recente", disconnectCurrentDevice: "Disconnetti il EInk attuale prima di collegare un altro dispositivo", sendFailed: "Invio non riuscito.", folderUnavailable: "Questa cartella non può essere utilizzata", deleteFailed: "Eliminazione non riuscita.", errorMessage: "Errore: {error}", connectionFailed: "Impossibile connettere il dispositivo" },
    "es-419": { latestVersion: "V1.2 Más reciente", disconnectCurrentDevice: "Desconecta el EInk actual antes de conectar otro dispositivo", sendFailed: "Error al enviar.", folderUnavailable: "No se puede usar esta carpeta", deleteFailed: "Error al eliminar.", errorMessage: "Error: {error}", connectionFailed: "No se pudo conectar el dispositivo" },
    ms: { latestVersion: "V1.2 Terkini", disconnectCurrentDevice: "Putuskan sambungan EInk semasa sebelum menyambungkan peranti lain", sendFailed: "Penghantaran gagal.", folderUnavailable: "Folder ini tidak boleh digunakan", deleteFailed: "Pemadaman gagal.", errorMessage: "Ralat: {error}", connectionFailed: "Tidak dapat menyambungkan peranti" },
    no: { latestVersion: "V1.2 Nyeste", disconnectCurrentDevice: "Koble fra gjeldende EInk-enhet før du kobler til en annen", sendFailed: "Sending mislyktes.", folderUnavailable: "Denne mappen kan ikke brukes", deleteFailed: "Sletting mislyktes.", errorMessage: "Feil: {error}", connectionFailed: "Kan ikke koble til enheten" },
    pl: { latestVersion: "V1.2 Najnowsza", disconnectCurrentDevice: "Odłącz bieżące urządzenie EInk przed połączeniem innego", sendFailed: "Wysyłanie nie powiodło się.", folderUnavailable: "Nie można użyć tego folderu", deleteFailed: "Usuwanie nie powiodło się.", errorMessage: "Błąd: {error}", connectionFailed: "Nie można połączyć z urządzeniem" },
    pt: { latestVersion: "V1.2 Mais recente", disconnectCurrentDevice: "Desligue o EInk atual antes de ligar outro dispositivo", sendFailed: "Envio falhou.", folderUnavailable: "Esta pasta não pode ser utilizada", deleteFailed: "Eliminação falhou.", errorMessage: "Erro: {error}", connectionFailed: "Não foi possível ligar ao dispositivo" },
    ro: { latestVersion: "V1.2 Cea mai recentă", disconnectCurrentDevice: "Deconectează EInk-ul curent înainte de a conecta alt dispozitiv", sendFailed: "Trimiterea a eșuat.", folderUnavailable: "Acest dosar nu poate fi folosit", deleteFailed: "Ștergerea a eșuat.", errorMessage: "Eroare: {error}", connectionFailed: "Nu se poate conecta dispozitivul" },
    sv: { latestVersion: "V1.2 Senaste", disconnectCurrentDevice: "Koppla från den aktuella EInk-enheten innan du ansluter en annan", sendFailed: "Sändningen misslyckades.", folderUnavailable: "Den här mappen kan inte användas", deleteFailed: "Borttagning misslyckades.", errorMessage: "Fel: {error}", connectionFailed: "Det går inte att ansluta enheten" },
    th: { latestVersion: "V1.2 ล่าสุด", disconnectCurrentDevice: "ตัดการเชื่อมต่อ EInk ปัจจุบันก่อนเชื่อมต่ออุปกรณ์อื่น", sendFailed: "ส่งไม่สำเร็จ", folderUnavailable: "ไม่สามารถใช้โฟลเดอร์นี้ได้", deleteFailed: "ลบไม่สำเร็จ", errorMessage: "ข้อผิดพลาด: {error}", connectionFailed: "ไม่สามารถเชื่อมต่ออุปกรณ์ได้" },
    tr: { latestVersion: "V1.2 En yeni", disconnectCurrentDevice: "Başka bir aygıt bağlamadan önce geçerli EInk aygıtının bağlantısını kesin", sendFailed: "Gönderme başarısız.", folderUnavailable: "Bu klasör kullanılamaz", deleteFailed: "Silme başarısız.", errorMessage: "Hata: {error}", connectionFailed: "Aygıta bağlanılamıyor" },
    uk: { latestVersion: "V1.2 Остання", disconnectCurrentDevice: "Відключіть поточний EInk перед підключенням іншого пристрою", sendFailed: "Не вдалося надіслати.", folderUnavailable: "Цю папку неможливо використати", deleteFailed: "Не вдалося видалити.", errorMessage: "Помилка: {error}", connectionFailed: "Не вдалося підключити пристрій" },
    vi: { latestVersion: "V1.2 Mới nhất", disconnectCurrentDevice: "Ngắt kết nối EInk hiện tại trước khi kết nối thiết bị khác", sendFailed: "Gửi thất bại.", folderUnavailable: "Không thể sử dụng thư mục này", deleteFailed: "Xóa thất bại.", errorMessage: "Lỗi: {error}", connectionFailed: "Không thể kết nối thiết bị" },
};
Object.entries(EXTENDED_UI_MESSAGES).forEach(([language, text]) => Object.assign(UI_TEXT[language], text));
const getSystemLanguage = () => {
    const values = [];
    const add = (value) => {
        if (typeof value === "string" && value.trim()) {
            values.push(value.trim().toLowerCase());
        }
    };
    try {
        add(window?.SteamClient?.Settings?.GetCurrentLanguage?.());
    }
    catch (_) { }
    try {
        add(window?.LocalizationManager?.m_rgLocales?.[0]);
        add(window?.LocalizationManager?.m_strLanguage);
        add(window?.LocalizationManager?.GetLanguage?.());
    }
    catch (_) { }
    try {
        add(navigator?.language);
        (navigator?.languages || []).forEach(add);
    }
    catch (_) { }
    for (const lang of values) {
        if (lang.includes("tchinese") || lang.includes("traditional") || lang.startsWith("zh-hant") || lang === "zh-tw" || lang === "zh-hk" || lang === "zh-mo")
            return "zh-tw";
        if (lang.includes("schinese") || lang.includes("simplified") || lang.startsWith("zh-hans") || lang === "zh" || lang.startsWith("zh-cn") || lang.startsWith("zh-sg"))
            return "zh";
        const normalized = lang.replace(/_/g, "-").split(".", 1)[0];
        const direct = STEAM_LANGUAGE_ALIASES[normalized] || STEAM_LANGUAGE_ALIASES[normalized.split("-", 1)[0]];
        if (direct)
            return direct;
    }
    return "en";
};
const t = (key) => {
    const lang = getSystemLanguage();
    return UI_TEXT[lang]?.[key] || UI_TEXT.en[key] || key;
};
const formatUiText = (key, values = {}) => t(key).replace(/\{(\w+)\}/g, (_, name) => String(values[name] ?? ""));
const fitUiFontSize = (text, basePx, availableUnits, minimumPx = 9) => {
    const units = Array.from(String(text || "")).reduce((total, character) => total + (character.charCodeAt(0) > 0x2ff ? 1.9 : 1), 0);
    if (units <= availableUnits)
        return `${basePx}px`;
    const reduced = basePx - Math.ceil((units - availableUnits) / 3);
    return `${Math.max(minimumPx, reduced)}px`;
};
const FIXED_MODE_VALUES = new Set(["deck_status", "timeline", "clock", "weather", "agent"]);
const GAME_TIME_DISPLAY_MODES = ["time", "poster", "auto"];
const GAME_TIME_MODE_TITLES = { ar: "وضع العرض", "pt-br": "MODO DE EXIBIÇÃO", bg: "РЕЖИМ НА ЕКРАНА", cs: "REŽIM ZOBRAZENÍ", da: "VISNINGSTIL", nl: "WEERGAVEMODUS", en: "DISPLAY MODE", fi: "NÄYTTÖTILA", fr: "MODE D’AFFICHAGE", de: "ANZEIGEMODUS", el: "ΛΕΙΤΟΥΡΓΙΑ ΠΡΟΒΟΛΗΣ", hu: "MEGJELENÍTÉSI MÓD", id: "MODE TAMPILAN", it: "MODALITÀ DI VISUALIZZAZIONE", ja: "表示モード", ko: "표시 모드", "es-419": "MODO DE VISUALIZACIÓN", ms: "MOD PAPARAN", no: "VISNINGSMODUS", pl: "TRYB WYŚWIETLANIA", pt: "MODO DE EXIBIÇÃO", ro: "MOD AFIȘARE", ru: "РЕЖИМ ОТОБРАЖЕНИЯ", zh: "显示模式", es: "MODO DE VISUALIZACIÓN", sv: "VISNINGSLÄGE", "zh-tw": "顯示模式", th: "โหมดการแสดงผล", tr: "GÖRÜNTÜLEME MODU", uk: "РЕЖИМ ВІДОБРАЖЕННЯ", vi: "CHẾ ĐỘ HIỂN THỊ" };
const GAME_TIME_MODE_LABELS = {
    "ar": { time: "الوقت", poster: "الملصق", auto: "تلقائي" },
    "pt-br": { time: "Hora", poster: "Pôster", auto: "Automático" },
    "bg": { time: "Време", poster: "Плакат", auto: "Автоматично" },
    "cs": { time: "Čas", poster: "Plakát", auto: "Automaticky" },
    "da": { time: "Tid", poster: "Plakat", auto: "Automatisk" },
    "nl": { time: "Tijd", poster: "Poster", auto: "Automatisch" },
    "en": { time: "Time", poster: "Poster", auto: "Auto" },
    "fi": { time: "Aika", poster: "Juliste", auto: "Automaattinen" },
    "fr": { time: "Heure", poster: "Affiche", auto: "Auto" },
    "de": { time: "Zeit", poster: "Poster", auto: "Auto" },
    "el": { time: "Ώρα", poster: "Αφίσα", auto: "Αυτόματο" },
    "hu": { time: "Idő", poster: "Poszter", auto: "Automatikus" },
    "id": { time: "Waktu", poster: "Poster", auto: "Otomatis" },
    "it": { time: "Ora", poster: "Poster", auto: "Auto" },
    "ja": { time: "時刻", poster: "ポスター", auto: "自動" },
    "ko": { time: "시간", poster: "포스터", auto: "자동" },
    "es-419": { time: "Hora", poster: "Póster", auto: "Automático" },
    "ms": { time: "Masa", poster: "Poster", auto: "Automatik" },
    "no": { time: "Tid", poster: "Plakat", auto: "Automatisk" },
    "pl": { time: "Czas", poster: "Plakat", auto: "Automatycznie" },
    "pt": { time: "Hora", poster: "Pôster", auto: "Automático" },
    "ro": { time: "Ora", poster: "Poster", auto: "Automat" },
    "ru": { time: "Время", poster: "Постер", auto: "Авто" },
    "zh": { time: "时间", poster: "海报", auto: "自动" },
    "es": { time: "Hora", poster: "Póster", auto: "Automático" },
    "sv": { time: "Tid", poster: "Affisch", auto: "Automatiskt" },
    "zh-tw": { time: "時間", poster: "海報", auto: "自動" },
    "th": { time: "เวลา", poster: "โปสเตอร์", auto: "อัตโนมัติ" },
    "tr": { time: "Zaman", poster: "Poster", auto: "Otomatik" },
    "uk": { time: "Час", poster: "Постер", auto: "Авто" },
    "vi": { time: "Thời gian", poster: "Áp phích", auto: "Tự động" }
};
const MODULE_LABELS = [
    { id: 0, mode: "carousel", labelKey: "composite" },
    { id: 7, mode: "agent", labelKey: "agent" },
    { id: 4, mode: "clock", labelKey: "clock" },
    { id: 3, mode: "weather", labelKey: "weather" },
    { id: 2, mode: "deck_status", labelKey: "performance" },
    { id: 5, mode: "calendar", labelKey: "calendar" },
    { id: 1, mode: "timeline", labelKey: "gameTime" },
    { id: 6, mode: "custom", labelKey: "custom" },
];
const MODULE_SWITCH_OPTIONS = Array.from({ length: 12 }, (_, index) => {
    const value = (index + 1) * 5;
    return { value, label: `${value}${t("minutesSuffix")}` };
});
const GAMEPAD_ACTION_SELECTOR = "[data-gamepad-action='true']";
const GAMEPAD_REPEAT_MS = 180;
const GAMEPAD_AXIS_THRESHOLD = 0.55;
const GAMEPAD_ACTIVATION_GUARD_MS = 500;
const GAMEPAD_ACTIVATION_DEDUPE_MS = 500;
const GAMEPAD_DIRECTION_DEDUPE_MS = 80;
const GAMEPAD_FOCUS_BACKGROUND = "rgba(142,151,166,0.22)";
// --- UI helpers ---
const h = SP_REACT.createElement;
const daemonConnectionState = (status) => {
    if (status?.connection_state === "connecting" || status?.connection_state === "on")
        return status.connection_state;
    return status?.connected ? "on" : "off";
};
const canonicalMacAddress = (value) => String(value || "").trim().toUpperCase();
const normalizeCandidateRssi = (value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? Math.trunc(parsed) : null;
};
const signalBarsForRssi = (rssi) => {
    if (rssi === null)
        return 0;
    if (rssi >= -50)
        return 4;
    if (rssi >= -60)
        return 3;
    if (rssi >= -70)
        return 2;
    return 1;
};
const sortConnectionCandidatesByRssi = (candidates, connectedAddress = "") => [...candidates].sort((left, right) => {
    const leftConnected = canonicalMacAddress(left?.address) === canonicalMacAddress(connectedAddress);
    const rightConnected = canonicalMacAddress(right?.address) === canonicalMacAddress(connectedAddress);
    if (leftConnected !== rightConnected)
        return leftConnected ? -1 : 1;
    const leftRssi = normalizeCandidateRssi(left?.rssi);
    const rightRssi = normalizeCandidateRssi(right?.rssi);
    if (leftRssi === null && rightRssi === null)
        return canonicalMacAddress(left?.address).localeCompare(canonicalMacAddress(right?.address));
    if (leftRssi === null)
        return 1;
    if (rightRssi === null)
        return -1;
    return rightRssi - leftRssi || canonicalMacAddress(left?.address).localeCompare(canonicalMacAddress(right?.address));
});
const styles = {
    root: {
        color: "#f4f6fb",
        padding: "0",
        display: "flex",
        flexDirection: "column",
        gap: "12px",
        fontSize: "13px",
        lineHeight: 1.4,
        background: "#080f16",
        minHeight: "0",
    },
    panel: {
        background: "#081018",
        border: "1px solid rgba(142,151,166,0.22)",
        borderRadius: "0",
        overflow: "hidden",
        boxShadow: "0 10px 24px rgba(0,0,0,0.22)",
        width: "100%",
        minHeight: "750px",
        display: "flex",
        flexDirection: "column",
    },
    header: {
        minHeight: "71px",
        padding: "0 23px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        borderBottom: "1px solid rgba(142,151,166,0.24)",
        background: "#0c141d",
    },
    brand: {
        display: "flex",
        alignItems: "center",
        gap: "10px",
        fontSize: "20px",
        fontWeight: 700,
    },
    brandIcon: {
        width: "18px",
        height: "18px",
        border: "2px solid #8500ff",
        color: "#8500ff",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: "11px",
        lineHeight: 1,
    },
    versionPill: {
        border: "1px solid rgba(142,151,166,0.28)",
        borderRadius: "999px",
        padding: "3px 10px",
        color: "rgba(206,214,225,0.52)",
        fontSize: "12px",
    },
    controlRow: (active) => ({
        height: "101px",
        padding: "12px 16px",
        boxSizing: "border-box",
        flexShrink: 0,
        borderBottom: "1px solid rgba(142,151,166,0.22)",
        background: active ? GAMEPAD_FOCUS_BACKGROUND : "transparent",
        display: "flex",
        flexDirection: "column",
        gap: "10px",
    }),
    progressRow: {
        height: "56px",
        padding: "9px 16px",
        boxSizing: "border-box",
        flexShrink: 0,
        borderBottom: "1px solid rgba(142,151,166,0.22)",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
    },
    screenRow: (active) => ({
        height: "63px",
        padding: "0 16px",
        boxSizing: "border-box",
        flexShrink: 0,
        borderBottom: "1px solid rgba(142,151,166,0.22)",
        background: active ? GAMEPAD_FOCUS_BACKGROUND : "transparent",
        display: "flex",
        alignItems: "center",
    }),
    refreshRow: (active) => ({
        height: "98px",
        padding: "14px 16px 18px",
        boxSizing: "border-box",
        flexShrink: 0,
        borderBottom: "1px solid rgba(142,151,166,0.22)",
        background: active ? GAMEPAD_FOCUS_BACKGROUND : "transparent",
        display: "flex",
        flexDirection: "column",
        gap: "14px",
    }),
    rowTop: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "12px",
        width: "100%",
    },
    rowLabel: {
        fontSize: "15px",
        fontWeight: 600,
        color: "#eef3fb",
    },
    rowValue: {
        fontSize: "13px",
        color: "#dce3ed",
    },
    screenControlLabel: {
        fontSize: "16px",
        fontWeight: 600,
        color: "#fff",
    },
    screenControlValue: {
        fontSize: "14px",
        color: "#fff",
    },
    screenControlIntervalLabel: {
        fontSize: "15px",
        fontWeight: 600,
        color: "#fff",
    },
    screenControlToggleText: {
        flex: "1 1 auto",
        textAlign: "center",
        fontSize: "9px",
        lineHeight: "16px",
        color: "#fff",
    },
    rowRight: {
        display: "flex",
        alignItems: "center",
        justifyContent: "flex-end",
        gap: "10px",
        flex: "0 0 auto",
    },
    row: {
        display: "flex",
        gap: "8px",
        alignItems: "center",
        flexWrap: "wrap",
    },
    grow: { flex: "1 1 auto" },
    toggle: (on, busy) => ({
        width: "56px",
        height: "20px",
        border: "0",
        borderRadius: "999px",
        padding: "2px",
        background: on || busy ? "#8500ff" : "rgba(142,151,166,0.42)",
        color: "#fff",
        fontSize: "8px",
        display: "flex",
        alignItems: "center",
        justifyContent: on || busy ? "flex-end" : "flex-start",
        cursor: busy ? "wait" : "pointer",
    }),
    knob: {
        width: "16px",
        height: "16px",
        borderRadius: "50%",
        background: "#f8f9fb",
        flex: "0 0 auto",
    },
    spinner: {
        width: "12px",
        height: "12px",
        marginRight: "2px",
        borderRadius: "50%",
        background: "repeating-conic-gradient(from 0deg,#fff 0deg 20deg,transparent 20deg 45deg)",
        WebkitMask: "radial-gradient(circle,transparent 0 3px,#000 3.5px)",
        animation: "jsaux-gaming-spin 0.8s linear infinite",
        flex: "0 0 auto",
    },
    toggleText: {
        flex: "1 1 auto",
        textAlign: "center",
        fontSize: "8px",
        lineHeight: "16px",
    },
    range: {
        width: "100%",
        accentColor: "#8500ff",
    },
    moduleGrid: {
        padding: "23px",
        display: "grid",
        gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
        gap: "11px",
        borderBottom: "1px solid rgba(142,151,166,0.22)",
        flex: "1 1 auto",
    },
    moduleButton: (focused, disabled) => ({
        minHeight: "64px",
        border: "1px solid rgba(142,151,166,0.24)",
        background: focused ? "linear-gradient(90deg,#6e00ff,#9400ff)" : "#0b141d",
        color: disabled ? "rgba(255,255,255,0.35)" : (focused ? "#fff" : "#969ea8"),
        borderRadius: "8px",
        boxSizing: "border-box",
        padding: "10px 13px",
        overflow: "hidden",
        cursor: disabled ? "not-allowed" : "pointer",
        fontSize: "12px",
        display: "flex",
        alignItems: "center",
        gap: "12px",
        justifyContent: "flex-start",
        textAlign: "left",
    }),
    moduleIcon: {
        width: "26px",
        height: "26px",
        lineHeight: 1,
        color: "inherit",
        flex: "0 0 auto",
    },
    customArea: {
        padding: "24px 23px",
        display: "flex",
        flexDirection: "column",
        gap: "24px",
        borderBottom: "1px solid rgba(142,151,166,0.22)",
    },
    customEmpty: {
        flex: "1 1 auto",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
    },
    customGrid: {
        display: "grid",
        gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
        gridAutoRows: "110px",
        gap: "11px",
    },
    customCard: (targeted, focused, disabled, focusedItem = false) => ({
        border: focused ? "2px solid #8500ff" : (!focusedItem && targeted ? "2px solid #8500ff" : "1px solid #34404c"),
        outline: "none",
        outlineOffset: "-2px",
        boxShadow: "none",
        background: "#07151e",
        color: disabled ? "rgba(255,255,255,0.35)" : "#37404d",
        borderRadius: "9px",
        padding: "3px",
        fontSize: "12px",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        textAlign: "center",
        wordBreak: "break-word",
        cursor: disabled ? "not-allowed" : "pointer",
    }),
    customThumbnail: {
        width: "100%",
        height: "100%",
        display: "block",
        objectFit: "contain",
        borderRadius: "5px",
        background: "#ffffff",
    },
    customThumbnailFallback: {
        color: "#68747e",
        fontSize: "12px",
        textAlign: "center",
    },
    actionBar: {
        display: "flex",
        gap: "8px",
        justifyContent: "space-between",
        alignItems: "center",
    },
    customOperationProgress: {
        height: "56px",
        padding: "9px 0",
        boxSizing: "border-box",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
    },
    customDeleteButton: (disabled, focused = false) => ({
        flex: "1 1 0",
        height: "34px",
        border: "0",
        borderRadius: "8px",
        boxSizing: "border-box",
        color: disabled ? "rgba(255,255,255,0.45)" : "#fff",
        background: disabled ? "rgba(142,151,166,0.42)" : (focused ? "#d53b3b" : "rgba(142,151,166,0.42)"),
        boxShadow: "none",
        cursor: disabled ? "not-allowed" : "pointer",
        fontSize: "11px",
    }),
    customSelectButton: (disabled, focused = false) => ({
        flex: "1 1 0",
        height: "34px",
        border: "0",
        borderRadius: "8px",
        boxSizing: "border-box",
        color: disabled ? "rgba(255,255,255,0.45)" : "#fff",
        background: disabled ? "rgba(142,151,166,0.42)" : (focused ? "#8500ff" : "rgba(142,151,166,0.42)"),
        boxShadow: "none",
        cursor: disabled ? "not-allowed" : "pointer",
        fontSize: "11px",
    }),
    pillButton: (primary, disabled, focused = false) => ({
        minWidth: "86px",
        border: "2px solid transparent",
        borderRadius: "999px",
        padding: "6px 12px",
        boxSizing: "border-box",
        fontSize: "11px",
        color: focused ? "#fff" : (disabled ? "rgba(255,255,255,0.45)" : "#fff"),
        background: focused ? "#8500ff" : (disabled ? "rgba(142,151,166,0.42)" : (primary ? "#8500ff" : "rgba(142,151,166,0.42)")),
        cursor: disabled ? "not-allowed" : "pointer",
    }),
    select: {
        width: "100%",
        background: "#121212",
        color: "#fff",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: "8px",
        padding: "8px 10px",
    },
    button: (color, disabled) => ({
        border: "1px solid rgba(255,255,255,0.12)",
        background: disabled ? "rgba(255,255,255,0.08)" : color || "rgba(255,255,255,0.10)",
        color: disabled ? "rgba(255,255,255,0.45)" : "#fff",
        borderRadius: "8px",
        padding: "8px 10px",
        cursor: disabled ? "not-allowed" : "pointer",
        fontSize: "12px",
        textAlign: "left",
    }),
    input: {
        width: "100%",
        background: "#121212",
        color: "#fff",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: "8px",
        padding: "8px 10px",
        fontSize: "12px",
    },
    help: { fontSize: "11px", opacity: 0.68 },
    dim: { fontSize: "11px", opacity: 0.55 },
    path: {
        fontSize: "10px",
        opacity: 0.5,
        wordBreak: "break-all",
    },
    chipWrap: {
        display: "flex",
        gap: "6px",
        flexWrap: "wrap",
    },
    firmware: {
        height: "85px",
        padding: "14px 23px",
        boxSizing: "border-box",
        flexShrink: 0,
        marginTop: "auto",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: "12px",
        width: "100%",
        minWidth: 0,
        overflow: "hidden",
    },
    firmwareTitle: {
        fontSize: "13px",
        fontWeight: 400,
        color: "#fff",
    },
    firmwareSub: {
        fontSize: "13px",
        color: "#fff",
        marginTop: "2px",
    },
    chip: (active, color) => ({
        padding: "3px 7px",
        borderRadius: "999px",
        fontSize: "11px",
        background: active ? color : "rgba(255,255,255,0.08)",
        color: active ? "#fff" : "rgba(255,255,255,0.72)",
    }),
};
const ProgressBar = ({ pct }) => h("div", {
    style: {
        width: "100%",
        background: "rgba(255,255,255,0.12)",
        borderRadius: 999,
        height: 8,
        overflow: "hidden",
    },
}, h("div", {
    style: {
        width: `${Math.max(0, Math.min(100, pct || 0))}%`,
        height: "100%",
        background: "#59bf40",
    },
}));
const Content = () => {
    const FIRMWARE_UI = resolveFirmwareUi("1.2", "1.2", false, {
        updateNow: t("updateNow"),
        upToDate: t("upToDate"),
    });
    const intervalValueStyle = getSystemLanguage() === "en"
        ? { ...styles.screenControlValue, minWidth: "48px", flex: "0 0 auto", whiteSpace: "nowrap", textAlign: "right" }
        : styles.screenControlValue;
    const screenControlIntervalValueStyle = { ...intervalValueStyle, transform: "translateX(2ch)" };
    const [connectionState, setConnectionState] = _local_SP_REACT.useState("off");
    const connected = connectionState === "on";
    const scanning = connectionState === "connecting";
    const [battery, setBattery] = _local_SP_REACT.useState(0);
    const [address, setAddress] = _local_SP_REACT.useState("");
    const [confirmedConnectedMac, setConfirmedConnectedMac] = _local_SP_REACT.useState("");
    const [connectionPage, setConnectionPage] = _local_SP_REACT.useState(false);
    const [deviceCandidates, setDeviceCandidates] = _local_SP_REACT.useState([]);
    const [devicesScanning, setDevicesScanning] = _local_SP_REACT.useState(false);
    const [deviceSelectionPending, setDeviceSelectionPending] = _local_SP_REACT.useState("");
    const [mode, setModeState] = _local_SP_REACT.useState("deck_status");
    const [photoFrameInterval, setPhotoFrameInterval] = _local_SP_REACT.useState(5);
    const [photoFrameIntervalEnabled, setPhotoFrameIntervalEnabled] = _local_SP_REACT.useState(false);
    const [moduleSwitchInterval, setModuleSwitchInterval] = _local_SP_REACT.useState(5);
    const [moduleSwitchEnabled, setModuleSwitchEnabled] = _local_SP_REACT.useState(false);
    const [gameTimeDisplayMode, setGameTimeDisplayMode] = _local_SP_REACT.useState("auto");
    const [timelineSec, setTimelineSecSt] = _local_SP_REACT.useState(300);
    const [sending, setSending] = _local_SP_REACT.useState(false);
    const [progress, setProgress] = _local_SP_REACT.useState(0);
    const [displayProgressState, setDisplayProgressState] = _local_SP_REACT.useState("");
    const sendRequestRef = _local_SP_REACT.useRef(0);
    const [timelineIdx, setTimelineIdx] = _local_SP_REACT.useState(0);
    const [agentStatus, setAgentStatus] = _local_SP_REACT.useState({});
    const [customFiles, setCustomFiles] = _local_SP_REACT.useState([]);
    const [customFilePath, setCustomFilePath] = _local_SP_REACT.useState("");
    const [customTitle] = _local_SP_REACT.useState("");
    const [loadingFiles, setLoadingFiles] = _local_SP_REACT.useState(false);
    const [customOperation, setCustomOperation] = _local_SP_REACT.useState("");
    const [customOperationProgress, setCustomOperationProgress] = _local_SP_REACT.useState(0);
    const customProgressSourceRef = _local_SP_REACT.useRef("");
    const [ipCity, setIpCity] = _local_SP_REACT.useState("");
    const [selectedPanel, setSelectedPanel] = _local_SP_REACT.useState("screen");
    const selectedPanelRef = _local_SP_REACT.useRef("screen");
    const [gamepadFocusedId, setGamepadFocusedId] = _local_SP_REACT.useState("connection-page-entry");
    const gamepadRootRef = _local_SP_REACT.useRef(null);
    const hostBackButtonRef = _local_SP_REACT.useRef(null);
    const customGridFocusRef = _local_SP_REACT.useRef("custom:item:0");
    const customReturnPendingRef = _local_SP_REACT.useRef(false);
    const connectionPageRef = _local_SP_REACT.useRef(false);
    const connectionPageOperationRef = _local_SP_REACT.useRef(false);
    const confirmedConnectedMacRef = _local_SP_REACT.useRef("");
    const connectionStateRef = _local_SP_REACT.useRef("off");
    const connectionRequestPendingRef = _local_SP_REACT.useRef(false);
    const lastConnectionErrorRef = _local_SP_REACT.useRef("");
    const gamepadStateRef = _local_SP_REACT.useRef({
        focusedIndex: -1,
        focusedId: "",
        moduleBranch: "left",
        lastMoveAt: 0,
        lastActivationAt: Number.NEGATIVE_INFINITY,
        lastDirectionAt: Number.NEGATIVE_INFINITY,
        lastDirection: "",
        pressedButtons: new Set(),
    });
    const controlStateEpochRef = _local_SP_REACT.useRef("");
    const controlStateRevisionRef = _local_SP_REACT.useRef(-1);
    const applyDeviceStatus = _local_SP_REACT.useCallback((status) => {
        const previous = connectionStateRef.current;
        const next = daemonConnectionState(status);
        connectionStateRef.current = next;
        setConnectionState(next);
        setBattery(status?.battery || 0);
        setAddress(status?.address || "");
        const confirmedAddress = canonicalMacAddress(status?.address);
        if ((status?.connection_state === "on" || status?.connected === true) && confirmedAddress) {
            confirmedConnectedMacRef.current = confirmedAddress;
            setConfirmedConnectedMac(confirmedAddress);
        }
        else if (status?.connection_state === "off" && !connectionPageOperationRef.current) {
            confirmedConnectedMacRef.current = "";
            setConfirmedConnectedMac("");
        }
        if (next === "connecting")
            lastConnectionErrorRef.current = "";
        const error = String(status?.last_error || "");
        if (connectionPageOperationRef.current && previous === "connecting" && next === "off" && error && error !== lastConnectionErrorRef.current) {
            lastConnectionErrorRef.current = error;
            toaster.toast({ title: PRODUCT_NAME, body: t("connectionFailed") });
        }
    }, []);
    const [displayPreferences, setDisplayPreferences] = _local_SP_REACT.useState({ display_timezone: "system", weather_temperature_unit: "celsius", display_time_format: "24", display_auto_dst: true, weather_location_mode: "auto", weather_manual_location: null, weather_recent_locations: [] });
    const [settingsPicker, setSettingsPicker] = _local_SP_REACT.useState("");
    const [settingsQuery, setSettingsQuery] = _local_SP_REACT.useState("");
    const [settingsResults, setSettingsResults] = _local_SP_REACT.useState([]);
    const [settingsOptions, setSettingsOptions] = _local_SP_REACT.useState({ zones: [] });
    const [settingsCountry, setSettingsCountry] = _local_SP_REACT.useState("");
    const [settingsLocationOptions, setSettingsLocationOptions] = _local_SP_REACT.useState({ countries: [], next_offset: null });
    const [settingsLocalCities, setSettingsLocalCities] = _local_SP_REACT.useState([]);
    const [preferencesBusy, setPreferencesBusy] = _local_SP_REACT.useState(false);
    const [preferencesMessage, setPreferencesMessage] = _local_SP_REACT.useState("");
    const settingsPickerRef = _local_SP_REACT.useRef("");
    const settingsGenerationRef = _local_SP_REACT.useRef(0);
    const settingsBusyRef = _local_SP_REACT.useRef(false);
    const SETTINGS_TEXT = {"en":{"settings":"Settings","timezone":"Time Zone","units":"Weather Unit","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","country":"Country / Region","all":"All Countries / Regions","more":"More Cities","offline":"Local cities shown; online search unavailable.","format":"Time Format","dst":"Automatic DST","weather":"Weather Location","auto":"Automatic (IP)","manual":"Choose a City","system":"Follow System","search":"Search","back":"‹ Back","on":"On","off":"Off","update":"Online Update","unavailable":"Not Enabled","version":"Software Version","12":"12-hour","24":"24-hour","none":"No results. Try a city or country.","hint":"Common cities work offline; Search expands online","saving":"Saving…"},"zh":{"settings":"设置","timezone":"时区","units":"天气单位","celsius":"℃ 摄氏度","fahrenheit":"℉ 华氏度","country":"国家／地区","all":"全部国家／地区","more":"更多城市","offline":"已显示本机城市，联网扩展暂不可用。","format":"时间格式","dst":"自动夏令时","weather":"天气地址","auto":"自动定位（IP）","manual":"手动选择城市","system":"跟随系统","search":"搜索","back":"‹ 返回","on":"开","off":"关","update":"在线升级","unavailable":"未启用","version":"软件版本","12":"12小时制","24":"24小时制","none":"没有匹配结果，请尝试城市或国家名称。","hint":"常用城市可离线选择；搜索可联网扩展","saving":"保存中…"},"ar":{"settings":"الإعدادات","timezone":"المنطقة الزمنية","units":"وحدة الطقس","celsius":"℃ مئوية","fahrenheit":"℉ فهرنهايت","format":"تنسيق الوقت","dst":"التوقيت الصيفي التلقائي","weather":"موقع الطقس","country":"الدولة / المنطقة","all":"كل الدول / المناطق","more":"مدن أخرى","auto":"تلقائي (IP)","manual":"اختيار مدينة","system":"اتباع النظام","search":"بحث","back":"‹ رجوع","on":"تشغيل","off":"إيقاف","update":"تحديث عبر الإنترنت","unavailable":"غير مفعّل","version":"إصدار البرنامج","12":"12 ساعة","24":"24 ساعة","none":"لا توجد نتائج.","hint":"ابحث عن مدينة / منطقة","saving":"جارٍ الحفظ…","offline":"عُرضت المدن المحلية؛ البحث عبر الإنترنت غير متاح."},"pt-br":{"settings":"Configurações","timezone":"Fuso horário","units":"Unidade do clima","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Formato da hora","dst":"Horário de verão automático","weather":"Local do clima","country":"País / região","all":"Todos os países / regiões","more":"Mais cidades","auto":"Automático (IP)","manual":"Escolher cidade","system":"Seguir sistema","search":"Pesquisar","back":"‹ Voltar","on":"Ligado","off":"Desligado","update":"Atualização online","unavailable":"Desativado","version":"Versão do software","12":"12 horas","24":"24 horas","none":"Nenhum resultado.","hint":"Pesquisar cidade / região","saving":"Salvando…","offline":"Cidades locais exibidas; busca online indisponível."},"bg":{"settings":"Настройки","timezone":"Часова зона","units":"Метео единица","celsius":"℃ Целзий","fahrenheit":"℉ Фаренхайт","format":"Формат на часа","dst":"Автоматично лятно време","weather":"Местоположение за времето","country":"Държава / регион","all":"Всички държави / региони","more":"Още градове","auto":"Автоматично (IP)","manual":"Избор на град","system":"По системата","search":"Търсене","back":"‹ Назад","on":"Вкл.","off":"Изкл.","update":"Онлайн актуализация","unavailable":"Не е включено","version":"Версия на софтуера","12":"12 часа","24":"24 часа","none":"Няма резултати.","hint":"Търсене на град / регион","saving":"Записване…","offline":"Показани са местни градове; онлайн търсенето не е налично."},"cs":{"settings":"Nastavení","timezone":"Časové pásmo","units":"Jednotka počasí","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Formát času","dst":"Automatický letní čas","weather":"Místo počasí","country":"Země / oblast","all":"Všechny země / oblasti","more":"Další města","auto":"Automaticky (IP)","manual":"Vybrat město","system":"Podle systému","search":"Hledat","back":"‹ Zpět","on":"Zapnuto","off":"Vypnuto","update":"Online aktualizace","unavailable":"Není aktivní","version":"Verze softwaru","12":"12 hodin","24":"24 hodin","none":"Nenalezeny žádné výsledky.","hint":"Hledat město / oblast","saving":"Ukládání…","offline":"Zobrazena místní města; online hledání není dostupné."},"da":{"settings":"Indstillinger","timezone":"Tidszone","units":"Vejrenhed","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Tidsformat","dst":"Automatisk sommertid","weather":"Vejrlokation","country":"Land / område","all":"Alle lande / områder","more":"Flere byer","auto":"Automatisk (IP)","manual":"Vælg en by","system":"Følg systemet","search":"Søg","back":"‹ Tilbage","on":"Til","off":"Fra","update":"Onlineopdatering","unavailable":"Ikke aktiveret","version":"Softwareversion","12":"12 timer","24":"24 timer","none":"Ingen resultater.","hint":"Søg by / område","saving":"Gemmer…","offline":"Lokale byer vises; onlinesøgning er ikke tilgængelig."},"nl":{"settings":"Instellingen","timezone":"Tijdzone","units":"Weereenheid","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Tijdnotatie","dst":"Automatische zomertijd","weather":"Weerlocatie","country":"Land / regio","all":"Alle landen / regio’s","more":"Meer steden","auto":"Automatisch (IP)","manual":"Stad kiezen","system":"Systeem volgen","search":"Zoeken","back":"‹ Terug","on":"Aan","off":"Uit","update":"Online bijwerken","unavailable":"Niet ingeschakeld","version":"Softwareversie","12":"12 uur","24":"24 uur","none":"Geen resultaten.","hint":"Zoek stad / regio","saving":"Opslaan…","offline":"Lokale steden weergegeven; online zoeken is niet beschikbaar."},"fi":{"settings":"Asetukset","timezone":"Aikavyöhyke","units":"Sääyksikkö","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Aikamuoto","dst":"Automaattinen kesäaika","weather":"Sääsijainti","country":"Maa / alue","all":"Kaikki maat / alueet","more":"Lisää kaupunkeja","auto":"Automaattinen (IP)","manual":"Valitse kaupunki","system":"Järjestelmän mukaan","search":"Hae","back":"‹ Takaisin","on":"Päällä","off":"Pois","update":"Verkkopäivitys","unavailable":"Ei käytössä","version":"Ohjelmistoversio","12":"12 tuntia","24":"24 tuntia","none":"Ei tuloksia.","hint":"Hae kaupunkia / aluetta","saving":"Tallennetaan…","offline":"Paikalliset kaupungit näytetään; verkkohaku ei ole käytettävissä."},"fr":{"settings":"Paramètres","timezone":"Fuseau horaire","units":"Unité météo","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Format de l’heure","dst":"Heure d’été automatique","weather":"Lieu météo","country":"Pays / région","all":"Tous les pays / régions","more":"Plus de villes","auto":"Automatique (IP)","manual":"Choisir une ville","system":"Suivre le système","search":"Rechercher","back":"‹ Retour","on":"Activé","off":"Désactivé","update":"Mise à jour en ligne","unavailable":"Non activé","version":"Version du logiciel","12":"12 heures","24":"24 heures","none":"Aucun résultat.","hint":"Rechercher une ville / région","saving":"Enregistrement…","offline":"Villes locales affichées ; recherche en ligne indisponible."},"de":{"settings":"Einstellungen","timezone":"Zeitzone","units":"Wetter-Einheit","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Zeitformat","dst":"Automatische Sommerzeit","weather":"Wetterstandort","country":"Land / Region","all":"Alle Länder / Regionen","more":"Weitere Städte","auto":"Automatisch (IP)","manual":"Stadt auswählen","system":"System folgen","search":"Suchen","back":"‹ Zurück","on":"Ein","off":"Aus","update":"Online-Update","unavailable":"Nicht aktiviert","version":"Softwareversion","12":"12 Stunden","24":"24 Stunden","none":"Keine Ergebnisse.","hint":"Stadt / Region suchen","saving":"Speichern…","offline":"Lokale Städte angezeigt; Onlinesuche nicht verfügbar."},"el":{"settings":"Ρυθμίσεις","timezone":"Ζώνη ώρας","units":"Μονάδα καιρού","celsius":"℃ Κελσίου","fahrenheit":"℉ Φαρενάιτ","format":"Μορφή ώρας","dst":"Αυτόματη θερινή ώρα","weather":"Τοποθεσία καιρού","country":"Χώρα / περιοχή","all":"Όλες οι χώρες / περιοχές","more":"Περισσότερες πόλεις","auto":"Αυτόματα (IP)","manual":"Επιλογή πόλης","system":"Ακολούθηση συστήματος","search":"Αναζήτηση","back":"‹ Πίσω","on":"Ενεργό","off":"Ανενεργό","update":"Online ενημέρωση","unavailable":"Δεν είναι ενεργό","version":"Έκδοση λογισμικού","12":"12 ώρες","24":"24 ώρες","none":"Δεν βρέθηκαν αποτελέσματα.","hint":"Αναζήτηση πόλης / περιοχής","saving":"Αποθήκευση…","offline":"Εμφανίζονται τοπικές πόλεις· η online αναζήτηση δεν είναι διαθέσιμη."},"hu":{"settings":"Beállítások","timezone":"Időzóna","units":"Időjárási egység","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Időformátum","dst":"Automatikus nyári idő","weather":"Időjárási hely","country":"Ország / régió","all":"Minden ország / régió","more":"További városok","auto":"Automatikus (IP)","manual":"Város választása","system":"Rendszer követése","search":"Keresés","back":"‹ Vissza","on":"Be","off":"Ki","update":"Online frissítés","unavailable":"Nincs engedélyezve","version":"Szoftververzió","12":"12 óra","24":"24 óra","none":"Nincs találat.","hint":"Város / régió keresése","saving":"Mentés…","offline":"Helyi városok láthatók; az online keresés nem érhető el."},"id":{"settings":"Pengaturan","timezone":"Zona waktu","units":"Satuan cuaca","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Format waktu","dst":"Waktu musim panas otomatis","weather":"Lokasi cuaca","country":"Negara / wilayah","all":"Semua negara / wilayah","more":"Kota lainnya","auto":"Otomatis (IP)","manual":"Pilih kota","system":"Ikuti sistem","search":"Cari","back":"‹ Kembali","on":"Aktif","off":"Nonaktif","update":"Pembaruan online","unavailable":"Tidak aktif","version":"Versi perangkat lunak","12":"12 jam","24":"24 jam","none":"Tidak ada hasil.","hint":"Cari kota / wilayah","saving":"Menyimpan…","offline":"Kota lokal ditampilkan; pencarian online tidak tersedia."},"it":{"settings":"Impostazioni","timezone":"Fuso orario","units":"Unità meteo","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Formato ora","dst":"Ora legale automatica","weather":"Posizione meteo","country":"Paese / regione","all":"Tutti i paesi / regioni","more":"Altre città","auto":"Automatico (IP)","manual":"Scegli città","system":"Segui sistema","search":"Cerca","back":"‹ Indietro","on":"Attivo","off":"Disattivo","update":"Aggiornamento online","unavailable":"Non attivo","version":"Versione software","12":"12 ore","24":"24 ore","none":"Nessun risultato.","hint":"Cerca città / regione","saving":"Salvataggio…","offline":"Città locali mostrate; ricerca online non disponibile."},"ja":{"settings":"設定","timezone":"タイムゾーン","units":"天気単位","celsius":"℃ 摂氏","fahrenheit":"℉ 華氏","format":"時刻形式","dst":"自動夏時間","weather":"天気の場所","country":"国 / 地域","all":"すべての国 / 地域","more":"他の都市","auto":"自動 (IP)","manual":"都市を選択","system":"システムに従う","search":"検索","back":"‹ 戻る","on":"オン","off":"オフ","update":"オンライン更新","unavailable":"無効","version":"ソフトウェアバージョン","12":"12時間","24":"24時間","none":"結果がありません。","hint":"都市 / 地域を検索","saving":"保存中…","offline":"ローカル都市を表示中。オンライン検索は利用できません。"},"ko":{"settings":"설정","timezone":"시간대","units":"날씨 단위","celsius":"℃ 섭씨","fahrenheit":"℉ 화씨","format":"시간 형식","dst":"자동 일광 절약 시간","weather":"날씨 위치","country":"국가 / 지역","all":"모든 국가 / 지역","more":"더 많은 도시","auto":"자동 (IP)","manual":"도시 선택","system":"시스템 따르기","search":"검색","back":"‹ 뒤로","on":"켜짐","off":"꺼짐","update":"온라인 업데이트","unavailable":"사용 안 함","version":"소프트웨어 버전","12":"12시간","24":"24시간","none":"결과 없음.","hint":"도시 / 지역 검색","saving":"저장 중…","offline":"로컬 도시를 표시합니다. 온라인 검색을 사용할 수 없습니다."},"es-419":{"settings":"Configuración","timezone":"Zona horaria","units":"Unidad meteorológica","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Formato de hora","dst":"Horario de verano automático","weather":"Ubicación del clima","country":"País / región","all":"Todos los países / regiones","more":"Más ciudades","auto":"Automático (IP)","manual":"Elegir ciudad","system":"Seguir sistema","search":"Buscar","back":"‹ Atrás","on":"Activado","off":"Desactivado","update":"Actualización en línea","unavailable":"No activado","version":"Versión del software","12":"12 horas","24":"24 horas","none":"Sin resultados.","hint":"Buscar ciudad / región","saving":"Guardando…","offline":"Se muestran ciudades locales; la búsqueda en línea no está disponible."},"ms":{"settings":"Tetapan","timezone":"Zon waktu","units":"Unit cuaca","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Format masa","dst":"Waktu musim panas automatik","weather":"Lokasi cuaca","country":"Negara / wilayah","all":"Semua negara / wilayah","more":"Lagi bandar","auto":"Automatik (IP)","manual":"Pilih bandar","system":"Ikut sistem","search":"Cari","back":"‹ Kembali","on":"Hidup","off":"Mati","update":"Kemas kini dalam talian","unavailable":"Tidak didayakan","version":"Versi perisian","12":"12 jam","24":"24 jam","none":"Tiada hasil.","hint":"Cari bandar / wilayah","saving":"Menyimpan…","offline":"Bandar tempatan dipaparkan; carian dalam talian tidak tersedia."},"no":{"settings":"Innstillinger","timezone":"Tidssone","units":"Værenhet","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Tidsformat","dst":"Automatisk sommertid","weather":"Værsted","country":"Land / region","all":"Alle land / regioner","more":"Flere byer","auto":"Automatisk (IP)","manual":"Velg by","system":"Følg systemet","search":"Søk","back":"‹ Tilbake","on":"På","off":"Av","update":"Nettoppdatering","unavailable":"Ikke aktivert","version":"Programvareversjon","12":"12 timer","24":"24 timer","none":"Ingen resultater.","hint":"Søk etter by / region","saving":"Lagrer…","offline":"Lokale byer vises; nettsøk er ikke tilgjengelig."},"pl":{"settings":"Ustawienia","timezone":"Strefa czasowa","units":"Jednostka pogody","celsius":"℃ Celsjusz","fahrenheit":"℉ Fahrenheit","format":"Format czasu","dst":"Automatyczny czas letni","weather":"Lokalizacja pogody","country":"Kraj / region","all":"Wszystkie kraje / regiony","more":"Więcej miast","auto":"Automatycznie (IP)","manual":"Wybierz miasto","system":"Zgodnie z systemem","search":"Szukaj","back":"‹ Wstecz","on":"Wł.","off":"Wył.","update":"Aktualizacja online","unavailable":"Nie włączono","version":"Wersja oprogramowania","12":"12 godzin","24":"24 godziny","none":"Brak wyników.","hint":"Szukaj miasta / regionu","saving":"Zapisywanie…","offline":"Wyświetlono miasta lokalne; wyszukiwanie online niedostępne."},"pt":{"settings":"Definições","timezone":"Fuso horário","units":"Unidade meteorológica","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Formato da hora","dst":"Hora de verão automática","weather":"Localização meteorológica","country":"País / região","all":"Todos os países / regiões","more":"Mais cidades","auto":"Automático (IP)","manual":"Escolher cidade","system":"Seguir sistema","search":"Pesquisar","back":"‹ Voltar","on":"Ligado","off":"Desligado","update":"Atualização online","unavailable":"Não ativado","version":"Versão do software","12":"12 horas","24":"24 horas","none":"Sem resultados.","hint":"Pesquisar cidade / região","saving":"A guardar…","offline":"Cidades locais mostradas; pesquisa online indisponível."},"ro":{"settings":"Setări","timezone":"Fus orar","units":"Unitate meteo","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Format oră","dst":"Ora de vară automată","weather":"Locație meteo","country":"Țară / regiune","all":"Toate țările / regiunile","more":"Mai multe orașe","auto":"Automat (IP)","manual":"Alege orașul","system":"Urmează sistemul","search":"Caută","back":"‹ Înapoi","on":"Pornit","off":"Oprit","update":"Actualizare online","unavailable":"Neactivat","version":"Versiune software","12":"12 ore","24":"24 de ore","none":"Niciun rezultat.","hint":"Caută oraș / regiune","saving":"Se salvează…","offline":"Orașele locale sunt afișate; căutarea online nu este disponibilă."},"ru":{"settings":"Настройки","timezone":"Часовой пояс","units":"Единица погоды","celsius":"℃ Цельсий","fahrenheit":"℉ Фаренгейт","format":"Формат времени","dst":"Автоматическое летнее время","weather":"Место погоды","country":"Страна / регион","all":"Все страны / регионы","more":"Другие города","auto":"Авто (IP)","manual":"Выбрать город","system":"По системе","search":"Поиск","back":"‹ Назад","on":"Вкл.","off":"Выкл.","update":"Онлайн-обновление","unavailable":"Не включено","version":"Версия ПО","12":"12 часов","24":"24 часа","none":"Нет результатов.","hint":"Поиск города / региона","saving":"Сохранение…","offline":"Показаны местные города; онлайн-поиск недоступен."},"es":{"settings":"Ajustes","timezone":"Zona horaria","units":"Unidad meteorológica","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Formato de hora","dst":"Horario de verano automático","weather":"Ubicación del clima","country":"País / región","all":"Todos los países / regiones","more":"Más ciudades","auto":"Automático (IP)","manual":"Elegir ciudad","system":"Seguir sistema","search":"Buscar","back":"‹ Atrás","on":"Activado","off":"Desactivado","update":"Actualización en línea","unavailable":"No activado","version":"Versión del software","12":"12 horas","24":"24 horas","none":"Sin resultados.","hint":"Buscar ciudad / región","saving":"Guardando…","offline":"Se muestran ciudades locales; la búsqueda en línea no está disponible."},"sv":{"settings":"Inställningar","timezone":"Tidszon","units":"Väder-enhet","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Tidsformat","dst":"Automatisk sommartid","weather":"Väderplats","country":"Land / region","all":"Alla länder / regioner","more":"Fler städer","auto":"Automatiskt (IP)","manual":"Välj stad","system":"Följ systemet","search":"Sök","back":"‹ Tillbaka","on":"På","off":"Av","update":"Onlineuppdatering","unavailable":"Inte aktiverad","version":"Programvaruversion","12":"12 timmar","24":"24 timmar","none":"Inga resultat.","hint":"Sök stad / region","saving":"Sparar…","offline":"Lokala städer visas; onlinesökning är inte tillgänglig."},"zh-tw":{"settings":"設定","timezone":"時區","units":"天氣單位","celsius":"℃ 攝氏度","fahrenheit":"℉ 華氏度","format":"時間格式","dst":"自動夏令時間","weather":"天氣位置","country":"國家／地區","all":"全部國家／地區","more":"更多城市","auto":"自動定位（IP）","manual":"手動選擇城市","system":"跟隨系統","search":"搜尋","back":"‹ 返回","on":"開","off":"關","update":"線上更新","unavailable":"未啟用","version":"軟體版本","12":"12 小時制","24":"24 小時制","none":"沒有符合結果。","hint":"搜尋城市／地區","saving":"儲存中…","offline":"已顯示本機城市；無法使用線上搜尋。"},"th":{"settings":"การตั้งค่า","timezone":"เขตเวลา","units":"หน่วยสภาพอากาศ","celsius":"℃ เซลเซียส","fahrenheit":"℉ ฟาเรนไฮต์","format":"รูปแบบเวลา","dst":"เวลาออมแสงอัตโนมัติ","weather":"ตำแหน่งสภาพอากาศ","country":"ประเทศ / ภูมิภาค","all":"ทุกประเทศ / ภูมิภาค","more":"เมืองเพิ่มเติม","auto":"อัตโนมัติ (IP)","manual":"เลือกเมือง","system":"ตามระบบ","search":"ค้นหา","back":"‹ ย้อนกลับ","on":"เปิด","off":"ปิด","update":"อัปเดตออนไลน์","unavailable":"ไม่ได้เปิดใช้งาน","version":"เวอร์ชันซอฟต์แวร์","12":"12 ชั่วโมง","24":"24 ชั่วโมง","none":"ไม่พบผลลัพธ์","hint":"ค้นหาเมือง / ภูมิภาค","saving":"กำลังบันทึก…","offline":"แสดงเมืองในเครื่อง ไม่สามารถค้นหาออนไลน์ได้"},"tr":{"settings":"Ayarlar","timezone":"Saat dilimi","units":"Hava birimi","celsius":"℃ Celsius","fahrenheit":"℉ Fahrenheit","format":"Saat biçimi","dst":"Otomatik yaz saati","weather":"Hava konumu","country":"Ülke / bölge","all":"Tüm ülkeler / bölgeler","more":"Daha fazla şehir","auto":"Otomatik (IP)","manual":"Şehir seç","system":"Sistemi izle","search":"Ara","back":"‹ Geri","on":"Açık","off":"Kapalı","update":"Çevrimiçi güncelleme","unavailable":"Etkin değil","version":"Yazılım sürümü","12":"12 saat","24":"24 saat","none":"Sonuç yok.","hint":"Şehir / bölge ara","saving":"Kaydediliyor…","offline":"Yerel şehirler gösteriliyor; çevrimiçi arama kullanılamıyor."},"uk":{"settings":"Налаштування","timezone":"Часовий пояс","units":"Одиниця погоди","celsius":"℃ Цельсій","fahrenheit":"℉ Фаренгейт","format":"Формат часу","dst":"Автоматичний літній час","weather":"Місце погоди","country":"Країна / регіон","all":"Усі країни / регіони","more":"Інші міста","auto":"Автоматично (IP)","manual":"Вибрати місто","system":"За системою","search":"Пошук","back":"‹ Назад","on":"Увімк.","off":"Вимк.","update":"Онлайн-оновлення","unavailable":"Не ввімкнено","version":"Версія ПЗ","12":"12 годин","24":"24 години","none":"Немає результатів.","hint":"Пошук міста / регіону","saving":"Збереження…","offline":"Показано місцеві міста; онлайн-пошук недоступний."},"vi":{"settings":"Cài đặt","timezone":"Múi giờ","units":"Đơn vị thời tiết","celsius":"℃ Độ C","fahrenheit":"℉ Độ F","format":"Định dạng giờ","dst":"Giờ mùa hè tự động","weather":"Vị trí thời tiết","country":"Quốc gia / khu vực","all":"Tất cả quốc gia / khu vực","more":"Thêm thành phố","auto":"Tự động (IP)","manual":"Chọn thành phố","system":"Theo hệ thống","search":"Tìm kiếm","back":"‹ Quay lại","on":"Bật","off":"Tắt","update":"Cập nhật trực tuyến","unavailable":"Chưa bật","version":"Phiên bản phần mềm","12":"12 giờ","24":"24 giờ","none":"Không có kết quả.","hint":"Tìm thành phố / khu vực","saving":"Đang lưu…","offline":"Đang hiển thị thành phố cục bộ; tìm kiếm trực tuyến không khả dụng."}};
    const preferenceText = (key) => {
        const text = SETTINGS_TEXT[getSystemLanguage()] || SETTINGS_TEXT.en;
        return text[key] || SETTINGS_TEXT.en[key] || key;
    };
    const focusPreference = (id) => {
        const owner = gamepadRootRef.current?.ownerDocument.defaultView || window;
        owner.requestAnimationFrame(() => owner.requestAnimationFrame(() => focusDefaultGamepadElement(id)));
    };
    const openSettingsPage = () => {
        selectedPanelRef.current = "settings";
        setSelectedPanel("settings");
        setPreferencesMessage("");
        focusPreference("settings:timezone");
        void getDisplayOptions().then(setSettingsOptions).catch(error => setPreferencesMessage(String(error)));
    };
    const closeSettingsPage = () => {
        if (selectedPanelRef.current !== "settings") return false;
        settingsGenerationRef.current++;
        if (settingsPickerRef.current === "country") {
            settingsPickerRef.current = "weather";
            setSettingsPicker("weather");
            setSettingsQuery("");
            setSettingsResults([]);
            focusPreference("settings:country");
        } else if (settingsPickerRef.current) {
            const key = settingsPickerRef.current;
            settingsPickerRef.current = "";
            setSettingsPicker("");
            focusPreference(`settings:${key}`);
        } else {
            selectedPanelRef.current = "layout";
            setSelectedPanel("layout");
            focusPreference("settings-entry");
        }
        return true;
    };
    const savePreference = async (patch) => {
        if (settingsBusyRef.current) return;
        settingsBusyRef.current = true;
        setPreferencesBusy(true);
        setPreferencesMessage("");
        try {
            await saveSettings(patch);
            applyControlState(await getControlState());
            if (settingsPickerRef.current) closeSettingsPage();
            void getDisplayOptions().then(setSettingsOptions).catch(() => {});
        } catch (error) {
            setPreferencesMessage(String(error));
        } finally {
            settingsBusyRef.current = false;
            setPreferencesBusy(false);
        }
    };
    const openSettingsPicker = (key) => {
        if (settingsBusyRef.current) return;
        if (key === "dst") {
            void savePreference({ display_auto_dst: !displayPreferences.display_auto_dst });
            return;
        }
        if (key === "units") {
            void savePreference({ weather_temperature_unit: displayPreferences.weather_temperature_unit === "fahrenheit" ? "celsius" : "fahrenheit" });
            return;
        }
        if (key === "format") {
            void savePreference({ display_time_format: String(displayPreferences.display_time_format) === "12" ? "24" : "12" });
            return;
        }
        settingsGenerationRef.current++;
        settingsPickerRef.current = key;
        setSettingsPicker(key);
        setSettingsQuery("");
        setSettingsResults([]);
        setPreferencesMessage("");
        if (key === "weather") {
            const initial = settingsOptions.weather_locations || { countries: [], cities: [], next_offset: null };
            setSettingsCountry(initial.country_code || "");
            setSettingsLocationOptions(initial);
            setSettingsLocalCities(initial.cities || []);
        }
        focusPreference(key === "format" ? "settings-option:24" : key === "units" ? `settings-option:${displayPreferences.weather_temperature_unit || "celsius"}` : "settings:search-input");
    };
    const loadWeatherChoices = async (offset = 0, online = false) => {
        const generation = ++settingsGenerationRef.current;
        const query = settingsQuery.trim();
        setPreferencesMessage("");
        let localCities = settingsLocalCities;
        try {
            const value = await getWeatherLocationOptions(settingsCountry, query, offset, 40, getSystemLanguage());
            if (generation !== settingsGenerationRef.current || settingsPickerRef.current !== "weather") return;
            setSettingsLocationOptions(value);
            if (!settingsCountry) setSettingsCountry(value.country_code);
            localCities = value.cities;
            setSettingsLocalCities(previous => offset ? previous.concat(value.cities) : value.cities);
            setSettingsResults([]);
            if (offset && value.cities.length) {
                const previousPoints = new Set(settingsLocalCities.map(item => `${item.latitude},${item.longitude}`));
                const next = value.cities.find(item => !previousPoints.has(`${item.latitude},${item.longitude}`));
                if (next) focusPreference(`settings-option:city-${next.latitude},${next.longitude}`);
            }
            if (!value.cities.length && !online) setPreferencesMessage(preferenceText("none"));
            if (online && query.length >= 2) {
                try {
                    const rows = await searchWeatherLocations(query, getSystemLanguage(), value.country_code);
                    if (generation !== settingsGenerationRef.current || settingsPickerRef.current !== "weather") return;
                    setSettingsResults(rows);
                    if (!rows.length && !localCities.length) setPreferencesMessage(preferenceText("none"));
                } catch (error) {
                    if (generation === settingsGenerationRef.current && settingsPickerRef.current === "weather") setPreferencesMessage(localCities.length ? preferenceText("offline") : String(error));
                }
            }
        } catch (error) {
            if (generation === settingsGenerationRef.current && settingsPickerRef.current === "weather") setPreferencesMessage(localCities.length ? preferenceText("offline") : String(error));
        }
    };
    _local_SP_REACT.useEffect(() => {
        if (settingsPicker !== "weather") return;
        const owner = gamepadRootRef.current?.ownerDocument.defaultView || window;
        const timer = owner.setTimeout(() => void loadWeatherChoices(), settingsQuery ? 250 : 0);
        return () => owner.clearTimeout(timer);
    }, [settingsPicker, settingsCountry, settingsQuery]);
    const openWeatherCountry = () => {
        settingsGenerationRef.current++;
        settingsPickerRef.current = "country";
        setSettingsPicker("country");
        setSettingsQuery("");
        setPreferencesMessage("");
        focusPreference("settings:search-input");
    };
    const chooseWeatherCountry = (code) => {
        settingsGenerationRef.current++;
        settingsPickerRef.current = "weather";
        setSettingsCountry(code);
        setSettingsPicker("weather");
        setSettingsQuery("");
        setSettingsResults([]);
        setSettingsLocalCities([]);
        setPreferencesMessage("");
        focusPreference("settings:country");
    };
    const preferenceButtonStyle = (id) => ({ border: "0", borderBottom: "1px solid #39414b", borderRadius: "0", background: gamepadFocusedId === id ? (["timezone", "weather", "country"].includes(settingsPicker) ? "linear-gradient(90deg,#6e00ff,#9400ff)" : "#252b33") : "transparent", color: "#fff", minHeight: "46px", padding: "9px 8px", textAlign: "left", width: "100%", fontFamily: "inherit", fontSize: "14px", cursor: "pointer" });
    const renderSettingsPage = () => {
        const config = displayPreferences;
        const zh = getSystemLanguage().startsWith("zh");
        const countryLabel = item => (zh ? item.name_zh : item.name) || item.name;
        const countries = settingsLocationOptions.countries || [];
        const zone = settingsOptions.zones.find(item => item.id === config.display_timezone);
        const zoneValue = `${config.display_timezone === "system" ? preferenceText("system") : zone?.label || config.display_timezone} ${config.display_preview?.offset || zone?.offset || ""}`;
        const weatherValue = config.weather_location_mode === "manual" ? config.weather_manual_location?.name || preferenceText("manual") : `${preferenceText("auto")} ${config.weather_auto_city || ""}`;
        const selectedCountry = countries.find(item => item.code === settingsCountry);
        const query = settingsQuery.toLowerCase().trim();
        let choices = [];
        if (settingsPicker === "units") choices = ["celsius", "fahrenheit"].map(value => ({ id: value, label: preferenceText(value), patch: { weather_temperature_unit: value } }));
        if (settingsPicker === "format") choices = ["24", "12"].map(value => ({ id: value, label: preferenceText(value), patch: { display_time_format: value } }));
        if (settingsPicker === "timezone") choices = [{ id: "system", label: preferenceText("system"), patch: { display_timezone: "system" } }, ...settingsOptions.zones.filter(item => `${item.label} ${item.id}`.toLowerCase().includes(query)).map(item => ({ id: item.id, label: `${item.label} ${item.offset}`, patch: { display_timezone: item.id } }))];
        if (settingsPicker === "country") choices = [{ id: "country-ALL", label: preferenceText("all"), country: "ALL" }, ...countries.filter(item => `${countryLabel(item)} ${item.name} ${item.code}`.toLowerCase().includes(query)).map(item => ({ id: `country-${item.code}`, label: countryLabel(item), country: item.code }))];
        if (settingsPicker === "weather") {
            choices = [{ id: "auto", label: preferenceText("auto"), patch: { weather_location_mode: "auto" } }];
            const seen = new Set();
            const items = [...(!query ? config.weather_recent_locations || [] : []), ...settingsResults, ...settingsLocalCities];
            for (const item of items) {
                if (settingsCountry && settingsCountry !== "ALL" && item.country_code !== settingsCountry) continue;
                const name = zh && item.name_zh ? item.name_zh : item.name;
                const country = countries.find(value => value.code === item.country_code);
                const label = [name, item.admin1, country ? countryLabel(country) : item.country || item.country_code].filter(Boolean).join(" · ");
                if (query && !`${label} ${item.name_en || ""} ${item.name || ""}`.toLowerCase().includes(query)) continue;
                const point = `${item.latitude},${item.longitude}`;
                if (seen.has(point)) continue;
                seen.add(point);
                choices.push({ id: `city-${point}`, label, patch: { weather_location_mode: "manual", weather_manual_location: { ...item, name } } });
            }
        }
        return h("div", { key: "settings-page", "data-jsaux-section": "settings", style: { minHeight: "620px", display: "flex", flexDirection: "column" } }, [
            h("div", { key: "header", style: { ...styles.header, justifyContent: "flex-start", gap: "12px" } }, [
                h("button", { ...gamepadNavigationProps("settings:back"), key: "back", onClick: closeSettingsPage, style: { ...preferenceButtonStyle("settings:back"), width: "28px", minHeight: "32px", borderBottom: "0", padding: "0", fontSize: "28px" } }, "‹"),
                h("span", { key: "icon", style: { color: "#969da7", fontSize: "26px" } }, "⚙"),
                h("span", { key: "title", style: { fontSize: "18px", color: "#969da7" } }, preferenceText(settingsPicker || "settings")),
            ]),
            settingsPicker && !["format", "units"].includes(settingsPicker) ? h("div", { key: "search", style: { display: "flex", gap: "8px", padding: "12px" } }, [
                h("input", { ...gamepadNavigationProps("settings:search-input"), key: "input", type: "text", value: settingsQuery, placeholder: preferenceText("hint"), onChange: event => { setSettingsQuery(event.target.value); setSettingsResults([]); settingsGenerationRef.current++; setPreferencesMessage(""); }, onKeyDown: event => { if (event.key === "Enter") { if (settingsPicker === "weather") void loadWeatherChoices(0, true); else setSettingsQuery(settingsQuery.trim()); } }, style: { width: "100%", minWidth: "0", border: gamepadFocusedId === "settings:search-input" ? "2px solid #8500ff" : "1px solid #39414b", background: gamepadFocusedId === "settings:search-input" ? "linear-gradient(90deg,#6e00ff,#9400ff)" : "#0d141c", color: "#fff", borderRadius: "4px", padding: "8px", fontSize: "14px" } }),
                ["weather", "timezone"].includes(settingsPicker) ? h("button", { ...gamepadNavigationProps("settings:search"), key: "search-button", onClick: () => settingsPicker === "weather" ? void loadWeatherChoices(0, true) : setSettingsQuery(settingsQuery.trim()), style: { ...preferenceButtonStyle("settings:search"), width: "60px", border: gamepadFocusedId === "settings:search" ? "1px solid #8500ff" : "1px solid #39414b", minHeight: "36px", whiteSpace: "nowrap" } }, preferenceText("search")) : null,
            ]) : null,
            settingsPicker === "weather" ? h("button", { ...gamepadNavigationProps("settings:country"), key: "country", onClick: openWeatherCountry, style: { ...preferenceButtonStyle("settings:country"), width: "auto", margin: "0 12px" } }, `${preferenceText("country")}: ${selectedCountry ? countryLabel(selectedCountry) : preferenceText("all")} ▾`) : null,
            settingsPicker ? h("div", { key: "choices", style: { overflowY: "auto", maxHeight: settingsPicker === "weather" ? "410px" : "500px", padding: "0 12px", scrollbarWidth: "thin" } }, [
                ...choices.map(choice => h("button", { ...gamepadNavigationProps(`settings-option:${choice.id}`, false, preferencesBusy), key: choice.id, disabled: preferencesBusy, onClick: () => choice.country ? chooseWeatherCountry(choice.country) : void savePreference(choice.patch), style: preferenceButtonStyle(`settings-option:${choice.id}`) }, choice.label)),
                settingsPicker === "weather" && settingsLocationOptions.next_offset != null ? h("button", { ...gamepadNavigationProps("settings:more"), key: "more", onClick: () => void loadWeatherChoices(settingsLocationOptions.next_offset), style: preferenceButtonStyle("settings:more") }, preferenceText("more")) : null,
            ]) : h("div", { key: "rows", style: { padding: "0 12px" } }, [
                ...[["timezone", zoneValue], ["units", preferenceText(config.weather_temperature_unit || "celsius")], ["format", preferenceText(config.display_time_format)], ["dst", preferenceText(config.display_auto_dst ? "on" : "off")], ["weather", weatherValue]].map(([key, value]) => h("button", { ...gamepadNavigationProps(`settings:${key}`, false, preferencesBusy), key, disabled: preferencesBusy, onClick: () => openSettingsPicker(key), style: { ...preferenceButtonStyle(`settings:${key}`), display: "flex", gap: "8px", alignItems: "center" } }, [h("span", { key: "label", style: { flex: "0 0 92px", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: fitUiFontSize(preferenceText(key), 14, 8, 9) } }, preferenceText(key)), h("span", { key: "value", style: { flex: "1 1 auto", minWidth: "0", overflow: "hidden", textOverflow: "ellipsis", fontSize: "13px" } }, value)])),
                ...[["update", preferenceText("unavailable")], ["version", FIRMWARE_UI.currentVersion]].map(([key, value]) => h("div", { key, style: { ...preferenceButtonStyle(key), display: "flex", gap: "8px", width: "auto", cursor: "default", color: "#969da7" } }, [h("span", { key: "label", style: { flex: "0 0 92px" } }, preferenceText(key)), h("span", { key: "value", style: { fontSize: "13px" } }, value)])),
            ]),
            h("div", { key: "message", role: "status", style: { color: "#969da7", fontSize: "12px", padding: "12px", overflowWrap: "anywhere" } }, preferencesBusy ? "" : preferencesMessage || (settingsPicker === "weather" && !settingsQuery ? preferenceText("local") : "")),
        ]);
    };

    const applyControlState = _local_SP_REACT.useCallback((snapshot) => {
        if (!snapshot || typeof snapshot !== "object")
            return;
        const epoch = String(snapshot.epoch || "");
        const revision = Number(snapshot.revision);
        if (epoch && epoch !== controlStateEpochRef.current) {
            controlStateEpochRef.current = epoch;
            controlStateRevisionRef.current = -1;
        }
        if (epoch && Number.isFinite(revision)) {
            if (revision <= controlStateRevisionRef.current)
                return;
            controlStateRevisionRef.current = revision;
        }
        if (snapshot.status && typeof snapshot.status === "object")
            applyDeviceStatus(snapshot.status);
        const cfg = snapshot.settings;
        if (!cfg || typeof cfg !== "object")
            return;
        setDisplayPreferences(previous => ({ ...previous, ...cfg }));
        const activeModuleId = Number(cfg.active_module_id ?? cfg.single_module_id);
        const moduleMode = ({ 0: "carousel", 1: "timeline", 2: "deck_status", 3: "weather", 4: "clock", 5: "calendar", 6: "custom", 7: "agent" })[activeModuleId];
        const nextMode = cfg.mode === "dashboard" || cfg.mode === "carousel"
            ? "carousel"
            : moduleMode || (FIXED_MODE_VALUES.has(cfg.mode) ? cfg.mode : "deck_status");
        setModeState(nextMode);
        if (Number.isInteger(activeModuleId) && activeModuleId >= 0)
            setTimelineIdx(activeModuleId);
        const configuredPhotoFrameInterval = Number(cfg.photo_frame_interval_minutes ?? 5);
        setPhotoFrameInterval(Math.max(1, Math.min(60, Number.isFinite(configuredPhotoFrameInterval) ? configuredPhotoFrameInterval : 5)));
        setPhotoFrameIntervalEnabled(Boolean(cfg.photo_frame_interval_enabled));
        const configuredModuleSwitchInterval = Number(cfg.module_switch_interval_minutes ?? 5);
        const normalizedModuleSwitchInterval = Math.max(5, Math.min(60, Number.isFinite(configuredModuleSwitchInterval) ? configuredModuleSwitchInterval : 5));
        setModuleSwitchInterval(Math.round(normalizedModuleSwitchInterval / 5) * 5);
        setModuleSwitchEnabled(Boolean(cfg.module_switch_enabled));
        const configuredGameTimeMode = String(cfg.game_time_display_mode || "auto").toLowerCase();
        setGameTimeDisplayMode(GAME_TIME_DISPLAY_MODES.includes(configuredGameTimeMode) ? configuredGameTimeMode : "auto");
        setTimelineSecSt(Math.max(300, Math.min(3600, Number(cfg.stay_duration ?? cfg.timeline_sec) || 300)));
        setCustomFilePath(cfg.custom_selected_path || "");
        if (cfg.agent_status && typeof cfg.agent_status === "object")
            setAgentStatus(cfg.agent_status);
    }, [applyDeviceStatus]);

    _local_SP_REACT.useLayoutEffect(() => {
        const root = gamepadRootRef.current;
        const contentContainer = root?.parentElement;
        const pluginPanel = contentContainer?.parentElement;
        const hostHeader = Array.from(pluginPanel?.children || []).find((element) => element !== contentContainer && element.querySelector("button[role='button']"));
        if (!hostHeader || !contentContainer)
            return;
        hostBackButtonRef.current = hostHeader.querySelector("button[role='button']");
        const previousDisplay = hostHeader.style.display;
        const previousPaddingTop = contentContainer.style.paddingTop;
        hostHeader.style.display = "none";
        contentContainer.style.paddingTop = "0px";
        return () => {
            hostBackButtonRef.current = null;
            hostHeader.style.display = previousDisplay;
            contentContainer.style.paddingTop = previousPaddingTop;
        };
    }, []);
    const isElementEnabled = (element) => {
        if (element.getAttribute("data-gamepad-navigation") === "false")
            return false;
        if (element.hasAttribute("disabled") && element.getAttribute("data-gamepad-allow-disabled") !== "true")
            return false;
        if (element.getAttribute("data-disabled") === "true")
            return false;
        if (element.getAttribute("aria-disabled") === "true" && element.getAttribute("data-gamepad-activatable") !== "false")
            return false;
        return true;
    };
    const getGamepadElements = () => {
        const root = gamepadRootRef.current;
        if (!root)
            return [];
        const targets = Array.from(root.querySelectorAll(GAMEPAD_ACTION_SELECTOR))
            .filter(isElementEnabled)
            .map((element) => ({
            id: element.getAttribute("data-gamepad-id") || "",
            element,
        }))
            .filter((target) => !!target.id);
        return targets;
    };
    const getGamepadActiveElement = () => {
        const root = gamepadRootRef.current;
        if (!root)
            return null;
        return root.ownerDocument.activeElement;
    };
    const syncGamepadSemanticFocus = (id) => {
        const elements = getGamepadElements();
        const index = elements.findIndex((target) => target.id === id);
        if (index < 0)
            return;
        gamepadStateRef.current.focusedIndex = index;
        gamepadStateRef.current.focusedId = id;
        setGamepadFocusedId(id);
        gamepadStateRef.current.moduleBranch = resolveGamepadModuleBranch(id, gamepadStateRef.current.moduleBranch);
    };
    const takeSteamFocus = (element) => {
        const ownerWindow = gamepadRootRef.current?.ownerDocument.defaultView || window;
        const controller = ownerWindow?.GamepadNavTree?.m_context?.m_controller
            || ownerWindow?.FocusNavController
            || ownerWindow?.opener?.GamepadNavTree?.m_context?.m_controller
            || ownerWindow?.opener?.FocusNavController;
        const context = controller?.m_ActiveContext || controller?.m_LastActiveContext;
        const findNode = (node) => {
            if (!node)
                return null;
            if (node.Element === element)
                return node;
            for (const child of node.m_rgChildren || []) {
                const match = findNode(child);
                if (match)
                    return match;
            }
            return null;
        };
        for (const tree of context?.m_rgGamepadNavigationTrees || []) {
            const node = findNode(tree?.Root);
            if (node?.BTakeFocus?.())
                return true;
        }
        return false;
    };
    const focusSemanticElement = (element) => {
        if (!takeSteamFocus(element))
            element.focus({ preventScroll: true });
    };
    const focusGamepadElement = (elements, index, moduleBranch = gamepadStateRef.current.moduleBranch) => {
        const target = elements[index];
        if (!target)
            return;
        gamepadStateRef.current.focusedIndex = index;
        gamepadStateRef.current.focusedId = target.id;
        setGamepadFocusedId(target.id);
        gamepadStateRef.current.moduleBranch = resolveGamepadModuleBranch(target.id, moduleBranch);
        focusSemanticElement(target.element);
        if (shouldScrollGamepadTargetToTop(target.id))
            gamepadRootRef.current?.scrollIntoView({ block: "start" });
        else
            target.element.scrollIntoView({ block: "nearest" });
    };
    const focusDefaultGamepadElement = (id = "connection-page-entry") => {
        const elements = getGamepadElements();
        const index = elements.findIndex((target) => target.id === id);
        if (index < 0)
            return false;
        focusGamepadElement(elements, index);
        return true;
    };
    const focusGamepadElementOrFallback = (id, ...fallbackIds) =>
        [id, ...fallbackIds].some((targetId) => focusDefaultGamepadElement(targetId));
    const restoreCustomGridFocus = () => {
        if (!customReturnPendingRef.current)
            return;
        customReturnPendingRef.current = false;
        const target = customGridFocusRef.current;
        const ownerWindow = gamepadRootRef.current?.ownerDocument.defaultView || window;
        ownerWindow.requestAnimationFrame(() => ownerWindow.requestAnimationFrame(() => focusGamepadElementOrFallback(target, customFiles.length > 0 ? "custom:item:0" : "custom:upload")));
    };
    const finishCustomOperationAfterPaint = () => {
        customProgressSourceRef.current = "";
        const ownerWindow = gamepadRootRef.current?.ownerDocument.defaultView || window;
        ownerWindow.requestAnimationFrame(() => ownerWindow.requestAnimationFrame(() => {
            setCustomOperation("");
            setCustomOperationProgress(0);
        }));
    };
    const moveCustomGamepadFocus = (direction) => {
        const elements = getGamepadElements();
        const ids = elements.map((target) => target.id);
        const itemIds = ids.filter((id) => id.startsWith("custom:item:"));
        const activeId = getGamepadActiveElement()?.getAttribute("data-gamepad-id") || "";
        const currentId = itemIds.includes(activeId) ? activeId : gamepadStateRef.current.focusedId;
        const itemIndex = itemIds.indexOf(currentId);
        if (itemIndex >= 0) {
            let targetIndex = itemIndex;
            if (direction === "left")
                targetIndex = itemIndex - 1;
            else if (direction === "right")
                targetIndex = itemIndex + 1;
            else if (direction === "up")
                targetIndex = itemIndex - 2;
            else if (direction === "down")
                targetIndex = itemIndex + 2;
            const targetId = itemIds[targetIndex];
            if (targetId)
                return focusDefaultGamepadElement(targetId);
            if (direction === "down")
                return focusGamepadElementOrFallback("custom:upload", currentId);
            if (direction === "up")
                return focusGamepadElementOrFallback(itemIds[0], "custom:upload");
            return true;
        }
        if (currentId === "custom:select" && direction === "right")
            return focusGamepadElementOrFallback("custom:delete", "custom:select");
        if (currentId === "custom:delete" && direction === "left")
            return focusGamepadElementOrFallback("custom:select", "custom:delete");
        if (currentId === "custom:upload" && direction === "up")
            return focusGamepadElementOrFallback(itemIds.at(-1) || "custom:upload", "custom:upload");
        if (currentId === "custom:upload" && direction === "down")
            return focusGamepadElementOrFallback("custom:back", "custom:upload");
        if (currentId === "custom:back" && direction === "up")
            return focusGamepadElementOrFallback("custom:upload", "custom:back");
        if (currentId === "custom:back")
            return true;
        return focusGamepadElementOrFallback(itemIds[0] || "custom:upload", "custom:upload");
    };
    const moveGamepadFocus = (direction) => {
        // Game Time is a vertical picker. Keep its focus inside the picker so
        // analog-stick input cannot fall through to the main module grid.
        if (selectedPanelRef.current === "game-time") {
            const elements = getGamepadElements();
            const ids = elements.map((target) => target.id);
            const modeIds = ids.filter((id) => id.startsWith("game-time-mode:"));
            const activeId = elements.find((target) => target.element === getGamepadActiveElement())?.id || "";
            const currentId = modeIds.includes(activeId) ? activeId : gamepadStateRef.current.focusedId;
            const modeIndex = modeIds.indexOf(currentId);
            if (modeIndex >= 0 && (direction === "up" || direction === "down" || direction === "left" || direction === "right")) {
                const step = direction === "up" || direction === "left" ? -1 : 1;
                const nextIndex = Math.max(0, Math.min(modeIds.length - 1, modeIndex + step));
                focusDefaultGamepadElement(modeIds[nextIndex]);
                return;
            }
            if (direction === "right" && ids.includes("game-time:back")) {
                focusDefaultGamepadElement(modeIds[0] || "game-time:back");
                return;
            }
            if (direction === "left" && currentId !== "game-time:back" && ids.includes("game-time:back")) {
                focusDefaultGamepadElement("game-time:back");
                return;
            }
        }
        if (selectedPanelRef.current === "settings") {
            const elements = getGamepadElements();
            const ids = elements.map(target => target.id);
            const currentIndex = resolveGamepadFocusIndex(ids, gamepadStateRef.current.focusedId, "", gamepadStateRef.current.focusedIndex);
            const next = Math.max(0, Math.min(elements.length - 1, currentIndex + (direction === "down" || direction === "right" ? 1 : -1)));
            if (next >= 0) focusGamepadElement(elements, next);
            return;
        }
        if (selectedPanelRef.current === "custom" || gamepadRootRef.current?.querySelector('[data-jsaux-section="custom"]')) {
            moveCustomGamepadFocus(direction);
            return;
        }
        const elements = getGamepadElements();
        const ids = elements.map((target) => target.id);
        const activeElement = getGamepadActiveElement();
        const activeId = elements.find((target) => target.element === activeElement)?.id || "";
        if (connectionPageRef.current) {
            const currentIndex = resolveGamepadFocusIndex(ids, gamepadStateRef.current.focusedId, activeId, gamepadStateRef.current.focusedIndex);
            const step = direction === "down" || direction === "right" ? 1 : -1;
            const nextIndex = Math.max(0, Math.min(elements.length - 1, currentIndex + step));
            if (nextIndex >= 0)
                focusGamepadElement(elements, nextIndex);
            return;
        }
        const nextState = resolveGamepadNavigationState(ids, gamepadStateRef.current, activeId, direction);
        if (nextState.focusedIndex >= 0)
            focusGamepadElement(elements, nextState.focusedIndex, nextState.moduleBranch);
    };
    const getFocusedRange = () => {
        const element = getGamepadActiveElement();
        if (element?.tagName === "INPUT" && element.getAttribute("type") === "range" && isElementEnabled(element))
            return element;
        const selectedElement = getGamepadElements().find((target) => target.id === gamepadStateRef.current.focusedId)?.element;
        if (selectedElement?.tagName === "INPUT" && selectedElement.getAttribute("type") === "range" && isElementEnabled(selectedElement))
            return selectedElement;
        return null;
    };
    const nudgeFocusedRange = (step) => {
        const range = getFocusedRange();
        if (!range)
            return false;
        if (step > 0)
            range.stepUp();
        else
            range.stepDown();
        const ownerDocument = range.ownerDocument || document;
        const EventCtor = ownerDocument.defaultView?.Event || Event;
        range.dispatchEvent(new EventCtor("input", { bubbles: true }));
        range.dispatchEvent(new EventCtor("change", { bubbles: true }));
        return true;
    };
    const activateGamepadFocus = () => {
        const elements = getGamepadElements();
        const ids = elements.map((target) => target.id);
        const activeElement = getGamepadActiveElement();
        const activeId = elements.find((target) => target.element === activeElement)?.id || "";
        const currentIndex = resolveGamepadFocusIndex(ids, gamepadStateRef.current.focusedId, activeId, gamepadStateRef.current.focusedIndex);
        const target = elements[currentIndex];
        if (target && shouldActivateGamepadTarget(target.id, target.element.getAttribute("data-gamepad-activatable") !== "false")) {
            if (target.id === "photo-frame") {
                gamepadRootRef.current?.querySelector('[data-gamepad-id="photo-frame-toggle"]')?.click();
                return;
            }
            if (target.id === "module-switch") {
                gamepadRootRef.current?.querySelector('[data-gamepad-id="module-switch-toggle"]')?.click();
                return;
            }
            syncGamepadSemanticFocus(target.id);
            if (target.id.startsWith("game-time-mode:")) {
                void handleGameTimeDisplayModeSelect(target.id.slice("game-time-mode:".length));
                return;
            }
            if (target.id.startsWith("custom:item:")) {
                const EventCtor = target.element.ownerDocument.defaultView?.Event || Event;
                target.element.dispatchEvent(new EventCtor("click", { bubbles: true, cancelable: true }));
                return;
            }
            target.element.click();
            return;
        }
        if (!target)
            focusDefaultGamepadElement("connection-page-entry");
    };
    const closeGameTimeModePage = () => {
        if (selectedPanelRef.current !== "game-time")
            return false;
        selectedPanelRef.current = "layout";
        setSelectedPanel("layout");
        const ownerWindow = gamepadRootRef.current?.ownerDocument.defaultView || window;
        ownerWindow.requestAnimationFrame(() => focusDefaultGamepadElement("module:timeline"));
        return true;
    };
    const closeConnectionPage = () => {
        if (!connectionPageRef.current)
            return false;
        connectionPageRef.current = false;
        setConnectionPage(false);
        selectedPanelRef.current = "screen";
        setSelectedPanel("screen");
        const ownerWindow = gamepadRootRef.current?.ownerDocument.defaultView || window;
        ownerWindow.requestAnimationFrame(() => focusDefaultGamepadElement("connection-page-entry"));
        return true;
    };
    const closeCustomPage = () => {
        if (selectedPanelRef.current !== "custom")
            return false;
        selectedPanelRef.current = "layout";
        setSelectedPanel("layout");
        const ownerWindow = gamepadRootRef.current?.ownerDocument.defaultView || window;
        ownerWindow.requestAnimationFrame(() => focusDefaultGamepadElement("module:custom"));
        return true;
    };
    _local_SP_REACT.useEffect(() => {
        (async () => {
            try {
                applyControlState(await getControlState());
            }
            catch (_) { }
            try {
                const loc = await getIpLocation();
                if (loc?.city)
                    setIpCity(`${loc.city}${loc.country ? ", " + loc.country : ""}`);
            }
            catch (_) { }
        })();
    }, [applyControlState]);
    _local_SP_REACT.useEffect(() => {
        const onProgress = addEventListener("progress", (pct) => {
            const nextPct = Math.max(0, Math.min(100, Number(pct) || 0));
            setProgress(nextPct);
            if (customProgressSourceRef.current === "select")
                setCustomOperationProgress(nextPct);
            if (nextPct >= 100) {
                restoreCustomGridFocus();
                if (customProgressSourceRef.current === "select")
                    finishCustomOperationAfterPaint();
            }
        });
        const onDisplayState = addEventListener("display_state", (state) => {
            if (!state || typeof state !== "object")
                return;
            const nextState = String(state.state || "");
            setDisplayProgressState(nextState);
            if (state.progress !== null && state.progress !== undefined)
                setProgress(Math.max(0, Math.min(100, Number(state.progress) || 0)));
            if (nextState === "retrying") {
                // Five percent means "connecting". Reset it while the
                // daemon is rediscovering the selected MAC address.
                setProgress(0);
            }
            else if (nextState === "failed" || nextState === "cancelled") {
                setProgress(0);
                setSending(false);
            }
        });
        const onStatus = addEventListener("status_update", (s) => {
            applyDeviceStatus(s);
        });
        const onControlState = addEventListener("control_state_update", (snapshot) => {
            applyControlState(snapshot);
        });
        const onTimeline = addEventListener("timeline_idx", (idx) => setTimelineIdx(Number(idx) || 0));
        const onAgentStatus = addEventListener("agent_status_update", (payload) => {
            if (payload && typeof payload === "object")
                setAgentStatus(payload);
        });
        const onCustomFileSelected = addEventListener("custom_file_selected", (payload) => {
            if (payload?.path !== undefined) {
                setCustomFilePath(payload.path || "");
            }
        });
        return () => {
            removeEventListener("progress", onProgress);
            removeEventListener("display_state", onDisplayState);
            removeEventListener("status_update", onStatus);
            removeEventListener("control_state_update", onControlState);
            removeEventListener("timeline_idx", onTimeline);
            removeEventListener("custom_file_selected", onCustomFileSelected);
            removeEventListener("agent_status_update", onAgentStatus);
        };
    }, [applyControlState, applyDeviceStatus]);
    _local_SP_REACT.useEffect(() => {
        selectedPanelRef.current = selectedPanel;
    }, [selectedPanel]);
    _local_SP_REACT.useEffect(() => {
        let hasSteamInputBridge = false;
        let steamInputRegistration = null;
        let activationReadyAt = Number.POSITIVE_INFINITY;
        let activationArmed = false;
        let isGamepadVisible = false;
        const cancelPressedSources = new Set();
        let cancelPressActive = false;
        const ownerDocument = gamepadRootRef.current?.ownerDocument || document;
        const ownerWindow = ownerDocument.defaultView || window;
        const inputWindow = (window.opener || window);
        const eventWindows = Array.from(new Set([window, inputWindow, ownerWindow]));
        const closeGamingCustomPage = () => {
            if (selectedPanelRef.current !== "custom")
                return false;
            if (["custom:select", "custom:delete"].includes(gamepadStateRef.current.focusedId)) {
                ownerWindow.requestAnimationFrame(() => ownerWindow.requestAnimationFrame(() => focusGamepadElementOrFallback(customGridFocusRef.current, "custom:upload")));
                return true;
            }
            return closeCustomPage();
        };
        const closeGamingPanel = () => {
            if (closeSettingsPage()) return;
            if (closeConnectionPage())
                return;
            if (closeGameTimeModePage())
                return;
            if (closeGamingCustomPage())
                return;
            hostBackButtonRef.current?.click();
        };
        const handleGamepadCancel = (pressedNow, source) => {
            const sourceKey = `${source}:cancel`;
            if (!pressedNow) {
                cancelPressedSources.delete(sourceKey);
                if (cancelPressedSources.size === 0)
                    cancelPressActive = false;
                return;
            }
            if (cancelPressedSources.has(sourceKey))
                return;
            cancelPressedSources.add(sourceKey);
            if (cancelPressActive)
                return;
            cancelPressActive = true;
            closeGamingPanel();
        };
        const isGamepadPanelVisible = () => {
            const root = gamepadRootRef.current;
            if (!root || ownerDocument.hidden)
                return false;
            return root.getClientRects().length > 0;
        };
        const syncGamepadVisibility = () => {
            const visible = isGamepadPanelVisible();
            if (didGamepadPanelBecomeVisible(isGamepadVisible, visible)) {
                activationArmed = false;
                activationReadyAt = window.performance.now() + GAMEPAD_ACTIVATION_GUARD_MS;
                gamepadStateRef.current.pressedButtons.add("activate");
                gamepadStateRef.current.focusedIndex = -1;
                gamepadStateRef.current.focusedId = "";
                gamepadStateRef.current.moduleBranch = "left";
                focusDefaultGamepadElement("connection-page-entry");
            }
            else if (!visible && isGamepadVisible) {
                activationArmed = false;
                gamepadStateRef.current.pressedButtons.delete("activate");
            }
            isGamepadVisible = visible;
        };
        const releaseGamepadActivation = () => {
            gamepadStateRef.current.pressedButtons.delete("activate");
            if (isGamepadVisible)
                activationArmed = true;
        };
        const tryActivateGamepadFocus = () => {
            const alreadyPressed = gamepadStateRef.current.pressedButtons.has("activate");
            gamepadStateRef.current.pressedButtons.add("activate");
            const now = window.performance.now();
            if (shouldActivateGamepadInput(activationArmed, alreadyPressed, now, activationReadyAt)
                && shouldHandleGamepadActivation(gamepadStateRef.current.lastActivationAt, now, GAMEPAD_ACTIVATION_DEDUPE_MS)) {
                gamepadStateRef.current.lastActivationAt = now;
                activateGamepadFocus();
            }
        };
        const consumeVgpEvent = (event) => {
            event.preventDefault?.();
            event.stopPropagation?.();
            event.stopImmediatePropagation?.();
        };
        const handleGamepadDirection = (direction) => {
            const now = window.performance.now();
            if (!shouldHandleGamepadDirection(direction, gamepadStateRef.current.lastDirectionAt, gamepadStateRef.current.lastDirection, now, GAMEPAD_DIRECTION_DEDUPE_MS))
                return;
            gamepadStateRef.current.lastDirection = direction;
            gamepadStateRef.current.lastDirectionAt = now;
            if (direction === "left" || direction === "right") {
                const step = direction === "right" ? 1 : -1;
                if (!nudgeFocusedRange(step))
                    moveGamepadFocus(direction);
                return;
            }
            moveGamepadFocus(direction);
        };
        const handleVgpActivate = (event) => {
            syncGamepadVisibility();
            if (!isGamepadVisible)
                return;
            if (event.detail?.button === 2) {
                consumeVgpEvent(event);
                handleGamepadCancel(event.type === "vgp_onbuttondown", "vgp");
                return;
            }
            const direction = mapDeckyGamepadButton(Number(event.detail?.button));
            if (direction) {
                consumeVgpEvent(event);
                if (event.type === "vgp_onbuttondown")
                    handleGamepadDirection(direction);
                return;
            }
            if (event.detail?.button !== 1)
                return;
            consumeVgpEvent(event);
            if (event.type === "vgp_onbuttonup") {
                releaseGamepadActivation();
                return;
            }
            tryActivateGamepadFocus();
        };
        const handleKeyDown = (event) => {
            if (event.target?.tagName === "INPUT" && event.target.type === "text" && event.key !== "Escape") return;
            syncGamepadVisibility();
            if (!isGamepadVisible)
                return;
            if (event.key === "Escape") {
                consumeVgpEvent(event);
                handleGamepadCancel(true, "keyboard");
                return;
            }
            if (event.defaultPrevented)
                return;
            if (event.key === "Enter" || event.key === " ") {
                consumeVgpEvent(event);
                tryActivateGamepadFocus();
                return;
            }
            if (event.key === "ArrowLeft") {
                if (!nudgeFocusedRange(-1))
                    moveGamepadFocus("left");
                event.preventDefault();
                return;
            }
            if (event.key === "ArrowRight") {
                if (!nudgeFocusedRange(1))
                    moveGamepadFocus("right");
                event.preventDefault();
                return;
            }
            if (event.key === "ArrowUp") {
                moveGamepadFocus("up");
                event.preventDefault();
                return;
            }
            if (event.key === "ArrowDown") {
                moveGamepadFocus("down");
                event.preventDefault();
            }
        };
        const handleKeyUp = (event) => {
            if (event.target?.tagName === "INPUT" && event.target.type === "text" && event.key !== "Escape") return;
            syncGamepadVisibility();
            if (!isGamepadVisible)
                return;
            if (event.key === "Escape") {
                consumeVgpEvent(event);
                handleGamepadCancel(false, "keyboard");
                return;
            }
            if (event.key === "Enter" || event.key === " ") {
                consumeVgpEvent(event);
                releaseGamepadActivation();
            }
        };
        let frame = 0;
        const pollGamepads = () => {
            syncGamepadVisibility();
            if (!isGamepadVisible) {
                frame = window.requestAnimationFrame(pollGamepads);
                return;
            }
            const gamepads = navigator.getGamepads?.() ?? [];
            const gamepad = Array.from(gamepads).find(Boolean);
            const now = Date.now();
            if (gamepad) {
                const vertical = Math.abs(gamepad.axes[1] ?? 0) > GAMEPAD_AXIS_THRESHOLD ? Math.sign(gamepad.axes[1] ?? 0) : 0;
                const horizontal = Math.abs(gamepad.axes[0] ?? 0) > GAMEPAD_AXIS_THRESHOLD ? Math.sign(gamepad.axes[0] ?? 0) : 0;
                const dpadUp = gamepad.buttons[12]?.pressed;
                const dpadDown = gamepad.buttons[13]?.pressed;
                const dpadLeft = gamepad.buttons[14]?.pressed;
                const dpadRight = gamepad.buttons[15]?.pressed;
                const step = dpadDown || vertical > 0 ? 1 : dpadUp || vertical < 0 ? -1 : 0;
                const rangeStep = dpadRight || horizontal > 0 ? 1 : dpadLeft || horizontal < 0 ? -1 : 0;
                if (now - gamepadStateRef.current.lastMoveAt >= GAMEPAD_REPEAT_MS) {
                    if (rangeStep !== 0) {
                        if (!nudgeFocusedRange(rangeStep))
                            moveGamepadFocus(rangeStep > 0 ? "right" : "left");
                        gamepadStateRef.current.lastMoveAt = now;
                    }
                    else if (step !== 0) {
                        moveGamepadFocus(step > 0 ? "down" : "up");
                        gamepadStateRef.current.lastMoveAt = now;
                    }
                }
                const confirmPressed = Boolean(gamepad.buttons[0]?.pressed);
                const cancelPressed = Boolean(gamepad.buttons[1]?.pressed);
                handleGamepadCancel(cancelPressed, "browser-gamepad");
                if (confirmPressed)
                    tryActivateGamepadFocus();
                else if (!confirmPressed) {
                    releaseGamepadActivation();
                }
            }
            frame = window.requestAnimationFrame(pollGamepads);
        };
        const steamInputWindow = eventWindows.find((candidateWindow) => candidateWindow?.SteamClient?.Input?.RegisterForControllerInputMessages);
        const steamInput = steamInputWindow?.SteamClient?.Input;
        if (steamInput?.RegisterForControllerInputMessages) {
            hasSteamInputBridge = true;
            steamInputRegistration = steamInput.RegisterForControllerInputMessages((_controllerIndex, button, pressed) => {
                syncGamepadVisibility();
                if (!isGamepadVisible)
                    return;
                const action = mapSteamControllerButton(Number(button));
                if (!action)
                    return;
                if (action === "activate") {
                    if (!pressed) {
                        releaseGamepadActivation();
                        return;
                    }
                    tryActivateGamepadFocus();
                    return;
                }
                if (action === "cancel") {
                    handleGamepadCancel(pressed, "steam-input");
                    return;
                }
                const pressedKey = `steam-${button}`;
                if (!pressed) {
                    gamepadStateRef.current.pressedButtons.delete(pressedKey);
                    return;
                }
                if (gamepadStateRef.current.pressedButtons.has(pressedKey))
                    return;
                gamepadStateRef.current.pressedButtons.add(pressedKey);
                handleGamepadDirection(action);
            });
        }
        syncGamepadVisibility();
        ownerDocument.addEventListener("visibilitychange", syncGamepadVisibility);
        eventWindows.forEach((eventWindow) => {
            eventWindow.addEventListener("keydown", handleKeyDown, true);
            eventWindow.addEventListener("keyup", handleKeyUp, true);
            eventWindow.addEventListener("vgp_onbuttondown", handleVgpActivate, true);
            eventWindow.addEventListener("vgp_onbuttonup", handleVgpActivate, true);
        });
        frame = ownerWindow.requestAnimationFrame(pollGamepads);
        return () => {
            ownerDocument.removeEventListener("visibilitychange", syncGamepadVisibility);
            eventWindows.forEach((eventWindow) => {
                eventWindow.removeEventListener("keydown", handleKeyDown, true);
                eventWindow.removeEventListener("keyup", handleKeyUp, true);
                eventWindow.removeEventListener("vgp_onbuttondown", handleVgpActivate, true);
                eventWindow.removeEventListener("vgp_onbuttonup", handleVgpActivate, true);
            });
            ownerWindow.cancelAnimationFrame(frame);
            if (typeof steamInputRegistration === "function")
                steamInputRegistration();
            else if (steamInputRegistration?.unregister)
                steamInputRegistration.unregister();
        };
    }, []);
    _local_SP_REACT.useEffect(() => {
        if (selectedPanel !== "custom" || loadingFiles)
            return;
        const target = customFiles.length > 0 ? customGridFocusRef.current : "custom:upload";
        let secondFrame = 0;
        const frame = window.requestAnimationFrame(() => {
            secondFrame = window.requestAnimationFrame(() => focusGamepadElementOrFallback(target, customFiles.length > 0 ? "custom:item:0" : "custom:upload"));
        });
        return () => {
            window.cancelAnimationFrame(frame);
            if (secondFrame)
                window.cancelAnimationFrame(secondFrame);
        };
    }, [selectedPanel, customFiles.length, loadingFiles, customOperation]);
    const handleScan = _local_SP_REACT.useCallback(async () => {
        if (connectionRequestPendingRef.current)
            return;
        connectionRequestPendingRef.current = true;
        try {
            await refreshConnectionCandidates();
        }
        catch (e) {
            toaster.toast({ title: "JSAUX E-INK", body: formatUiText("errorMessage", { error: e }) });
        }
        finally {
            connectionRequestPendingRef.current = false;
        }
    }, [applyDeviceStatus]);
    const handleDisconnect = _local_SP_REACT.useCallback(async () => {
        if (connectionRequestPendingRef.current)
            return;
        connectionRequestPendingRef.current = true;
        try {
            await callWithTimeout(setConnectionEnabledFn(false), 15000, "Disconnect");
            // Do not rely only on the Decky event stream. Older Decky/SteamOS
            // combinations can drop that event, leaving the toggle visually
            // ON after the backend has already disconnected.
            const status = await callWithTimeout(getStatus(), 10000, "Device status");
            applyDeviceStatus(status);
        }
        catch (e) {
            toaster.toast({ title: "JSAUX E-INK", body: formatUiText("errorMessage", { error: e }) });
        }
        finally {
            connectionRequestPendingRef.current = false;
        }
    }, [applyDeviceStatus]);
    const refreshConnectionCandidates = _local_SP_REACT.useCallback(async () => {
        if (connectionPageOperationRef.current)
            return;
        connectionPageOperationRef.current = true;
        setDevicesScanning(true);
        try {
            // The daemon scan budget is bounded to 12 seconds.  Keep the
            // plugin spinner from waiting 45 seconds when an older BlueZ
            // runtime leaves an RPC in progress; the user can retry.
            const result = await callWithTimeout(scanDevices(), 18000, "Bluetooth scan");
            const candidates = sortConnectionCandidatesByRssi((Array.isArray(result) ? result : []).filter((candidate) => String(candidate?.name || "").includes(PRODUCT_NAME) && !!canonicalMacAddress(candidate?.address)), confirmedConnectedMacRef.current);
            setDeviceCandidates(candidates);
            let scanStatus = null;
            try {
                scanStatus = await callWithTimeout(getStatus(), 10000, "Device status");
                applyDeviceStatus(scanStatus);
            }
            catch (statusError) {
                // Keep a successful scan visible even if an older Decky
                // runtime drops the follow-up status request.
                if (candidates.length === 0)
                    throw statusError;
            }
            if (candidates.length === 0) {
                const scanError = String(scanStatus?.last_error || "").trim();
                if (scanError && !scanError.toLowerCase().startsWith("bluetooth busy:")) {
                    toaster.toast({ title: PRODUCT_NAME, body: scanError });
                    return;
                }
            }
        }
        catch (e) {
            toaster.toast({ title: PRODUCT_NAME, body: formatUiText("errorMessage", { error: e }) });
        }
        finally {
            setDevicesScanning(false);
            connectionPageOperationRef.current = false;
        }
    }, [applyDeviceStatus]);
    const openConnectionPage = _local_SP_REACT.useCallback(() => {
        connectionPageRef.current = true;
        setConnectionPage(true);
        setSelectedPanel("screen");
        setDeviceCandidates([]);
        const ownerWindow = gamepadRootRef.current?.ownerDocument.defaultView || window;
        ownerWindow.requestAnimationFrame(() => focusDefaultGamepadElement("connection-page-back"));
        void refreshConnectionCandidates();
    }, []);
    const selectConnectionCandidate = _local_SP_REACT.useCallback(async (candidate) => {
        const candidateAddress = canonicalMacAddress(candidate?.address);
        if (!candidateAddress || connectionPageOperationRef.current)
            return;
        const replacingAddress = confirmedConnectedMacRef.current && candidateAddress !== confirmedConnectedMacRef.current
            ? confirmedConnectedMacRef.current
            : "";
        connectionPageOperationRef.current = true;
        setDeviceSelectionPending(candidateAddress);
        try {
            let operationSucceeded = false;
            if (candidateAddress === confirmedConnectedMacRef.current) {
                const disconnectResult = await callWithTimeout(disconnect(), 15000, "Disconnect");
                operationSucceeded = Boolean(disconnectResult);
            }
            else {
                if (replacingAddress)
                    await callWithTimeout(disconnect(), 15000, "Disconnect");
                const connectionResult = await callWithTimeout(connectDevice(candidate.address), 20000, "Connect");
                operationSucceeded = Boolean(connectionResult);
            }
            const status = await callWithTimeout(getStatus(), 10000, "Device status");
            // Apply the RPC response directly as the authoritative UI state;
            // the event stream is only a supplemental update channel.
            applyDeviceStatus(status);
            if (!operationSucceeded && !lastConnectionErrorRef.current)
                toaster.toast({ title: PRODUCT_NAME, body: String(status?.last_error || t("connectionFailed")) });
        }
        catch (e) {
            toaster.toast({ title: PRODUCT_NAME, body: formatUiText("errorMessage", { error: e }) });
            // Backend status_update is authoritative; avoid a second page-level rerender here.
        }
        finally {
            setDeviceSelectionPending("");
            connectionPageOperationRef.current = false;
        }
    }, [applyDeviceStatus]);
    const withSend = _local_SP_REACT.useCallback((fn) => async () => {
        const requestId = ++sendRequestRef.current;
        setSending(true);
        setProgress(0);
        setDisplayProgressState("starting");
        try {
            const ok = await fn();
            if (!ok && requestId === sendRequestRef.current) {
                toaster.toast({ title: "JSAUX E-INK", body: t("sendFailed") });
            }
            return Boolean(ok);
        }
        catch (e) {
            if (requestId === sendRequestRef.current)
                toaster.toast({ title: "JSAUX E-INK", body: formatUiText("errorMessage", { error: e }) });
            return false;
        }
        finally {
            if (requestId === sendRequestRef.current) {
                setSending(false);
                setDisplayProgressState("");
                restoreCustomGridFocus();
            }
        }
    }, []);
    _local_SP_REACT.useCallback((id) => {
        if (id === 6 && !customFilePath)
            return;
        return withSend(() => sendModuleFn(id))();
    }, [customFilePath, withSend]);
    const handleRefresh = _local_SP_REACT.useMemo ? withSend(() => refreshNow()) : withSend(() => refreshNow());
    const applyDisplayModeConfig = _local_SP_REACT.useCallback(async (nextMode, nextStayDuration = timelineSec) => {
        const clampedStayDuration = Math.max(300, Math.min(3600, Number(nextStayDuration) || 300));
        if (nextMode === "carousel") {
            await saveSettings({
                mode: "carousel",
                display_mode: "multi",
                stay_duration: clampedStayDuration,
            });
            return;
        }
        await saveSettings({
            mode: nextMode,
            display_mode: "single",
            stay_duration: clampedStayDuration,
        });
    }, [timelineSec]);
    _local_SP_REACT.useCallback(async (nextMode) => {
        setModeState(nextMode);
        await applyDisplayModeConfig(nextMode);
        if (connected) {
            await handleRefresh();
        }
    }, [applyDisplayModeConfig, connected, handleRefresh]);
    const handlePhotoFrameIntervalChange = _local_SP_REACT.useCallback(async (value) => {
        if (!photoFrameIntervalEnabled)
            return;
        const next = Math.max(1, Math.min(60, Number(value) || 1));
        setPhotoFrameInterval(next);
        await saveSettings({ photo_frame_interval_minutes: next });
    }, [photoFrameIntervalEnabled]);
    const handlePhotoFrameIntervalEnabledChange = _local_SP_REACT.useCallback(async () => {
        const next = !photoFrameIntervalEnabled;
        setPhotoFrameIntervalEnabled(next);
        const ownerWindow = gamepadRootRef.current?.ownerDocument.defaultView || window;
        ownerWindow.requestAnimationFrame(() => ownerWindow.requestAnimationFrame(() => focusDefaultGamepadElement("photo-frame")));
        await saveSettings({ photo_frame_interval_enabled: next });
    }, [photoFrameIntervalEnabled]);
    const handleModuleSwitchIntervalChange = _local_SP_REACT.useCallback(async (value) => {
        if (!moduleSwitchEnabled)
            return;
        const normalized = Math.max(5, Math.min(60, Number(value) || 5));
        const next = Math.round(normalized / 5) * 5;
        setModuleSwitchInterval(next);
        await saveSettings({ module_switch_interval_minutes: next });
    }, [moduleSwitchEnabled]);
    const handleModuleSwitchEnabledChange = _local_SP_REACT.useCallback(async () => {
        const next = !moduleSwitchEnabled;
        setModuleSwitchEnabled(next);
        const ownerWindow = gamepadRootRef.current?.ownerDocument.defaultView || window;
        ownerWindow.requestAnimationFrame(() => ownerWindow.requestAnimationFrame(() => focusDefaultGamepadElement("module-switch")));
        await saveSettings({ module_switch_enabled: next });
    }, [moduleSwitchEnabled]);
    const handleSelectCustomFile = _local_SP_REACT.useCallback((path) => {
        const nextPath = path || "";
        setCustomFilePath(nextPath);
        if (nextPath)
            void setPhotoFrameSelectedFile(nextPath);
    }, []);
    _local_SP_REACT.useCallback(async (value) => {
        const next = Math.max(300, Math.min(3600, Number(value) || 300));
        setTimelineSecSt(next);
        await saveSettings({
            stay_duration: next,
        });
    }, []);
    const beginCustomOperation = _local_SP_REACT.useCallback((operation) => {
        customProgressSourceRef.current = operation;
        setCustomOperation(operation);
        setCustomOperationProgress(0);
    }, []);
    const clearCustomOperation = _local_SP_REACT.useCallback(() => {
        customProgressSourceRef.current = "";
        setCustomOperation("");
        setCustomOperationProgress(0);
    }, []);
    const handleOpenCustomActions = _local_SP_REACT.useCallback(async (path, index) => {
        customGridFocusRef.current = `custom:item:${index}`;
        clearCustomOperation();
        await handleSelectCustomFile(path);
        const ownerWindow = gamepadRootRef.current?.ownerDocument.defaultView || window;
        ownerWindow.requestAnimationFrame(() => ownerWindow.requestAnimationFrame(() => focusGamepadElementOrFallback("custom:select", customGridFocusRef.current)));
    }, [clearCustomOperation, handleSelectCustomFile]);
    const handleApplySelectedCustom = _local_SP_REACT.useCallback(async () => {
        if (!customFilePath)
            return;
        beginCustomOperation("select");
        customReturnPendingRef.current = true;
        const ok = await withSend(() => sendCustomFile(customFilePath, customTitle))();
        if (!ok)
            clearCustomOperation();
    }, [beginCustomOperation, clearCustomOperation, customFilePath, customTitle, withSend]);
    const refreshCustomAssets = _local_SP_REACT.useCallback(async (selectFirst = false) => {
        const files = await listPhotoFrameFiles();
        const normalized = Array.isArray(files) ? files : [];
        setCustomFiles(normalized);
        if (selectFirst && normalized.length > 0) {
            const nextPath = normalized[0].path;
            setCustomFilePath(nextPath);
            await setPhotoFrameSelectedFile(nextPath);
        }
        return normalized;
    }, []);
    const handleSelectPhotoFrameFolder = _local_SP_REACT.useCallback(async () => {
        setLoadingFiles(true);
        try {
            const picked = await openFilePicker(0 /* FileSelectionType.FILE */, "/home/deck/Pictures", true, true, undefined, ["jpg", "jpeg", "png", "bmp", "gif", "svg", "webp"], false, false, 1);
            const candidate = Array.isArray(picked) ? picked[0] : picked;
            const selectedPath = typeof candidate === "string"
                ? candidate
                : candidate?.realpath || candidate?.path || candidate?.directory || "";
            if (!selectedPath)
                return;
            const folderSet = await setPhotoFrameFolder(selectedPath);
            if (folderSet) {
                await refreshCustomAssets(true);
                return;
            }
            const imported = await importPhotoFrameAsset(selectedPath);
            if (!imported || !imported.path)
                throw new Error(t("folderUnavailable"));
            await refreshCustomAssets(false);
        }
        catch (error) {
            toaster.toast({ title: "JSAUX E-INK", body: formatUiText("errorMessage", { error }) });
        }
        finally {
            setLoadingFiles(false);
        }
    }, [refreshCustomAssets]);
    const handleDeleteCustomFile = _local_SP_REACT.useCallback(async () => {
        const deletedPath = customFilePath;
        if (!deletedPath)
            return;
        const deletedIndex = customFiles.findIndex((file) => file.path === deletedPath);
        beginCustomOperation("delete");
        try {
            if (!await excludePhotoFrameFile(deletedPath)) {
                toaster.toast({ title: "JSAUX E-INK", body: t("deleteFailed") });
                clearCustomOperation();
                return;
            }
            setCustomOperationProgress(50);
            setCustomFilePath("");
            const normalized = await refreshCustomAssets(false);
            setCustomOperationProgress(100);
            finishCustomOperationAfterPaint();
            const nextIndex = normalized.length > 0 ? Math.max(0, Math.min(deletedIndex, normalized.length - 1)) : -1;
            customGridFocusRef.current = nextIndex >= 0 ? `custom:item:${nextIndex}` : "custom:upload";
            const ownerWindow = gamepadRootRef.current?.ownerDocument.defaultView || window;
            ownerWindow.requestAnimationFrame(() => ownerWindow.requestAnimationFrame(() => focusGamepadElementOrFallback(customGridFocusRef.current, "custom:upload")));
        }
        catch (error) {
            clearCustomOperation();
            toaster.toast({ title: "JSAUX E-INK", body: formatUiText("errorMessage", { error }) });
        }
    }, [beginCustomOperation, clearCustomOperation, customFilePath, customFiles, handleSelectCustomFile, refreshCustomAssets]);
    const handleLoadFiles = _local_SP_REACT.useCallback(async (selectFirst = false) => {
        setLoadingFiles(true);
        try {
            await refreshCustomAssets(selectFirst);
        }
        catch (error) {
            toaster.toast({ title: "JSAUX E-INK", body: formatUiText("errorMessage", { error }) });
        }
        finally {
            setLoadingFiles(false);
        }
    }, [refreshCustomAssets]);
    const currentModuleSwitchIdx = Math.max(0, MODULE_SWITCH_OPTIONS.findIndex((opt) => opt.value === Number(moduleSwitchInterval)));
    const handleToggle = connected ? handleDisconnect : handleScan;
    const sendLayoutModule = async (m) => {
        let ok = false;
        if (m.mode === "carousel")
            ok = await sendDashboardFn();
        else if (m.mode === "clock")
            ok = await sendClockFn();
        else if (m.mode === "weather")
            ok = await sendWeatherFn(0, 0);
        else
            ok = await sendModuleFn(m.id);
        return ok;
    };
    const handleGameTimeDisplayModeSelect = async (nextMode) => {
        if (!GAME_TIME_DISPLAY_MODES.includes(nextMode))
            return;
        setGameTimeDisplayMode(nextMode);
        await saveSettings({ game_time_display_mode: nextMode });
        selectedPanelRef.current = "layout";
        setSelectedPanel("layout");
        // The UI connection flag can briefly lag behind the daemon after a
        // BLE reconnect. Refresh from the authoritative backend status so a
        // saved mode is rendered immediately instead of silently doing
        // nothing while `connected` is stale.
        const status = await getStatus();
        applyDeviceStatus(status);
        if (status?.connection_enabled && status?.address)
            await withSend(() => sendModuleFn(1))();
    };
    const handleModuleClick = async (m) => {
        if (m.mode === "timeline") {
            selectedPanelRef.current = "game-time";
            setSelectedPanel("game-time");
            const ownerWindow = gamepadRootRef.current?.ownerDocument.defaultView || window;
            ownerWindow.requestAnimationFrame(() => ownerWindow.requestAnimationFrame(() => focusGamepadElementOrFallback("game-time-mode:time", "game-time-mode:auto")));
            return;
        }
        const nextPanel = m.mode === "custom" ? "custom" : "layout";
        selectedPanelRef.current = nextPanel;
        setSelectedPanel(nextPanel);
        if (m.mode === "custom") {
            if (customFiles.length === 0) {
                await handleLoadFiles();
            }
            const ownerWindow = gamepadRootRef.current?.ownerDocument.defaultView || window;
            ownerWindow.requestAnimationFrame(() => ownerWindow.requestAnimationFrame(() => focusGamepadElementOrFallback(customGridFocusRef.current, "custom:item:0", "custom:upload")));
            return;
        }
        setModeState(m.mode);
        if (connected) {
            await withSend(() => sendLayoutModule(m))();
        }
    };
    const handleModuleSwitchIdx = async (idx) => {
        const opt = MODULE_SWITCH_OPTIONS[Math.max(0, Math.min(MODULE_SWITCH_OPTIONS.length - 1, Number(idx) || 0))];
        await handleModuleSwitchIntervalChange(opt.value);
    };
    const gamepadNavigationProps = (id, focusOnly = false, disabled = false) => ({
        className: "jsaux-gamepad-action",
        "data-gamepad-action": "true",
        "data-gamepad-id": id,
        "data-gamepad-activatable": focusOnly ? "false" : "true",
        "data-disabled": disabled ? "true" : "false",
        onFocus: () => {
            syncGamepadSemanticFocus(id);
            if (["connection-page-entry", "connection", "photo-frame", "photo-frame-toggle", "module-switch", "module-switch-toggle", "game-time"].includes(id)) {
                setSelectedPanel(["connection-page-entry", "connection"].includes(id) ? "screen" : id === "game-time" ? "game-time" : id);
            }
        },
    });
    const handleFocusCustomFile = (id, _path) => {
        // Focus is navigation-only; do not mark a second asset selected.
        syncGamepadSemanticFocus(id);
    };
    const renderGameTimeMode = () => h("div", { key: "game-time-mode", style: { display: "flex", flexDirection: "column", minHeight: "750px" }, "data-jsaux-section": "game-time-mode" }, [
        h("div", { key: "header", style: styles.header }, [
            h("button", { ...gamepadNavigationProps("game-time:back"), key: "back", type: "button", onClick: closeGameTimeModePage, style: { width: "32px", height: "32px", padding: 0, border: 0, borderRadius: "6px", background: gamepadFocusedId === "game-time:back" ? GAMEPAD_FOCUS_BACKGROUND : "transparent", color: "#eef3fb", fontSize: "28px", lineHeight: 1 } }, "‹"),
            h("span", { key: "title", style: styles.rowLabel }, GAME_TIME_MODE_TITLES[getSystemLanguage()] || GAME_TIME_MODE_TITLES.en),
        ]),
        h("div", { key: "options", style: { display: "flex", flexDirection: "column", gap: "12px", padding: "32px 24px" } }, GAME_TIME_DISPLAY_MODES.map((option) => {
            const focused = gamepadFocusedId === `game-time-mode:${option}`;
            const selected = gameTimeDisplayMode === option;
            return h("button", { ...gamepadNavigationProps(`game-time-mode:${option}`), key: option, type: "button", onClick: () => handleGameTimeDisplayModeSelect(option), style: { ...styles.screenRow(focused), minHeight: "58px", border: focused ? "1px solid #8500ff" : "1px solid rgba(255,255,255,0.12)", color: "#fff", background: focused ? "rgba(133,0,255,0.26)" : "rgba(255,255,255,0.04)", fontSize: "16px", fontWeight: selected ? 700 : 500, textAlign: "left", padding: "0 22px", cursor: "pointer" } }, `${selected ? "●" : "○"} ${(GAME_TIME_MODE_LABELS[getSystemLanguage()] || GAME_TIME_MODE_LABELS.en)[option] || option}`);
        })),
    ]);
    const renderConnectionPage = () => {
        const pageBusy = devicesScanning || !!deviceSelectionPending;
        const connectedCandidate = deviceCandidates.find((candidate) => canonicalMacAddress(candidate?.address) === confirmedConnectedMac);
        const visibleDeviceCandidates = sortConnectionCandidatesByRssi(confirmedConnectedMac
            ? [{
                ...(connectedCandidate || {}),
                name: connectedCandidate?.name || PRODUCT_NAME,
                address: confirmedConnectedMac,
                battery,
            }, ...deviceCandidates.filter((candidate) => canonicalMacAddress(candidate?.address) !== confirmedConnectedMac)]
            : deviceCandidates, confirmedConnectedMac);
        return h("div", { key: "connection-page", style: { display: "flex", flexDirection: "column", minHeight: "750px" }, "data-jsaux-section": "connection-page" }, [
            h("div", { key: "connection-page-header", style: styles.header }, [
                h("button", {
                    ...gamepadNavigationProps("connection-page-back"),
                    key: "back",
                    type: "button",
                    onClick: closeConnectionPage,
                    style: { width: "32px", height: "32px", padding: 0, border: "0", borderRadius: "6px", background: gamepadFocusedId === "connection-page-back" ? GAMEPAD_FOCUS_BACKGROUND : "transparent", color: "#eef3fb", cursor: "pointer", fontSize: "28px", lineHeight: 1 },
                }, "‹"),
                h("span", { key: "back-label", style: { ...styles.rowLabel, flex: "0 0 auto", fontSize: fitUiFontSize(preferenceText("back"), 12, 15, 10) } }, preferenceText("back")),
                h("span", { key: "title", style: { ...styles.rowLabel, flex: "1 1 auto", textAlign: "center", fontSize: fitUiFontSize(t("screenSwitch"), 15, 22, 11) } }, t("screenSwitch")),
                h("button", {
                    ...gamepadNavigationProps("connection-page-refresh", false, pageBusy),
                    key: "refresh",
                    type: "button",
                    "aria-label": t("refreshRate"),
                    onClick: refreshConnectionCandidates,
                    disabled: pageBusy,
                    style: { width: "32px", height: "32px", padding: 0, border: "0", borderRadius: "6px", background: !pageBusy && gamepadFocusedId === "connection-page-refresh" ? GAMEPAD_FOCUS_BACKGROUND : "transparent", color: "#eef3fb", cursor: pageBusy ? "not-allowed" : "pointer", fontSize: "26px", lineHeight: 1 },
                }, h$1("span", { key: "refresh-icon-rotation", style: { display: "inline-flex", animation: devicesScanning ? "jsaux-gaming-spin 0.8s linear infinite" : "none" } }, h$1(ControlIcon, { key: "refresh-icon", name: "refresh", size: 24, color: "#eef3fb", strokeWidth: 1.8 }))),
            ]),
            h("div", { key: "connection-candidates", style: { display: "flex", flexDirection: "column", flex: "1 1 auto", maxHeight: "620px", overflowY: "auto", overscrollBehavior: "contain", scrollbarWidth: "thin" } }, [
                visibleDeviceCandidates.map((candidate) => {
                    const candidateAddress = canonicalMacAddress(candidate?.address);
                    const candidateId = `connection-candidate:${candidateAddress}`;
                    const candidateBusy = deviceSelectionPending === candidateAddress;
                    const candidateConnected = candidateAddress === confirmedConnectedMac;
                    const switchingBlocked = Boolean(confirmedConnectedMac) && !candidateConnected;
                    const candidateRssi = normalizeCandidateRssi(candidate?.rssi);
                    const activeSignalBars = signalBarsForRssi(candidateRssi);
                    return h("div", { key: candidateAddress, style: { ...styles.screenRow(gamepadFocusedId === candidateId), height: "66px" } }, [
                        h("div", { key: "candidate-signal", style: { width: "44px", flex: "0 0 44px", marginLeft: "0", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "3px" } }, [
                            h("div", { key: "bars", style: { height: "24px", display: "flex", alignItems: "flex-end", gap: "2px" } }, [0, 1, 2, 3].map((index) => h("span", { key: `bar-${index}`, style: { width: "4px", height: `${7 + index * 5}px`, background: index < activeSignalBars ? "#8500ff" : "rgba(142,151,166,0.28)", display: "block" } }))),
                            h("span", { key: "rssi", style: { color: "rgba(206,214,225,0.58)", fontSize: "9px", lineHeight: 1, whiteSpace: "nowrap" } }, candidateRssi === null ? "-- dBm" : `${candidateRssi} dBm`),
                        ]),
                        h("div", { key: "candidate-details", style: { display: "flex", flexDirection: "column", justifyContent: "center", marginLeft: "16px", flex: "1 1 auto", minWidth: 0 } }, [
                            h("span", { key: "name", style: { ...styles.rowValue, fontSize: "11px", lineHeight: 1.2, fontWeight: 400, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, candidate?.name || PRODUCT_NAME),
                            h("span", { key: "address", style: { ...styles.path, fontSize: "10px", lineHeight: 1.2, whiteSpace: "nowrap" } }, candidateAddress),
                        ]),
                        h("span", { key: "battery", className: "candidate-battery", style: { ...styles.path, fontSize: "11px", marginLeft: "3ch", whiteSpace: "nowrap", flex: "0 0 auto" } }, candidate?.battery == null ? "--%" : `${Math.max(0, Math.min(100, Number(candidate.battery) || 0))}%`),
                        h("button", {
                            ...gamepadNavigationProps(candidateId, false, pageBusy || switchingBlocked),
                            key: "toggle",
                            type: "button",
                            onClick: () => selectConnectionCandidate(candidate),
                            disabled: pageBusy || switchingBlocked,
                            style: { ...styles.toggle(candidateConnected, candidateBusy), width: "36px", flex: "0 0 36px", marginLeft: "12px" },
                        }, candidateBusy ? h("span", { key: "spinner", style: styles.spinner, "aria-label": t("connecting") }) : [
                            candidateConnected ? h("span", { key: "on", style: styles.toggleText }, "ON") : null,
                            h("span", { key: "knob", style: styles.knob }),
                            !candidateConnected ? h("span", { key: "off", style: styles.toggleText }, "OFF") : null,
                        ]),
                    ]);
                }),
            ]),
        ]);
    };
    const renderGamingCustom = () => {
        const customOperationBusy = customOperation !== "" && customOperationProgress < 100;
        const focusedItem = gamepadFocusedId?.startsWith("custom:item:");
        const deleteDisabled = !customFilePath || loadingFiles || sending || customOperationBusy;
        const selectDisabled = !customFilePath || loadingFiles || sending || customOperationBusy;
        const uploadDisabled = loadingFiles || sending || customOperationBusy;
        return h("div", { key: "custom", style: styles.customArea, "data-jsaux-section": "custom" }, [
            customFiles.length > 0 ? h("div", { key: "grid", style: styles.customGrid }, customFiles.map((file, index) => h("button", {
                ...gamepadNavigationProps(`custom:item:${index}`, false, sending || customOperationBusy),
                key: file.path,
                type: "button",
                onClick: () => handleOpenCustomActions(file.path, index),
                onFocus: () => handleFocusCustomFile(`custom:item:${index}`, file.path),
                disabled: sending || customOperationBusy,
                style: styles.customCard(customFilePath === file.path, gamepadFocusedId === `custom:item:${index}`, sending || customOperationBusy, focusedItem),
            }, file.thumbnail_png_base64 ? h("img", {
                src: `data:image/png;base64,${file.thumbnail_png_base64}`,
                alt: file.name,
                draggable: false,
                style: styles.customThumbnail,
            }) : h("span", { style: styles.customThumbnailFallback }, t("thumbnail"))))) : null,
            h("div", { key: "actions", style: styles.actionBar }, [
                h("button", {
                    ...gamepadNavigationProps("custom:select", false, selectDisabled),
                    key: "select",
                    type: "button",
                    onClick: handleApplySelectedCustom,
                    disabled: selectDisabled,
                    style: styles.customSelectButton(selectDisabled, gamepadFocusedId === "custom:select"),
                }, t("apply")),
                h("button", {
                    ...gamepadNavigationProps("custom:delete", false, deleteDisabled),
                    key: "delete",
                    type: "button",
                    onClick: handleDeleteCustomFile,
                    disabled: deleteDisabled,
                    style: styles.customDeleteButton(deleteDisabled, gamepadFocusedId === "custom:delete"),
                }, t("delete")),
            ]),
            h("div", { key: "upload-area", style: customFiles.length === 0 ? styles.customEmpty : undefined }, h("button", {
                ...gamepadNavigationProps("custom:upload", false, uploadDisabled),
                key: "upload",
                type: "button",
                onClick: handleSelectPhotoFrameFolder,
                disabled: uploadDisabled,
      style: { ...styles.pillButton(gamepadFocusedId === "custom:upload", uploadDisabled, gamepadFocusedId === "custom:upload"), width: customFiles.length === 0 ? "180px" : "100%", height: "34px", borderRadius: "8px" },
            }, loadingFiles ? t("scanning") : t("upload"))),
            h("button", {
                ...gamepadNavigationProps("custom:back", false, false),
                key: "back",
                type: "button",
                onClick: closeCustomPage,
                style: { ...styles.pillButton(false, false, gamepadFocusedId === "custom:back"), alignSelf: "flex-start", minWidth: "96px" },
            }, preferenceText("back")),
            customOperation ? h("div", { key: "custom-operation-progress", style: styles.customOperationProgress }, [
                h("div", { key: "custom-operation-text", style: styles.help }, `${t(customOperation === "select" ? "apply" : "delete")} ${customOperationProgress}%`),
                h(ProgressBar, { key: "custom-operation-bar", pct: customOperationProgress }),
            ]) : null,
        ]);
    };
    return h("div", { ref: gamepadRootRef, style: styles.root, "data-ui-surface": "gaming" }, [
        h("style", { key: "gamepad-style" }, `
            @keyframes jsaux-gaming-spin{to{transform:rotate(360deg)}}
            .jsaux-gamepad-action:focus {
                outline: none;
            }
        `),
        h("div", { key: "panel", style: { ...styles.panel, minHeight: selectedPanel === "custom" ? "0" : "750px" } }, [
            !connectionPage && selectedPanel !== "custom" && selectedPanel !== "settings" ? h("div", { key: "header", style: styles.header, "data-jsaux-section": "header" }, [
                h("div", { key: "brand", style: styles.brand }, [
                    h("span", { key: "brand-icon", style: styles.brandIcon }, h(EInkMark, { size: 18, color: "#8500ff" })),
                    h("span", { key: "brand-text", style: { whiteSpace: "nowrap", fontSize: "16px" } }, PRODUCT_NAME),
                ]),
                h("span", { key: "version", style: styles.versionPill }, FIRMWARE_UI.currentVersion),
            ]) : null,
            connectionPage ? renderConnectionPage() : selectedPanel === "settings" ? renderSettingsPage() : selectedPanel === "game-time" ? renderGameTimeMode() : selectedPanel === "custom" ? renderGamingCustom() : [
                h("div", {
                    key: "screen",
                    style: styles.screenRow(gamepadFocusedId === "connection-page-entry" || gamepadFocusedId === "connection"),
                    onClick: openConnectionPage,
                }, [
                    h("div", { key: "top", style: styles.rowTop }, [
                        h("button", {
                            ...gamepadNavigationProps("connection-page-entry"),
                            key: "entry",
                            type: "button",
                            "aria-label": t("screenSwitch"),
                            onClick: (e) => {
                                e.stopPropagation();
                                openConnectionPage();
                            },
                            style: { ...styles.screenControlLabel, fontSize: fitUiFontSize(t("screenSwitch"), 16, 22, 12), flex: "1 1 auto", minWidth: 0, padding: 0, border: "0", background: "transparent", textAlign: "left", cursor: "pointer", fontFamily: "inherit", lineHeight: "inherit" },
                        }, t("screenSwitch")),
                        h("div", { key: "connection-state", style: { display: "flex", alignItems: "center", gap: "8px", flex: "0 0 auto" } }, [
                            h("div", {
                                key: "connection-entry-status",
                                "aria-label": t("connectionStatus"),
                                style: { display: "flex", alignItems: "center", gap: "6px", color: confirmedConnectedMac ? "#8500ff" : "rgba(255,255,255,0.35)", cursor: "default", pointerEvents: "none" },
                            }, [
                                h("span", { key: "dot", style: { width: "10px", height: "10px", borderRadius: "50%", background: confirmedConnectedMac ? "#8500ff" : "rgba(255,255,255,0.35)", flex: "0 0 auto" } }),
                                h("span", { key: "label", style: { ...styles.screenControlValue, fontSize: fitUiFontSize(confirmedConnectedMac ? t("connectionConnected") : t("connectionDisconnected"), 11, 10, 9), lineHeight: 1, whiteSpace: "nowrap" } }, confirmedConnectedMac ? t("connectionConnected") : t("connectionDisconnected")),
                            ]),
                            h("span", {
                                key: "connection-entry-chevron",
                                "aria-hidden": true,
                                style: { color: "#eef3fb", fontSize: "30px", lineHeight: 1, marginLeft: "4px", flex: "0 0 auto", pointerEvents: "none" },
                            }, "›"),
                        ]),
                    ]),
                ]),
                h("div", {
                    key: "photo-frame",
                    style: styles.controlRow(gamepadFocusedId === "photo-frame" || gamepadFocusedId === "photo-frame-toggle"),
                    onClick: () => setSelectedPanel("photo-frame"),
                }, [
                    h("div", { key: "top", style: styles.rowTop }, [
                        h("span", { key: "label", style: { ...styles.screenControlIntervalLabel, fontSize: fitUiFontSize(t("imageSwitchInterval"), 14, 21, 10) } }, t("imageSwitchInterval")),
                        h("span", { key: "value", style: screenControlIntervalValueStyle }, `${photoFrameInterval}${t("minutesSuffix")}`),
                        h("button", {
                            ...gamepadNavigationProps("photo-frame-toggle"),
                            "data-gamepad-navigation": "false",
                            key: "toggle",
                            type: "button",
                            onClick: (event) => { event.stopPropagation(); handlePhotoFrameIntervalEnabledChange(); },
                            style: styles.toggle(photoFrameIntervalEnabled, false),
                        }, [
                            photoFrameIntervalEnabled ? h("span", { key: "on", style: styles.screenControlToggleText }, "ON") : null,
                            h("span", { key: "knob", style: styles.knob }),
                            !photoFrameIntervalEnabled ? h("span", { key: "off", style: styles.screenControlToggleText }, "OFF") : null,
                        ]),
                    ]),
                    h(PdfRange, {
                        key: "range", id: "gaming-photo-frame-interval", min: 1, max: 60, step: 1, value: photoFrameInterval,
                        actionProps: { ...gamepadNavigationProps("photo-frame"), "data-gamepad-allow-disabled": "true" }, disabled: !photoFrameIntervalEnabled, onChange: handlePhotoFrameIntervalChange,
                    }),
                ]),
                h("div", {
                    key: "module-switch",
                    style: styles.refreshRow(gamepadFocusedId === "module-switch" || gamepadFocusedId === "module-switch-toggle"),
                    onClick: () => setSelectedPanel("module-switch"),
                }, [
                    h("div", { key: "top", style: styles.rowTop }, [
                        h("span", { key: "label", style: { ...styles.screenControlIntervalLabel, fontSize: fitUiFontSize(t("moduleSwitchInterval"), 14, 21, 10) } }, t("moduleSwitchInterval")),
                        h("span", { key: "value", style: screenControlIntervalValueStyle }, MODULE_SWITCH_OPTIONS[currentModuleSwitchIdx]?.label || `${moduleSwitchInterval}${t("minutesSuffix")}`),
                        h("button", {
                            ...gamepadNavigationProps("module-switch-toggle"),
                            "data-gamepad-navigation": "false",
                            key: "toggle",
                            type: "button",
                            onClick: (event) => { event.stopPropagation(); handleModuleSwitchEnabledChange(); },
                            style: styles.toggle(moduleSwitchEnabled, false),
                        }, [
                            moduleSwitchEnabled ? h("span", { key: "on", style: styles.screenControlToggleText }, "ON") : null,
                            h("span", { key: "knob", style: styles.knob }),
                            !moduleSwitchEnabled ? h("span", { key: "off", style: styles.screenControlToggleText }, "OFF") : null,
                        ]),
                    ]),
                    h(PdfRange, {
                        key: "module-switch-range", id: "gaming-module-switch", min: 0, max: MODULE_SWITCH_OPTIONS.length - 1, step: 1,
                        value: currentModuleSwitchIdx < 0 ? 0 : currentModuleSwitchIdx, discrete: MODULE_SWITCH_OPTIONS.length,
                        actionProps: { ...gamepadNavigationProps("module-switch"), "data-gamepad-allow-disabled": "true" }, disabled: !moduleSwitchEnabled, onChange: handleModuleSwitchIdx,
                    }),
                ]),
                h("div", { key: "modules", style: styles.moduleGrid }, MODULE_LABELS.map((m) => h("button", {
                    ...gamepadNavigationProps(`module:${m.mode}`),
                    key: m.id,
                    type: "button",
                    "data-module-mode": m.mode,
                    onClick: () => handleModuleClick(m),
                    style: styles.moduleButton(gamepadFocusedId === `module:${m.mode}`, false),
                }, [
                    h("span", { key: "icon", style: styles.moduleIcon }, h(ModuleIcon, { mode: m.mode, size: 26 })),
                    h("span", { key: "label", style: { flex: "1 1 0", minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", fontSize: fitUiFontSize(t(m.labelKey), 13, 11, 8), color: "#fff", whiteSpace: "nowrap" } }, t(m.labelKey)),
                ]))),
                sending ? h("div", { key: "sending", style: styles.progressRow }, [
                    h("div", { key: "txt", style: styles.help }, `${displayProgressState === "retrying" ? ((getSystemLanguage().startsWith("zh") || getSystemLanguage() === "schinese") ? "正在重新连接设备…" : "Reconnecting…") : displayProgressState === "starting" ? ((getSystemLanguage().startsWith("zh") || getSystemLanguage() === "schinese") ? "正在连接设备…" : "Connecting…") : t("syncing")} ${progress}%`),
                    h(ProgressBar, { key: "bar", pct: progress }),
                ]) : null,
                h("div", { key: "firmware", style: styles.firmware, "data-jsaux-section": "firmware" }, [
                    h("button", { ...gamepadNavigationProps("settings-entry"), key: "settings", type: "button", onClick: openSettingsPage,
                        style: { border: gamepadFocusedId === "settings-entry" ? "1px solid #8500ff" : "1px solid rgba(142,151,166,0.24)", borderRadius: "9px", background: gamepadFocusedId === "settings-entry" ? "linear-gradient(90deg,#6e00ff,#9400ff)" : "#0b141d", color: gamepadFocusedId === "settings-entry" ? "#fff" : "#969da7", width: "122px", maxWidth: "44%", height: "60px", fontSize: "18px", display: "flex", alignItems: "center", justifyContent: "center", gap: "10px", cursor: "pointer", overflow: "hidden" } }, [
                        h("span", { key: "icon", style: { fontSize: "27px", flex: "0 0 auto" } }, "⚙"), h("span", { key: "title", style: { minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: fitUiFontSize(preferenceText("settings"), 18, 9, 10) } }, preferenceText("settings"))]),
                    h("div", { key: "version", style: { textAlign: "right", marginLeft: "auto", minWidth: 0, flex: "1 1 auto", overflow: "hidden" } }, [
                        h("div", { key: "title", style: { ...styles.firmwareTitle, fontSize: fitUiFontSize(t("firmware"), 13, 10, 9), whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, t("firmware")),
                        h("div", { key: "number", style: { ...styles.firmwareSub, fontSize: fitUiFontSize(FIRMWARE_UI.currentVersion, 13, 10, 9), whiteSpace: "nowrap" } }, FIRMWARE_UI.currentVersion),
                        h("div", { key: "status", style: { ...styles.firmwareSub, paddingTop: "3px", fontSize: fitUiFontSize(preferenceText("unavailable"), 13, 12, 8), whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, preferenceText("unavailable")),
                    ]),
                ]),
            ],
        ]),
    ]);
};
var index = definePlugin(() => ({
    name: "JSAUX E-INK",
    titleView: h(EInkTitle, {}),
    content: h(Content, {}),
    icon: h(EInkMark, { size: 22, color: "currentColor" }),
    onDismount() { },
}));

export { index as default };
// Source: verified live bundle plus gaming_preferences.inc.js; old source map intentionally omitted.
