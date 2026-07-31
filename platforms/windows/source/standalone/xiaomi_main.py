#!/usr/bin/env python3
"""Independent Xiaomi Remote 2 Pro bridge and tray host."""

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
from tkinter import ttk


APP_NAME = "MiVibe Remote"
APP_VERSION = "0.1.5"
APP_ID = "MiVibeRemote"
CONTROL_PORT = 31690

# These must be set before importing any Xiaomi or audio bridge module.
os.environ.setdefault("REMOTE_BRIDGE_XIAOMI_APP_ID", APP_ID)
os.environ.setdefault("REMOTE_BRIDGE_XIAOMI_RUNTIME_ID", APP_ID)
os.environ.setdefault("REMOTE_BRIDGE_XIAOMI_VERSION", APP_VERSION)
os.environ.setdefault("REMOTE_BRIDGE_PCM_PORT", "31680")
os.environ.setdefault("REMOTE_BRIDGE_AUDIO_CONTROL_PORT", "31681")
os.environ.setdefault("REMOTE_BRIDGE_XIAOMI_HID_TAP_PORT", "31684")
os.environ.setdefault("REMOTE_BRIDGE_RAW_INPUT_NAME", "Xiaomi Remote")
os.environ.setdefault("REMOTE_BRIDGE_RAW_INPUT_ID", "XiaomiRemoteRawInput")
os.environ.setdefault("REMOTE_BRIDGE_RAW_INPUT_OWNER", "xiaomi-mapping")

from PIL import Image, ImageDraw
import pystray

from runtime_launcher import role_command
from bridges.xiaomi.xiaomi_config import APPDATA, CONFIG_PATH, load_config


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
        return subprocess.Popen(
            role_command(role, arguments, unbuffered=True),
            cwd=str(Path(sys.executable).resolve().parent),
            stdout=stream,
            stderr=subprocess.STDOUT,
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

    def restart_bridge(self) -> None:
        with self._lock:
            self._stop(self.bridge)
            self.bridge = self._spawn(
                "xiaomi-worker",
                ["--config", str(CONFIG_PATH)],
                LOG_DIR / "bridge.log",
            )
            log(f"bridge restarted pid={self.bridge.pid}")

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
        self.root.geometry("560x330")
        self.root.minsize(520, 300)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.workers = XiaomiWorkers()
        self.settings_processes: list[subprocess.Popen] = []
        self.stop_event = threading.Event()
        self.control_socket: socket.socket | None = None
        self.tray: pystray.Icon | None = None
        self.status_var = tk.StringVar(value="正在启动")
        self.detail_var = tk.StringVar(value="")
        self._build_ui()
        self._start_tray()
        self._start_control()
        self.workers.start()
        if minimized:
            self.root.withdraw()
        self.root.after(800, self._poll)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=APP_NAME, font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text=f"v{APP_VERSION} · Windows · 独立运行",
            foreground="#666666",
        ).pack(anchor="w", pady=(2, 20))
        ttk.Label(frame, textvariable=self.status_var, font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            textvariable=self.detail_var,
            foreground="#555555",
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=(8, 24))
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="按键与语音设置", command=self.open_settings).pack(side="left")
        ttk.Button(buttons, text="重启桥接", command=self.workers.restart_bridge).pack(side="left", padx=10)
        ttk.Button(buttons, text="打开日志", command=self.open_logs).pack(side="left")
        ttk.Button(buttons, text="退出", command=self.exit).pack(side="right")
        ttk.Label(
            frame,
            text="本包不含输入法或语音识别。小米语音所需 VB-CABLE 由小米安装流程从官方地址获取。",
            foreground="#777777",
            wraplength=500,
        ).pack(anchor="w", pady=(26, 0))

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
            pystray.MenuItem("重启桥接", lambda *_: self.root.after(0, self.workers.restart_bridge)),
            pystray.MenuItem("退出", lambda *_: self.root.after(0, self.exit)),
        )
        self.tray = pystray.Icon(APP_ID, self._icon(), APP_NAME, menu)
        threading.Thread(target=self.tray.run, name="xiaomi-tray", daemon=True).start()

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
                if command in {"RESTART:xiaomi", "RESTART"}:
                    self.root.after(0, self.workers.restart_bridge)
                    response = b"OK restart"
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
        process = subprocess.Popen(
            role_command("xiaomi-settings", ["--hub-port", str(CONTROL_PORT)]),
            cwd=str(Path(sys.executable).resolve().parent),
            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        self.settings_processes.append(process)

    @staticmethod
    def open_logs() -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer", str(LOG_DIR)])

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self) -> None:
        self.root.withdraw()

    def _poll(self) -> None:
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

    def exit(self) -> None:
        self.stop_event.set()
        if self.control_socket:
            self.control_socket.close()
        for process in self.settings_processes:
            if process.poll() is None:
                process.terminate()
        self.workers.stop()
        if self.tray:
            self.tray.stop()
        self.root.after(80, self.root.destroy)


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


if __name__ == "__main__":
    raise SystemExit(main())
