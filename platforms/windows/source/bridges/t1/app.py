#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
import uuid

try:
    import pystray
    from PIL import Image, ImageDraw
except Exception:
    pystray = None
    Image = None
    ImageDraw = None


APP_NAME = "iPazzPort遥控器桥接"
APP_ID = "iPazzPortRemoteBridge"
APP_VERSION = os.environ.get("REMOTE_BRIDGE_T1_VERSION", "1.6.4-managed")
DEFAULT_HUB_PORT = 28690
T1_CONTROL_PORT = int(os.environ.get("REMOTE_BRIDGE_T1_CONTROL_PORT", "30682"))

ROOT = Path(__file__).resolve().parent
from bridges.shortcut_capture import KeyboardShortcutCapture
from runtime_launcher import role_command
APPDATA = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_ID
CONFIG_PATH = APPDATA / "config.json"
LOG_DIR = APPDATA / "logs"
BRIDGE_LOG = LOG_DIR / "bridge.log"
LEARN_LOG = LOG_DIR / "learn_events.jsonl"
PANEL_LOG = LOG_DIR / "panel.log"
BUNDLED_CONFIG = ROOT / "config.json"

CREATE_NO_WINDOW = 0x08000000

BG = "#f5f5f7"
CARD = "#ffffff"
TEXT = "#1d1d1f"
MUTED = "#6e6e73"
BORDER = "#d2d2d7"
BLUE = "#007aff"
BLUE_DARK = "#0062cc"

REMOTE_BUTTONS = [
    {"id": "power", "label": "电源", "short": "电源", "x": 198, "y": 36, "w": 36, "h": 36, "round": True},
    {"id": "up", "label": "上", "short": "上", "x": 122, "y": 96, "w": 64, "h": 48},
    {"id": "left", "label": "左", "short": "左", "x": 80, "y": 144, "w": 58, "h": 58},
    {"id": "ok", "label": "确定", "short": "确定", "x": 132, "y": 146, "w": 50, "h": 50, "round": True},
    {"id": "right", "label": "右", "short": "右", "x": 176, "y": 144, "w": 58, "h": 58},
    {"id": "down", "label": "下", "short": "下", "x": 122, "y": 198, "w": 64, "h": 48},
    {"id": "delete", "label": "删除", "short": "删除", "x": 78, "y": 278, "w": 66, "h": 44},
    {"id": "voice", "label": "话筒", "short": "语音", "x": 164, "y": 278, "w": 66, "h": 44, "accent": True},
    {"id": "mute", "label": "静音", "short": "静音", "x": 78, "y": 348, "w": 66, "h": 48},
    {"id": "home", "label": "主页", "short": "主页", "x": 164, "y": 348, "w": 66, "h": 48},
    {"id": "mouse", "label": "鼠标", "short": "鼠标", "x": 78, "y": 408, "w": 66, "h": 48},
    {"id": "menu", "label": "菜单", "short": "菜单", "x": 164, "y": 408, "w": 66, "h": 48},
    {"id": "volume_up", "label": "音量+", "short": "音+", "x": 254, "y": 162, "w": 28, "h": 90, "side": True},
    {"id": "volume_down", "label": "音量-", "short": "音-", "x": 254, "y": 266, "w": 28, "h": 90, "side": True},
]

HOTKEY_TOKEN_MAP = {
    "cmd": "win",
    "command": "win",
    "win": "win",
    "windows": "win",
    "ctrl": "ctrl",
    "control": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "option": "alt",
    "leftalt": "leftalt",
    "rightalt": "rightalt",
    "space": "space",
    "enter": "enter",
    "return": "enter",
    "esc": "esc",
    "escape": "esc",
    "delete": "delete",
    "backspace": "backspace",
    "minus": "minus",
    "-": "minus",
    "左alt": "leftalt",
    "右alt": "rightalt",
    "左ctrl": "leftctrl",
    "右ctrl": "rightctrl",
    "左shift": "leftshift",
    "右shift": "rightshift",
    "左win": "leftwin",
    "右win": "rightwin",
    "空格键": "space", "空格键（space）": "space",
    "回车键": "enter", "回车键（enter）": "enter",
    "退出键": "esc", "退出键（esc）": "esc",
    "删除键": "delete", "删除键（delete）": "delete",
    "退格键": "backspace", "退格键（backspace）": "backspace",
    "制表键": "tab", "制表键（tab）": "tab",
    "起始键": "home", "起始键（home）": "home",
    "结束键": "end", "结束键（end）": "end",
    "上翻页键": "pageup", "上翻页键（pageup）": "pageup",
    "下翻页键": "pagedown", "下翻页键（pagedown）": "pagedown",
    "左方向键": "left", "左方向键（left）": "left",
    "右方向键": "right", "右方向键（right）": "right",
    "上方向键": "up", "上方向键（up）": "up",
    "下方向键": "down", "下方向键（down）": "down",
}

KEY_DISPLAY = {
    "win": "Win",
    "ctrl": "Ctrl",
    "shift": "Shift",
    "alt": "Alt",
    "leftalt": "左 Alt",
    "rightalt": "右 Alt",
    "leftctrl": "左 Ctrl",
    "rightctrl": "右 Ctrl",
    "leftshift": "左 Shift",
    "rightshift": "右 Shift",
    "leftwin": "左 Win",
    "rightwin": "右 Win",
    "space": "空格键（Space）",
    "enter": "回车键（Enter）",
    "esc": "退出键（Esc）",
    "delete": "删除键（Delete）",
    "backspace": "退格键（Backspace）",
    "tab": "制表键（Tab）",
    "home": "起始键（Home）",
    "end": "结束键（End）",
    "pageup": "上翻页键（Page Up）",
    "pagedown": "下翻页键（Page Down）",
    "left": "左方向键（Left）",
    "right": "右方向键（Right）",
    "up": "上方向键（Up）",
    "down": "下方向键（Down）",
    "minus": "-",
}

ACTION_LABELS = {
    "保持原样": "none",
    "语音输入": "push_to_talk",
    "快捷键": "hotkey",
    "单键": "key",
    "输入文本": "text",
}
ACTION_KIND_LABELS = {v: k for k, v in ACTION_LABELS.items()}
ACTION_KIND_LABELS["none"] = "保持原样"
ACTION_KIND_LABELS["hotkey_down"] = "语音输入"

KEY_VALUES = [
    *[f"F{i}" for i in range(1, 25)],
    *list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
    *[str(i) for i in range(10)],
    "回车键（Enter）",
    "退出键（Esc）",
    "空格键（Space）",
    "制表键（Tab）",
    "退格键（Backspace）",
    "删除键（Delete）",
    "起始键（Home）",
    "结束键（End）",
    "上翻页键（Page Up）",
    "下翻页键（Page Down）",
    "左方向键（Left）",
    "右方向键（Right）",
    "上方向键（Up）",
    "下方向键（Down）",
    "-",
    "=",
    "左 Alt",
    "右 Alt",
]


def log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with PANEL_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"配置根节点必须是对象: {path}")
    return data


def validate_config(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("配置根节点必须是对象")
    for key in ("button_aliases", "button_bindings", "bindings"):
        if key in data and not isinstance(data[key], dict):
            raise ValueError(f"配置字段 {key} 必须是对象")
    if "device_match" in data and not isinstance(data["device_match"], list):
        raise ValueError("配置字段 device_match 必须是数组")


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with temp_path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def save_json(path: Path, data: dict) -> None:
    validate_config(data)
    content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    _atomic_write_text(path, content)
    last_good = path.with_name(f"{path.stem}.last-good{path.suffix}")
    _atomic_write_text(last_good, content)


def ensure_config() -> None:
    APPDATA.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    bundled = load_json(BUNDLED_CONFIG)
    cfg = bundled
    if CONFIG_PATH.exists():
        try:
            cfg = load_json(CONFIG_PATH)
            validate_config(cfg)
        except Exception as exc:
            corrupt = CONFIG_PATH.with_name(
                f"config.corrupt-{time.strftime('%Y%m%d-%H%M%S')}.json"
            )
            try:
                shutil.copy2(CONFIG_PATH, corrupt)
            except OSError:
                pass
            last_good = CONFIG_PATH.with_name(
                f"{CONFIG_PATH.stem}.last-good{CONFIG_PATH.suffix}"
            )
            try:
                cfg = load_json(last_good)
                validate_config(cfg)
                log(f"配置损坏，已回退到 last-good: {exc}")
            except Exception:
                cfg = bundled
                log(f"配置损坏，已回退到内置安全配置: {exc}")
    cfg.setdefault("button_aliases", {})
    for key, value in bundled.get("button_aliases", {}).items():
        cfg["button_aliases"].setdefault(key, value)
    cfg.setdefault("button_bindings", {})
    voice_actions = cfg["button_bindings"].get("voice", [])
    if isinstance(voice_actions, dict):
        voice_actions = [voice_actions]
    voice_states = set()
    for action in voice_actions if isinstance(voice_actions, list) else []:
        if action.get("type") == "hotkey_down":
            action.setdefault("audio_source", "Mic Device")
            action.setdefault("audio_tail_ms", 120)
            action.setdefault("audio_release_mode", "signal_end")
            action.setdefault("audio_trigger_mode", "toggle_hotkey")
            voice_states.add(str(action.get("state_id") or ""))
    for actions in cfg.get("bindings", {}).values():
        if isinstance(actions, dict):
            actions = [actions]
        for action in actions if isinstance(actions, list) else []:
            if action.get("type") == "hotkey_up" and str(action.get("state_id") or "") in voice_states:
                action.setdefault("audio_source", "Mic Device")
                action.setdefault("audio_tail_ms", 120)
                action.setdefault("audio_release_mode", "signal_end")
                action.setdefault("audio_trigger_mode", "toggle_hotkey")
    enabled, keys, mode = voice_settings(cfg)
    apply_voice_settings(cfg, enabled, keys, mode)
    cfg["learn_log"] = "logs/learn_events.jsonl"
    cfg["action_log"] = "logs/action_events.jsonl"
    save_json(CONFIG_PATH, cfg)


def voice_settings(cfg: dict) -> tuple[bool, list[str], str]:
    actions = cfg.get("button_bindings", {}).get("voice", [])
    action = first_action(actions)
    keys = list(cfg.get("voice_hotkey", []))
    if not keys and action and action.get("type") in {"hotkey", "hotkey_down"}:
        keys = list(action.get("keys", []))
    if not keys:
        keys = ["rightalt"]
    raw_mode = "toggle"
    enabled = bool(cfg.get("voice_shortcut_enabled", bool(action)))
    return enabled, keys, raw_mode


def apply_voice_settings(cfg: dict, enabled: bool, keys: list[str], mode: str) -> None:
    # T1 only exposes a ~120 ms HID pulse even during a long physical press.
    # Keep the target hotkey held between the first and second voice-button press.
    mode = "toggle"
    cfg["voice_shortcut_enabled"] = bool(enabled)
    cfg["voice_hotkey"] = list(keys)
    cfg["voice_trigger_mode"] = mode
    button_bindings = cfg.setdefault("button_bindings", {})
    release_bindings = cfg.setdefault("bindings", {})
    if not enabled or not keys:
        button_bindings.pop("voice", None)
        release_bindings.pop("hid:02-00-00", None)
        return
    trigger_mode = "toggle_hotkey"
    release_mode = "second_press"
    state_id = "voice_input_shortcut"
    button_bindings["voice"] = [
        {
            "type": "hotkey_down",
            "keys": list(keys),
            "state_id": state_id,
            "audio_source": "Mic Device",
            "audio_tail_ms": 120,
            "audio_release_mode": release_mode,
            "audio_release_min_hold_ms": 1500,
            "audio_release_silence_ms": 3000,
            "audio_signal_start_timeout_ms": 8000,
            "audio_max_hold_ms": 300000,
            "audio_trigger_mode": trigger_mode,
            "second_press_stops": True,
        },
        {"type": "log", "message": f"voice -> {format_keys(keys)}"},
    ]
    release_bindings.pop("hid:02-00-00", None)


def t1_control_request(op: str, timeout: float = 0.5) -> dict:
    request_id = uuid.uuid4().hex
    payload = json.dumps(
        {"op": op, "request_id": request_id},
        ensure_ascii=False,
    ).encode("utf-8")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(timeout)
        client.sendto(payload, ("127.0.0.1", T1_CONTROL_PORT))
        response, _ = client.recvfrom(4096)
    result = json.loads(response.decode("utf-8"))
    if result.get("request_id") != request_id:
        raise RuntimeError("T1 状态响应与请求不匹配")
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "T1 控制失败"))
    return result


def bridge_command(extra: list[str]) -> list[str]:
    return role_command("t1-worker", extra, unbuffered=True)


def run_bridge_main(argv: list[str]) -> int:
    from . import bridge_core

    return bridge_core.main(argv)


def normalize_key(raw: str) -> str:
    value = raw.strip().lower().replace(" ", "")
    if value in HOTKEY_TOKEN_MAP:
        return HOTKEY_TOKEN_MAP[value]
    if len(value) == 1 and value.isprintable():
        return value
    if value.startswith("f") and value[1:].isdigit():
        return value
    return value


def parse_keys(value: str) -> list[str]:
    return [key for key in (normalize_key(part) for part in value.split("+")) if key]


def format_keys(keys: list[str]) -> str:
    parts = []
    for key in keys:
        raw = str(key).lower()
        parts.append(KEY_DISPLAY.get(raw, raw.upper() if len(raw) == 1 else raw))
    return "+".join(parts)


def first_action(actions) -> dict | None:
    if isinstance(actions, dict):
        actions = [actions]
    if not isinstance(actions, list):
        return None
    for action in actions:
        if isinstance(action, dict) and action.get("type") != "log":
            return action
    return None


def action_label(actions) -> str:
    action = first_action(actions)
    if not action:
        return "未设置"
    kind = action.get("type")
    if kind == "hotkey":
        return format_keys(action.get("keys", []))
    if kind == "hotkey_down":
        if action.get("audio_trigger_mode") == "toggle_hotkey":
            return "语音开关 " + format_keys(action.get("keys", []))
        return "按住 " + format_keys(action.get("keys", []))
    if kind == "key":
        return format_keys([action.get("key", "")])
    if kind == "text":
        return "文本"
    return kind or "动作"


def button_runtime_supported(cfg: dict, button_id: str) -> bool:
    aliases = cfg.get("button_aliases", {}).get(button_id, [])
    if isinstance(aliases, str):
        aliases = [aliases]
    for event_id in aliases if isinstance(aliases, list) else []:
        event_id = str(event_id).lower()
        if event_id.startswith("hid:") and cfg.get("listen_consumer", True):
            return True
        if event_id.startswith("kbd:") and cfg.get("listen_keyboard", False):
            return True
        if event_id.startswith("mouse:") and cfg.get("listen_mouse", False):
            return True
    return False


def split_event_ids(value: str) -> list[str]:
    result = []
    for item in value.replace(",", "\n").splitlines():
        item = item.strip()
        if item:
            result.append(item)
    return result


def rounded_rect(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs):
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=12, **kwargs)


class BridgeProcess:
    def __init__(self):
        self.process: subprocess.Popen | None = None
        self.mode = "stopped"
        self.message = "未启动"
        self._lock = threading.Lock()

    def status(self) -> dict:
        with self._lock:
            alive = self.process is not None and self.process.poll() is None
            if self.process is not None and not alive and self.mode != "stopped":
                self.message = f"{self.mode} 已退出"
                self.mode = "stopped"
            result = {
                "alive": alive,
                "mode": self.mode,
                "pid": self.process.pid if alive and self.process else "",
                "message": self.message,
            }
        if alive:
            try:
                runtime = t1_control_request("status", timeout=0.2)
                if int(runtime.get("pid") or 0) == int(result["pid"]):
                    result.update(runtime)
            except Exception:
                pass
        return result

    def start(self, learn: bool = False) -> None:
        with self._lock:
            self._stop_locked()
            mode = "learning" if learn else "running"
            log_path = LEARN_LOG if learn else BRIDGE_LOG
            args = ["--config", str(CONFIG_PATH)]
            if learn:
                args.extend(["--learn", "--verbose"])
            cmd = bridge_command(args)
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            log_file = log_path.open("a", encoding="utf-8")
            self.process = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self.mode = mode
            self.message = "学习中" if learn else "已运行"
            log(f"started {mode} pid={self.process.pid}")

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()
            self.mode = "stopped"
            self.message = "已停止"

    def _stop_locked(self) -> None:
        if self.process is None:
            return
        if self.process.poll() is None:
            try:
                status = t1_control_request("status", timeout=0.35)
                if int(status.get("pid") or 0) == self.process.pid:
                    t1_control_request("shutdown", timeout=2.0)
                    self.process.wait(timeout=3.0)
            except Exception:
                pass
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
        self.process = None

    def stop_voice(self) -> bool:
        try:
            result = t1_control_request("stop_voice", timeout=2.0)
            self.message = "T1 语音已结束"
            return bool(result.get("stopped"))
        except Exception as exc:
            self.message = f"结束语音失败: {exc}"
            return False


class ManagedBridgeProxy:
    """Restart only the T1 role owned by Remote Bridge Hub."""

    def __init__(self, hub_port: int):
        self.hub_port = hub_port
        self.message = "由遥控器中心管理"

    def _send(self, command: str) -> bool:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(0.8)
                client.sendto(command.encode("utf-8"), ("127.0.0.1", self.hub_port))
                response, _ = client.recvfrom(256)
                return response.startswith(b"OK")
        except OSError:
            return False

    def status(self) -> dict:
        try:
            runtime = t1_control_request("status", timeout=0.25)
            active = bool(runtime.get("voice_active"))
            return {
                "alive": True,
                "mode": "managed",
                "pid": runtime.get("pid") or "中心",
                "message": "T1 语音正在占用" if active else self.message,
                **runtime,
            }
        except Exception:
            return {
                "alive": False,
                "mode": "managed",
                "pid": "-",
                "message": "T1 桥接未响应，中心正在恢复",
                "voice_active": False,
            }

    def start(self, learn: bool = False) -> None:
        if learn:
            self.message = "托管模式不启动第二个学习进程"
            messagebox.showinfo(
                APP_NAME,
                "当前桥接由遥控器中心托管。为避免重复监听，学习模式暂不从这里启动。",
            )
            return
        queued = self._send("RESTART:t1")
        self.message = "中心已接收 T1 重启" if queued else "T1 重启通知未确认"

    def stop(self) -> None:
        return

    def stop_voice(self) -> bool:
        try:
            result = t1_control_request("stop_voice", timeout=2.0)
            self.message = "T1 语音已结束"
            return bool(result.get("stopped"))
        except Exception as exc:
            self.message = f"结束语音失败: {exc}"
            return False


def list_devices() -> str:
    cmd = bridge_command(["--list-devices"])
    return subprocess.check_output(
        cmd,
        cwd=str(ROOT),
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


class MainPanel:
    def __init__(
        self,
        root: tk.Tk,
        bridge: BridgeProcess | ManagedBridgeProxy,
        tray: "TrayController | None",
        managed: bool = False,
    ):
        self.root = root
        self.bridge = bridge
        self.tray = tray
        self.managed = managed
        self.config: dict = {}
        self.selected_id = "voice"
        self.status_var = tk.StringVar(value="")
        self.title_var = tk.StringVar(value="")
        self.action_type_var = tk.StringVar(value="快捷键")
        self.value_var = tk.StringVar(value="")
        self.event_var = tk.StringVar(value="")
        self.ctrl_var = tk.BooleanVar(value=False)
        self.shift_var = tk.BooleanVar(value=False)
        self.alt_var = tk.BooleanVar(value=False)
        self.win_var = tk.BooleanVar(value=False)
        self.voice_enabled_var = tk.BooleanVar(value=True)
        self.voice_mode_var = tk.StringVar(value="开关型")
        self.capture_status_var = tk.StringVar(value="按录入后，直接按目标单键或组合键")
        self.diagnostics_visible = tk.BooleanVar(value=False)
        self.capture = KeyboardShortcutCapture(
            self.root,
            self._capture_complete,
            self._capture_failed,
            thread_name="t1-shortcut-capture",
        )
        self._setup()
        self._build()
        self.load_config()
        self.select_button("voice")
        self.poll()

    def _setup(self) -> None:
        self.root.title(APP_NAME)
        self.root.geometry("1000x780")
        self.root.minsize(994, 750)
        self.root.configure(bg=BG)
        self.root.protocol("WM_DELETE_WINDOW", self.hide if self.tray else self.exit_app)
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background=BG)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Title.TLabel", background=CARD, foreground=TEXT, font=("Microsoft YaHei UI", 16, "bold"))
        style.configure("Body.TLabel", background=BG, foreground=TEXT, font=("Microsoft YaHei UI", 10))
        style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=("Microsoft YaHei UI", 9))
        style.configure("TButton", padding=(12, 7), font=("Microsoft YaHei UI", 9))
        style.configure("Primary.TButton", background=BLUE, foreground="#ffffff", padding=(14, 7), font=("Microsoft YaHei UI", 9, "bold"))
        style.map("Primary.TButton", background=[("active", BLUE_DARK), ("pressed", BLUE_DARK)], foreground=[("active", "#ffffff")])
        style.configure("Apple.TCheckbutton", background=CARD, foreground=TEXT, font=("Microsoft YaHei UI", 9))

    def _build(self) -> None:
        frame = ttk.Frame(self.root, style="App.TFrame", padding=18)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(1, weight=1)

        header = ttk.Frame(frame, style="App.TFrame")
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        ttk.Label(header, text=APP_NAME, style="Body.TLabel", font=("Microsoft YaHei UI", 15, "bold")).pack(side="left")
        ttk.Label(header, textvariable=self.status_var, style="Body.TLabel").pack(side="right")

        left = ttk.Frame(frame, style="App.TFrame")
        left.grid(row=1, column=0, sticky="ns", padx=(0, 14))
        self.canvas = tk.Canvas(left, width=334, height=604, bg=BG, highlightthickness=0)
        self.canvas.pack()

        card = ttk.Frame(frame, style="Card.TFrame", padding=20)
        card.grid(row=1, column=1, sticky="nsew")
        card.columnconfigure(0, weight=1)

        ttk.Label(card, textvariable=self.title_var, style="Title.TLabel").grid(row=0, column=0, sticky="w")

        ttk.Label(card, text="动作", style="Muted.TLabel").grid(row=1, column=0, sticky="w", pady=(18, 4))
        self.action_combo = ttk.Combobox(card, textvariable=self.action_type_var, values=list(ACTION_LABELS.keys()), state="readonly")
        self.action_combo.grid(row=2, column=0, sticky="ew")

        ttk.Label(card, text="快捷键", style="Muted.TLabel").grid(row=3, column=0, sticky="w", pady=(16, 4))
        modifiers = ttk.Frame(card, style="Card.TFrame")
        modifiers.grid(row=4, column=0, sticky="ew")
        ttk.Checkbutton(modifiers, text="Ctrl 控制键", variable=self.ctrl_var, style="Apple.TCheckbutton").pack(side="left", padx=(0, 12))
        ttk.Checkbutton(modifiers, text="Shift 上档键", variable=self.shift_var, style="Apple.TCheckbutton").pack(side="left", padx=(0, 12))
        ttk.Checkbutton(modifiers, text="Alt 换档键", variable=self.alt_var, style="Apple.TCheckbutton").pack(side="left", padx=(0, 12))
        ttk.Checkbutton(modifiers, text="Win 系统键", variable=self.win_var, style="Apple.TCheckbutton").pack(side="left", padx=(0, 12))

        shortcut_row = ttk.Frame(card, style="Card.TFrame")
        shortcut_row.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        shortcut_row.columnconfigure(0, weight=1)
        self.value_combo = ttk.Combobox(shortcut_row, textvariable=self.value_var, values=KEY_VALUES)
        self.value_combo.grid(row=0, column=0, sticky="ew")
        self.capture_button = ttk.Button(
            shortcut_row, text="按真实键盘录入", command=self.toggle_capture
        )
        self.capture_button.grid(row=0, column=1, padx=(8, 0))

        presets = ttk.Frame(card, style="Card.TFrame")
        presets.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        for label, keys in [("语音", ["ctrl", "alt", "f12"]), ("退格", ["backspace"]), ("复制", ["ctrl", "c"]), ("粘贴", ["ctrl", "v"])]:
            ttk.Button(presets, text=label, command=lambda k=keys: self.set_keys(k)).pack(side="left", padx=(0, 8))

        self.voice_options = ttk.Frame(card, style="Card.TFrame")
        self.voice_options.grid(row=7, column=0, sticky="ew", pady=(16, 0))
        ttk.Checkbutton(
            self.voice_options,
            text="启用语音快捷键（Voice Hotkey）",
            variable=self.voice_enabled_var,
            style="Apple.TCheckbutton",
        ).pack(side="left")
        ttk.Combobox(
            self.voice_options,
            textvariable=self.voice_mode_var,
            values=("开关型",),
            state="readonly",
            width=8,
        ).pack(side="left", padx=(12, 0))
        ttk.Label(
            self.voice_options,
            textvariable=self.capture_status_var,
            style="Muted.TLabel",
        ).pack(side="left", padx=(10, 0))
        self.stop_voice_button = ttk.Button(
            self.voice_options,
            text="立即结束语音",
            command=self.stop_voice_now,
        )
        self.stop_voice_button.pack(side="right", padx=(12, 0))

        self.voice_note = ttk.Label(
            card,
            text=(
                "T1 语音使用说明（T1 Voice）\n"
                "1. 长按并保持语音键说话，中途不要松开\n"
                "2. 说完后松开语音键，再短按一次结束并提交输入\n"
                "输入法收到的是当前配置快捷键的快速点按，不是长按。"
            ),
            style="Muted.TLabel",
            justify="left",
            wraplength=560,
        )
        self.voice_note.grid(row=8, column=0, sticky="ew", pady=(12, 0))

        buttons = ttk.Frame(card, style="Card.TFrame")
        buttons.grid(row=9, column=0, sticky="ew", pady=(20, 0))
        ttk.Button(buttons, text="保存", command=self.save_current, style="Primary.TButton").pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="清空", command=self.clear_current).pack(side="left", padx=(0, 8))

        diag_toggle = ttk.Checkbutton(
            card,
            text="高级",
            variable=self.diagnostics_visible,
            command=self.toggle_diagnostics,
            style="Apple.TCheckbutton",
        )
        diag_toggle.grid(row=10, column=0, sticky="w", pady=(18, 0))

        self.diag = ttk.Frame(card, style="Card.TFrame")
        ttk.Label(self.diag, text="原始事件 ID", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(4, 4))
        ttk.Entry(self.diag, textvariable=self.event_var).grid(row=1, column=0, sticky="ew")
        diag_buttons = ttk.Frame(self.diag, style="Card.TFrame")
        diag_buttons.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        if not self.managed:
            ttk.Button(diag_buttons, text="学习原始键", command=self.start_learn).pack(side="left", padx=(0, 8))
        ttk.Button(diag_buttons, text="重启桥接", command=self.restart_bridge).pack(side="left", padx=(0, 8))
        ttk.Button(diag_buttons, text="设备", command=self.show_devices).pack(side="left", padx=(0, 8))
        ttk.Button(diag_buttons, text="日志", command=self.open_logs).pack(side="left", padx=(0, 8))
        self.diag.columnconfigure(0, weight=1)

        self.draw_remote()

    def load_config(self) -> None:
        try:
            self.config = load_json(CONFIG_PATH)
        except Exception:
            self.config = {}
        self.config.setdefault("button_aliases", {})
        self.config.setdefault("button_bindings", {})

    def save_config(self) -> None:
        save_json(CONFIG_PATH, self.config)

    def draw_remote(self) -> None:
        self.canvas.delete("all")
        rounded_rect(self.canvas, 56, 12, 250, 576, 48, fill="#141416", outline="#050505", width=1)
        rounded_rect(self.canvas, 68, 26, 238, 560, 40, fill="#f8f8fa", outline="#d8d8de", width=1)
        self.canvas.create_oval(94, 78, 220, 236, fill="#202124", outline="#101012", width=2)
        self.canvas.create_oval(129, 123, 185, 181, fill="#303136", outline="#101012", width=1)
        rounded_rect(self.canvas, 118, 540, 188, 552, 6, fill="#1f2024", outline="#050505", width=1)
        self.canvas.create_text(153, 530, text="USB-C", fill=MUTED, font=("Segoe UI", 7))
        for button in REMOTE_BUTTONS:
            self.draw_button(button)

    def draw_button(self, item: dict) -> None:
        button_id = item["id"]
        selected = button_id == self.selected_id
        configured = bool(self.config.get("button_bindings", {}).get(button_id))
        supported = button_runtime_supported(self.config, button_id)
        x, y, w, h = item["x"], item["y"], item["w"], item["h"]
        tag = f"button_{button_id}"
        fill = "#ffffff"
        outline = BORDER
        text = TEXT
        if item.get("side"):
            fill = "#2d2d31"
            text = "#ffffff"
        elif item.get("accent"):
            fill = "#f2f7ff"
            outline = "#b9d7ff"
        if not supported:
            fill = "#ececef"
            outline = "#d8d8dc"
            text = "#9a9aa0"
        if configured:
            fill = "#eef7ff" if not item.get("side") else "#2d2d31"
            outline = "#9dccff"
        if selected:
            fill = BLUE
            outline = BLUE_DARK
            text = "#ffffff"
        if item.get("round"):
            self.canvas.create_oval(x, y, x + w, y + h, fill=fill, outline=outline, width=2, tags=(tag,))
        else:
            radius = 10 if item.get("side") else 14
            rounded_rect(self.canvas, x, y, x + w, y + h, radius, fill=fill, outline=outline, width=2, tags=(tag,))
        self.canvas.create_text(x + w / 2, y + h / 2 - 6, text=item["short"], fill=text, font=("Segoe UI", 9, "bold"), tags=(tag,))
        self.canvas.create_text(
            x + w / 2,
            y + h / 2 + 10,
            text=(
                action_label(self.config.get("button_bindings", {}).get(button_id))
                if supported
                else "未识别"
            )[:12],
            fill=text if selected else MUTED,
            font=("Segoe UI", 7),
            tags=(tag,),
        )
        self.canvas.tag_bind(tag, "<Button-1>", lambda _event, bid=button_id: self.select_button(bid))

    def clear_modifiers(self) -> None:
        self.ctrl_var.set(False)
        self.shift_var.set(False)
        self.alt_var.set(False)
        self.win_var.set(False)

    def set_keys(self, keys: list[str]) -> None:
        self.action_type_var.set("快捷键")
        self.apply_keys(keys)

    def apply_keys(self, keys: list[str]) -> None:
        self.clear_modifiers()
        plain = []
        for key in keys:
            key = str(key).lower()
            if key == "ctrl":
                self.ctrl_var.set(True)
            elif key == "shift":
                self.shift_var.set(True)
            elif key == "alt":
                self.alt_var.set(True)
            elif key == "win":
                self.win_var.set(True)
            else:
                plain.append(key)
        self.value_var.set(format_keys(plain) if plain else "")

    def selected_modifiers(self) -> list[str]:
        keys = []
        if self.ctrl_var.get():
            keys.append("ctrl")
        if self.shift_var.get():
            keys.append("shift")
        if self.alt_var.get():
            keys.append("alt")
        if self.win_var.get():
            keys.append("win")
        return keys

    def keys_from_fields(self) -> list[str]:
        value = self.value_var.get().strip()
        typed = parse_keys(value) if "+" in value else [normalize_key(value)]
        keys = []
        for key in [*self.selected_modifiers(), *typed]:
            if key and key not in keys:
                keys.append(key)
        return keys

    def select_button(self, button_id: str) -> None:
        if self.capture.active:
            self.capture.cancel()
            self.capture_button.configure(text="按真实键盘录入")
        self.selected_id = button_id
        item = next((button for button in REMOTE_BUTTONS if button["id"] == button_id), {"label": button_id})
        supported = button_runtime_supported(self.config, button_id)
        self.title_var.set(item["label"] if supported else f"{item['label']}（当前未识别）")
        self.event_var.set(", ".join(self.config.get("button_aliases", {}).get(button_id, [])))
        action = first_action(self.config.get("button_bindings", {}).get(button_id))
        if button_id == "voice":
            self.voice_note.grid()
            enabled, voice_keys, voice_mode = voice_settings(self.config)
            self.voice_enabled_var.set(enabled)
            self.voice_mode_var.set("开关型")
            self.action_type_var.set("语音输入")
            self.apply_keys(voice_keys)
            self.capture_status_var.set("按一次开始，再按一次结束；停顿不会自动断开")
            self.voice_note.configure(
                text=(
                    "T1 语音使用说明（T1 Voice）\n"
                    "1. 长按并保持语音键说话，中途不要松开\n"
                    "2. 说完后松开语音键，再短按一次结束并提交输入\n"
                    f"输入法收到的是 {format_keys(voice_keys)} 快速点按。"
                    "若忘记结束，5 分钟会自动收口。"
                )
            )
            self.draw_remote()
            return
        self.voice_note.grid_remove()
        if not supported:
            self.capture_status_var.set(
                "当前监听模式没有采到这个按键；原生功能不受影响，映射暂不会触发"
            )
        if not action:
            self.action_type_var.set("保持原样")
            self.value_var.set("")
            self.clear_modifiers()
        else:
            kind = action.get("type", "hotkey")
            self.action_type_var.set(ACTION_KIND_LABELS.get(kind, "快捷键"))
            if kind in {"hotkey", "hotkey_down"}:
                self.apply_keys(action.get("keys", []))
            elif kind == "key":
                self.clear_modifiers()
                self.value_var.set(format_keys([action.get("key", "")]))
            elif kind == "text":
                self.clear_modifiers()
                self.value_var.set(str(action.get("text", "")))
        self.draw_remote()

    def toggle_capture(self) -> None:
        if self.capture.active:
            self.capture.cancel()
            self.capture_button.configure(text="按真实键盘录入")
            self.capture_status_var.set("已取消录入")
            return
        self.capture_button.configure(text="取消录入")
        self.capture_status_var.set("正在录入，请按目标快捷键……")
        self.capture.start()

    def _capture_complete(self, result: dict) -> None:
        tokens = list(result.get("tokens", []))
        if not tokens:
            self._capture_failed("没有识别到有效按键")
            return
        self.apply_keys(tokens)
        self.action_type_var.set("语音输入" if self.selected_id == "voice" else "快捷键")
        if self.selected_id == "voice":
            self.voice_enabled_var.set(True)
        self.capture_button.configure(text="按真实键盘录入")
        self.capture_status_var.set(f"已录入 {format_keys(tokens)}，等待保存")

    def _capture_failed(self, error: str) -> None:
        self.capture.cancel()
        self.capture_button.configure(text="按真实键盘录入")
        self.capture_status_var.set("录入失败，可以重试")
        messagebox.showerror(APP_NAME, error)

    def make_actions(self) -> list[dict]:
        kind = ACTION_LABELS.get(self.action_type_var.get(), "hotkey")
        if kind == "none":
            return []
        if kind == "hotkey":
            keys = self.keys_from_fields()
            if not keys:
                raise ValueError("快捷键不能为空")
            action = {"type": "hotkey", "keys": keys}
            if self.selected_id == "voice":
                action["hold_ms"] = 120
                action["cooldown_ms"] = 30000
            message = f"{self.selected_id} -> {format_keys(keys)}"
        elif kind == "push_to_talk":
            keys = self.keys_from_fields()
            if not keys:
                raise ValueError("按住说话快捷键不能为空")
            action = {
                "type": "hotkey_down",
                "keys": keys,
                "state_id": f"{self.selected_id}_push_to_talk",
            }
            if self.selected_id == "voice":
                action["audio_source"] = "Mic Device"
                action["audio_tail_ms"] = 120
                action["audio_release_mode"] = "signal_end"
                action["audio_trigger_mode"] = "toggle_hotkey"
            message = f"{self.selected_id} hold -> {format_keys(keys)}"
        elif kind == "key":
            keys = parse_keys(self.value_var.get())
            if not keys:
                raise ValueError("单键不能为空")
            action = {"type": "key", "key": keys[0]}
            message = f"{self.selected_id} -> {format_keys([keys[0]])}"
        elif kind == "text":
            action = {"type": "text", "text": self.value_var.get()}
            message = f"{self.selected_id} -> text"
        else:
            action = {"type": kind}
            message = f"{self.selected_id} -> {kind}"
        log_action = {"type": "log", "message": message}
        if self.selected_id == "voice":
            log_action["cooldown_ms"] = 30000
        return [action, log_action]

    def save_current(self) -> None:
        try:
            self.load_config()
            self.config.setdefault("button_aliases", {})[self.selected_id] = split_event_ids(self.event_var.get())
            if self.selected_id == "voice":
                keys = self.keys_from_fields()
                if self.voice_enabled_var.get() and not keys:
                    raise ValueError("语音快捷键不能为空")
                mode = "toggle" if self.voice_mode_var.get() == "开关型" else "hold"
                apply_voice_settings(
                    self.config,
                    bool(self.voice_enabled_var.get()),
                    keys,
                    mode,
                )
                self.save_config()
                self.restart_bridge()
                self.select_button("voice")
                return
            actions = self.make_actions()
            bindings = self.config.setdefault("button_bindings", {})
            if actions:
                bindings[self.selected_id] = actions
            else:
                bindings.pop(self.selected_id, None)
            self.save_config()
            self.restart_bridge()
            self.select_button(self.selected_id)
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"保存失败: {exc}")

    def clear_current(self) -> None:
        if self.selected_id == "voice":
            self.voice_enabled_var.set(False)
        self.action_type_var.set("保持原样")
        self.value_var.set("")
        self.clear_modifiers()
        self.save_current()

    def restart_bridge(self) -> None:
        self.bridge.start(learn=False)

    def stop_voice_now(self) -> None:
        stopped = self.bridge.stop_voice()
        self.capture_status_var.set(
            "T1 语音已结束" if stopped else "当前没有活动语音，或桥接暂未响应"
        )

    def start_learn(self) -> None:
        self.bridge.start(learn=True)

    def show_devices(self) -> None:
        try:
            content = list_devices()
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"读取设备失败: {exc}")
            return
        win = tk.Toplevel(self.root)
        win.title("设备")
        win.geometry("760x420")
        box = scrolledtext.ScrolledText(win, wrap="none", font=("Consolas", 9))
        box.pack(fill="both", expand=True)
        box.insert("1.0", content)
        box.configure(state="disabled")

    def open_logs(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["explorer.exe", str(LOG_DIR)])

    def toggle_diagnostics(self) -> None:
        if self.diagnostics_visible.get():
            self.diag.grid(row=11, column=0, sticky="ew", pady=(8, 0))
        else:
            self.diag.grid_remove()

    def poll(self) -> None:
        status = self.bridge.status()
        if status.get("mode") == "managed":
            self.status_var.set(status.get("message", "由遥控器中心管理"))
        else:
            state = "运行中" if status["alive"] else "已停止"
            self.status_var.set(f"{state}  PID {status['pid'] or '-'}")
        if (
            self.selected_id == "voice"
            and not self.capture.active
        ):
            if status.get("voice_active"):
                started_at_ms = status.get("voice_started_at_ms")
                elapsed = (
                    max(0, int((time.time() * 1000 - started_at_ms) / 1000))
                    if started_at_ms
                    else 0
                )
                self.capture_status_var.set(f"T1 语音正在占用 · {elapsed} 秒")
            else:
                self.capture_status_var.set("T1 语音待机；按一次开始，再按一次结束")
        if self.tray:
            self.tray.update(status)
        self.root.after(1000, self.poll)

    def hide(self) -> None:
        self.root.withdraw()

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def exit_app(self) -> None:
        if self.tray:
            self.tray.stop()
        self.bridge.stop()
        self.root.after(100, self.root.destroy)


class TrayController:
    def __init__(self, bridge: BridgeProcess):
        self.bridge = bridge
        self.panel: MainPanel | None = None
        self.icon = None
        self.last_state = None

    def bind(self, panel: MainPanel) -> None:
        self.panel = panel

    def start(self) -> None:
        if pystray is None:
            return
        menu = pystray.Menu(
            pystray.MenuItem("打开面板", self.show),
            pystray.MenuItem("重启桥接", self.restart),
            pystray.MenuItem("停止桥接", self.stop_bridge),
            pystray.MenuItem("退出", self.exit_app),
        )
        self.icon = pystray.Icon(APP_ID, self.make_icon("stopped"), APP_NAME, menu)
        threading.Thread(target=self.icon.run, daemon=True, name="ipazzport-tray").start()

    def make_icon(self, state: str):
        if Image is None:
            return None
        color = {"running": "#2fa84f", "learning": "#d9a300", "stopped": "#777777"}.get(state, BLUE)
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=12, fill="#111827")
        draw.ellipse((20, 12, 44, 36), fill=color)
        draw.rounded_rectangle((25, 34, 39, 52), radius=5, fill=color)
        return image

    def update(self, status: dict) -> None:
        if not self.icon:
            return
        state = status.get("mode") if status.get("alive") else "stopped"
        if state != self.last_state:
            self.last_state = state
            self.icon.icon = self.make_icon(state)
        self.icon.title = f"{APP_NAME} - {status.get('message', '')}"

    def show(self, icon=None, item=None) -> None:
        if self.panel:
            self.panel.root.after(0, self.panel.show)

    def restart(self, icon=None, item=None) -> None:
        self.bridge.start(learn=False)

    def stop_bridge(self, icon=None, item=None) -> None:
        self.bridge.stop()

    def exit_app(self, icon=None, item=None) -> None:
        if self.panel:
            self.panel.root.after(0, self.panel.exit_app)

    def stop(self) -> None:
        if self.icon:
            self.icon.stop()


def acquire_single_instance() -> bool:
    if os.name != "nt":
        return True
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\iPazzPortRemoteBridge")
    if ctypes.windll.kernel32.GetLastError() == 183:
        return False
    globals()["_APP_MUTEX"] = mutex
    return True


def app_main(
    autorun: bool = False,
    minimized: bool = False,
    managed_settings: bool = False,
    hub_port: int = DEFAULT_HUB_PORT,
) -> int:
    ensure_config()
    if not managed_settings and not acquire_single_instance():
        return 0
    bridge = ManagedBridgeProxy(hub_port) if managed_settings else BridgeProcess()
    root = tk.Tk()
    tray = TrayController(bridge) if pystray is not None and not managed_settings else None
    panel = MainPanel(root, bridge, tray, managed=managed_settings)
    if tray:
        tray.bind(panel)
        tray.start()
    if autorun and not managed_settings:
        bridge.start(learn=False)
    if minimized and tray:
        root.withdraw()
    try:
        root.mainloop()
    finally:
        if tray:
            tray.stop()
        bridge.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--bridge", action="store_true")
    parser.add_argument("--autorun", action="store_true")
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--managed-settings", action="store_true")
    parser.add_argument("--hub-port", type=int, default=DEFAULT_HUB_PORT)
    args, rest = parser.parse_known_args(argv)
    if args.bridge:
        ensure_config()
        return run_bridge_main(rest)
    return app_main(
        autorun=args.autorun,
        minimized=args.minimized,
        managed_settings=args.managed_settings,
        hub_port=args.hub_port,
    )


if os.name == "nt":
    import ctypes


if __name__ == "__main__":
    raise SystemExit(main())
