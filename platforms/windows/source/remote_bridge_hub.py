#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-tray supervisor for the Xiaomi, T1 and Hanvon remote bridges."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urlparse
import uuid
import webbrowser

from PIL import Image, ImageDraw
import psutil
import pystray

from runtime_launcher import application_root, role_command
from bridges.audio_client import AudioRouterClient, AudioRouterError


APP_NAME = "遥控器中心"
APP_ID = "RemoteBridgeHub"
APP_VERSION = "0.6.29"
DEFAULT_COMMUNITY_URL = "https://ai.2655ai.com/voice#community"
VB_CABLE_URL = "https://vb-audio.com/Cable/"
SHOW_PORT = 28690
T1_CONTROL_PORT = 30682
HANVON_CONTROL_PORT = 30683
CREATE_NO_WINDOW = 0x08000000

APPDATA = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_ID
LOG_DIR = APPDATA / "logs"
CONFIG_PATH = APPDATA / "config.json"
HUB_LOG = LOG_DIR / "hub.log"
XIAOMI_CONFIG_PATH = APPDATA / "xiaomi.json"
T1_APPDATA = Path(os.environ.get("APPDATA", str(Path.home()))) / "iPazzPortRemoteBridge"
T1_LOG_PATH = T1_APPDATA / "logs" / "bridge.log"

_LOG_LOCK = threading.Lock()
_APP_MUTEX = None
INTERNAL_ROLES = frozenset(
    {
        "audio",
        "xiaomi-worker",
        "xiaomi-hid-injector",
        "t1-worker",
        "hanvon-worker",
        "xiaomi-settings",
        "t1-settings",
        "hanvon-settings",
    }
)


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def app_log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with _LOG_LOCK:
        try:
            if HUB_LOG.exists() and HUB_LOG.stat().st_size > 3_000_000:
                backup = HUB_LOG.with_suffix(".log.1")
                if backup.exists():
                    backup.unlink()
                HUB_LOG.rename(backup)
        except OSError:
            pass
        with HUB_LOG.open("a", encoding="utf-8") as stream:
            stream.write(f"[{now_text()}] {message}\n")


def default_config() -> dict:
    return {
        "version": APP_VERSION,
        "auto_restart": True,
        "start_minimized": True,
        "community_url": DEFAULT_COMMUNITY_URL,
        "enabled": {"xiaomi": True, "t1": True, "hanvon": True},
    }


def load_config() -> dict:
    APPDATA.mkdir(parents=True, exist_ok=True)
    config = default_config()
    if CONFIG_PATH.exists():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
            config.update(loaded)
            config["enabled"] = {
                **default_config()["enabled"],
                **loaded.get("enabled", {}),
            }
        except Exception as exc:
            app_log(f"config load warning: {exc}")
    config["version"] = APP_VERSION
    config["community_url"] = validated_community_url(
        config.get("community_url")
    ) or DEFAULT_COMMUNITY_URL
    config.pop("python", None)
    save_config(config)
    return config


def save_config(config: dict) -> None:
    APPDATA.mkdir(parents=True, exist_ok=True)
    content = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    temp_path = CONFIG_PATH.with_name(
        f".{CONFIG_PATH.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, CONFIG_PATH)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def t1_control_request(op: str, timeout: float = 0.5) -> dict:
    request_id = uuid.uuid4().hex
    payload = json.dumps({"op": op, "request_id": request_id}).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(timeout)
        client.sendto(payload, ("127.0.0.1", T1_CONTROL_PORT))
        response, _ = client.recvfrom(4096)
    result = json.loads(response.decode("utf-8"))
    if result.get("request_id") != request_id:
        raise RuntimeError("T1 status response did not match the request")
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "T1 control failed"))
    return result


def hanvon_control_request(op: str, timeout: float = 0.5) -> dict:
    request_id = uuid.uuid4().hex
    payload = json.dumps({"op": op, "request_id": request_id}).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(timeout)
        client.sendto(payload, ("127.0.0.1", HANVON_CONTROL_PORT))
        response, _ = client.recvfrom(4096)
    result = json.loads(response.decode("utf-8"))
    if result.get("request_id") != request_id:
        raise RuntimeError("Hanvon status response did not match the request")
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "Hanvon control failed"))
    return result


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer.exe", str(path)])


def validated_community_url(value: object) -> str:
    candidate = str(value or "").strip()
    try:
        parsed = urlparse(candidate)
    except ValueError:
        return ""
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        return ""
    return candidate


def open_community_page(value: object = DEFAULT_COMMUNITY_URL) -> bool:
    url = validated_community_url(value)
    if not url:
        return False
    try:
        return bool(webbrowser.open(url, new=2))
    except Exception as exc:
        app_log(f"community page open warning: {exc}")
        return False


def acquire_single_instance() -> bool:
    global _APP_MUTEX
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\RemoteBridgeHub")
    if not handle:
        return True
    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(handle)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.sendto(b"SHOW", ("127.0.0.1", SHOW_PORT))
        except OSError:
            pass
        return False
    _APP_MUTEX = handle
    return True


def cleanup_legacy_processes() -> None:
    current_pid = os.getpid()
    matches: list[psutil.Process] = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if process.pid == current_pid:
                continue
            name = (process.info.get("name") or "").casefold()
            command = " ".join(process.info.get("cmdline") or []).casefold()
            dispatched_role = "--role" in command and (
                name.startswith("remotebridgehub")
                or "remote_bridge_hub.py" in command
            )
            if (
                name not in {"python.exe", "pythonw.exe"}
                and not name.startswith("hanvonpenbridge")
                and not dispatched_role
            ):
                continue
            legacy = (
                dispatched_role
                or name.startswith("hanvonpenbridge")
                or "atvv_live_bridge.py" in command
                or "vb_cable_sink.py" in command
                or "audio_router.py" in command
                or "ipazzport" in command
                or "voice_typing_hid.py" in command
                or "hanvon_headless.py" in command
            )
            if legacy:
                matches.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    for process in matches:
        try:
            for child in process.children(recursive=True):
                child.terminate()
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    if matches:
        psutil.wait_procs(matches, timeout=3.0)
        for process in matches:
            try:
                if process.is_running():
                    process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        app_log(f"legacy cleanup count={len(matches)}")


@dataclass(frozen=True)
class BridgeSpec:
    bridge_id: str
    name: str
    role: str
    arguments: tuple[str, ...] = ()
    log_path: Path | None = None


class ManagedBridge:
    def __init__(self, spec: BridgeSpec):
        self.spec = spec
        self.process: subprocess.Popen | None = None
        self.log_stream = None
        self.last_start = 0.0
        self.last_exit_code: int | None = None
        self.restart_after = 0.0

    @property
    def alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> None:
        if self.alive:
            return
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = self.spec.log_path or (LOG_DIR / f"{self.spec.bridge_id}.log")
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.log_stream = log_path.open("a", encoding="utf-8", buffering=1)
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        arguments = (
            value.replace("{parent_pid}", str(os.getpid()))
            for value in self.spec.arguments
        )
        command = role_command(self.spec.role, arguments, unbuffered=True)
        self.process = subprocess.Popen(
            command,
            cwd=str(application_root()),
            env=environment,
            stdout=self.log_stream,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )
        self.last_start = time.monotonic()
        self.last_exit_code = None
        app_log(
            f"started {self.spec.bridge_id} pid={self.process.pid} "
            f"role={self.spec.role}"
        )

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is not None and process.poll() is None:
            if self.spec.bridge_id == "t1":
                try:
                    status = t1_control_request("status", timeout=0.35)
                    if int(status.get("pid") or 0) == process.pid:
                        t1_control_request("shutdown", timeout=2.0)
                        process.wait(timeout=3.0)
                        app_log(f"graceful stop t1 pid={process.pid}")
                except Exception as exc:
                    app_log(f"graceful stop fallback t1 pid={process.pid}: {exc}")
            elif self.spec.bridge_id == "hanvon":
                try:
                    status = hanvon_control_request("status", timeout=0.35)
                    if int(status.get("pid") or 0) == process.pid:
                        hanvon_control_request("shutdown", timeout=2.0)
                        process.wait(timeout=4.0)
                        app_log(f"graceful stop hanvon pid={process.pid}")
                except Exception as exc:
                    app_log(
                        f"graceful stop fallback hanvon pid={process.pid}: {exc}"
                    )
            try:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=4.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
            except OSError:
                pass
        if process is not None:
            self.last_exit_code = process.poll()
        if self.log_stream is not None:
            try:
                self.log_stream.close()
            except OSError:
                pass
            self.log_stream = None
        app_log(f"stopped {self.spec.bridge_id} code={self.last_exit_code}")

    def restart(self) -> int:
        self.stop()
        time.sleep(0.2)
        self.start()
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError(f"{self.spec.bridge_id} failed to restart")
        return int(self.process.pid)

    def observe_exit(self) -> None:
        if self.process is None or self.process.poll() is None:
            return
        self.last_exit_code = self.process.returncode
        app_log(
            f"exited {self.spec.bridge_id} code={self.last_exit_code} "
            f"uptime={time.monotonic() - self.last_start:.1f}s"
        )
        self.process = None
        if self.log_stream is not None:
            try:
                self.log_stream.close()
            except OSError:
                pass
            self.log_stream = None
        retry_delay = (
            30.0
            if self.spec.bridge_id == "audio" and self.last_exit_code == 20
            else 3.0
        )
        self.restart_after = time.monotonic() + retry_delay


class BridgeManager:
    def __init__(self, config: dict):
        self.config = config
        t1_config = (
            Path(os.environ.get("APPDATA", str(Path.home())))
            / "iPazzPortRemoteBridge"
            / "config.json"
        )
        specs = (
            BridgeSpec(
                "xiaomi",
                "小米蓝牙遥控器 2",
                "xiaomi-worker",
                ("--config", str(XIAOMI_CONFIG_PATH)),
            ),
            BridgeSpec(
                "t1",
                "谷歌 T1",
                "t1-worker",
                (
                    "--config",
                    str(t1_config),
                    "--control-port",
                    str(T1_CONTROL_PORT),
                ),
                log_path=T1_LOG_PATH,
            ),
            BridgeSpec(
                "hanvon",
                "汉王 V60",
                "hanvon-worker",
                ("--control-port", str(HANVON_CONTROL_PORT)),
            ),
        )
        self.bridges = {
            spec.bridge_id: ManagedBridge(spec) for spec in specs
        }
        self.audio_router = ManagedBridge(
            BridgeSpec(
                "audio",
                "音频路由",
                "audio",
                ("--parent-pid", "{parent_pid}"),
            )
        )
        self.audio_client = AudioRouterClient("hub", timeout=0.25)

    def wait_for_audio_ready(self, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if not self.audio_router.alive:
                break
            try:
                self.audio_client.status()
                return True
            except (AudioRouterError, OSError) as exc:
                last_error = exc
                time.sleep(0.05)
        app_log(f"audio ready timeout: {last_error or 'router exited'}")
        return False

    def enabled(self, bridge_id: str) -> bool:
        return bool(self.config.get("enabled", {}).get(bridge_id, True))

    def set_enabled(self, bridge_id: str, enabled: bool) -> None:
        self.config.setdefault("enabled", {})[bridge_id] = bool(enabled)
        save_config(self.config)
        bridge = self.bridges[bridge_id]
        if enabled:
            bridge.start()
        else:
            bridge.stop()

    def start_enabled(self) -> None:
        try:
            self.audio_router.start()
            self.wait_for_audio_ready()
        except Exception as exc:
            app_log(f"start error audio: {exc}")
        for bridge_id, bridge in self.bridges.items():
            if self.enabled(bridge_id):
                try:
                    bridge.start()
                except Exception as exc:
                    app_log(f"start error {bridge_id}: {exc}")

    def ensure_running(self) -> None:
        self.audio_router.observe_exit()
        if (
            not self.audio_router.alive
            and self.config.get("auto_restart", True)
            and time.monotonic() >= self.audio_router.restart_after
        ):
            try:
                self.audio_router.start()
            except Exception as exc:
                self.audio_router.restart_after = time.monotonic() + 5.0
                app_log(f"auto-restart error audio: {exc}")
        for bridge_id, bridge in self.bridges.items():
            bridge.observe_exit()
            if not self.enabled(bridge_id) or bridge.alive:
                continue
            if not self.config.get("auto_restart", True):
                continue
            if time.monotonic() < bridge.restart_after:
                continue
            try:
                bridge.start()
            except Exception as exc:
                bridge.restart_after = time.monotonic() + 5.0
                app_log(f"auto-restart error {bridge_id}: {exc}")

    def restart(self, bridge_id: str) -> int:
        bridge = self.bridges[bridge_id]
        self.config.setdefault("enabled", {})[bridge_id] = True
        save_config(self.config)
        return bridge.restart()

    def restart_all(self) -> None:
        if not self.audio_router.alive:
            try:
                self.audio_router.start()
                self.wait_for_audio_ready()
            except Exception as exc:
                app_log(f"restart-all start error audio: {exc}")
        for bridge_id in self.bridges:
            if self.enabled(bridge_id):
                try:
                    self.bridges[bridge_id].restart()
                except Exception as exc:
                    app_log(f"restart error {bridge_id}: {exc}")

    def stop_all(self) -> None:
        for bridge in self.bridges.values():
            bridge.stop()
        self.audio_router.stop()

    def running_count(self) -> int:
        return sum(1 for bridge in self.bridges.values() if bridge.alive)

    def t1_runtime_status(self) -> dict:
        bridge = self.bridges["t1"]
        if not bridge.alive:
            return {"voice_active": False}
        try:
            status = t1_control_request("status", timeout=0.2)
            if int(status.get("pid") or 0) == bridge.process.pid:
                return status
        except Exception:
            pass
        return {"voice_active": False, "unavailable": True}


def bridge_toggle_label(enabled: bool) -> str:
    """Return an unambiguous label for a bridge enable toggle."""

    return "✓ 已启用" if enabled else "○ 已停用"


def audio_status_text(alive: bool, exit_code: int | None) -> str:
    if alive:
        return "语音驱动正常 · 普通按键和语音功能均可使用"
    if exit_code == 20:
        return "语音驱动未就绪 · 普通按键仍可使用 · 安装 VB-CABLE 后点“重启全部”"
    if exit_code is None:
        return "正在检测语音驱动 · 普通按键不受影响"
    return f"语音驱动异常（代码 {exit_code}）· 普通按键仍可使用"


class HubApplication:
    def __init__(self, root: tk.Tk, manager: BridgeManager):
        self.root = root
        self.manager = manager
        self.closing = False
        self.status_labels: dict[str, tk.StringVar] = {}
        self.audio_status_var = tk.StringVar(value=audio_status_text(False, None))
        self.enabled_vars: dict[str, tk.BooleanVar] = {}
        self.toggle_labels: dict[str, tk.StringVar] = {}
        self.toggle_buttons: dict[str, ttk.Button] = {}
        self.tray: pystray.Icon | None = None
        self.command_queue: queue.Queue[tuple[str, object | None]] = queue.Queue()
        self.settings_processes: list[subprocess.Popen] = []
        self._build_window()
        self._start_tray()
        self._start_control_listener()
        self.root.after(500, self._poll)

    def _build_window(self) -> None:
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("700x545")
        self.root.minsize(640, 510)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.root.configure(bg="#0f172a")

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Hub.TFrame", background="#0f172a")
        style.configure(
            "Title.TLabel",
            background="#0f172a",
            foreground="#f8fafc",
            font=("Microsoft YaHei UI", 18, "bold"),
        )
        style.configure(
            "Body.TLabel",
            background="#0f172a",
            foreground="#cbd5e1",
            font=("Microsoft YaHei UI", 10),
        )
        style.configure(
            "Card.TFrame", background="#1e293b", relief="flat"
        )
        style.configure(
            "Card.TLabel",
            background="#1e293b",
            foreground="#f8fafc",
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        style.configure(
            "Status.TLabel",
            background="#1e293b",
            foreground="#94a3b8",
            font=("Microsoft YaHei UI", 9),
        )
        style.configure(
            "ToggleOn.TButton",
            background="#16a34a",
            foreground="#ffffff",
            font=("Microsoft YaHei UI", 9, "bold"),
            padding=(10, 5),
        )
        style.map(
            "ToggleOn.TButton",
            background=[("active", "#22c55e"), ("pressed", "#15803d")],
            foreground=[("disabled", "#d1fae5")],
        )
        style.configure(
            "ToggleOff.TButton",
            background="#475569",
            foreground="#f8fafc",
            font=("Microsoft YaHei UI", 9),
            padding=(10, 5),
        )
        style.map(
            "ToggleOff.TButton",
            background=[("active", "#64748b"), ("pressed", "#334155")],
            foreground=[("disabled", "#cbd5e1")],
        )

        outer = ttk.Frame(self.root, style="Hub.TFrame", padding=20)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="一个托盘统一管理三套成熟桥接 · 全部后台无窗口运行",
            style="Body.TLabel",
        ).pack(anchor="w", pady=(3, 10))

        audio_bar = ttk.Frame(outer, style="Card.TFrame", padding=(12, 8))
        audio_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(
            audio_bar,
            textvariable=self.audio_status_var,
            style="Status.TLabel",
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            audio_bar,
            text="语音驱动帮助",
            command=lambda: webbrowser.open(VB_CABLE_URL, new=2),
        ).pack(side="right", padx=(8, 0))

        for bridge_id, bridge in self.manager.bridges.items():
            card = ttk.Frame(outer, style="Card.TFrame", padding=12)
            card.pack(fill="x", pady=4)
            name = ttk.Label(card, text=bridge.spec.name, style="Card.TLabel")
            name.grid(row=0, column=0, sticky="w")
            enabled = tk.BooleanVar(value=self.manager.enabled(bridge_id))
            self.enabled_vars[bridge_id] = enabled
            toggle_label = tk.StringVar(value=bridge_toggle_label(enabled.get()))
            self.toggle_labels[bridge_id] = toggle_label
            toggle = ttk.Button(
                card,
                textvariable=toggle_label,
                style="ToggleOn.TButton" if enabled.get() else "ToggleOff.TButton",
                command=lambda bid=bridge_id: self._toggle(bid),
            )
            self.toggle_buttons[bridge_id] = toggle
            toggle.grid(row=0, column=1, padx=8)
            ttk.Button(
                card,
                text="具体设置",
                command=lambda bid=bridge_id: self._open_settings(bid),
            ).grid(row=0, column=2, padx=(4, 0))
            ttk.Button(
                card,
                text="重启",
                command=lambda bid=bridge_id: self._restart_one(bid),
            ).grid(row=0, column=3, padx=(6, 0))
            status = tk.StringVar(value="正在启动")
            self.status_labels[bridge_id] = status
            ttk.Label(card, textvariable=status, style="Status.TLabel").grid(
                row=1, column=0, columnspan=4, sticky="w", pady=(5, 0)
            )
            card.columnconfigure(0, weight=1)

        actions = ttk.Frame(outer, style="Hub.TFrame")
        actions.pack(fill="x", pady=(14, 0))
        ttk.Button(actions, text="重启全部", command=self._restart_all).pack(
            side="left"
        )
        ttk.Button(actions, text="打开日志", command=lambda: open_folder(LOG_DIR)).pack(
            side="left", padx=8
        )
        ttk.Button(actions, text="隐藏到托盘", command=self.hide).pack(side="left")
        ttk.Button(actions, text="退出中心", command=self.exit).pack(side="right")

        community = ttk.Frame(outer, style="Card.TFrame", padding=12)
        community.pack(fill="x", pady=(14, 0))
        ttk.Label(community, text="用户社群", style="Card.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            community,
            text="安装协助、设备适配和版本更新",
            style="Status.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Button(
            community,
            text="查看微信二维码",
            command=self._open_community,
        ).grid(row=0, column=1, rowspan=2, padx=(16, 0))
        community.columnconfigure(0, weight=1)

        ttk.Label(
            outer,
            text="三套设备独立保存；语音快捷键可分别录入，不绑定任何输入法。",
            style="Body.TLabel",
        ).pack(anchor="w", pady=(16, 0))

    @staticmethod
    def _make_icon(running: int = 0) -> Image.Image:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((5, 5, 59, 59), radius=15, fill="#111827")
        colors = ["#22c55e" if i < running else "#475569" for i in range(3)]
        for index, x in enumerate((19, 32, 45)):
            draw.ellipse((x - 6, 17, x + 6, 29), fill=colors[index])
            draw.rounded_rectangle((x - 3, 29, x + 3, 46), radius=3, fill=colors[index])
        return image

    def _start_tray(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("打开遥控器中心", self.show, default=True),
            pystray.MenuItem("重启全部桥接", self._tray_restart),
            pystray.MenuItem("打开日志目录", self._tray_logs),
            pystray.MenuItem("加入用户社群", self._tray_community),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._tray_exit),
        )
        self.tray = pystray.Icon(
            APP_ID,
            self._make_icon(0),
            f"{APP_NAME} v{APP_VERSION}",
            menu,
        )
        threading.Thread(
            target=self.tray.run,
            name="remote-bridge-hub-tray",
            daemon=True,
        ).start()

    def _start_control_listener(self) -> None:
        def listen() -> None:
            server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                if os.name == "nt" and hasattr(socket, "SIO_UDP_CONNRESET"):
                    try:
                        server.ioctl(socket.SIO_UDP_CONNRESET, False)
                    except OSError:
                        pass
                server.bind(("127.0.0.1", SHOW_PORT))
                server.settimeout(0.5)
                while not self.closing:
                    try:
                        payload, peer = server.recvfrom(4096)
                    except socket.timeout:
                        continue
                    except ConnectionResetError:
                        continue
                    command = payload.decode("utf-8", errors="ignore").strip()
                    request = None
                    try:
                        parsed = json.loads(command)
                        if isinstance(parsed, dict):
                            request = parsed
                    except json.JSONDecodeError:
                        pass
                    if (
                        request is not None
                        and request.get("op") == "restart"
                        and request.get("bridge") in self.manager.bridges
                        and request.get("request_id")
                    ):
                        request_id = str(request["request_id"])
                        done = threading.Event()
                        outcome: dict[str, object] = {}
                        self.command_queue.put(
                            (
                                "restart_sync",
                                (
                                    str(request["bridge"]),
                                    request_id,
                                    done,
                                    outcome,
                                ),
                            )
                        )
                        if not done.wait(8.0):
                            outcome.update(
                                ok=False,
                                request_id=request_id,
                                error="hub timed out while restarting bridge",
                            )
                        server.sendto(json.dumps(outcome).encode("utf-8"), peer)
                    elif command == "SHOW":
                        self.command_queue.put(("show", None))
                    elif command.startswith("RESTART:"):
                        bridge_id = command.partition(":")[2].strip().lower()
                        if bridge_id in self.manager.bridges:
                            self.command_queue.put(("restart", bridge_id))
                            server.sendto(b"OK:QUEUED", peer)
                    elif command.startswith("SETTINGS:"):
                        bridge_id = command.partition(":")[2].strip().lower()
                        if bridge_id in self.manager.bridges:
                            self.command_queue.put(("settings", bridge_id))
                            server.sendto(b"OK:QUEUED", peer)
                    elif command == "EXIT":
                        self.command_queue.put(("exit", None))
            except OSError as exc:
                app_log(f"show listener warning: {exc}")
            finally:
                server.close()

        threading.Thread(target=listen, name="hub-control-listener", daemon=True).start()

    def show(self, _icon=None, _item=None) -> None:
        self.command_queue.put(("show", None))

    def _show_now(self) -> None:
        self.root.state("normal")
        self.root.deiconify()
        self.root.update_idletasks()
        self.root.lift()
        self.root.focus_force()
        try:
            self.root.attributes("-topmost", True)
            self.root.after(250, lambda: self.root.attributes("-topmost", False))
        except tk.TclError:
            pass

    def hide(self) -> None:
        self.root.withdraw()

    def _refresh_toggle(self, bridge_id: str) -> None:
        enabled = bool(self.enabled_vars[bridge_id].get())
        self.toggle_labels[bridge_id].set(bridge_toggle_label(enabled))
        self.toggle_buttons[bridge_id].configure(
            style="ToggleOn.TButton" if enabled else "ToggleOff.TButton"
        )

    def _toggle(self, bridge_id: str) -> None:
        previous = bool(self.enabled_vars[bridge_id].get())
        self.enabled_vars[bridge_id].set(not previous)
        self._refresh_toggle(bridge_id)
        try:
            self.manager.set_enabled(
                bridge_id, self.enabled_vars[bridge_id].get()
            )
        except Exception as exc:
            self.enabled_vars[bridge_id].set(previous)
            self._refresh_toggle(bridge_id)
            messagebox.showerror(APP_NAME, str(exc))

    def _open_settings(self, bridge_id: str) -> None:
        roles = {
            "xiaomi": "xiaomi-settings",
            "t1": "t1-settings",
            "hanvon": "hanvon-settings",
        }
        arguments = {
            "xiaomi": ("--hub-port", str(SHOW_PORT)),
            "t1": ("--hub-port", str(SHOW_PORT)),
            "hanvon": ("--hub-port", str(SHOW_PORT)),
        }
        try:
            self.settings_processes = [
                process
                for process in self.settings_processes
                if process.poll() is None
            ]
            process = subprocess.Popen(
                role_command(roles[bridge_id], arguments[bridge_id]),
                cwd=str(application_root()),
                creationflags=CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.settings_processes.append(process)
            app_log(f"opened settings {bridge_id} pid={process.pid}")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"无法打开{self.manager.bridges[bridge_id].spec.name}设置: {exc}")

    def _restart_one(self, bridge_id: str) -> None:
        try:
            self.manager.restart(bridge_id)
            self.enabled_vars[bridge_id].set(True)
            self._refresh_toggle(bridge_id)
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def _restart_all(self) -> None:
        try:
            self.manager.restart_all()
        except Exception as exc:
            messagebox.showerror(APP_NAME, str(exc))

    def _open_community(self) -> None:
        url = self.manager.config.get("community_url", DEFAULT_COMMUNITY_URL)
        if not open_community_page(url):
            messagebox.showinfo(
                APP_NAME,
                f"浏览器没有自动打开，请手动访问：\n{url}",
            )

    def _tray_restart(self, _icon=None, _item=None) -> None:
        self.root.after(0, self._restart_all)

    def _tray_community(self, _icon=None, _item=None) -> None:
        self.root.after(0, self._open_community)

    @staticmethod
    def _tray_logs(_icon=None, _item=None) -> None:
        open_folder(LOG_DIR)

    def _tray_exit(self, _icon=None, _item=None) -> None:
        self.root.after(0, self.exit)

    def _poll(self) -> None:
        if self.closing:
            return
        while True:
            try:
                command, payload = self.command_queue.get_nowait()
            except queue.Empty:
                break
            if command == "show":
                self._show_now()
            elif command == "restart" and isinstance(payload, str):
                try:
                    self.manager.restart(payload)
                    self.enabled_vars[payload].set(True)
                    self._refresh_toggle(payload)
                except Exception as exc:
                    app_log(f"remote restart error {payload}: {exc}")
            elif command == "restart_sync" and isinstance(payload, tuple):
                bridge_id, request_id, done, outcome = payload
                try:
                    bridge_pid = self.manager.restart(str(bridge_id))
                    outcome.update(
                        ok=True,
                        request_id=str(request_id),
                        pid=bridge_pid,
                    )
                    self.enabled_vars[str(bridge_id)].set(True)
                    self._refresh_toggle(str(bridge_id))
                    app_log(
                        f"settings restart confirmed request={request_id} "
                        f"bridge={bridge_pid}"
                    )
                except Exception as exc:
                    outcome.update(
                        ok=False,
                        request_id=str(request_id),
                        error=str(exc),
                    )
                    app_log(f"remote restart error {bridge_id}: {exc}")
                finally:
                    done.set()
            elif command == "settings" and isinstance(payload, str):
                self._open_settings(payload)
            elif command == "exit":
                self.exit()
                return
        self.manager.ensure_running()
        running = self.manager.running_count()
        self.audio_status_var.set(
            audio_status_text(
                self.manager.audio_router.alive,
                self.manager.audio_router.last_exit_code,
            )
        )
        t1_runtime = self.manager.t1_runtime_status()
        for bridge_id, bridge in self.manager.bridges.items():
            if bridge.alive:
                if bridge_id == "t1" and t1_runtime.get("voice_active"):
                    opened_ms = t1_runtime.get("voice_started_at_ms")
                    elapsed = (
                        max(0, int((time.time() * 1000 - opened_ms) / 1000))
                        if opened_ms
                        else 0
                    )
                    text = f"语音占用中 · {elapsed} 秒 · PID {bridge.process.pid}"
                elif bridge_id == "t1" and t1_runtime.get("unavailable"):
                    text = f"运行中 · 状态未响应 · PID {bridge.process.pid}"
                else:
                    text = f"运行中 · PID {bridge.process.pid}"
            elif self.manager.enabled(bridge_id):
                text = f"正在重连 · 最近退出码 {bridge.last_exit_code}"
            else:
                text = "已停用"
            self.status_labels[bridge_id].set(text)
        if self.tray:
            self.tray.icon = self._make_icon(running)
            audio_text = "音频正常" if self.manager.audio_router.alive else "音频异常"
            self.tray.title = f"{APP_NAME} · {running}/3 路运行 · {audio_text}"
        self.root.after(1000, self._poll)

    def exit(self) -> None:
        if self.closing:
            return
        self.closing = True
        for process in self.settings_processes:
            try:
                if process.poll() is None:
                    process.terminate()
            except OSError:
                pass
        self.manager.stop_all()
        if self.tray:
            self.tray.stop()
        self.root.after(100, self.root.destroy)


def run_internal_role(role: str, argv: list[str]) -> int:
    """Run one packaged worker or settings entry without starting the hub."""

    if role == "audio":
        from bridges.audio import audio_router

        return audio_router.main(argv)
    if role == "xiaomi-worker":
        from bridges.xiaomi import atvv_live_bridge

        return atvv_live_bridge.main(argv)
    if role == "xiaomi-hid-injector":
        from bridges.xiaomi import hid_tap_injector

        return hid_tap_injector.main(argv)
    if role == "t1-worker":
        from bridges.t1 import app as t1_app

        return t1_app.main(["--bridge", *argv])
    if role == "hanvon-worker":
        from bridges.hanvon import hanvon_headless

        return hanvon_headless.main(argv)
    if role == "xiaomi-settings":
        from bridges.xiaomi import xiaomi_settings

        return xiaomi_settings.main(argv)
    if role == "t1-settings":
        from bridges.t1 import app as t1_app

        return t1_app.main(["--managed-settings", *argv])
    if role == "hanvon-settings":
        from bridges.hanvon import hanvon_pen_app

        return hanvon_pen_app.main(["--managed-settings", *argv])
    raise ValueError(f"未知内部角色: {role}")


def run_internal_role_safely(role: str, argv: list[str]) -> int:
    """Keep packaged background roles from showing PyInstaller tracebacks."""

    try:
        return run_internal_role(role, argv)
    except Exception as exc:
        app_log(f"internal role failed role={role} error={type(exc).__name__}: {exc}")
        print(
            f"INTERNAL ROLE FAILED role={role} error={type(exc).__name__}: {exc}",
            flush=True,
        )
        return 70


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == ["--role"]:
        if len(arguments) < 2:
            app_log("internal role missing")
            return 2
        role = arguments[1]
        if role not in INTERNAL_ROLES:
            app_log(f"未知内部角色: {role}")
            return 2
        return run_internal_role_safely(role, arguments[2:])
    if arguments:
        app_log(f"unsupported hub arguments: {arguments!r}")
        return 2
    if not acquire_single_instance():
        return 0
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    app_log(f"{APP_NAME} v{APP_VERSION} starting")
    cleanup_legacy_processes()
    config = load_config()
    manager = BridgeManager(config)
    manager.start_enabled()

    root = tk.Tk()
    application = HubApplication(root, manager)
    if config.get("start_minimized", True):
        root.withdraw()
    else:
        application.show()
    try:
        root.mainloop()
    finally:
        if not application.closing:
            application.exit()
        app_log("hub stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
