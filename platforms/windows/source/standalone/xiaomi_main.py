#!/usr/bin/env python3
"""Independent Xiaomi Bluetooth Remote 2 bridge and tray host."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox
import traceback


APP_NAME = "MiVibe Remote"
APP_VERSION = "0.1.20"
APP_ID = "MiVibeRemote"
CONTROL_PORT = 31690

# These must be set before importing any Xiaomi or audio bridge module.
os.environ.setdefault("REMOTE_BRIDGE_XIAOMI_APP_ID", APP_ID)
os.environ.setdefault("REMOTE_BRIDGE_XIAOMI_RUNTIME_ID", APP_ID)
os.environ.setdefault("REMOTE_BRIDGE_XIAOMI_VERSION", APP_VERSION)
os.environ.setdefault("REMOTE_BRIDGE_PCM_PORT", "31680")
os.environ.setdefault("REMOTE_BRIDGE_AUDIO_CONTROL_PORT", "31681")
os.environ.setdefault("REMOTE_BRIDGE_XIAOMI_HID_TAP_PORT", "31684")
os.environ.setdefault("REMOTE_BRIDGE_XIAOMI_CONTROL_PORT", str(CONTROL_PORT))
os.environ.setdefault("REMOTE_BRIDGE_RAW_INPUT_NAME", "Xiaomi Remote")
os.environ.setdefault("REMOTE_BRIDGE_RAW_INPUT_ID", "XiaomiRemoteRawInput")
os.environ.setdefault("REMOTE_BRIDGE_RAW_INPUT_OWNER", "xiaomi-mapping")

from PIL import Image, ImageDraw
import pystray

from runtime_launcher import role_command
from bridges.xiaomi.xiaomi_config import APPDATA, CONFIG_PATH, load_config
from standalone.about_info import AUTHOR_LINE
from standalone.about_window import AboutWindow
from standalone.environment_check import EnvironmentCheckWindow, run_environment_check
from standalone.windows_update import MainThreadShutdownBridge, WinSparkleUpdater


LOG_DIR = APPDATA / "logs"
HOST_LOG = LOG_DIR / "host.log"
CREATE_NO_WINDOW = 0x08000000


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with HOST_LOG.open("a", encoding="utf-8") as stream:
        stream.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")


def run_internal_role(role: str, argv: list[str]) -> int:
    if role == "audio":
        from bridges.audio import audio_router

        return audio_router.main(argv)
    if role == "xiaomi-worker":
        from bridges.xiaomi import atvv_live_bridge

        return atvv_live_bridge.main(argv)
    if role == "xiaomi-settings":
        from bridges.xiaomi import xiaomi_settings

        return xiaomi_settings.main(argv)
    if role == "xiaomi-hid-injector":
        from bridges.xiaomi import hid_tap_injector

        return hid_tap_injector.main(argv)
    raise ValueError(f"小米独立包不支持内部角色：{role}")


class XiaomiWorkers:
    def __init__(self) -> None:
        self.audio: subprocess.Popen | None = None
        self.bridge: subprocess.Popen | None = None
        self._lock = threading.RLock()

    @staticmethod
    def _spawn(role: str, arguments: list[str], log_path: Path) -> subprocess.Popen:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stream = log_path.open("a", encoding="utf-8")
        child_environment = os.environ.copy()
        child_environment["PYTHONUTF8"] = "1"
        child_environment["PYTHONIOENCODING"] = "utf-8"
        return subprocess.Popen(
            role_command(role, arguments, unbuffered=True),
            cwd=str(Path(sys.executable).resolve().parent),
            stdout=stream,
            stderr=subprocess.STDOUT,
            env=child_environment,
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    @staticmethod
    def _stop(process: subprocess.Popen | None) -> None:
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2.0)

    def _wait_for_audio(self, timeout: float = 4.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.audio is None or self.audio.poll() is not None:
                return False
            request_id = f"startup-{os.getpid()}-{time.monotonic_ns()}"
            payload = json.dumps(
                {
                    "op": "status",
                    "owner": "xiaomi-launcher",
                    "client_pid": os.getpid(),
                    "request_id": request_id,
                }
            ).encode("utf-8")
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                    client.settimeout(0.25)
                    client.sendto(payload, ("127.0.0.1", 31681))
                    response, _ = client.recvfrom(4096)
                result = json.loads(response.decode("utf-8"))
                if result.get("ok") and result.get("request_id") == request_id:
                    return True
            except (OSError, UnicodeError, json.JSONDecodeError):
                time.sleep(0.1)
        return False

    def start(self) -> None:
        with self._lock:
            self.stop()
            self.audio = self._spawn(
                "audio",
                ["--parent-pid", str(os.getpid())],
                LOG_DIR / "audio.log",
            )
            if not self._wait_for_audio():
                log("audio router did not become ready before bridge start")
            self.bridge = self._spawn(
                "xiaomi-worker",
                ["--config", str(CONFIG_PATH)],
                LOG_DIR / "bridge.log",
            )
            log(f"workers started audio={self.audio.pid} bridge={self.bridge.pid}")

    def restart_bridge(self) -> int:
        with self._lock:
            self._stop(self.bridge)
            self.bridge = self._spawn(
                "xiaomi-worker",
                ["--config", str(CONFIG_PATH)],
                LOG_DIR / "bridge.log",
            )
            bridge_pid = int(self.bridge.pid)
            time.sleep(0.15)
            exit_code = self.bridge.poll()
            if exit_code is not None:
                raise RuntimeError(
                    f"bridge exited during restart pid={bridge_pid} code={exit_code}"
                )
            log(f"bridge restarted pid={bridge_pid}")
            return bridge_pid

    def stop(self) -> None:
        with self._lock:
            self._stop(self.bridge)
            self._stop(self.audio)
            self.bridge = None
            self.audio = None

    def status(self) -> dict:
        with self._lock:
            bridge_alive = self.bridge is not None and self.bridge.poll() is None
            audio_alive = self.audio is not None and self.audio.poll() is None
            bridge_code = None if self.bridge is None else self.bridge.poll()
            audio_code = None if self.audio is None else self.audio.poll()
        return {
            "bridge_alive": bridge_alive,
            "audio_alive": audio_alive,
            "bridge_code": bridge_code,
            "audio_code": audio_code,
        }


class XiaomiApp:
    def __init__(self, root: tk.Tk, minimized: bool) -> None:
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("820x540")
        self.root.minsize(760, 500)
        self.root.configure(background="#eef2f7")
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.workers = XiaomiWorkers()
        self.settings_processes: list[subprocess.Popen] = []
        self.stop_event = threading.Event()
        self._main_thread_id = threading.get_ident()
        self._update_shutdown = MainThreadShutdownBridge(log)
        self._exiting = False
        self.control_socket: socket.socket | None = None
        self.tray: pystray.Icon | None = None
        self.guide_window: tk.Toplevel | None = None
        self.status_var = tk.StringVar(value="正在启动")
        self.detail_var = tk.StringVar(value="")
        self.updater = WinSparkleUpdater(
            APP_NAME,
            APP_VERSION,
            log,
            self._request_update_shutdown,
            self._can_install_update,
        )
        self.about = AboutWindow(
            self.root,
            APP_NAME,
            APP_VERSION,
            self.check_updates,
            log,
        )
        self.environment_check = EnvironmentCheckWindow(
            self.root,
            check_provider=self._collect_environment_check,
            on_repair=self.repair_audio,
            on_restart=self.restart_workers,
            on_open_logs=self.open_logs,
        )
        self._build_ui()
        self._start_tray()
        self._start_control()
        try:
            self.workers.start()
        except Exception as exc:
            log(f"worker startup failed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
            self.status_var.set("程序已打开，但后台桥接启动失败")
            self.detail_var.set("点击“打开日志”查看原因；窗口会保留，不会静默退出。")
        if minimized:
            self.root.withdraw()
        self.root.after(1500, self._start_updater)
        self.root.after(800, self._poll)

    def _build_ui(self) -> None:
        background = "#eef2f7"
        navy = "#101b31"
        text = "#152033"
        muted = "#64748b"
        blue = "#1677ff"

        header = tk.Frame(self.root, bg=navy, padx=28, pady=22)
        header.pack(fill="x")
        title_block = tk.Frame(header, bg=navy)
        title_block.pack(side="left", fill="x", expand=True)
        tk.Label(
            title_block,
            text=APP_NAME,
            bg=navy,
            fg="white",
            font=("Microsoft YaHei UI", 20, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_block,
            text=f"小米蓝牙遥控器 2 · Windows 工作流控制台 · v{APP_VERSION}",
            bg=navy,
            fg="#aebbd0",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(4, 0))
        tk.Button(
            header,
            text="关于",
            command=self.show_about,
            relief="flat",
            bg="#1a2945",
            fg="white",
            activebackground="#263a60",
            activeforeground="white",
            padx=14,
            pady=7,
            cursor="hand2",
        ).pack(side="right")

        content = tk.Frame(self.root, bg=background, padx=20, pady=18)
        content.pack(fill="both", expand=True)

        status_card = tk.Frame(
            content,
            bg="white",
            highlightbackground="#dce3ed",
            highlightthickness=1,
            padx=20,
            pady=17,
        )
        status_card.pack(fill="x")
        status_title = tk.Frame(status_card, bg="white")
        status_title.pack(fill="x")
        tk.Label(
            status_title,
            text="运行状态",
            bg="white",
            fg=muted,
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="left")
        author_link = tk.Label(
            status_title,
            text=AUTHOR_LINE,
            bg="white",
            fg=blue,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9),
        )
        author_link.pack(side="right")
        author_link.bind("<Button-1>", lambda _event: self.show_about())
        tk.Label(
            status_card,
            textvariable=self.status_var,
            bg="white",
            fg=text,
            font=("Microsoft YaHei UI", 16, "bold"),
        ).pack(anchor="w", pady=(7, 0))
        tk.Label(
            status_card,
            textvariable=self.detail_var,
            bg="white",
            fg=muted,
            wraplength=720,
            justify="left",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(6, 0))

        primary = tk.Frame(content, bg=background)
        primary.pack(fill="x", pady=(14, 0))
        tk.Button(
            primary,
            text="按键与语音设置",
            command=self.open_settings,
            relief="flat",
            bg=blue,
            fg="white",
            activebackground="#0d5fd4",
            activeforeground="white",
            font=("Microsoft YaHei UI", 11, "bold"),
            padx=22,
            pady=12,
            cursor="hand2",
        ).pack(side="left", fill="x", expand=True)
        tk.Button(
            primary,
            text="环境检查",
            command=self.show_environment_check,
            relief="flat",
            bg="#13a76b",
            fg="white",
            activebackground="#0d8a57",
            activeforeground="white",
            font=("Microsoft YaHei UI", 11, "bold"),
            padx=22,
            pady=12,
            cursor="hand2",
        ).pack(side="left", fill="x", expand=True, padx=(12, 0))

        tools_card = tk.Frame(
            content,
            bg="white",
            highlightbackground="#dce3ed",
            highlightthickness=1,
            padx=18,
            pady=15,
        )
        tools_card.pack(fill="x", pady=(14, 0))
        tk.Label(
            tools_card,
            text="维护工具",
            bg="white",
            fg=text,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w", pady=(0, 10))
        tool_buttons = tk.Frame(tools_card, bg="white")
        tool_buttons.pack(fill="x")
        for label, command in (
            ("重启桥接", self.restart_workers),
            ("安装/修复语音驱动", self.repair_audio),
            ("使用教程", self.show_guide),
            ("检查更新", self.check_updates),
            ("打开日志", self.open_logs),
        ):
            tk.Button(
                tool_buttons,
                text=label,
                command=command,
                relief="flat",
                bg="#f2f5f9",
                fg=text,
                activebackground="#e3e9f1",
                padx=12,
                pady=8,
                cursor="hand2",
            ).pack(side="left", padx=(0, 8))

        footer = tk.Frame(content, bg=background)
        footer.pack(fill="x", pady=(14, 0))
        tk.Label(
            footer,
            text="MiVibe 不包含输入法或语音识别；遥控器声音通过 VB-CABLE 送给你选择的输入法。",
            bg=background,
            fg=muted,
            wraplength=650,
            justify="left",
            font=("Microsoft YaHei UI", 8),
        ).pack(side="left")
        tk.Button(
            footer,
            text="退出",
            command=self.exit,
            relief="flat",
            bg=background,
            fg="#cf3333",
            activebackground="#ffe8e8",
            padx=12,
            pady=6,
            cursor="hand2",
        ).pack(side="right")

    @staticmethod
    def _icon(color: str = "#2f80ed") -> Image.Image:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=15, fill="#202124")
        draw.ellipse((19, 14, 45, 40), fill=color)
        draw.rounded_rectangle((28, 35, 36, 51), radius=4, fill=color)
        return image

    def _start_tray(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("打开状态", lambda *_: self.root.after(0, self.show)),
            pystray.MenuItem("按键与语音设置", lambda *_: self.root.after(0, self.open_settings)),
            pystray.MenuItem("环境检查", lambda *_: self.root.after(0, self.show_environment_check)),
            pystray.MenuItem("使用教程", lambda *_: self.root.after(0, self.show_guide)),
            pystray.MenuItem("检查更新", lambda *_: self.root.after(0, self.check_updates)),
            pystray.MenuItem("重启桥接", lambda *_: self.root.after(0, self.workers.restart_bridge)),
            pystray.MenuItem(
                "关于 MiVibe Remote",
                lambda *_: self.root.after(0, self.show_about),
            ),
            pystray.MenuItem("退出", lambda *_: self.root.after(0, self.exit)),
        )
        self.tray = pystray.Icon(APP_ID, self._icon(), APP_NAME, menu)
        def run_tray() -> None:
            try:
                self.tray.run()
            except Exception as exc:
                log(f"tray failed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")

        threading.Thread(target=run_tray, name="xiaomi-tray", daemon=True).start()

    def _start_control(self) -> None:
        def serve() -> None:
            server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.control_socket = server
            server.bind(("127.0.0.1", CONTROL_PORT))
            server.settimeout(0.5)
            while not self.stop_event.is_set():
                try:
                    payload, peer = server.recvfrom(1024)
                except socket.timeout:
                    continue
                except OSError:
                    break
                command = payload.decode("utf-8", errors="replace").strip()
                request_id = ""
                request = None
                try:
                    parsed = json.loads(command)
                    if isinstance(parsed, dict):
                        request = parsed
                        request_id = str(parsed.get("request_id") or "")
                except json.JSONDecodeError:
                    pass
                if (
                    request is not None
                    and request.get("op") == "restart"
                    and request.get("bridge") == "xiaomi"
                    and request_id
                ):
                    try:
                        bridge_pid = self.workers.restart_bridge()
                        response = json.dumps(
                            {
                                "ok": True,
                                "request_id": request_id,
                                "pid": bridge_pid,
                            }
                        ).encode("utf-8")
                        log(
                            f"settings restart confirmed request={request_id} "
                            f"bridge={bridge_pid}"
                        )
                    except Exception as exc:
                        response = json.dumps(
                            {
                                "ok": False,
                                "request_id": request_id,
                                "error": str(exc),
                            }
                        ).encode("utf-8")
                        log(
                            f"settings restart failed request={request_id} "
                            f"error={type(exc).__name__}: {exc}"
                        )
                elif command in {"RESTART:xiaomi", "RESTART"}:
                    try:
                        bridge_pid = self.workers.restart_bridge()
                        response = f"OK restart pid={bridge_pid}".encode("ascii")
                    except Exception as exc:
                        response = f"ERROR restart {type(exc).__name__}".encode(
                            "ascii", errors="replace"
                        )
                elif command == "SHOW":
                    self.root.after(0, self.show)
                    response = b"OK show"
                else:
                    response = b"ERROR unsupported"
                try:
                    server.sendto(response, peer)
                except OSError:
                    pass
            server.close()

        threading.Thread(target=serve, name="xiaomi-control", daemon=True).start()

    def open_settings(self) -> None:
        self.settings_processes = [
            process for process in self.settings_processes if process.poll() is None
        ]
        process = subprocess.Popen(
            role_command("xiaomi-settings", ["--hub-port", str(CONTROL_PORT)]),
            cwd=str(Path(sys.executable).resolve().parent),
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.settings_processes.append(process)

    def _collect_environment_check(self):
        return run_environment_check(
            app_dir=Path(sys.executable).resolve().parent,
            config_path=CONFIG_PATH,
            log_dir=LOG_DIR,
            worker_status=self.workers.status(),
        )

    def show_environment_check(self) -> None:
        self.environment_check.show()

    @staticmethod
    def open_logs() -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(LOG_DIR)])

    def restart_workers(self) -> None:
        try:
            self.workers.start()
        except Exception as exc:
            log(f"worker restart failed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
            self.status_var.set("后台桥接启动失败")
            self.detail_var.set("主窗口会继续保留。点击“打开日志”查看具体错误。")

    def _start_updater(self) -> None:
        self.updater.initialize()

    def _can_install_update(self) -> bool:
        settings_are_open = any(
            process.poll() is None for process in self.settings_processes
        )
        return not settings_are_open and not getattr(
            self, "_audio_repair_running", False
        )

    def _request_update_shutdown(self) -> None:
        """Exit gracefully after WinSparkle launches the update installer."""

        if threading.get_ident() == self._main_thread_id:
            self.exit(for_update=True)
            return

        self._update_shutdown.request_and_wait()

    def check_updates(self) -> None:
        if not self.updater.initialized and not self.updater.initialize():
            messagebox.showinfo(
                "MiVibe Remote",
                self.updater.disabled_reason or "当前无法启动在线更新服务。",
            )
            return
        if not self.updater.check_with_ui():
            messagebox.showerror(
                "MiVibe Remote",
                "无法打开更新检查，请稍后重试或查看日志。",
            )

    def show_about(self) -> None:
        self.about.show()

    def show_guide(self) -> None:
        if self.guide_window is not None and self.guide_window.winfo_exists():
            self.guide_window.deiconify()
            self.guide_window.lift()
            self.guide_window.focus_force()
            return

        window = tk.Toplevel(self.root)
        self.guide_window = window
        window.title("MiVibe Remote 使用教程")
        window.geometry("720x650")
        window.minsize(640, 520)
        window.configure(bg="#eef2f7")
        window.protocol("WM_DELETE_WINDOW", window.withdraw)

        header = tk.Frame(window, bg="#101b31", padx=26, pady=20)
        header.pack(fill="x")
        tk.Label(
            header,
            text="使用教程",
            bg="#101b31",
            fg="white",
            font=("Microsoft YaHei UI", 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            header,
            text="第一次安装按顺序完成；以后只需要按住语音键说话。",
            bg="#101b31",
            fg="#aebbd0",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(4, 0))

        canvas = tk.Canvas(window, bg="#eef2f7", highlightthickness=0)
        scrollbar = tk.Scrollbar(window, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(fill="both", expand=True)
        body = tk.Frame(canvas, bg="#eef2f7", padx=18, pady=16)
        item = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))

        steps = (
            ("1", "连接遥控器", "先在 Windows 蓝牙设置中连接“小米蓝牙语音遥控器”。方向键能移动光标，说明基础连接成功。"),
            ("2", "运行环境检查", "点击主界面的“环境检查”。VB-CABLE 的 CABLE Input 和 CABLE Output 必须同时存在。"),
            (
                "3",
                "选择一个预设",
                "在“按键与语音设置”里选择 Codex、WorkBuddy、微信输入或千问办公；也可以点击“新增自定义”保存自己的整套配置。",
            ),
            ("4", "核对输入法快捷键", "MiVibe 的语音快捷键、触发方式必须与目标输入法一致。按住说话请选择按住型；点一次开始、再点一次结束请选择开关型。"),
            ("5", "完成一次真实测试", "把光标放进文本框，按住遥控器原生麦克风键说完整一句话，松开后等待文字出现。"),
        )
        for number, title, detail in steps:
            card = tk.Frame(
                body,
                bg="white",
                highlightbackground="#dce3ed",
                highlightthickness=1,
                padx=16,
                pady=14,
            )
            card.pack(fill="x", pady=(0, 10))
            badge = tk.Label(
                card,
                text=number,
                bg="#1677ff",
                fg="white",
                font=("Microsoft YaHei UI", 10, "bold"),
                width=3,
                pady=4,
            )
            badge.pack(side="left", anchor="n")
            copy = tk.Frame(card, bg="white")
            copy.pack(side="left", fill="x", expand=True, padx=(12, 0))
            tk.Label(
                copy,
                text=title,
                bg="white",
                fg="#152033",
                font=("Microsoft YaHei UI", 11, "bold"),
            ).pack(anchor="w")
            tk.Label(
                copy,
                text=detail,
                bg="white",
                fg="#64748b",
                font=("Microsoft YaHei UI", 9),
                justify="left",
                anchor="w",
                wraplength=570,
            ).pack(fill="x", pady=(5, 0))

        actions = tk.Frame(window, bg="#eef2f7", padx=18, pady=14)
        actions.pack(fill="x")
        tk.Button(
            actions,
            text="打开按键与语音设置",
            command=self.open_settings,
            relief="flat",
            bg="#1677ff",
            fg="white",
            activebackground="#0d5fd4",
            activeforeground="white",
            padx=18,
            pady=9,
            cursor="hand2",
        ).pack(side="left")
        tk.Button(
            actions,
            text="环境检查",
            command=self.show_environment_check,
            relief="flat",
            bg="white",
            fg="#152033",
            activebackground="#e5eaf1",
            padx=18,
            pady=9,
            cursor="hand2",
        ).pack(side="left", padx=(10, 0))

    def repair_audio(self) -> None:
        if getattr(self, "_audio_repair_running", False):
            messagebox.showinfo(
                "MiVibe Remote",
                "语音驱动安装程序已在运行，请完成现有窗口后再试。",
            )
            return
        script = Path(sys.executable).resolve().parent / "support" / "configure-xiaomi-audio.ps1"
        if not script.is_file():
            messagebox.showerror("MiVibe Remote", f"找不到语音驱动修复脚本：\n{script}")
            return
        self.status_var.set("正在打开 VB-CABLE 官方安装程序")
        self.detail_var.set("请在官方安装窗口中点击 Install，完成后重启 Windows。")
        self._audio_repair_running = True

        def run_repair() -> None:
            try:
                result = subprocess.run(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(script),
                        "-Mode",
                        "Repair",
                        "-AppPath",
                        str(Path(sys.executable).resolve().parent),
                    ],
                    cwd=str(script.parent),
                    creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
                    check=False,
                )
                log(f"audio repair exited code={result.returncode}")
            except Exception as exc:
                log(f"audio repair failed: {type(exc).__name__}: {exc}\n{traceback.format_exc()}")
            finally:
                self._audio_repair_running = False
                self.root.after(0, self.restart_workers)

        threading.Thread(target=run_repair, name="xiaomi-audio-repair", daemon=True).start()

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self) -> None:
        self.root.withdraw()

    def _poll(self) -> None:
        if self._update_shutdown.dispatch_one(
            lambda completion: self.exit(for_update=True, completion=completion)
        ):
            return

        status = self.workers.status()
        if status["bridge_alive"] and status["audio_alive"]:
            text = "按键桥接和小米语音均已运行"
            detail = "遥控器已配对后即可使用；首次完整按键接管可能出现一次 Windows 管理员确认。"
            color = "#2fa84f"
        elif status["bridge_alive"]:
            text = "普通按键已运行，语音环境未就绪"
            detail = "小米语音依赖 VB-CABLE。请从开始菜单运行“小米语音环境检查与修复”。"
            color = "#d99500"
        else:
            text = "桥接未运行"
            detail = f"进程退出码：bridge={status['bridge_code']} audio={status['audio_code']}。请打开日志检查。"
            color = "#d94141"
        self.status_var.set(text)
        self.detail_var.set(detail)
        if self.tray:
            self.tray.icon = self._icon(color)
            self.tray.title = f"{APP_NAME} · {text}"
        self.root.after(1000, self._poll)

    def exit(
        self,
        *,
        for_update: bool = False,
        completion: threading.Event | None = None,
    ) -> None:
        if self._exiting:
            if completion:
                completion.set()
            return
        self._exiting = True
        self.stop_event.set()
        if self.control_socket:
            self.control_socket.close()
        for process in self.settings_processes:
            if process.poll() is None:
                process.terminate()
        self.workers.stop()
        # Calling WinSparkle cleanup from its own shutdown callback may wait on
        # the callback and deadlock. The process unloads the DLL moments later.
        if not for_update:
            self.updater.cleanup()
        if self.tray:
            self.tray.stop()
        if for_update:
            self.root.destroy()
        else:
            self.root.after(80, self.root.destroy)
        if completion:
            completion.set()


def acquire_single_instance() -> bool:
    handle = ctypes.windll.kernel32.CreateMutexW(
        None, False, "Global\\MiVibeRemoteApp"
    )
    if ctypes.windll.kernel32.GetLastError() == 183:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.sendto(b"SHOW", ("127.0.0.1", CONTROL_PORT))
        except OSError:
            pass
        return False
    globals()["_APP_MUTEX"] = handle
    return True


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) >= 2 and arguments[0] == "--role":
        return run_internal_role(arguments[1], arguments[2:])
    parser = argparse.ArgumentParser(description=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--minimized", action="store_true")
    args = parser.parse_args(arguments)
    if not acquire_single_instance():
        return 0
    # Materialize the customer-owned config before workers and settings start.
    load_config(CONFIG_PATH)
    root = tk.Tk()
    XiaomiApp(root, args.minimized)
    root.mainloop()
    return 0


def run_with_crash_report() -> int:
    try:
        return main()
    except Exception as exc:
        details = f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        try:
            log(f"fatal application error:\n{details}")
        except Exception:
            pass
        is_background_role = len(sys.argv) >= 3 and sys.argv[1] == "--role"
        if not is_background_role and os.name == "nt":
            try:
                ctypes.windll.user32.MessageBoxW(
                    None,
                    f"MiVibe Remote 启动失败，错误已写入：\n{HOST_LOG}\n\n{type(exc).__name__}: {exc}",
                    "MiVibe Remote",
                    0x10,
                )
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    raise SystemExit(run_with_crash_report())
