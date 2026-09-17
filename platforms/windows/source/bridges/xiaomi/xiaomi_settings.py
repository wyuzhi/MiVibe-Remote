#!/usr/bin/env python3
"""Visual, keyboard-learning settings window for the Xiaomi remote."""

from __future__ import annotations

import argparse
import copy
import ctypes
from ctypes import wintypes
import json
import os
import socket
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
import uuid

from .xiaomi_config import (
    APP_VERSION,
    BUTTONS,
    CODEX_VOICE_TRIGGER_MODE,
    CONFIG_PATH,
    DEFAULT_VOICE_HOTKEY,
    KEYS_CONFIG_PATH,
    MAPPING_SCHEMA_VERSION,
    PRESET_ORDER,
    QIANWEN_VOICE_TRIGGER_MODE,
    WORKBUDDY_VOICE_TRIGGER_MODE,
    WECHAT_VOICE_TRIGGER_MODE,
    apply_remote_identity,
    codex_button_bindings,
    custom_preset_definitions,
    hotkey_injection_method,
    hotkey_tokens,
    load_config,
    load_keys_config,
    resolve_hotkey_virtual_keys,
    qianwen_button_bindings,
    save_config,
    save_keys_config,
    save_preset_button_bindings,
    saved_preset_button_bindings,
    voice_hotkey_from_configs,
    wechat_button_bindings,
    workbuddy_button_bindings,
)


APP_NAME = "MiVibe Remote 设置"
DEFAULT_HUB_PORT = 28690
SETTINGS_CONTROL_PORT_OFFSET = 1
CONTROL_REQUEST_TIMEOUT = 6.0
BG = "#eef2f7"
CARD = "#ffffff"
TEXT = "#152033"
MUTED = "#64748b"
BORDER = "#dce3ed"
BLUE = "#1677ff"
BLUE_DARK = "#0d5fd4"
CYAN = "#25c2f5"
NAVY = "#101b31"
NAVY_LIGHT = "#1a2945"
SOFT_BLUE = "#edf6ff"
SOFT_GRAY = "#f7f9fc"
SUCCESS = "#13a76b"

BUTTON_LABELS = dict(BUTTONS)
KEY_DISPLAY = {
    "ctrl": "Ctrl",
    "leftctrl": "左 Ctrl",
    "rightctrl": "右 Ctrl",
    "shift": "Shift",
    "leftshift": "左 Shift",
    "rightshift": "右 Shift",
    "alt": "Alt",
    "leftalt": "左 Alt",
    "rightalt": "右 Alt",
    "win": "Win",
    "leftwin": "左 Win",
    "rightwin": "右 Win",
    "esc": "退出键（Esc）",
    "enter": "回车键（Enter）",
    "space": "空格键（Space）",
    "tab": "制表键（Tab）",
    "backspace": "退格键（Backspace）",
    "delete": "删除键（Delete）",
    "insert": "插入键（Insert）",
    "home": "起始键（Home）",
    "end": "结束键（End）",
    "pageup": "上翻页键（Page Up）",
    "pagedown": "下翻页键（Page Down）",
    "left": "←",
    "right": "→",
    "up": "↑",
    "down": "↓",
    "apps": "菜单键",
    "volume_mute": "静音",
    "volume_up": "音量 +",
    "volume_down": "音量 -",
    "media_next": "下一曲",
    "media_prev": "上一曲",
    "media_stop": "停止播放",
    "media_play_pause": "播放 / 暂停",
}

# Coordinates follow a straight-on 264x1087 Remote 2 reference grid.
REMOTE_CROP = (0, 0, 264, 1087)
REMOTE_PHOTO_HEIGHT = 530
REMOTE_HOTSPOTS = {
    "power": (31, 38, 107, 118, "oval"),
    "mic": (155, 38, 229, 118, "oval"),
    "up": (90, 141, 174, 220, "oval"),
    "left": (25, 206, 105, 289, "oval"),
    "ok": (78, 194, 185, 304, "oval"),
    "right": (158, 206, 239, 289, "oval"),
    "down": (90, 285, 175, 364, "oval"),
    "back": (34, 376, 122, 470, "oval"),
    "volume_up": (147, 376, 236, 468, "oval"),
    "home": (34, 479, 122, 573, "oval"),
    "volume_down": (147, 464, 236, 556, "oval"),
    "menu": (34, 586, 122, 681, "oval"),
    "tv": (147, 586, 236, 681, "oval"),
}


def first_action(actions) -> dict | None:
    if isinstance(actions, dict):
        actions = [actions]
    if not isinstance(actions, list):
        return None
    return next(
        (
            item
            for item in actions
            if isinstance(item, dict) and item.get("type") not in {None, "none", "log"}
        ),
        None,
    )


def normalize_key(raw: str) -> str:
    value = raw.strip().lower()
    aliases = {
        "control": "ctrl",
        "left control": "leftctrl",
        "right control": "rightctrl",
        "left ctrl": "leftctrl",
        "right ctrl": "rightctrl",
        "left shift": "leftshift",
        "right shift": "rightshift",
        "left alt": "leftalt",
        "right alt": "rightalt",
        "左 ctrl": "leftctrl",
        "右 ctrl": "rightctrl",
        "左 shift": "leftshift",
        "右 shift": "rightshift",
        "左 alt": "leftalt",
        "右 alt": "rightalt",
        "左 win": "leftwin",
        "右 win": "rightwin",
        "windows": "win",
        "left win": "leftwin",
        "right win": "rightwin",
        "return": "enter",
        "escape": "esc",
        "page up": "pageup",
        "page down": "pagedown",
        "volume up": "volume_up",
        "volume down": "volume_down",
        "volume mute": "volume_mute",
        "退出键": "esc",
        "回车键": "enter",
        "空格键": "space",
        "制表键": "tab",
        "退格键": "backspace",
        "删除键": "delete",
        "插入键": "insert",
        "起始键": "home",
        "结束键": "end",
        "上翻页键": "pageup",
        "下翻页键": "pagedown",
        "退出键（esc）": "esc",
        "回车键（enter）": "enter",
        "空格键（space）": "space",
        "制表键（tab）": "tab",
        "退格键（backspace）": "backspace",
        "删除键（delete）": "delete",
        "插入键（insert）": "insert",
        "起始键（home）": "home",
        "结束键（end）": "end",
        "上翻页键（page up）": "pageup",
        "下翻页键（page down）": "pagedown",
    }
    return aliases.get(value, value.replace(" ", ""))


def split_hotkey(value: str) -> list[str]:
    result = []
    for raw in value.replace("＋", "+").split("+"):
        key = normalize_key(raw)
        if key and key not in result:
            result.append(key)
    return result


def format_keys(keys: list[str]) -> str:
    parts = []
    for key in keys:
        value = str(key).lower()
        if value in KEY_DISPLAY:
            parts.append(KEY_DISPLAY[value])
        elif value.startswith("vk_"):
            parts.append(f"VK {value[3:].upper()}")
        elif len(value) == 1:
            parts.append(value.upper())
        else:
            parts.append(value.upper() if value.startswith("f") else value)
    return " + ".join(parts)


def format_action(actions) -> str:
    action = first_action(actions)
    if not action:
        return "未设置"
    action_type = str(action.get("type", "hotkey"))
    if action_type == "hotkey":
        return format_keys(list(action.get("keys", []))) or "未设置"
    if action_type == "key":
        return format_keys([str(action.get("key", ""))])
    if action_type == "text":
        return f"输入文本：{action.get('text', '')}"
    if action_type == "command":
        return str(action.get("label") or "启动程序")
    if action_type == "preset_cycle":
        return "循环切换预设"
    if action_type == "mouse_wheel":
        return "鼠标滚轮上" if int(action.get("delta", 0)) > 0 else "鼠标滚轮下"
    return action_type


def capture_encoding(capture: dict | None) -> str:
    if not isinstance(capture, dict) or capture.get("source") == "manual":
        return "手动输入，保存时会校验按键名称"
    vk = capture.get("vk")
    scan = capture.get("scan_code")
    if vk is None or scan is None:
        return "内置默认映射"
    extension = "E0" if capture.get("extended") else "N"
    modifiers = capture.get("modifiers", [])
    prefix = ""
    if modifiers:
        prefix = "修饰键 " + ", ".join(
            f"{item.get('label', item.get('token', ''))}(VK 0x{int(item.get('vk', 0)):02X})"
            for item in modifiers
        ) + "  ·  "
    return f"{prefix}VK 0x{int(vk):02X}  ·  SC 0x{int(scan):03X}  ·  {extension}"


def send_hub_restart(port: int, timeout: float = CONTROL_REQUEST_TIMEOUT) -> int:
    request_id = uuid.uuid4().hex
    request = json.dumps(
        {
            "op": "restart",
            "bridge": "xiaomi",
            "request_id": request_id,
        }
    ).encode("utf-8")
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(timeout)
            client.sendto(request, ("127.0.0.1", port))
            response, _ = client.recvfrom(4096)
    except (OSError, TimeoutError) as exc:
        raise RuntimeError(
            "主程序没有确认桥接重启，请回到 MiVibe 主界面点击“重启桥接”后重试"
        ) from exc

    try:
        result = json.loads(response.decode("utf-8"))
        if result.get("request_id") != request_id:
            raise ValueError("restart response request id mismatch")
        if not result.get("ok"):
            raise ValueError(str(result.get("error") or "bridge restart failed"))
        pid = int(result.get("pid") or 0)
        if pid <= 0:
            raise ValueError("bridge restart returned no worker pid")
        return pid
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise RuntimeError(f"桥接重启未得到有效确认：{exc}") from exc


def notify_existing_settings(port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(timeout)
            client.sendto(b"SHOW", ("127.0.0.1", port))
            response, _ = client.recvfrom(256)
        return response == b"OK show"
    except (OSError, TimeoutError):
        return False


def claim_settings_instance(hub_port: int) -> socket.socket | None:
    port = hub_port + SETTINGS_CONTROL_PORT_OFFSET
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        server.bind(("127.0.0.1", port))
    except OSError as exc:
        server.close()
        if notify_existing_settings(port):
            return None
        raise RuntimeError(
            "按键设置窗口端口已被占用，但无法唤醒已有窗口"
        ) from exc
    server.settimeout(0.5)
    return server


class KbdLlHookStruct(ctypes.Structure):
    _fields_ = [
        ("vk_code", wintypes.DWORD),
        ("scan_code", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra_info", ctypes.c_size_t),
    ]


class KeyboardShortcutCapture:
    """Capture and temporarily suppress one physical keyboard shortcut."""

    WH_KEYBOARD_LL = 13
    HC_ACTION = 0
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    WM_QUIT = 0x0012
    LLKHF_EXTENDED = 0x01
    LLKHF_INJECTED = 0x10

    MODIFIERS = {
        0x10: ("shift", "Shift"),
        0x11: ("ctrl", "Ctrl"),
        0x12: ("alt", "Alt"),
        0x5B: ("leftwin", "左 Win"),
        0x5C: ("rightwin", "右 Win"),
        0xA0: ("leftshift", "左 Shift"),
        0xA1: ("rightshift", "右 Shift"),
        0xA2: ("leftctrl", "左 Ctrl"),
        0xA3: ("rightctrl", "右 Ctrl"),
        0xA4: ("leftalt", "左 Alt"),
        0xA5: ("rightalt", "右 Alt"),
    }
    MODIFIER_ORDER = {
        "ctrl": 10,
        "leftctrl": 10,
        "rightctrl": 11,
        "shift": 20,
        "leftshift": 20,
        "rightshift": 21,
        "alt": 30,
        "leftalt": 30,
        "rightalt": 31,
        "leftwin": 40,
        "rightwin": 41,
    }
    NAMED_KEYS = {
        0x08: "backspace",
        0x09: "tab",
        0x0D: "enter",
        0x13: "pause",
        0x14: "capslock",
        0x1B: "esc",
        0x20: "space",
        0x21: "pageup",
        0x22: "pagedown",
        0x23: "end",
        0x24: "home",
        0x25: "left",
        0x26: "up",
        0x27: "right",
        0x28: "down",
        0x2C: "printscreen",
        0x2D: "insert",
        0x2E: "delete",
        0x5D: "apps",
        0x60: "num0",
        0x61: "num1",
        0x62: "num2",
        0x63: "num3",
        0x64: "num4",
        0x65: "num5",
        0x66: "num6",
        0x67: "num7",
        0x68: "num8",
        0x69: "num9",
        0x6A: "multiply",
        0x6B: "add",
        0x6D: "subtract",
        0x6E: "decimal",
        0x6F: "divide",
        0xAD: "volume_mute",
        0xAE: "volume_down",
        0xAF: "volume_up",
        0xB0: "media_next",
        0xB1: "media_prev",
        0xB2: "media_stop",
        0xB3: "media_play_pause",
        0xBA: ";",
        0xBB: "=",
        0xBC: ",",
        0xBD: "-",
        0xBE: ".",
        0xBF: "/",
        0xC0: "`",
        0xDB: "[",
        0xDC: "\\",
        0xDD: "]",
        0xDE: "'",
    }

    def __init__(self, root: tk.Tk, on_result, on_error):
        self.root = root
        self.on_result = on_result
        self.on_error = on_error
        self.active = False
        self.captured = False
        self.thread: threading.Thread | None = None
        self.thread_id = 0
        self.hook = None
        self.proc = None
        self.blocked_vks: set[int] = set()
        self.active_modifiers: dict[int, dict] = {}
        self.modifier_history: dict[int, dict] = {}

    @classmethod
    def key_token(cls, vk: int) -> str:
        if ord("A") <= vk <= ord("Z"):
            return chr(vk).lower()
        if ord("0") <= vk <= ord("9"):
            return chr(vk)
        if 0x70 <= vk <= 0x87:
            return f"f{vk - 0x6F}"
        return cls.NAMED_KEYS.get(vk, f"vk_{vk:02x}")

    @classmethod
    def make_result(
        cls,
        tokens: list[str],
        vk: int,
        scan_code: int,
        flags: int,
        modifiers: list[dict],
    ) -> dict:
        return {
            "tokens": tokens,
            "capture": {
                "source": "keyboard_hook",
                "vk": int(vk),
                "scan_code": int(scan_code),
                "extended": bool(flags & cls.LLKHF_EXTENDED),
                "modifiers": [dict(item) for item in modifiers],
            },
        }

    def start(self) -> None:
        if os.name != "nt":
            self.on_error("当前系统不支持 Windows 键盘捕获")
            return
        previous_thread = self.thread
        self.cancel()
        if (
            previous_thread is not None
            and previous_thread.is_alive()
            and previous_thread is not threading.current_thread()
        ):
            previous_thread.join(timeout=0.5)
        self.active = True
        self.captured = False
        self.blocked_vks.clear()
        self.active_modifiers.clear()
        self.modifier_history.clear()
        self.thread = threading.Thread(
            target=self._run,
            name="xiaomi-keyboard-shortcut-capture",
            daemon=True,
        )
        self.thread.start()

    def cancel(self) -> None:
        self.active = False
        if self.thread_id and os.name == "nt":
            try:
                ctypes.windll.user32.PostThreadMessageW(
                    self.thread_id, self.WM_QUIT, 0, 0
                )
            except Exception:
                pass

    def _modifier_items(self) -> list[dict]:
        values = list(self.active_modifiers.values())
        return sorted(
            values,
            key=lambda item: self.MODIFIER_ORDER.get(item["token"], 99),
        )

    def _notify_result(self, result: dict) -> None:
        self.root.after(0, lambda: self.on_result(result))

    def _post_quit(self) -> None:
        if self.thread_id:
            ctypes.windll.user32.PostThreadMessageW(
                self.thread_id, self.WM_QUIT, 0, 0
            )

    def _callback(self, code: int, wparam: int, lparam: int) -> int:
        user32 = ctypes.windll.user32
        if code != self.HC_ACTION or not self.active:
            return int(user32.CallNextHookEx(self.hook, code, wparam, lparam))
        info = ctypes.cast(lparam, ctypes.POINTER(KbdLlHookStruct)).contents
        if info.flags & self.LLKHF_INJECTED:
            return int(user32.CallNextHookEx(self.hook, code, wparam, lparam))

        vk = int(info.vk_code)
        is_down = int(wparam) in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN)
        is_up = int(wparam) in (self.WM_KEYUP, self.WM_SYSKEYUP)
        if not is_down and not is_up:
            return int(user32.CallNextHookEx(self.hook, code, wparam, lparam))

        if is_down:
            self.blocked_vks.add(vk)
            modifier = self.MODIFIERS.get(vk)
            if modifier:
                item = {"token": modifier[0], "label": modifier[1], "vk": vk}
                self.active_modifiers[vk] = item
                self.modifier_history.setdefault(vk, item)
            elif not self.captured:
                modifiers = self._modifier_items()
                tokens = [item["token"] for item in modifiers]
                tokens.append(self.key_token(vk))
                self.captured = True
                self._notify_result(
                    self.make_result(
                        tokens,
                        vk,
                        int(info.scan_code),
                        int(info.flags),
                        modifiers,
                    )
                )
        else:
            self.blocked_vks.discard(vk)
            released_modifier = self.active_modifiers.pop(vk, None)
            if (
                released_modifier is not None
                and not self.captured
                and not self.active_modifiers
                and self.modifier_history
            ):
                modifiers = sorted(
                    self.modifier_history.values(),
                    key=lambda item: self.MODIFIER_ORDER.get(item["token"], 99),
                )
                self.captured = True
                self._notify_result(
                    self.make_result(
                        [item["token"] for item in modifiers],
                        vk,
                        int(info.scan_code),
                        int(info.flags),
                        modifiers[:-1],
                    )
                )
            if self.captured and not self.blocked_vks:
                self.active = False
                self._post_quit()
        return 1

    def _run(self) -> None:
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            self.thread_id = int(kernel32.GetCurrentThreadId())
            proc_type = ctypes.WINFUNCTYPE(
                ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
            )
            self.proc = proc_type(self._callback)
            user32.SetWindowsHookExW.argtypes = (
                ctypes.c_int,
                proc_type,
                wintypes.HINSTANCE,
                wintypes.DWORD,
            )
            user32.SetWindowsHookExW.restype = wintypes.HHOOK
            user32.CallNextHookEx.argtypes = (
                wintypes.HHOOK,
                ctypes.c_int,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            user32.CallNextHookEx.restype = ctypes.c_ssize_t
            user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
            user32.UnhookWindowsHookEx.restype = wintypes.BOOL
            user32.PostThreadMessageW.argtypes = (
                wintypes.DWORD,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            user32.PostThreadMessageW.restype = wintypes.BOOL
            kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            self.hook = user32.SetWindowsHookExW(
                self.WH_KEYBOARD_LL,
                self.proc,
                kernel32.GetModuleHandleW(None),
                0,
            )
            if not self.hook:
                raise OSError(f"键盘钩子启动失败，Win32={ctypes.get_last_error()}")
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            message = str(exc)
            self.root.after(0, lambda: self.on_error(message))
        finally:
            if self.hook:
                try:
                    ctypes.windll.user32.UnhookWindowsHookEx(self.hook)
                except Exception:
                    pass
            self.hook = None
            self.thread_id = 0
            self.active = False


class XiaomiSettingsWindow:
    def __init__(
        self,
        root: tk.Tk,
        hub_port: int,
        instance_socket: socket.socket | None = None,
    ):
        self.root = root
        self.hub_port = hub_port
        self.instance_socket = instance_socket
        self.instance_stop = threading.Event()
        self.config = load_config()
        self.keys_config = load_keys_config()
        self.working_custom_presets = copy.deepcopy(
            custom_preset_definitions(self.keys_config)
        )
        self.working_preset = str(self.config.get("active_preset", "codex"))
        if self.working_preset not in set(PRESET_ORDER) | set(
            self.working_custom_presets
        ):
            self.working_preset = "codex"
        self.working_profiles = copy.deepcopy(
            self.keys_config.get("preset_bindings", {})
        )
        # The top-level mapping is the live runtime profile and is canonical
        # for upgrades from versions that did not persist presets separately.
        live_bindings = self.keys_config.get("button_bindings", {})
        if isinstance(live_bindings, dict):
            self.working_profiles[self.working_preset] = copy.deepcopy(
                live_bindings
            )
        self.working_bindings = copy.deepcopy(
            self.working_profiles.get(self.working_preset)
            or saved_preset_button_bindings(
                self.keys_config, self.working_preset
            )
        )
        if self.config.get("voice_shortcut_enabled", True) or self.working_bindings.get("mic"):
            try:
                voice_keys = voice_hotkey_from_configs(self.config, self.keys_config)
            except ValueError:
                voice_keys = list(DEFAULT_VOICE_HOTKEY)
            current_mic = first_action(self.working_bindings.get("mic"))
            current_keys = (
                hotkey_tokens(current_mic.get("keys", []))
                if current_mic and current_mic.get("type") == "hotkey"
                else []
            )
            if current_keys != voice_keys:
                self.working_bindings["mic"] = [
                    {"type": "hotkey", "keys": voice_keys, "capture": {"source": "migration"}}
                ]
            self.config["voice_hotkey"] = "+".join(voice_keys)
        self.selected_id = "power"
        self.capture_button_id = "power"
        self.hovered_id: str | None = None

        self.selected_label_var = tk.StringVar()
        self.current_mapping_var = tk.StringVar()
        self.result_mapping_var = tk.StringVar()
        self.encoding_var = tk.StringVar()
        self.capture_status_var = tk.StringVar(value="先点左边的遥控器按键")
        self.photo_hint_var = tk.StringVar(value="点击照片中的任意按键")
        self.manual_var = tk.StringVar()
        self.save_status_var = tk.StringVar(value="所有修改会先保留在此窗口，保存后才应用")
        self.preset_name_var = tk.StringVar()
        self.voice_help_var = tk.StringVar()
        self.voice_enabled = tk.BooleanVar(
            value=bool(self.config.get("voice_shortcut_enabled", True))
        )
        self.voice_trigger_mode = tk.StringVar(
            value=(
                "按住型"
                if str(self.config.get("voice_trigger_mode", "hold")) == "hold"
                else "开关型"
            )
        )
        self.gain_db = tk.StringVar(value=str(self.config.get("gain_db", 10.0)))

        self.capture = KeyboardShortcutCapture(
            self.root, self._capture_complete, self._capture_failed
        )
        self.preset_buttons: dict[str, ttk.Button] = {}
        self.preset_area: tk.Frame | None = None
        self.add_preset_button: ttk.Button | None = None
        self._build()
        self.select_button(self.selected_id)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._start_instance_listener()

    def _start_instance_listener(self) -> None:
        if self.instance_socket is None:
            return
        server = self.instance_socket

        def listen() -> None:
            while not self.instance_stop.is_set():
                try:
                    payload, peer = server.recvfrom(256)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if payload == b"SHOW":
                    self.root.after(0, self._show_now)
                    try:
                        server.sendto(b"OK show", peer)
                    except OSError:
                        pass

        threading.Thread(
            target=listen,
            name="xiaomi-settings-single-instance",
            daemon=True,
        ).start()

    def _show_now(self) -> None:
        self.root.state("normal")
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()
        try:
            self.root.attributes("-topmost", True)
            self.root.after(250, lambda: self.root.attributes("-topmost", False))
        except tk.TclError:
            pass

    def _build(self) -> None:
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        initial_width = max(900, min(1180, screen_width - 64))
        initial_height = max(660, min(860, screen_height - 96))
        self.root.geometry(f"{initial_width}x{initial_height}")
        self.root.minsize(min(900, initial_width), min(620, initial_height))
        self.root.configure(bg=BG)

        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "Primary.TButton",
            background=BLUE,
            foreground="#ffffff",
            borderwidth=0,
            padding=(22, 11),
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        style.map(
            "Primary.TButton",
            background=[("active", BLUE_DARK), ("pressed", BLUE_DARK)],
            foreground=[("active", "#ffffff")],
        )
        style.configure(
            "Capture.TButton",
            background=BLUE,
            foreground="#ffffff",
            borderwidth=0,
            padding=(18, 14),
            font=("Microsoft YaHei UI", 11, "bold"),
        )
        style.map(
            "Capture.TButton",
            background=[("active", BLUE_DARK), ("pressed", BLUE_DARK)],
            foreground=[("active", "#ffffff")],
        )
        style.configure(
            "Quiet.TButton",
            background=CARD,
            foreground=TEXT,
            bordercolor=BORDER,
            padding=(12, 8),
            font=("Microsoft YaHei UI", 9),
        )
        style.map("Quiet.TButton", background=[("active", "#f1f5f9")])
        style.configure(
            "Preset.TButton",
            background="#f2f5f9",
            foreground="#475569",
            bordercolor="#d9e1eb",
            padding=(14, 9),
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.configure(
            "PresetActive.TButton",
            background=NAVY,
            foreground="#ffffff",
            bordercolor=NAVY,
            padding=(14, 9),
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.map(
            "PresetActive.TButton",
            background=[("active", NAVY_LIGHT)],
            foreground=[("active", "#ffffff")],
        )
        style.configure(
            "Apple.TCheckbutton",
            background=CARD,
            foreground=TEXT,
            font=("Microsoft YaHei UI", 9),
        )
        style.configure(
            "Voice.TCheckbutton",
            background=SOFT_GRAY,
            foreground=TEXT,
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        style.configure("TEntry", padding=(8, 8), fieldbackground="#ffffff")
        style.configure("TCombobox", padding=(7, 6))

        # High-DPI Windows machines often have fewer than 900 logical vertical
        # pixels. Keep the footer at its natural height and scroll the complete
        # page instead of letting Tk clip its buttons into thin strips.
        page = tk.Canvas(
            self.root,
            bg=BG,
            highlightthickness=0,
            bd=0,
            yscrollincrement=24,
        )
        page_scroll = ttk.Scrollbar(self.root, orient="vertical", command=page.yview)
        page.configure(yscrollcommand=page_scroll.set)
        page_scroll.pack(side="right", fill="y")
        page.pack(side="left", fill="both", expand=True)

        outer = tk.Frame(page, bg=BG, padx=18, pady=16)
        page_window = page.create_window((0, 0), window=outer, anchor="nw")

        def update_scroll_region(_event=None) -> None:
            page.configure(scrollregion=page.bbox("all"))

        def fit_page_width(event) -> None:
            page.itemconfigure(page_window, width=event.width)

        def scroll_page(event) -> None:
            if page.bbox("all") and outer.winfo_reqheight() > page.winfo_height():
                page.yview_scroll(-int(event.delta / 120), "units")

        outer.bind("<Configure>", update_scroll_region)
        page.bind("<Configure>", fit_page_width)
        self.root.bind("<MouseWheel>", scroll_page, add="+")

        header = tk.Frame(outer, bg=NAVY, padx=24, pady=18)
        header.pack(fill="x", pady=(0, 14))
        brand_mark = tk.Label(
            header,
            text="M",
            bg=CYAN,
            fg=NAVY,
            width=3,
            height=1,
            font=("Segoe UI", 18, "bold"),
        )
        brand_mark.pack(side="left", padx=(0, 14))
        title_block = tk.Frame(header, bg=NAVY)
        title_block.pack(side="left", fill="y")
        tk.Label(
            title_block,
            text="MiVibe Remote",
            bg=NAVY,
            fg="#ffffff",
            font=("Segoe UI", 18, "bold"),
        ).pack(anchor="w")
        tk.Label(
            title_block,
            text="小米蓝牙遥控器 2 · 按键与语音工作流控制台",
            bg=NAVY,
            fg="#aebbd0",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(4, 0))
        header_meta = tk.Frame(header, bg=NAVY)
        header_meta.pack(side="right", anchor="center")
        tk.Label(
            header_meta,
            text="当前模式",
            bg=NAVY,
            fg="#8191aa",
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="e")
        tk.Label(
            header_meta,
            textvariable=self.preset_name_var,
            bg=NAVY,
            fg=CYAN,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(side="left", pady=(3, 0))
        tk.Label(
            header_meta,
            text=f"  ·  v{APP_VERSION}",
            bg=NAVY,
            fg="#aebbd0",
            font=("Segoe UI", 9),
        ).pack(side="left", pady=(4, 0))

        body = tk.Frame(outer, bg=BG)
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        left_card = tk.Frame(
            body,
            bg=CARD,
            width=380,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        left_card.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        left_card.grid_propagate(False)
        tk.Label(
            left_card,
            text="遥控器按键",
            bg=CARD,
            fg=TEXT,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(anchor="w", padx=20, pady=(18, 0))
        tk.Label(
            left_card,
            textvariable=self.photo_hint_var,
            bg=CARD,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", padx=20, pady=(5, 0))
        tk.Label(
            left_card,
            text="●  13 个按键均可配置",
            bg="#eafaf4",
            fg=SUCCESS,
            font=("Microsoft YaHei UI", 8, "bold"),
            padx=9,
            pady=4,
        ).pack(anchor="w", padx=20, pady=(12, 0))
        self.canvas = tk.Canvas(
            left_card,
            width=360,
            height=530,
            bg="#fbfcfe",
            highlightthickness=0,
            cursor="hand2",
        )
        self.canvas.pack(padx=10, pady=(10, 0))
        self.canvas.bind("<Button-1>", self._canvas_click)
        self.canvas.bind("<Motion>", self._canvas_motion)
        self.canvas.bind("<Leave>", self._canvas_leave)
        tk.Label(
            left_card,
            text="MiVibe Remote 2  ·  蓝色光圈表示当前按键",
            bg=CARD,
            fg=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="center", pady=(0, 14))

        right_card = tk.Frame(
            body,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=26,
            pady=22,
        )
        right_card.grid(row=0, column=1, sticky="nsew")

        tk.Label(
            right_card,
            text="按键映射",
            bg=CARD,
            fg=BLUE,
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(anchor="w")
        tk.Label(
            right_card,
            textvariable=self.selected_label_var,
            bg=CARD,
            fg=TEXT,
            font=("Microsoft YaHei UI", 20, "bold"),
        ).pack(anchor="w", pady=(3, 14))

        current_box = tk.Frame(
            right_card,
            bg=SOFT_GRAY,
            highlightbackground="#e7ecf3",
            highlightthickness=1,
            padx=16,
            pady=12,
        )
        current_box.pack(fill="x")
        tk.Label(
            current_box,
            text="当前映射",
            bg=SOFT_GRAY,
            fg=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w")
        tk.Label(
            current_box,
            textvariable=self.current_mapping_var,
            bg=SOFT_GRAY,
            fg=TEXT,
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(anchor="w", pady=(3, 0))

        self.capture_button = ttk.Button(
            right_card,
            text="按真实键盘录入",
            command=self.toggle_capture,
            style="Capture.TButton",
        )
        self.capture_button.pack(fill="x", pady=(16, 0))
        tk.Label(
            right_card,
            textvariable=self.capture_status_var,
            bg=CARD,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(7, 0))

        result_box = tk.Frame(
            right_card,
            bg=SOFT_BLUE,
            highlightbackground="#bcdcff",
            highlightthickness=1,
            padx=16,
            pady=12,
        )
        result_box.pack(fill="x", pady=(14, 0))
        tk.Label(
            result_box,
            text="将要应用",
            bg=SOFT_BLUE,
            fg=BLUE_DARK,
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w")
        tk.Label(
            result_box,
            textvariable=self.result_mapping_var,
            bg=SOFT_BLUE,
            fg=TEXT,
            font=("Microsoft YaHei UI", 14, "bold"),
        ).pack(anchor="w", pady=(3, 0))
        tk.Label(
            result_box,
            textvariable=self.encoding_var,
            bg=SOFT_BLUE,
            fg=MUTED,
            font=("Consolas", 8),
            wraplength=510,
            justify="left",
        ).pack(anchor="w", pady=(5, 0))

        manual_row = tk.Frame(right_card, bg=CARD)
        manual_row.pack(fill="x", pady=(14, 0))
        self.manual_entry = ttk.Entry(manual_row, textvariable=self.manual_var)
        self.manual_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(
            manual_row,
            text="手动应用",
            command=self.apply_manual,
            style="Quiet.TButton",
        ).pack(side="left", padx=(8, 0))
        tk.Label(
            right_card,
            text="也可以手动输入，例如 Ctrl+Alt+V",
            bg=CARD,
            fg=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(4, 0))

        mouse_row = tk.Frame(right_card, bg=CARD)
        mouse_row.pack(fill="x", pady=(12, 0))
        tk.Label(
            mouse_row,
            text="鼠标滚轮",
            bg=CARD,
            fg=MUTED,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        ttk.Button(
            mouse_row,
            text="滚轮向上",
            command=lambda: self.set_selected_to_mouse_wheel(120),
            style="Quiet.TButton",
        ).pack(side="left", padx=(10, 0))
        ttk.Button(
            mouse_row,
            text="滚轮向下",
            command=lambda: self.set_selected_to_mouse_wheel(-120),
            style="Quiet.TButton",
        ).pack(side="left", padx=(8, 0))

        key_buttons = tk.Frame(right_card, bg=CARD)
        key_buttons.pack(fill="x", pady=(13, 0))
        ttk.Button(
            key_buttons,
            text="清除映射",
            command=self.clear_selected,
            style="Quiet.TButton",
        ).pack(side="left")
        ttk.Button(
            key_buttons,
            text="恢复默认",
            command=self.restore_selected,
            style="Quiet.TButton",
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            key_buttons,
            text="设为模式切换键",
            command=self.set_selected_to_preset_cycle,
            style="Quiet.TButton",
        ).pack(side="left", padx=(8, 0))

        tk.Frame(right_card, bg="#e5eaf1", height=1).pack(fill="x", pady=(20, 16))
        tk.Label(
            right_card,
            text="语音输入",
            bg=CARD,
            fg=TEXT,
            font=("Microsoft YaHei UI", 12, "bold"),
        ).pack(anchor="w")
        tk.Label(
            right_card,
            text="设置遥控器麦克风对应的触发方式和声音增益",
            bg=CARD,
            fg=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(3, 0))
        voice_row = tk.Frame(
            right_card,
            bg=SOFT_GRAY,
            highlightbackground="#e7ecf3",
            highlightthickness=1,
            padx=14,
            pady=12,
        )
        voice_row.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(
            voice_row,
            text="启用语音快捷键",
            variable=self.voice_enabled,
            style="Voice.TCheckbutton",
        ).pack(side="left")
        tk.Label(
            voice_row,
            text="触发方式",
            bg=SOFT_GRAY,
            fg=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(side="left", padx=(20, 6))
        self.voice_mode_combo = ttk.Combobox(
            voice_row,
            textvariable=self.voice_trigger_mode,
            values=("开关型", "按住型"),
            state="readonly",
            width=8,
        )
        self.voice_mode_combo.pack(side="left", padx=(12, 0))
        self.voice_mode_combo.bind("<<ComboboxSelected>>", self._voice_mode_changed)
        self.voice_help_label = tk.Label(
            right_card,
            textvariable=self.voice_help_var,
            bg="#f2f7fd",
            fg=TEXT,
            font=("Microsoft YaHei UI", 8),
            justify="left",
            anchor="w",
            padx=14,
            pady=10,
        )
        self.voice_help_label.pack(fill="x", pady=(10, 0))
        tk.Label(
            voice_row,
            text="增益 dB",
            bg=SOFT_GRAY,
            fg=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(side="left", padx=(20, 6))
        ttk.Entry(voice_row, textvariable=self.gain_db, width=7).pack(side="left")

        footer = tk.Frame(
            outer,
            bg=CARD,
            highlightbackground=BORDER,
            highlightthickness=1,
            padx=18,
            pady=13,
        )
        footer.pack(fill="x", pady=(12, 0))
        preset_area = tk.Frame(footer, bg=CARD)
        preset_area.pack(side="left")
        self.preset_area = preset_area
        tk.Label(
            preset_area,
            text="快捷预设",
            bg=CARD,
            fg=TEXT,
            font=("Microsoft YaHei UI", 9, "bold"),
        ).pack(side="left", padx=(0, 10))
        for preset_id, label, command in (
            ("codex", "Codex", self.apply_codex_preset),
            ("workbuddy", "WorkBuddy", self.apply_workbuddy_preset),
            ("wechat", "微信输入", self.apply_wechat_preset),
            ("qianwen", "千问办公", self.apply_qianwen_preset),
        ):
            button = ttk.Button(
                preset_area,
                text=label,
                command=command,
                style="Preset.TButton",
            )
            button.pack(side="left", padx=(0, 7))
            self.preset_buttons[preset_id] = button
        for preset_id, details in self.working_custom_presets.items():
            self._add_custom_preset_button(
                preset_id, str(details.get("name", "自定义"))
            )
        self.add_preset_button = ttk.Button(
            preset_area,
            text="＋ 新增自定义",
            command=self.add_custom_preset,
            style="Preset.TButton",
        )
        self.add_preset_button.pack(side="left", padx=(0, 7))
        action_area = tk.Frame(footer, bg=CARD)
        action_area.pack(side="right")
        ttk.Button(
            action_area,
            text="关闭",
            command=self.close,
            style="Quiet.TButton",
        ).pack(side="right")
        ttk.Button(
            action_area,
            text="保存并应用",
            command=self.save,
            style="Primary.TButton",
        ).pack(side="right", padx=(0, 9))
        ttk.Button(
            action_area,
            text="重置",
            command=self.restore_all,
            style="Quiet.TButton",
        ).pack(side="right", padx=(0, 9))

        status_bar = tk.Frame(outer, bg=BG)
        status_bar.pack(fill="x", pady=(7, 0))
        tk.Label(
            status_bar,
            text="●",
            bg=BG,
            fg=SUCCESS,
            font=("Segoe UI", 8),
        ).pack(side="left")
        tk.Label(
            status_bar,
            textvariable=self.save_status_var,
            bg=BG,
            fg=MUTED,
            font=("Microsoft YaHei UI", 8),
        ).pack(side="left", padx=(5, 0))

        self._refresh_preset_styles()
        self.draw_remote()

    def _refresh_preset_styles(self) -> None:
        labels = {
            "codex": "Codex 模式",
            "workbuddy": "WorkBuddy 模式",
            "wechat": "微信输入模式",
            "qianwen": "千问办公模式",
        }
        custom = self.working_custom_presets.get(self.working_preset, {})
        self.preset_name_var.set(
            labels.get(
                self.working_preset,
                f"{custom.get('name', '自定义')} 模式",
            )
        )
        for preset_id, button in self.preset_buttons.items():
            button.configure(
                style=(
                    "PresetActive.TButton"
                    if preset_id == self.working_preset
                    else "Preset.TButton"
                )
            )

    def _display_bbox(self, source_bbox: tuple[int, int, int, int]) -> tuple[float, ...]:
        left, top, _right, _bottom = REMOTE_CROP
        scale = REMOTE_PHOTO_HEIGHT / (REMOTE_CROP[3] - REMOTE_CROP[1])
        photo_width = (REMOTE_CROP[2] - REMOTE_CROP[0]) * scale
        offset_x = (360 - photo_width) / 2
        x1, y1, x2, y2 = source_bbox
        return (
            offset_x + (x1 - left) * scale,
            (y1 - top) * scale,
            offset_x + (x2 - left) * scale,
            (y2 - top) * scale,
        )

    def draw_remote(self) -> None:
        self.canvas.delete("all")
        self._draw_remote_silhouette()
        self._draw_hotspot_overlay()

    def _draw_remote_silhouette(self) -> None:
        """Draw a clean silver Remote 2 fallback without third-party artwork."""

        def rounded_box(
            x1: float,
            y1: float,
            x2: float,
            y2: float,
            radius: float,
            *,
            fill: str,
            outline: str = "",
            width: int = 1,
            tags: tuple[str, ...] = (),
        ) -> None:
            points = (
                x1 + radius,
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
                y2,
                x2 - radius,
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
                y1,
            )
            self.canvas.create_polygon(
                points,
                smooth=True,
                splinesteps=24,
                fill=fill,
                outline=outline,
                width=width,
                tags=tags,
            )

        left, top, right, bottom = 115, 3, 245, 527
        rounded_box(
            left + 4,
            top + 5,
            right + 5,
            bottom + 4,
            17,
            fill="#c9c9cc",
            tags=("remote_shadow",),
        )
        rounded_box(
            left,
            top,
            right,
            bottom,
            17,
            fill="#d7d9db",
            outline="#9fa2a5",
            width=2,
            tags=("remote_body",),
        )
        # Subtle aluminium bands make the fallback read as the real silver body
        # instead of the old black pill-shaped placeholder.
        inner_left = left + 12
        inner_right = right - 12
        aluminium = (
            "#d5d7da",
            "#e7e8ea",
            "#f2f3f4",
            "#e5e7e9",
            "#d9dbde",
            "#eef0f1",
            "#d7d9dc",
        )
        band_width = (inner_right - inner_left) / len(aluminium)
        for index, shade in enumerate(aluminium):
            self.canvas.create_rectangle(
                inner_left + index * band_width,
                top + 13,
                inner_left + (index + 1) * band_width + 1,
                bottom - 13,
                fill=shade,
                outline="",
                tags=("remote_body",),
            )
        self.canvas.create_line(
            left + 11,
            top + 20,
            left + 11,
            bottom - 20,
            fill="#f7f7f8",
            width=2,
            tags=("remote_body",),
        )
        self.canvas.create_line(
            right - 11,
            top + 20,
            right - 11,
            bottom - 20,
            fill="#b9bbbd",
            tags=("remote_body",),
        )

        button_fill = "#171b22"
        button_outline = "#0e0f11"
        glyph = "#f6f7f8"

        def button_oval(
            button_id: str,
            label: str,
            size: int = 10,
            *,
            label_color: str = glyph,
        ) -> None:
            x1, y1, x2, y2 = self._display_bbox(REMOTE_HOTSPOTS[button_id][:4])
            self.canvas.create_oval(
                x1,
                y1,
                x2,
                y2,
                fill=button_fill,
                outline=button_outline,
                width=2,
                tags=("remote_button",),
            )
            self.canvas.create_arc(
                x1 + 2,
                y1 + 2,
                x2 - 2,
                y2 - 2,
                start=25,
                extent=130,
                style="arc",
                outline="#55585d",
                tags=("remote_button",),
            )
            self.canvas.create_text(
                (x1 + x2) / 2,
                (y1 + y2) / 2,
                text=label,
                fill=label_color,
                font=("Segoe UI Symbol", size, "bold"),
                tags=("remote_button",),
            )

        button_oval("power", "⏻", 11, label_color="#ff645f")
        button_oval("mic", "●", 7, label_color=CYAN)
        mic_x1, mic_y1, mic_x2, mic_y2 = self._display_bbox(
            REMOTE_HOTSPOTS["mic"][:4]
        )
        mic_cx = (mic_x1 + mic_x2) / 2
        mic_cy = (mic_y1 + mic_y2) / 2
        self.canvas.create_line(
            mic_cx,
            mic_cy + 2,
            mic_cx,
            mic_cy + 8,
            fill=CYAN,
            width=2,
            tags=("remote_button",),
        )
        self.canvas.create_arc(
            mic_cx - 5,
            mic_cy - 2,
            mic_cx + 5,
            mic_cy + 8,
            start=180,
            extent=180,
            style="arc",
            outline=CYAN,
            width=2,
            tags=("remote_button",),
        )

        # One circular D-pad ring, matching the actual product construction.
        self.canvas.create_oval(
            126,
            68,
            234,
            177,
            fill=button_fill,
            outline=button_outline,
            width=2,
            tags=("remote_button",),
        )
        self.canvas.create_arc(
            130,
            72,
            230,
            173,
            start=28,
            extent=120,
            style="arc",
            outline="#505258",
            tags=("remote_button",),
        )
        for button_id, label in (
            ("up", "↑"),
            ("left", "←"),
            ("right", "→"),
            ("down", "↓"),
        ):
            x1, y1, x2, y2 = self._display_bbox(REMOTE_HOTSPOTS[button_id][:4])
            self.canvas.create_text(
                (x1 + x2) / 2,
                (y1 + y2) / 2,
                text=label,
                fill="#d8dade",
                font=("Segoe UI Symbol", 10),
                tags=("remote_button",),
            )
        ok_x1, ok_y1, ok_x2, ok_y2 = self._display_bbox(REMOTE_HOTSPOTS["ok"][:4])
        self.canvas.create_oval(
            ok_x1,
            ok_y1,
            ok_x2,
            ok_y2,
            fill="#282a2e",
            outline="#07080a",
            width=2,
            tags=("remote_button",),
        )
        self.canvas.create_text(
            (ok_x1 + ok_x2) / 2,
            (ok_y1 + ok_y2) / 2,
            text="OK",
            fill=glyph,
            font=("Segoe UI", 9, "bold"),
            tags=("remote_button",),
        )

        button_oval("back", "‹", 17)
        button_oval("home", "⌂", 11)
        button_oval("menu", "☰", 10)
        button_oval("tv", "TV", 7)

        volume_top = self._display_bbox(REMOTE_HOTSPOTS["volume_up"][:4])
        volume_bottom = self._display_bbox(REMOTE_HOTSPOTS["volume_down"][:4])
        vx1, vx2 = volume_top[0], volume_top[2]
        vy1, vy2 = volume_top[1], volume_bottom[3]
        rounded_box(
            vx1,
            vy1,
            vx2,
            vy2,
            (vx2 - vx1) / 2,
            fill=button_fill,
            outline=button_outline,
            width=2,
            tags=("remote_button",),
        )
        self.canvas.create_line(
            vx1 + 5,
            (volume_top[3] + volume_bottom[1]) / 2,
            vx2 - 5,
            (volume_top[3] + volume_bottom[1]) / 2,
            fill="#484a4f",
            tags=("remote_button",),
        )
        self.canvas.create_text(
            (vx1 + vx2) / 2,
            (volume_top[1] + volume_top[3]) / 2,
            text="+",
            fill=glyph,
            font=("Segoe UI", 16),
            tags=("remote_button",),
        )
        self.canvas.create_text(
            (vx1 + vx2) / 2,
            (volume_bottom[1] + volume_bottom[3]) / 2,
            text="−",
            fill=glyph,
            font=("Segoe UI", 15),
            tags=("remote_button",),
        )

        self.canvas.create_oval(
            175,
            400,
            185,
            410,
            outline="#858a91",
            width=1,
            tags=("remote_body",),
        )
        self.canvas.create_line(
            177,
            408,
            177,
            402,
            183,
            408,
            183,
            402,
            fill="#858a91",
            width=1,
            tags=("remote_body",),
        )
        self.canvas.create_text(
            180,
            488,
            text="MiVibe",
            fill="#4f5967",
            font=("Segoe UI", 11, "bold"),
            tags=("remote_body",),
        )

    def _draw_hotspot_overlay(self) -> None:
        self.canvas.delete("hotspot")
        for button_id, (x1, y1, x2, y2, shape) in REMOTE_HOTSPOTS.items():
            selected = button_id == self.selected_id
            hovered = button_id == self.hovered_id
            if not selected and not hovered:
                continue
            outline = BLUE if selected else "#58a6ff"
            width = 3 if selected else 2
            bbox = self._display_bbox((x1, y1, x2, y2))
            if shape == "oval":
                self.canvas.create_oval(
                    *bbox,
                    fill="",
                    outline=outline,
                    width=width,
                    tags=("hotspot",),
                )
            else:
                self.canvas.create_rectangle(
                    *bbox,
                    fill="",
                    outline=outline,
                    width=width,
                    tags=("hotspot",),
                )

    def _button_at_canvas(self, x: float, y: float) -> str | None:
        # Prefer the OK center before the surrounding D-pad directions.
        order = ["ok", *[key for key in REMOTE_HOTSPOTS if key != "ok"]]
        for button_id in order:
            x1, y1, x2, y2, _shape = REMOTE_HOTSPOTS[button_id]
            left, top, right, bottom = self._display_bbox((x1, y1, x2, y2))
            if left <= x <= right and top <= y <= bottom:
                return button_id
        return None

    def _canvas_click(self, event) -> None:
        button_id = self._button_at_canvas(event.x, event.y)
        if button_id:
            self.select_button(button_id)

    def _canvas_motion(self, event) -> None:
        button_id = self._button_at_canvas(event.x, event.y)
        if button_id == self.hovered_id:
            return
        self.hovered_id = button_id
        self.photo_hint_var.set(
            f"{BUTTON_LABELS.get(button_id, button_id)} · {format_action(self.working_bindings.get(button_id))}"
            if button_id
            else "点击照片中的任意按键"
        )
        self._draw_hotspot_overlay()

    def _canvas_leave(self, _event) -> None:
        self.hovered_id = None
        self.photo_hint_var.set("点击照片中的任意按键")
        self._draw_hotspot_overlay()

    def select_button(self, button_id: str) -> None:
        if button_id not in BUTTON_LABELS:
            return
        if self.capture.active and not self.capture.captured:
            self.capture.cancel()
            self.capture_button.configure(text=self._capture_button_text(button_id))
        self.selected_id = button_id
        actions = self.working_bindings.get(button_id, [])
        action = first_action(actions)
        label = BUTTON_LABELS[button_id]
        mapping = format_action(actions)
        self.selected_label_var.set(label)
        self.current_mapping_var.set(mapping)
        self.result_mapping_var.set(mapping)
        self.encoding_var.set(
            "Windows 原生鼠标滚轮事件"
            if action and action.get("type") == "mouse_wheel"
            else capture_encoding(action.get("capture") if action else None)
        )
        self.manual_var.set(
            "+".join(action.get("keys", []))
            if action and action.get("type") == "hotkey"
            else ""
        )
        if button_id == "mic":
            self.capture_status_var.set(
                "已选择小米遥控器 2 语音键；可录入任意有效 Windows 单键或组合键"
            )
        else:
            self.capture_status_var.set(f"已选择 {label}，可以开始录入")
        self.capture_button.configure(text=self._capture_button_text(button_id))
        self._update_voice_help()
        self._draw_hotspot_overlay()

    @staticmethod
    def _capture_button_text(button_id: str) -> str:
        return "录入遥控器语音快捷键" if button_id == "mic" else "按真实键盘录入"

    def _voice_mode_changed(self, _event=None) -> None:
        self.save_status_var.set("有未保存的语音触发方式修改")
        self._update_voice_help()

    def _update_voice_help(self) -> None:
        action = first_action(self.working_bindings.get("mic"))
        keys = (
            hotkey_tokens(action.get("keys", []))
            if action and action.get("type") == "hotkey"
            else []
        )
        shortcut = format_keys(keys) or "未设置"
        if self.voice_trigger_mode.get() == "按住型":
            behavior = "按住型：按下语音键时持续按住快捷键，松开时释放，适合按住说话类输入法。"
        else:
            behavior = "开关型：收到语音开始和结束事件时各点按一次快捷键，适合点击开关式输入法。"
        self.voice_help_var.set(
            "小米蓝牙遥控器 2 语音键可自定义\n"
            f"当前语音快捷键：{shortcut}\n"
            "设置：点左侧麦克风键 → 点“录入遥控器语音快捷键” → 在键盘按目标组合 → 保存并应用。\n"
            f"{behavior}\n"
            "实机说话：先短按一次唤醒，再按住语音键 2 秒以上边按边说，说完松开；只点一下不会传出完整语音。\n"
            "默认值为右 Alt。修改只影响语音键，不会改动方向、音量等其他按键；单次录音最长约 60 秒。"
        )

    def toggle_capture(self) -> None:
        if self.capture.active:
            self.capture.cancel()
            self.capture_button.configure(text=self._capture_button_text(self.selected_id))
            self.capture_status_var.set("已取消录入")
            return
        self.capture_button_id = self.selected_id
        self.capture_status_var.set("正在录入：请按目标键或组合键……")
        self.capture_button.configure(text="取消录入")
        self.capture.start()

    def _capture_complete(self, result: dict) -> None:
        tokens = list(result.get("tokens", []))
        if not tokens:
            self._capture_failed("没有识别到有效按键")
            return
        try:
            if self.capture_button_id == "mic":
                resolve_hotkey_virtual_keys(tokens)
        except ValueError as exc:
            self._capture_failed(str(exc))
            return
        action = {
            "type": "hotkey",
            "keys": tokens,
            "injection": hotkey_injection_method(tokens),
            "capture": result.get("capture", {}),
        }
        self.working_bindings[self.capture_button_id] = [action]
        if self.capture_button_id == "mic":
            self.voice_enabled.set(True)
        self.capture_button.configure(text=self._capture_button_text(self.capture_button_id))
        self.selected_id = self.capture_button_id
        self.save_status_var.set("有未保存的按键修改")
        self.select_button(self.capture_button_id)
        self.capture_status_var.set(f"已录入 {format_keys(tokens)}，等待保存")

    def _capture_failed(self, error: str) -> None:
        self.capture.cancel()
        self.capture_button.configure(text=self._capture_button_text(self.selected_id))
        self.capture_status_var.set("录入失败，可以重试")
        messagebox.showerror(APP_NAME, error)

    def apply_manual(self) -> None:
        keys = split_hotkey(self.manual_var.get())
        if not keys:
            messagebox.showerror(APP_NAME, "请输入一个按键或快捷键")
            return
        try:
            if self.selected_id == "mic":
                resolve_hotkey_virtual_keys(keys)
        except ValueError as exc:
            messagebox.showerror(APP_NAME, f"语音快捷键无效：{exc}")
            return
        self.working_bindings[self.selected_id] = [
            {
                "type": "hotkey",
                "keys": keys,
                "injection": hotkey_injection_method(keys),
                "capture": {"source": "manual"},
            }
        ]
        if self.selected_id == "mic":
            self.voice_enabled.set(True)
        self.save_status_var.set("有未保存的按键修改")
        self.select_button(self.selected_id)

    def clear_selected(self) -> None:
        self.working_bindings.pop(self.selected_id, None)
        if self.selected_id == "mic":
            self.voice_enabled.set(False)
        self.save_status_var.set("有未保存的按键修改")
        self.select_button(self.selected_id)

    def set_selected_to_preset_cycle(self) -> None:
        self.working_bindings[self.selected_id] = [
            {
                "type": "preset_cycle",
                "label": "循环切换预设",
            }
        ]
        if self.selected_id == "mic":
            self.voice_enabled.set(False)
        self.save_status_var.set(
            f"{BUTTON_LABELS[self.selected_id]} 已设为循环切换预设，保存后生效"
        )
        self.select_button(self.selected_id)

    def set_selected_to_mouse_wheel(self, delta: int) -> None:
        self.working_bindings[self.selected_id] = [
            {
                "type": "mouse_wheel",
                "delta": 120 if delta > 0 else -120,
                "label": "鼠标滚轮上" if delta > 0 else "鼠标滚轮下",
            }
        ]
        if self.selected_id == "mic":
            self.voice_enabled.set(False)
        self.save_status_var.set(
            f"{BUTTON_LABELS[self.selected_id]} 已设为"
            f"{'鼠标滚轮上' if delta > 0 else '鼠标滚轮下'}，保存后生效"
        )
        self.select_button(self.selected_id)

    def restore_selected(self) -> None:
        defaults = {
            "codex": codex_button_bindings,
            "workbuddy": workbuddy_button_bindings,
            "wechat": wechat_button_bindings,
            "qianwen": qianwen_button_bindings,
        }
        if self.working_preset in defaults:
            default_bindings = defaults[self.working_preset]()
        else:
            default_bindings = saved_preset_button_bindings(
                self.keys_config, self.working_preset
            )
        self.working_bindings[self.selected_id] = copy.deepcopy(
            default_bindings[self.selected_id]
        )
        if self.selected_id == "mic":
            self.voice_enabled.set(True)
        self.save_status_var.set("有未保存的按键修改")
        self.select_button(self.selected_id)

    def restore_all(self) -> None:
        if not messagebox.askyesno(APP_NAME, "恢复所有按键的默认映射？"):
            return
        self.working_preset = "codex"
        self.working_bindings = codex_button_bindings()
        self.working_profiles = {
            "codex": codex_button_bindings(),
            "workbuddy": workbuddy_button_bindings(),
            "wechat": wechat_button_bindings(),
            "qianwen": qianwen_button_bindings(),
            **{
                preset: copy.deepcopy(bindings)
                for preset, bindings in self.working_profiles.items()
                if preset in self.working_custom_presets
            },
        }
        self.voice_enabled.set(True)
        self.voice_trigger_mode.set(
            "按住型" if CODEX_VOICE_TRIGGER_MODE == "hold" else "开关型"
        )
        self.save_status_var.set("已恢复默认，尚未保存")
        self._refresh_preset_styles()
        self.select_button(self.selected_id)

    def apply_codex_preset(self) -> None:
        self._switch_preset("codex")
        self.voice_enabled.set(True)
        self.voice_trigger_mode.set(
            "按住型" if CODEX_VOICE_TRIGGER_MODE == "hold" else "开关型"
        )
        self.save_status_var.set("已载入 Codex 预设，点击“保存并应用”后生效")
        self._refresh_preset_styles()
        self.selected_id = "power"
        self.select_button(self.selected_id)

    def apply_workbuddy_preset(self) -> None:
        self._switch_preset("workbuddy")
        self.voice_enabled.set(True)
        self.voice_trigger_mode.set(
            "按住型" if WORKBUDDY_VOICE_TRIGGER_MODE == "hold" else "开关型"
        )
        self.save_status_var.set("已载入 WorkBuddy 预设，点击“保存并应用”后生效")
        self._refresh_preset_styles()
        self.selected_id = "power"
        self.select_button(self.selected_id)

    def apply_wechat_preset(self) -> None:
        self._switch_preset("wechat")
        self.voice_enabled.set(True)
        self.voice_trigger_mode.set(
            "按住型" if WECHAT_VOICE_TRIGGER_MODE == "hold" else "开关型"
        )
        self.save_status_var.set("已载入微信预设，点击“保存并应用”后生效")
        self._refresh_preset_styles()
        self.selected_id = "power"
        self.select_button(self.selected_id)

    def apply_qianwen_preset(self) -> None:
        self._switch_preset("qianwen")
        self.voice_enabled.set(True)
        self.voice_trigger_mode.set(
            "按住型" if QIANWEN_VOICE_TRIGGER_MODE == "hold" else "开关型"
        )
        self.save_status_var.set("已载入千问办公预设，点击“保存并应用”后生效")
        self._refresh_preset_styles()
        self.selected_id = "power"
        self.select_button(self.selected_id)

    def _add_custom_preset_button(self, preset_id: str, name: str) -> None:
        if self.preset_area is None or preset_id in self.preset_buttons:
            return
        button = ttk.Button(
            self.preset_area,
            text=name,
            command=lambda value=preset_id: self.apply_custom_preset(value),
            style="Preset.TButton",
        )
        pack_options = {"side": "left", "padx": (0, 7)}
        if self.add_preset_button is not None:
            pack_options["before"] = self.add_preset_button
        button.pack(**pack_options)
        self.preset_buttons[preset_id] = button

    def add_custom_preset(self) -> None:
        name = simpledialog.askstring(
            APP_NAME,
            "给新的自定义预设起个名字（最多 20 个字符）：",
            parent=self.root,
        )
        if name is None:
            return
        name = name.strip()
        if not name:
            messagebox.showerror(APP_NAME, "预设名称不能为空。")
            return
        if len(name) > 20:
            messagebox.showerror(APP_NAME, "预设名称不能超过 20 个字符。")
            return
        existing_names = {
            str(details.get("name", "")).casefold()
            for details in self.working_custom_presets.values()
        }
        if name.casefold() in existing_names:
            messagebox.showerror(APP_NAME, "已经有同名的自定义预设。")
            return

        self._remember_working_preset()
        preset_id = f"custom_{uuid.uuid4().hex[:12]}"
        self.working_custom_presets[preset_id] = {
            "name": name,
            "voice_hotkey": self._current_voice_hotkey(),
            "voice_trigger_mode": self._current_voice_trigger_mode(),
            "voice_shortcut_enabled": bool(self.voice_enabled.get()),
        }
        self.working_profiles[preset_id] = copy.deepcopy(self.working_bindings)
        self.working_preset = preset_id
        self._add_custom_preset_button(preset_id, name)
        self._refresh_preset_styles()
        self.save_status_var.set(
            f"已新增自定义预设“{name}”，点击“保存并应用”后保存到本机"
        )

    def apply_custom_preset(self, preset_id: str) -> None:
        details = self.working_custom_presets.get(preset_id)
        if not isinstance(details, dict):
            return
        self._switch_preset(preset_id)
        self.voice_enabled.set(bool(details.get("voice_shortcut_enabled", True)))
        self.voice_trigger_mode.set(
            "开关型"
            if str(details.get("voice_trigger_mode", "hold")) == "toggle"
            else "按住型"
        )
        self.save_status_var.set(
            f"已载入自定义预设“{details.get('name', '自定义')}”，点击“保存并应用”后生效"
        )
        self._refresh_preset_styles()
        self.selected_id = "power"
        self.select_button(self.selected_id)

    def _current_voice_hotkey(self) -> str:
        action = first_action(self.working_bindings.get("mic"))
        if action and action.get("type") == "hotkey":
            return "+".join(hotkey_tokens(action.get("keys", [])))
        return ""

    def _current_voice_trigger_mode(self) -> str:
        return "toggle" if self.voice_trigger_mode.get() == "开关型" else "hold"

    def _remember_working_preset(self) -> None:
        self.working_profiles[self.working_preset] = copy.deepcopy(
            self.working_bindings
        )
        details = self.working_custom_presets.get(self.working_preset)
        if isinstance(details, dict):
            details["voice_hotkey"] = self._current_voice_hotkey()
            details["voice_trigger_mode"] = self._current_voice_trigger_mode()
            details["voice_shortcut_enabled"] = bool(self.voice_enabled.get())

    def _switch_preset(self, preset: str) -> None:
        cycle_bindings = self._cycle_bindings()
        self._remember_working_preset()
        self.working_preset = preset
        defaults = {
            "codex": codex_button_bindings,
            "workbuddy": workbuddy_button_bindings,
            "wechat": wechat_button_bindings,
            "qianwen": qianwen_button_bindings,
        }
        self.working_bindings = copy.deepcopy(
            self.working_profiles.get(preset)
            or (
                defaults[preset]()
                if preset in defaults
                else codex_button_bindings()
            )
        )
        self.working_bindings.update(cycle_bindings)

    def _cycle_bindings(self) -> dict:
        result = {}
        for button, actions in self.working_bindings.items():
            action_list = actions if isinstance(actions, list) else [actions]
            if any(
                isinstance(action, dict) and action.get("type") == "preset_cycle"
                for action in action_list
            ):
                result[button] = copy.deepcopy(actions)
        return result

    def save(self) -> None:
        try:
            gain = float(self.gain_db.get())
            if not -12.0 <= gain <= 30.0:
                raise ValueError("麦克风增益应在 -12 到 30 dB 之间")

            mic_action = first_action(self.working_bindings.get("mic"))
            mic_keys = (
                list(mic_action.get("keys", []))
                if mic_action and mic_action.get("type") == "hotkey"
                else []
            )
            voice_enabled = bool(self.voice_enabled.get()) and bool(mic_keys)
            if self.voice_enabled.get() and not mic_keys:
                raise ValueError("已经启用语音快捷键，请先给遥控器麦克风键录入一个快捷键")
            if mic_keys:
                resolve_hotkey_virtual_keys(mic_keys)
            voice_mode = {
                "开关型": "toggle",
                "按住型": "hold",
            }.get(self.voice_trigger_mode.get())
            if voice_mode is None:
                raise ValueError("请选择开关型或按住型语音触发方式")

            self.config["version"] = APP_VERSION
            self.config["gain_db"] = gain
            self.config["voice_shortcut_enabled"] = voice_enabled
            self.config["voice_trigger_mode"] = voice_mode
            self.config["voice_hotkey"] = "+".join(mic_keys)
            self.config["active_preset"] = self.working_preset
            self.config["raw_mapping_enabled"] = True

            self.keys_config["mapping_schema_version"] = MAPPING_SCHEMA_VERSION
            self._remember_working_preset()
            for preset, bindings in self.working_profiles.items():
                if (
                    preset in set(PRESET_ORDER) | set(self.working_custom_presets)
                    and isinstance(bindings, dict)
                ):
                    save_preset_button_bindings(
                        self.keys_config, preset, bindings
                    )
            self.keys_config["custom_presets"] = copy.deepcopy(
                self.working_custom_presets
            )
            self.keys_config["button_bindings"] = copy.deepcopy(
                self.working_bindings
            )
            address = str(self.config.get("address", "")).strip()
            if address:
                apply_remote_identity(self.config, self.keys_config, address)
            else:
                self.keys_config["device_match"] = []
                self.keys_config["allow_all_devices_for_actions"] = False
            self.keys_config["listen_keyboard"] = True
            self.keys_config["listen_mouse"] = False

            save_config(self.config, CONFIG_PATH)
            save_keys_config(self.keys_config, KEYS_CONFIG_PATH)
            try:
                bridge_pid = send_hub_restart(self.hub_port)
            except RuntimeError as exc:
                self.save_status_var.set("配置已保存，但桥接进程没有确认应用")
                messagebox.showerror(
                    APP_NAME,
                    "配置文件已经保存，但后台桥接没有重新加载。\n\n"
                    f"{exc}\n\n"
                    "在桥接重启成功前，旧快捷键仍可能继续生效。",
                )
                return
            self.save_status_var.set(
                f"已应用到桥接 PID {bridge_pid}：语音键 {format_keys(mic_keys) or '已关闭'} · {self.voice_trigger_mode.get()}"
            )
            self.select_button(self.selected_id)
            messagebox.showinfo(
                APP_NAME,
                "设置已保存并应用。\n\n"
                f"遥控器语音键：{format_keys(mic_keys) or '已关闭'}\n"
                f"触发方式：{self.voice_trigger_mode.get()}\n\n"
                "使用时先短按一次唤醒，再按住语音键 2 秒以上边按边说，说完松开。\n"
                "如果目标输入法没有响应，请确认它的快捷键与这里完全一致，并检查是否选对开关型/按住型。",
            )
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"保存失败：{exc}")

    def close(self) -> None:
        self.capture.cancel()
        self.instance_stop.set()
        if self.instance_socket is not None:
            try:
                self.instance_socket.close()
            except OSError:
                pass
            self.instance_socket = None
        self.root.destroy()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--hub-port", type=int, default=DEFAULT_HUB_PORT)
    args = parser.parse_args(argv)
    try:
        instance_socket = claim_settings_instance(args.hub_port)
    except RuntimeError as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(APP_NAME, str(exc))
        root.destroy()
        return 1
    if instance_socket is None:
        return 0
    root = tk.Tk()
    try:
        XiaomiSettingsWindow(root, args.hub_port, instance_socket)
        root.mainloop()
    finally:
        try:
            instance_socket.close()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
