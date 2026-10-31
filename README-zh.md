# JSAUX E-INK

[English](./README.md)

面向 **Steam Machine** 的 **JSAUX E-Ink Faceplate for Steam Machine** Decky 插件与 SteamOS 桌面端。

本公开仓库开源的是 **主机 App**：界面、画面渲染、本地 daemon、安装脚本与离线依赖包。  
**芯片固件 / OTA 刷写不提供**。详见 [PROPRIETARY.md](./PROPRIETARY.md)。

当前插件版本：**1.2**

公开源码唯一入口：
[github.com/JSAUX-Open-Source/JSAUX-E-INK](https://github.com/JSAUX-Open-Source/JSAUX-E-INK)

## 官方链接

- 安装指南：[jsaux.com — Steam Machine Faceplate App 安装说明](https://jsaux.com/pages/steam-machine-faceplate-app-installation-guide)
- 产品 / 售后：[jsaux.com](https://jsaux.com/)
- 问题与需求：使用 GitHub Issues（已提供模板）
- 贡献说明：[CONTRIBUTING.md](./CONTRIBUTING.md)
- 安全问题：[SECURITY.md](./SECURITY.md)（走 GitHub Private vulnerability reporting，不要发公开 Issue）

## 功能

- Game Mode（Decky）与 Desktop Mode 入口
- 时钟、天气、日历、游戏进度、性能、自定义图片等布局
- SteamOS 本地 daemon / WebSocket
- 离线天气城市目录
- 安装 / 卸载辅助脚本

## 开源了什么，没开源什么

**本仓库开源（主机 App）：**

- Game Mode / Desktop 界面（Game Mode 以预编译 `dist/` 发布；TypeScript `src/` 尚未放入本树）
- 本地渲染、daemon、SteamOS 安装辅助
- App 使用的主机侧 BLE 连接 / 查信息 / 传图代码（`eink_display.py`）
- 可选本机 Agent 布局辅助（仅 `agent_status.py`；无云端用量客户端，无本机 HTTP Agent 接收口）

**不提供：**

- 芯片固件二进制，以及芯片固件 / OTA 刷写
- 工厂侧硅片 / PCBA / 屏驱 IC 编程资料
- 云端 Codex / ChatGPT 用量客户端
- 本机 HTTP Agent 接收口（`/v1/agent/events`）、Agent bridge 局域网监听，或签发 `agent_token`

仅用本 App 树即可安装、BLE 连接、查询配件并刷图；应用内固件升级不可用。

## 运行环境

- [Steam Machine](https://store.steampowered.com/steammachine) / SteamOS，并已安装 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)
- Python 3.11+（SteamOS 自带解释器；仓库内含按 ABI 匹配的 wheel）
- BlueZ（Steam Machine / SteamOS 蓝牙栈）

## 开发者安装

改完 Python / 资源后，想在 Decky 里直接跑、又不必走完整提权安装时：

1. 在 Steam Machine / SteamOS 上确认已安装 [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader)。
2. 将本仓库（或解压后的 Release zip）拷到：

   `~/homebrew/plugins/jsaux-eink-display/`

   目录名必须是 **`jsaux-eink-display`**（与正式安装程序一致）。
3. 重启 Decky Loader（或整机重启），在 Game Mode 打开 **JSAUX E-INK**。
4. 插件日志：`~/homebrew/logs/jsaux-eink-display/`（或 Decky 为该插件生成的对应日志目录）。

普通用户安装仍请按[官方安装指南](https://jsaux.com/pages/steam-machine-faceplate-app-installation-guide)，或使用 GitHub Release 提供的 zip。

## 提权安装（会做什么）

`installer_*.sh` / `installer_privileged.py` 会通过 `pkexec`（或在无 `pkexec` 时用 `sudo`）申请 **一次** 管理员授权。Root 安装事务会：

- 安装 Decky 插件文件与 Desktop Mode 启动项
- 安装用户 systemd 单元 `jsaux-eink-daemon`（本机 WebSocket 桥）
- 安装 udev 规则，便于 Desktop Mode 使用 Steam Machine 触摸屏输入设备
- **不会** 创建或修改用户账户密码、写入密码文件，也不会留下常驻 root 监听进程

需要管理员密码时，请使用系统已有授权方式。若账户本身未设置密码，本安装程序不会替你设置密码。

## 隐私：天气定位

- 默认天气位置模式为 **`auto`**：应用可能调用 [ipwho.is](https://ipwho.is/)（首次及刷新时）根据公网 IP 估算城市/坐标。
- 若不想发起该请求：在应用里将天气位置改为 **手动**，并从离线城市目录/搜索中选择城市（`weather_location_mode=manual`）。
- 预报与地理编码使用 [Open-Meteo](https://open-meteo.com/)（CC BY 4.0）。全屏天气布局显示 **Open-Meteo** 署名；另见 [THIRD_PARTY_LICENSES.md](./THIRD_PARTY_LICENSES.md)。
- **商用：** Open-Meteo 免费接口通常限非商业用途——量产/商用前请法务确认合适套餐与条款；ipwho.is 条款请一并确认。

## 目录概览

| 路径 | 作用 |
|------|------|
| `main.py` | Decky 后端、渲染与连接编排 |
| `desktop_app.py` | 桌面模式 Tk 界面 |
| `eink_display.py` | App 使用的主机侧 BLE 连接与传图代码（不含芯片 OTA） |
| `eink_daemon.py` / `daemon_client.py` | 本地 daemon 与客户端 |
| `dist/` | 预编译 Game Mode UI |
| `py_modules/` / `runtime_wheels/` | 内嵌 Python 依赖 / wheel |
| `installer_*.sh` / `install_steamos_*.sh` / `udev/` / `systemd/` | SteamOS 安装辅助与主机规则/服务 |
| `pack_plugin_release.sh` | 打包可手动安装的 Release zip |

## 开发说明

- 本快照以预编译 `dist/index.js` 发布 Game Mode UI（TypeScript 应用源码尚未放入本树）。`npm run build` / `watch` 会提示后退出；请使用随仓库附带的 `dist/`。
- 用 `npm test`（`tests/` 下 unittest）做检查。请优先在 Steam Machine / SteamOS 上跑。
- 不要打乱 `main.py` / `eink_daemon.py` 顶部的 `sys.path` 引导。
- 天气城市数据许可见 `assets/weather-cities-LICENSE.txt`。
- 第三方声明见 [THIRD_PARTY_LICENSES.md](./THIRD_PARTY_LICENSES.md)。

## Release

维护者会在 GitHub Releases（例如 `v1.2`）上传 zip，解压到 `~/homebrew/plugins/jsaux-eink-display/` 即可试用。从干净树本地打包：

```bash
./pack_plugin_release.sh
```

## 许可证

本开源树采用 [MIT License](./LICENSE)。

**JSAUX** 及相关标识为商标；MIT 不授予商标权。

[PROPRIETARY.md](./PROPRIETARY.md) 中列出的不可用组件不随本仓库分发。
