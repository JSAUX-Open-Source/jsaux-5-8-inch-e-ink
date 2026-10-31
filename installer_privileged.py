#!/usr/bin/env python3
"""One authenticated installation transaction; user services run as their owner."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pwd
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

APP = "jsaux-eink-display"
DAEMON = "jsaux-eink-daemon.service"
LEGACY = "jsaux-monoink-daemon.service"
DECKY = "plugin_loader.service"
RULE = Path("/etc/udev/rules.d/99-jsaux-eink-touch.rules")


def run(args, *, check=True, capture=False, timeout=90):
    return subprocess.run(
        [str(x) for x in args],
        check=check,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        timeout=timeout,
        cwd="/",
        env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
    )


class Transaction:
    def __init__(self, action, uid, package, overlay):
        if os.geteuid() != 0:
            raise RuntimeError("Administrator authorization is required.")
        caller = int(os.environ.get("PKEXEC_UID") or os.environ.get("SUDO_UID") or "0")
        if uid < 1000 or caller != uid:
            raise RuntimeError("Unable to verify the calling desktop user.")
        user = pwd.getpwuid(uid)
        self.uid, self.gid, self.name = uid, user.pw_gid, user.pw_name
        self.home = Path(user.pw_dir).resolve()
        self.action = action
        self.plugin = self.home / "homebrew/plugins" / APP
        if self.plugin.is_symlink():
            raise RuntimeError("Refusing to replace a symbolic link installation.")
        self.package = Path(package).resolve() if package else None
        self.payload = self.package / "payload" / APP if self.package else None
        self.overlay = Path(overlay).resolve() if overlay else None
        if self.overlay and (
            not self.overlay.name.startswith("jsaux-eink-runtime-")
            or self.overlay.stat().st_uid != uid
        ):
            raise RuntimeError("Invalid runtime overlay.")
        self.stage = self.plugin.with_name(f".{APP}.installing.{os.getpid()}")
        self.backup = (
            self.home
            / "homebrew/backups/jsaux-eink"
            / (APP + "-" + time.strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid()))
        )
        self.scope = None
        self.mutated = False
        self.swapped = False
        self.saved_old = False
        self.artifacts = {}
        self.service_was_active = {}

    def user(self, args, **kw):
        env = [
            f"HOME={self.home}",
            f"USER={self.name}",
            f"LOGNAME={self.name}",
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "LANG=C.UTF-8",
            f"XDG_RUNTIME_DIR=/run/user/{self.uid}",
            f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{self.uid}/bus",
        ]
        return run(
            ["/usr/bin/runuser", "-u", self.name, "--", "/usr/bin/env", "-i", *env, *args], **kw
        )

    def user_service(self, *args, **kw):
        return self.user(["/usr/bin/systemctl", "--user", *args], **kw)

    def decky(self, *args, **kw):
        if self.scope == "user":
            return self.user_service(*args, DECKY, **kw)
        if self.scope == "system":
            return run(["/usr/bin/systemctl", *args, DECKY], **kw)

    def progress(self, number, label):
        print(f"JSAUX_PROGRESS {number} {label}", flush=True)

    def verify(self):
        if sys.platform != "linux" or os.uname().machine != "x86_64":
            raise RuntimeError("This package requires SteamOS/Linux x86_64.")
        if self.user_service("cat", DECKY, check=False, capture=True).returncode == 0:
            self.scope = "user"
        elif run(["systemctl", "cat", DECKY], check=False, capture=True).returncode == 0:
            self.scope = "system"
        if self.action == "install":
            if not self.scope or not (self.home / "homebrew").is_dir():
                raise RuntimeError("Decky Loader was not found.")
            for line in (self.package / "SHA256SUMS").read_text().splitlines():
                digest, relative = line.split("  ", 1)
                path = (self.package / relative).resolve()
                if not path.is_relative_to(self.package) or not path.is_file():
                    raise RuntimeError("Invalid package manifest path.")
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise RuntimeError(f"Package checksum failed: {relative}")
            for path in self.payload.rglob("*"):
                if path.is_symlink():
                    raise RuntimeError("Payload contains an unsupported symbolic link.")
        elif not self.plugin.is_dir():
            raise RuntimeError("JSAUX E-INK is not installed.")
        print(
            f"Administrator transaction: action={
                self.action} pid={
                os.getpid()} user={
                self.name} python={
                    sys.version.split()[0]}",
            flush=True,
        )

    def artifact_paths(self):
        services = self.home / ".config/systemd/user"
        apps = self.home / ".local/share/applications"
        paths = [
            RULE,
            services / DAEMON,
            services / LEGACY,
            services / "default.target.wants" / DAEMON,
            services / "default.target.wants" / LEGACY,
            self.home / "Desktop/JSAUX E-INK.desktop",
            self.home / ".local/share/icons/hicolor/scalable/apps/jsaux-eink.svg",
            self.home / ".local/share/icons/hicolor/256x256/apps/jsaux-eink.png",
        ]
        paths += [
            apps / name
            for name in (
                "jsaux-eink.desktop",
                "jsaux-eink-uninstall.desktop",
                "jsaux-eink-desktop.desktop",
                "JSAUX E-INK.desktop",
                "jsaux-eink-display.desktop",
                "Install JSAUX E-INK.desktop",
            )
        ]
        return paths

    def snapshot(self):
        for p in self.artifact_paths():
            if p.is_symlink():
                self.artifacts[p] = ("link", os.readlink(p), p.lstat())
            elif p.exists():
                self.artifacts[p] = ("file", p.read_bytes(), p.stat())
            else:
                self.artifacts[p] = None
        for name in (DAEMON, LEGACY):
            self.service_was_active[name] = (
                self.user_service(
                    "is-active", "--quiet", name, check=False, capture=True
                ).returncode
                == 0
            )

    def stop(self):
        self.mutated = True
        self.user_service("stop", DAEMON, check=False, capture=True)
        self.user_service("disable", "--now", LEGACY, check=False, capture=True)
        self.decky("stop", check=False, capture=True)
        # Close only this user's desktop app so it cannot keep running old code.
        for proc in Path("/proc").iterdir():
            if not proc.name.isdigit():
                continue
            try:
                args = (proc / "cmdline").read_bytes().split(b"\0")
                if (
                    proc.stat().st_uid == self.uid
                    and str(self.plugin / "desktop_app.py").encode() in args
                ):
                    os.kill(int(proc.name), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                pass

    def user_dir(self, p):
        missing = []
        current = p
        while not current.exists():
            missing.append(current)
            current = current.parent
        for directory in reversed(missing):
            directory.mkdir()
            os.chown(directory, self.uid, self.gid)

    def chown_tree(self, root):
        root = Path(root)
        if not root.exists():
            return
        for item in [root, *root.rglob("*")]:
            try:
                os.chown(item, self.uid, self.gid, follow_symlinks=False)
            except FileNotFoundError:
                pass

    def write_user_file(self, path, content, mode=0o644):
        path = Path(path)
        self.user_dir(path.parent)
        path.write_text(content, encoding="utf-8")
        os.chown(path, self.uid, self.gid)
        path.chmod(mode)

    def install_user_integration(self):
        # Create user-owned services and desktop entries without child sudo calls.
        services = self.home / ".config/systemd/user"
        wants = services / "default.target.wants"
        settings = self.home / "homebrew/settings/jsaux-eink-display"
        legacy_settings = self.home / "homebrew/settings/JSAUX-E-INK"
        applications = self.home / ".local/share/applications"
        icon_dir = self.home / ".local/share/icons/hicolor/scalable/apps"
        png_icon_dir = self.home / ".local/share/icons/hicolor/256x256/apps"
        desktop_dir = self.home / "Desktop"
        for directory in (
            services,
            wants,
            settings.parent,
            applications,
            icon_dir,
            png_icon_dir,
            desktop_dir,
        ):
            self.user_dir(directory)

        # Preserve settings made by the older package, including the legacy
        # capitalized directory used by pre-V1.1.2 installations.
        if not settings.exists() and legacy_settings.is_dir():
            shutil.copytree(legacy_settings, settings)
            self.chown_tree(settings)
            config = settings / "settings.json"
            if config.is_file():
                try:
                    text = config.read_text(encoding="utf-8")
                    text = text.replace(str(legacy_settings), str(settings))
                    config.write_text(text, encoding="utf-8")
                    os.chown(config, self.uid, self.gid)
                except (OSError, UnicodeError):
                    pass
        settings.mkdir(parents=True, exist_ok=True)
        self.chown_tree(settings)

        # Migrate and remove the obsolete monoink service before enabling the
        # single canonical daemon. This is deliberately done in this root
        # transaction so the user never sees a second authorization request.
        for old in (services / LEGACY, wants / LEGACY):
            old.unlink(missing_ok=True)
        template = self.plugin / "systemd" / DAEMON
        if not template.is_file():
            raise RuntimeError("Daemon service template is missing.")
        service_text = template.read_text(encoding="utf-8").replace("@APP_ROOT@", str(self.plugin))
        self.write_user_file(services / DAEMON, service_text)

        entry = self.plugin / "installer_entry.sh"
        launcher = self.plugin / "desktop_app_launcher.sh"
        source_icon = self.plugin / "assets/jsaux-eink.svg"
        source_png = self.plugin / "assets/jsaux-eink.png"
        if not launcher.is_file() or not entry.is_file():
            raise RuntimeError("Desktop integration files are missing.")
        if source_icon.is_file():
            shutil.copy2(source_icon, icon_dir / "jsaux-eink.svg")
            os.chown(icon_dir / "jsaux-eink.svg", self.uid, self.gid)
        if source_png.is_file():
            shutil.copy2(source_png, png_icon_dir / "jsaux-eink.png")
            os.chown(png_icon_dir / "jsaux-eink.png", self.uid, self.gid)

        app_file = applications / "jsaux-eink.desktop"
        uninstall_file = applications / "jsaux-eink-uninstall.desktop"
        desktop_shortcut = desktop_dir / "JSAUX E-INK.desktop"
        app_text = f"""[Desktop Entry]
Type=Application
Version=1.0
Name=JSAUX E-INK
Comment=Desktop controller for JSAUX E-INK
Exec=/usr/bin/bash "{launcher}"
Path={self.plugin}
Icon=jsaux-eink
Terminal=false
Categories=Settings;HardwareSettings;
StartupNotify=true
X-AppVersion=V1.2
StartupWMClass=jsaux-eink
"""
        uninstall_text = f"""[Desktop Entry]
Type=Application
Version=1.0
Name=Uninstall JSAUX E-INK
Comment=Remove JSAUX E-INK from Gaming Mode and Desktop Mode
Exec=/usr/bin/bash "{entry}" uninstall "{self.plugin}"
Icon=user-trash
Terminal=true
Categories=System;
StartupNotify=false
X-AppVersion=V1.2
"""
        self.write_user_file(app_file, app_text, 0o755)
        self.write_user_file(uninstall_file, uninstall_text, 0o755)
        desktop_shortcut.write_text(app_text, encoding="utf-8")
        os.chown(desktop_shortcut, self.uid, self.gid)
        desktop_shortcut.chmod(0o755)
        # Remove stale names created by older package versions.
        for stale in (
            applications / "jsaux-eink-desktop.desktop",
            applications / "JSAUX E-INK.desktop",
            applications / "jsaux-eink-display.desktop",
            applications / "Install JSAUX E-INK.desktop",
        ):
            stale.unlink(missing_ok=True)

        self.user_service("daemon-reload")
        self.user_service("enable", "--now", DAEMON)
        for args in (["update-desktop-database", str(applications)], ["kbuildsycoca6"]):
            if shutil.which(args[0]):
                self.user(args, check=False, capture=True)

    def install(self):
        self.progress(35, "正在准备安装文件 / Preparing installation files")
        self.plugin.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(self.payload, self.stage)
        if self.overlay:
            shutil.copytree(
                self.overlay / "py_modules", self.stage / "py_modules", dirs_exist_ok=True
            )
        # Keep the single-auth entry and root worker with the installed plugin;
        # future desktop uninstallers therefore use the same transaction.
        package_entry = Path(__file__).with_name("installer_entry.sh")
        package_worker = Path(__file__).resolve()
        shutil.copy2(package_entry, self.stage / "installer_entry.sh")
        shutil.copy2(package_worker, self.stage / "installer_privileged.py")
        for p in [self.stage, *self.stage.rglob("*")]:
            os.chown(p, self.uid, self.gid)
            if p.is_file() and (p.suffix == ".sh" or p.name == "installer_privileged.py"):
                p.chmod(0o755)
        self.snapshot()
        self.stop()
        self.backup.parent.mkdir(parents=True, exist_ok=True)
        if self.plugin.exists():
            self.plugin.rename(self.backup)
            self.saved_old = True
            print(f"Previous installation backup: {self.backup}", flush=True)
        self.stage.rename(self.plugin)
        self.swapped = True
        self.progress(60, "正在安装游戏模式和桌面模式 / Installing Gaming and Desktop modes")
        RULE.parent.mkdir(parents=True, exist_ok=True)
        rule_source = self.plugin / "udev" / RULE.name
        if not rule_source.is_file():
            raise RuntimeError("Touchscreen udev rule is missing.")
        shutil.copyfile(rule_source, RULE)
        RULE.chmod(0o644)
        run(["udevadm", "control", "--reload-rules"])
        run(["udevadm", "trigger", "--subsystem-match=input"])
        self.install_user_integration()
        self.progress(85, "正在验证后台服务 / Verifying services")
        self.decky("restart")
        if self.decky("is-active", "--quiet", check=False, capture=True).returncode:
            raise RuntimeError("Decky did not start after installation.")
        # Decky unloads and reloads the plugin asynchronously.  The daemon
        # socket can therefore be unavailable briefly after restart; a single
        # immediate request incorrectly rolled back otherwise successful
        # installations at 85%.  Poll the readiness endpoint within one
        # bounded window without invoking another privileged command.
        health = None
        last_error = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:39062/v1/health", timeout=3
                ) as response:
                    candidate = json.load(response)
                if candidate.get("ready"):
                    health = candidate
                    break
                last_error = RuntimeError("daemon reported not ready")
            except Exception as error:
                last_error = error
            time.sleep(1)
        if health is None:
            raise RuntimeError(f"JSAUX daemon failed its readiness check: {last_error}")
        print("Application and plugin installed; daemon readiness verified.", flush=True)

    def uninstall(self):
        self.snapshot()
        self.stop()
        self.progress(35, "正在移除应用和插件 / Removing application and plugin")
        # Remove known integration files directly, without executing old
        # uninstallers that might contain another password prompt.
        self.user_service("disable", "--now", DAEMON, check=False, capture=True)
        for p in self.artifact_paths():
            p.unlink(missing_ok=True)
        self.backup.parent.mkdir(parents=True, exist_ok=True)
        self.plugin.rename(self.backup)
        self.saved_old = True
        self.swapped = True
        self.user_service("daemon-reload")
        self.user_service("reset-failed", DAEMON, check=False, capture=True)
        run(["udevadm", "control", "--reload-rules"])
        run(["udevadm", "trigger", "--subsystem-match=input"])
        self.decky("restart")
        for args in (
            ["update-desktop-database", str(self.home / ".local/share/applications")],
            ["kbuildsycoca6"],
        ):
            if shutil.which(args[0]):
                self.user(args, check=False, capture=True)
        print(f"Settings preserved: {self.home}/homebrew/settings/{APP}", flush=True)
        print(f"Recoverable application backup: {self.backup}", flush=True)

    def rollback(self):
        if not self.mutated:
            return
        print("Restoring previous installation after failure...", flush=True)
        self.user_service("stop", DAEMON, check=False, capture=True)
        if self.swapped and self.plugin.exists():
            shutil.rmtree(self.plugin)
        if self.saved_old and self.backup.exists():
            self.backup.rename(self.plugin)
        for p, saved in self.artifacts.items():
            p.unlink(missing_ok=True)
            if saved is None:
                continue
            kind, data, st = saved
            p.parent.mkdir(parents=True, exist_ok=True)
            if kind == "link":
                p.symlink_to(data)
            else:
                p.write_bytes(data)
                p.chmod(st.st_mode & 0o777)
            os.chown(p, st.st_uid, st.st_gid, follow_symlinks=False)
        run(["udevadm", "control", "--reload-rules"], check=False)
        self.user_service("daemon-reload", check=False, capture=True)
        for name, active in self.service_was_active.items():
            if active:
                self.user_service("start", name, check=False, capture=True)
        self.decky("restart", check=False, capture=True)

    def execute(self):
        self.verify()
        try:
            if self.action == "install":
                self.install()
            else:
                self.uninstall()
            self.progress(100, "操作完成 / Operation completed")
        except BaseException:
            self.rollback()
            raise
        finally:
            if self.stage.exists():
                shutil.rmtree(self.stage)


def main():
    if len(sys.argv) != 5 or sys.argv[1] not in ("install", "uninstall"):
        raise RuntimeError("Invalid installer arguments.")
    if os.geteuid() != 0:
        raise RuntimeError("Administrator authorization is required.")
    # No authorization cache, password file, policy change or root listener.
    with open("/run/lock/jsaux-eink-installer.lock", "w") as lock:
        os.chmod(lock.name, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another JSAUX installation is already running.")
        job = Transaction(sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4])
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(130))
        signal.signal(signal.SIGINT, lambda *_: sys.exit(130))
        job.execute()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr, flush=True)
        sys.exit(1)
