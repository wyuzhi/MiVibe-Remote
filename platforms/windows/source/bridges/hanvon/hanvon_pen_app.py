# -*- coding: utf-8 -*-
"""Hanvon V60 / Ai Pointer voice pen bridge application.

Windows-only tray application with configurable pen-key mappings.
The low-level HID and microphone handshake code stays in voice_typing_hid.py.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
import winreg

import pystray
from PIL import Image, ImageDraw

from . import voice_typing_hid as core
from bridges.audio_client import AudioRouterClient, AudioRouterError
from bridges.native_audio import NativeAudioSessionClient, standalone_native_audio_enabled
from bridges.physical_hotkey_monitor import PhysicalHotkeyMonitor
from bridges.shortcut_capture import KeyboardShortcutCapture, tokens_to_display


APP_NAME = os.environ.get("REMOTE_BRIDGE_V60_APP_NAME", "汉王语音笔桥接")
APP_ID = "HanvonPenBridge"
APP_VERSION = os.environ.get("REMOTE_BRIDGE_V60_VERSION", "0.3.1")
SUPPORTED_OS_NOTE = "暂时只支持 Windows"
DEFAULT_HUB_PORT = 28690

ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
APPDATA = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_ID
CONFIG_PATH = APPDATA / "config.json"
LOG_PATH = APPDATA / "HanvonPenBridge.log"
VOICE_RUNTIME_PATH = APPDATA / "voice-runtime.json"

STARTUP_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_REG_NAME = "HanvonPenBridge"


ACTION_LABELS = {
    "disabled": "禁用",
    "right_alt": "右 Alt 键（Right Alt）",
    "enter": "回车键（Enter）",
    "backspace": "退格键（Backspace）",
    "ctrl_backspace": "Ctrl + 退格键（Backspace）",
    "tail_backspace": "移到末尾后删除",
    "left_click": "鼠标左键点击",
    "click_enter": "点击后按回车键（Enter）",
    "custom_hotkey": "自定义热键",
}

ACTION_IDS_BY_LABEL = {label: action_id for action_id, label in ACTION_LABELS.items()}

PEN_KEYS = [
    ("mic", "麦克风键"),
    ("pageup", "上翻页键"),
    ("pagedown", "下翻页键"),
]


def app_log(message: str) -> None:
    APPDATA.mkdir(parents=True, exist_ok=True)
    try:
        if LOG_PATH.exists() and LOG_PATH.stat().st_size > 2_000_000:
            old = APPDATA / "HanvonPenBridge.log.1"
            if old.exists():
                old.unlink()
            LOG_PATH.rename(old)
    except Exception:
        pass
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"[{core.ts()}] {message}\n")


def _normalize_mapping(action_id: str) -> dict:
    if action_id == "disabled":
        return {"type": "disabled", "value": "", "custom": ""}
    if action_id == "custom_hotkey":
        return {"type": "hotkey", "value": "", "custom": "Ctrl+Alt+V"}
    return {"type": "action", "value": action_id, "custom": ""}


def default_config() -> dict:
    cfg = copy.deepcopy(core.DEFAULT_CONFIG)
    cfg.update(
        {
            "app_version": APP_VERSION,
            "start_minimized": False,
            "show_window_on_start": True,
            "auto_start": False,
            "retry_device_seconds": 2.0,
            "keyboard_hotkey_refresh": "Right Alt",
            "voice_shortcut_enabled": True,
            "voice_hotkey": "Right Alt",
            "voice_trigger_mode": "toggle",
            "pen_mappings": {
                "mic": {"type": "hotkey", "value": "Right Alt", "custom": "Right Alt"},
                "pageup": _normalize_mapping("tail_backspace"),
                "pagedown": _normalize_mapping("click_enter"),
            },
        }
    )
    return cfg


def migrate_legacy_config(cfg: dict) -> dict:
    cfg = copy.deepcopy(cfg)
    if "pen_mappings" not in cfg:
        old = cfg.get("key_to_action", {})
        cfg["pen_mappings"] = {
            "mic": _normalize_mapping(old.get("mic", "right_alt")),
            "pageup": _normalize_mapping(old.get("pageup", "tail_backspace")),
            "pagedown": _normalize_mapping(old.get("pagedown", "click_enter")),
        }
    for key, action_id in {"mic": "right_alt", "pageup": "tail_backspace", "pagedown": "click_enter"}.items():
        mapping = cfg["pen_mappings"].get(key)
        if not isinstance(mapping, dict):
            cfg["pen_mappings"][key] = _normalize_mapping(action_id)
    if "keyboard_hotkey_refresh" not in cfg:
        raw = cfg.get("keyboard_hotkey_vks") or [cfg.get("keyboard_hotkey_vk", "0xA5")]
        if raw == ["0xA5"] or raw == [0xA5]:
            cfg["keyboard_hotkey_refresh"] = "Right Alt"
        elif raw == ["0x12"] or raw == [0x12]:
            cfg["keyboard_hotkey_refresh"] = "Alt"
        else:
            cfg["keyboard_hotkey_refresh"] = "Right Alt"
    mic_mapping = cfg.get("pen_mappings", {}).get("mic", {})
    if "voice_shortcut_enabled" not in cfg:
        cfg["voice_shortcut_enabled"] = mic_mapping.get("type") != "disabled"
    if "voice_hotkey" not in cfg:
        if mic_mapping.get("type") == "hotkey":
            cfg["voice_hotkey"] = (
                mic_mapping.get("custom") or mic_mapping.get("value") or "Right Alt"
            )
        else:
            cfg["voice_hotkey"] = "Right Alt"
    if cfg.get("voice_trigger_mode") not in {"toggle", "hold"}:
        cfg["voice_trigger_mode"] = "toggle"
    cfg["keyboard_hotkey_refresh"] = cfg.get("voice_hotkey", "Right Alt")
    cfg["app_version"] = APP_VERSION
    return cfg


def load_app_config() -> dict:
    APPDATA.mkdir(parents=True, exist_ok=True)
    cfg = default_config()
    loaded = None
    if CONFIG_PATH.exists():
        loaded = CONFIG_PATH
    elif (ROOT / "voice_typing_hid_config.json").exists():
        loaded = ROOT / "voice_typing_hid_config.json"
    if loaded:
        try:
            loaded_cfg = json.loads(loaded.read_text(encoding="utf-8-sig"))
            cfg.update(loaded_cfg)
            for new_key in (
                "voice_shortcut_enabled",
                "voice_hotkey",
                "voice_trigger_mode",
            ):
                if new_key not in loaded_cfg:
                    cfg.pop(new_key, None)
        except Exception as exc:
            app_log(f"config load error from {loaded}: {exc}")
    cfg = migrate_legacy_config(cfg)
    save_app_config(cfg)
    return cfg


def save_app_config(cfg: dict) -> None:
    APPDATA.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


VK_MAP = {
    "CTRL": 0x11,
    "CONTROL": 0x11,
    "LEFT CTRL": 0xA2,
    "RIGHT CTRL": 0xA3,
    "SHIFT": 0x10,
    "LEFT SHIFT": 0xA0,
    "RIGHT SHIFT": 0xA1,
    "ALT": 0x12,
    "LEFT ALT": 0xA4,
    "RIGHT ALT": 0xA5,
    "MENU": 0x12,
    "WIN": 0x5B,
    "WINDOWS": 0x5B,
    "LEFT WIN": 0x5B,
    "RIGHT WIN": 0x5C,
    "ENTER": 0x0D,
    "RETURN": 0x0D,
    "BACKSPACE": 0x08,
    "BKSP": 0x08,
    "SPACE": 0x20,
    "TAB": 0x09,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "DELETE": 0x2E,
    "DEL": 0x2E,
    "INSERT": 0x2D,
    "INS": 0x2D,
    "HOME": 0x24,
    "END": 0x23,
    "PAGEUP": 0x21,
    "PAGE UP": 0x21,
    "PGUP": 0x21,
    "PAGEDOWN": 0x22,
    "PAGE DOWN": 0x22,
    "PGDN": 0x22,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "左 CTRL": 0xA2,
    "右 CTRL": 0xA3,
    "左 SHIFT": 0xA0,
    "右 SHIFT": 0xA1,
    "左 ALT": 0xA4,
    "右 ALT": 0xA5,
    "左 WIN": 0x5B,
    "右 WIN": 0x5C,
    "回车键": 0x0D,
    "退格键": 0x08,
    "空格键": 0x20,
    "制表键": 0x09,
    "退出键": 0x1B,
    "删除键": 0x2E,
    "插入键": 0x2D,
    "起始键": 0x24,
    "结束键": 0x23,
    "上翻页键": 0x21,
    "下翻页键": 0x22,
    "左方向键": 0x25,
    "上方向键": 0x26,
    "右方向键": 0x27,
    "下方向键": 0x28,
    "退出键（ESC）": 0x1B,
    "回车键（ENTER）": 0x0D,
    "空格键（SPACE）": 0x20,
    "制表键（TAB）": 0x09,
    "退格键（BACKSPACE）": 0x08,
    "删除键（DELETE）": 0x2E,
    "插入键（INSERT）": 0x2D,
    "起始键（HOME）": 0x24,
    "结束键（END）": 0x23,
    "上翻页键（PAGE UP）": 0x21,
    "下翻页键（PAGE DOWN）": 0x22,
    "左方向键（LEFT）": 0x25,
    "上方向键（UP）": 0x26,
    "右方向键（RIGHT）": 0x27,
    "下方向键（DOWN）": 0x28,
    "-": 0xBD,
    "=": 0xBB,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    ";": 0xBA,
    "[": 0xDB,
    "\\": 0xDC,
    "]": 0xDD,
    "'": 0xDE,
}

for i in range(1, 25):
    VK_MAP[f"F{i}"] = 0x6F + i
for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    VK_MAP[ch] = ord(ch)
for ch in "0123456789":
    VK_MAP[ch] = ord(ch)
for i in range(10):
    VK_MAP[f"NUM{i}"] = 0x60 + i


def parse_hotkey(text: str) -> list[int]:
    parts = [p.strip().upper() for p in text.replace("＋", "+").split("+") if p.strip()]
    vks = []
    for part in parts:
        if part.startswith("0X"):
            vk = int(part, 16)
        elif part.isdigit():
            vk = int(part)
        else:
            vk = VK_MAP.get(part)
        if vk is None:
            raise ValueError(f"不认识的按键: {part}")
        if vk not in vks:
            vks.append(vk)
    if not vks:
        raise ValueError("热键不能为空")
    return vks


def vk_input(vk: int, key_up: bool = False) -> core.INPUT:
    flags = core.KEYEVENTF_KEYUP if key_up else 0
    return core.INPUT(core.INPUT_KEYBOARD, core.INPUT_UNION(ki=core.KEYBDINPUT(vk, 0, flags, 0, 0)))


def send_hotkey(text: str) -> None:
    vks = parse_hotkey(text)
    items = [vk_input(vk, False) for vk in vks] + [vk_input(vk, True) for vk in reversed(vks)]
    core._send(tuple(items))


def send_hotkey_down(text: str) -> None:
    core._send(tuple(vk_input(vk, False) for vk in parse_hotkey(text)))


def send_hotkey_up(text: str) -> None:
    core._send(tuple(vk_input(vk, True) for vk in reversed(parse_hotkey(text))))


def do_backspace() -> None:
    core._send((core._scan(0x0E), core._scan(0x0E, up=True)))


def do_ctrl_backspace() -> None:
    core._send((core._scan(0x1D), core._scan(0x0E), core._scan(0x0E, up=True), core._scan(0x1D, up=True)))


def execute_mapping(mapping: dict) -> str:
    mapping_type = mapping.get("type", "action")
    if mapping_type == "disabled":
        return "disabled"
    if mapping_type == "hotkey":
        hotkey = mapping.get("custom") or mapping.get("value")
        send_hotkey(hotkey)
        return f"hotkey:{hotkey}"
    action = mapping.get("value", "disabled")
    if action == "disabled":
        return "disabled"
    if action == "right_alt":
        core.do_right_alt()
    elif action == "enter":
        core.do_enter()
    elif action == "backspace":
        do_backspace()
    elif action == "ctrl_backspace":
        do_ctrl_backspace()
    elif action == "tail_backspace":
        core.do_tail_backspace()
    elif action == "left_click":
        core.do_left_click()
    elif action == "click_enter":
        core.do_left_click()
        time.sleep(0.08)
        core.do_enter()
    else:
        raise ValueError(f"未知动作: {action}")
    return action


def install_startup(enable: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
        if enable:
            exe = Path(sys.executable).resolve()
            winreg.SetValueEx(key, STARTUP_REG_NAME, 0, winreg.REG_SZ, f'"{exe}" --minimized')
        else:
            try:
                winreg.DeleteValue(key, STARTUP_REG_NAME)
            except FileNotFoundError:
                pass
    if not enable:
        for link in startup_link_paths():
            try:
                link.unlink()
            except FileNotFoundError:
                pass


def is_startup_enabled() -> bool:
    if any(link.exists() for link in startup_link_paths()):
        return True
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_REG_PATH, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, STARTUP_REG_NAME)
        return bool(value)
    except FileNotFoundError:
        return False


def startup_link_paths() -> list[Path]:
    return [
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "HanvonPenBridge.lnk",
        Path(os.environ.get("USERPROFILE", "")) / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "HanvonPenBridge.lnk",
    ]


def open_folder(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.Popen(["explorer", str(path)])


class BridgeEngine:
    def __init__(self, cfg: dict):
        self._config = copy.deepcopy(cfg)
        self._config_lock = threading.Lock()
        self._status_lock = threading.Lock()
        self._status = {
            "state": "starting",
            "message": "正在启动",
            "opened": 0,
            "last_event": "",
            "updated_at": core.ts(),
        }
        self._stop = threading.Event()
        self._restart = threading.Event()
        self._audio_lock = threading.Lock()
        self._audio_token: str | None = None
        self._voice_lock = threading.RLock()
        self._voice_active = False
        self._shortcut_ignore_until = 0.0
        self._voice_shortcut_down = False
        self._held_voice_hotkey = ""
        self._audio_router = (
            NativeAudioSessionClient("hanvon")
            if standalone_native_audio_enabled()
            else AudioRouterClient("hanvon")
        )
        self._keyboard_hook_failed = threading.Event()
        self._physical_hotkey_monitor = PhysicalHotkeyMonitor(
            self._physical_hotkey_target,
            self._handle_physical_hotkey_edge,
            self._physical_hotkey_error,
            lambda: app_log("physical keyboard state monitor ready injected_filter=true"),
            thread_name="hanvon-physical-hotkey-monitor",
        )
        self._thread = threading.Thread(target=self._run, name="hanvon-bridge-engine", daemon=True)
        self._keyboard_thread = threading.Thread(target=self._keyboard_hotkey_loop, name="hanvon-keyboard-monitor", daemon=True)
        self._audio_watchdog_thread = threading.Thread(
            target=self._audio_watchdog_loop,
            name="hanvon-audio-state-watchdog",
            daemon=True,
        )

    def start(self) -> None:
        self._recover_stale_voice_state()
        self._thread.start()
        self._physical_hotkey_monitor.start()
        self._keyboard_thread.start()
        self._audio_watchdog_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._restart.set()
        self._physical_hotkey_monitor.stop()
        self._close_all_audio("engine_stop")

    def restart(self) -> None:
        app_log("bridge restart requested")
        self._restart.set()
        self._close_all_audio("engine_restart")

    def update_config(self, cfg: dict) -> None:
        with self._config_lock:
            self._config = copy.deepcopy(cfg)
        self._restart.set()

    def _audio_is_active(self) -> bool:
        with self._audio_lock:
            return self._audio_token is not None

    def _voice_is_active(self) -> bool:
        with self._voice_lock:
            return bool(self._voice_active)

    def _write_voice_runtime_state(
        self,
        active: bool,
        *,
        cfg: dict | None = None,
        reason: str,
    ) -> None:
        current = cfg or self.get_config()
        payload = {
            "active": bool(active),
            "shortcut_enabled": bool(current.get("voice_shortcut_enabled", True)),
            "hotkey": str(current.get("voice_hotkey", "Right Alt")),
            "mode": str(current.get("voice_trigger_mode", "toggle")),
            "pid": os.getpid(),
            "reason": str(reason),
            "updated_at": core.ts(),
        }
        APPDATA.mkdir(parents=True, exist_ok=True)
        temporary = VOICE_RUNTIME_PATH.with_suffix(
            f".json.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, VOICE_RUNTIME_PATH)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def _set_voice_active(
        self,
        active: bool,
        *,
        cfg: dict | None = None,
        reason: str,
    ) -> None:
        self._voice_active = bool(active)
        self._write_voice_runtime_state(active, cfg=cfg, reason=reason)

    def _mark_shortcut_injected(self) -> None:
        # GetAsyncKeyState may briefly observe our own SendInput chord. Keep the
        # keyboard monitor from interpreting that synthetic edge as a second,
        # physical toggle.
        self._shortcut_ignore_until = max(
            self._shortcut_ignore_until,
            time.monotonic() + 0.35,
        )

    def _send_voice_shortcut_start(self, cfg: dict) -> None:
        hotkey = str(cfg.get("voice_hotkey", "Right Alt"))
        mode = str(cfg.get("voice_trigger_mode", "toggle"))
        self._mark_shortcut_injected()
        if mode == "hold":
            send_hotkey_down(hotkey)
            self._voice_shortcut_down = True
            self._held_voice_hotkey = hotkey
        else:
            send_hotkey(hotkey)

    def _send_voice_shortcut_stop(self, cfg: dict, reason: str) -> None:
        hotkey = str(cfg.get("voice_hotkey", "Right Alt"))
        mode = str(cfg.get("voice_trigger_mode", "toggle"))
        self._mark_shortcut_injected()
        if mode == "hold":
            self._release_voice_shortcut(reason)
        else:
            send_hotkey(hotkey)

    def _recover_stale_voice_state(self) -> None:
        if not VOICE_RUNTIME_PATH.is_file():
            return
        try:
            previous = json.loads(VOICE_RUNTIME_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            app_log(f"voice runtime recovery warning: {exc}")
            return
        if not previous.get("active"):
            return
        hotkey = str(previous.get("hotkey") or "Right Alt")
        mode = str(previous.get("mode") or "toggle")
        shortcut_enabled = bool(previous.get("shortcut_enabled", True))
        recovered = not shortcut_enabled
        if shortcut_enabled:
            try:
                self._mark_shortcut_injected()
                if mode == "hold":
                    send_hotkey_up(hotkey)
                else:
                    send_hotkey(hotkey)
                recovered = True
                app_log(
                    "voice state recovered "
                    f"previous_pid={previous.get('pid')} mode={mode} hotkey={hotkey}"
                )
            except Exception as exc:
                app_log(f"voice state recovery failed: {exc}")
        if recovered:
            self._write_voice_runtime_state(
                False,
                cfg={
                    "voice_shortcut_enabled": shortcut_enabled,
                    "voice_hotkey": hotkey,
                    "voice_trigger_mode": mode,
                },
                reason="startup_recovery",
            )

    def _open_pen_audio(self) -> bool:
        with self._audio_lock:
            if self._audio_token is not None:
                return True
            try:
                self._audio_token = self._audio_router.open("Ai Pointer")
                app_log("audio opened mode=toggle")
                return True
            except AudioRouterError as exc:
                app_log(f"audio open warning: {exc}")
                return False

    def _close_pen_audio(self, reason: str, tail_ms: int = 0) -> None:
        with self._audio_lock:
            if self._audio_token is None:
                return
            token = self._audio_token
            self._audio_token = None
            try:
                self._audio_router.close(token, tail_ms=tail_ms)
                app_log(f"audio close reason={reason} tail_ms={tail_ms}")
            except AudioRouterError as exc:
                app_log(f"audio close warning reason={reason}: {exc}")

    def _close_all_audio(self, reason: str) -> None:
        with self._voice_lock:
            cfg = self.get_config()
            if self._voice_active and cfg.get("voice_shortcut_enabled", True):
                try:
                    self._send_voice_shortcut_stop(cfg, reason)
                    self._set_voice_active(False, cfg=cfg, reason=reason)
                    app_log(f"voice input stopped reason={reason}")
                except Exception as exc:
                    # Keep the persisted active bit. A clean next start will
                    # retry the release instead of assuming the input is off.
                    app_log(f"voice input stop warning reason={reason}: {exc}")
            else:
                self._release_voice_shortcut(reason)
                if self._voice_active:
                    self._set_voice_active(False, cfg=cfg, reason=reason)
            self._close_pen_audio(reason)

    def _release_voice_shortcut(self, reason: str) -> None:
        if not self._voice_shortcut_down:
            return
        try:
            send_hotkey_up(self._held_voice_hotkey or "Right Alt")
            app_log(f"voice shortcut released reason={reason}")
        except Exception as exc:
            app_log(f"voice shortcut release warning reason={reason}: {exc}")
        self._voice_shortcut_down = False
        self._held_voice_hotkey = ""

    def _handle_voice_button(self, cfg: dict) -> str:
        enabled = bool(cfg.get("voice_shortcut_enabled", True))
        hotkey = str(cfg.get("voice_hotkey", "Right Alt"))
        mode = str(cfg.get("voice_trigger_mode", "toggle"))
        with self._voice_lock:
            # Read the state only after taking the same lock used by the
            # keyboard-hotkey path.  Reading it before entering this lock
            # allowed a keyboard edge to race a pen edge and invert the two
            # state machines (audio/input state could end up one press apart).
            was_active = bool(self._voice_active)
            if not was_active:
                if not self._open_pen_audio():
                    # Do not toggle the input method unless the microphone route
                    # actually opened. Otherwise the next physical press is also
                    # treated as "start" and the two toggle states become inverted.
                    app_log("voice start cancelled: audio route unavailable")
                    return "voice_start_failed:audio_unavailable"
                if cfg.get("refresh_mic_before_pen_hotkey", True):
                    core.refresh_v60_mic("pen_mic_key", cfg)
                try:
                    if enabled:
                        self._send_voice_shortcut_start(cfg)
                    self._set_voice_active(True, cfg=cfg, reason="pen_start")
                except Exception:
                    self._release_voice_shortcut("shortcut_start_failed")
                    self._close_pen_audio("shortcut_start_failed")
                    self._set_voice_active(
                        False,
                        cfg=cfg,
                        reason="shortcut_start_failed",
                    )
                    raise
                return f"voice_start:{mode}:{hotkey}" if enabled else "voice_audio_start"
            if enabled:
                self._send_voice_shortcut_stop(cfg, "second_press")
            self._set_voice_active(False, cfg=cfg, reason="second_press")
            self._close_pen_audio("second_press", tail_ms=120)
            return f"voice_stop:{mode}:{hotkey}" if enabled else "voice_audio_stop"

    def _handle_external_voice_hotkey(self, cfg: dict, down: bool) -> str:
        mode = str(cfg.get("voice_trigger_mode", "toggle"))
        if time.monotonic() <= self._shortcut_ignore_until:
            return "synthetic_ignored"
        if mode == "toggle" and not down:
            return "toggle_release_ignored"
        with self._voice_lock:
            active = self._voice_active
            if (mode == "toggle" and active) or (mode == "hold" and not down and active):
                self._set_voice_active(False, cfg=cfg, reason="keyboard_stop")
                self._close_pen_audio("keyboard_stop", tail_ms=120)
                app_log("voice state synchronized from physical keyboard: stop")
                return "keyboard_stop"
            if down and not active:
                if not self._open_pen_audio():
                    app_log("keyboard voice start has no audio route")
                    return "keyboard_start_failed:audio_unavailable"
                if cfg.get("refresh_mic_before_pen_hotkey", True):
                    core.refresh_v60_mic("keyboard_voice_start", cfg)
                self._set_voice_active(True, cfg=cfg, reason="keyboard_start")
                app_log("voice state synchronized from physical keyboard: start")
                return "keyboard_start"
        return "keyboard_noop"

    def _physical_hotkey_target(self) -> tuple[int, ...]:
        cfg = self.get_config()
        if not cfg.get("keyboard_hotkey_state_sync", True):
            return ()
        return tuple(parse_hotkey(cfg.get("voice_hotkey", "Right Alt")))

    def _handle_physical_hotkey_edge(self, down: bool) -> None:
        cfg = self.get_config()
        result = self._handle_external_voice_hotkey(cfg, down)
        if (
            down
            and result not in {"synthetic_ignored", "toggle_release_ignored"}
            and cfg.get("keyboard_hotkey_mic_refresh", True)
        ):
            core.refresh_v60_mic(
                f"physical_keyboard_hotkey={cfg.get('voice_hotkey', 'Right Alt')}",
                cfg,
            )

    def _physical_hotkey_error(self, message: str) -> None:
        if not self._stop.is_set():
            app_log(f"physical keyboard monitor warning: {message}; using polling fallback")
            self._keyboard_hook_failed.set()

    def _reconcile_lost_audio(self, token: str, reason: str) -> bool:
        with self._voice_lock:
            with self._audio_lock:
                if self._audio_token != token:
                    return False
                self._audio_token = None
            cfg = self.get_config()
            if self._voice_active and cfg.get("voice_shortcut_enabled", True):
                try:
                    self._send_voice_shortcut_stop(cfg, reason)
                    self._set_voice_active(False, cfg=cfg, reason=reason)
                except Exception as exc:
                    app_log(f"voice state reconcile warning: {exc}")
            elif self._voice_active:
                self._set_voice_active(False, cfg=cfg, reason=reason)
            app_log(f"audio session lost; voice state reconciled reason={reason}")
            return True

    def _audio_watchdog_loop(self) -> None:
        unavailable_count = 0
        while not self._stop.wait(0.5):
            with self._audio_lock:
                token = self._audio_token
            if token is None:
                unavailable_count = 0
                continue
            missing = False
            try:
                status = self._audio_router.status()
                source = (status.get("sources") or {}).get("hanvon")
                missing = not source or int(source.get("client_pid") or 0) != os.getpid()
                unavailable_count = 0
            except (AudioRouterError, OSError):
                unavailable_count += 1
                if unavailable_count < 3:
                    continue
                missing = True
            if not missing:
                continue
            self._reconcile_lost_audio(token, "audio_session_lost")
            unavailable_count = 0

    def get_config(self) -> dict:
        with self._config_lock:
            return copy.deepcopy(self._config)

    def status(self) -> dict:
        with self._status_lock:
            return dict(self._status)

    def _set_status(self, state: str, message: str, opened: int | None = None, last_event: str | None = None) -> None:
        with self._status_lock:
            self._status["state"] = state
            self._status["message"] = message
            if opened is not None:
                self._status["opened"] = opened
            if last_event is not None:
                self._status["last_event"] = last_event
            self._status["updated_at"] = core.ts()

    def _reset_core_runtime(self) -> None:
        core._mic_keepalive_started = False
        core._mic_handle = None
        core._mic_last_refresh = 0.0

    def _sleep_or_stop(self, seconds: float) -> bool:
        end = time.time() + seconds
        while time.time() < end:
            if self._stop.is_set() or self._restart.is_set():
                return True
            time.sleep(0.1)
        return False

    def _run(self) -> None:
        core.LOG = LOG_PATH
        core.CONFIG = CONFIG_PATH
        app_log(f"{APP_NAME} v{APP_VERSION} started; {SUPPORTED_OS_NOTE}")
        while not self._stop.is_set():
            self._restart.clear()
            opened = []
            try:
                cfg = self.get_config()
                devs = core.pen_interfaces(cfg)
                opened = core.open_interfaces(devs)
                if not opened:
                    self._set_status("waiting", "未识别到语音笔，正在后台等待", opened=0)
                    app_log("no readable HID interface; waiting for device")
                    if self._sleep_or_stop(float(cfg.get("retry_device_seconds", 2.0))):
                        continue
                    continue

                self._reset_core_runtime()
                core.enable_v60_mic(opened, cfg)
                self._set_status("connected", "语音笔已连接，桥接运行中", opened=len(opened))
                app_log(f"bridge session opened interfaces={len(opened)}")
                self._read_loop(opened)
            except Exception as exc:
                self._set_status("error", f"桥接异常: {exc}", opened=0)
                app_log(f"bridge error: {exc}")
                self._sleep_or_stop(2.0)
            finally:
                self._close_all_audio("session_end")
                for _, handle in opened:
                    core._close(handle)
                self._reset_core_runtime()
        self._set_status("stopped", "已退出", opened=0)
        app_log("bridge engine stopped")

    def _read_loop(self, opened: list[tuple[dict, object]]) -> None:
        held = {}
        last_fire = {}
        last_presence_check = 0.0
        opened_paths = {d.get("path") for d, _ in opened}
        while not self._stop.is_set() and not self._restart.is_set():
            cfg = self.get_config()
            keycodes = {int(k): v for k, v in cfg.get("hid_keycodes", {}).items()}
            mappings = cfg.get("pen_mappings", {})
            debounce = float(cfg.get("debounce_ms", 250)) / 1000.0
            log_unknown = cfg.get("log_unknown", False)
            saw_data = False

            for d, handle in opened:
                data = core._read(handle)
                if not data:
                    continue
                saw_data = True
                btn = core.parse_button(data)
                if btn is None:
                    if log_unknown and not core.is_idle(data):
                        app_log(f"unknown report iface={d['interface_number']} {core.sig(d, data)}")
                    continue
                keycode, pressed = btn
                if not pressed:
                    held[id(handle)] = None
                    continue
                if held.get(id(handle)) == keycode:
                    continue
                held[id(handle)] = keycode
                logical = keycodes.get(keycode)
                if not logical:
                    if log_unknown:
                        app_log(f"unknown keycode={keycode} iface={d['interface_number']}")
                    continue
                now = time.time()
                if now - last_fire.get(logical, 0.0) < debounce:
                    continue
                last_fire[logical] = now
                mapping = mappings.get(logical, _normalize_mapping("disabled"))
                try:
                    if logical == "mic":
                        action_result = self._handle_voice_button(cfg)
                    else:
                        action_result = execute_mapping(mapping)
                    label = dict(PEN_KEYS).get(logical, logical)
                    message = f"{label}: {action_result}"
                    app_log(f"action {action_result} <- {logical}(key={keycode})")
                    self._set_status("connected", "语音笔已连接，桥接运行中", opened=len(opened), last_event=message)
                except Exception as exc:
                    app_log(f"action error {logical}: {exc}")
                    self._set_status("error", f"动作执行失败: {exc}", opened=len(opened))

            now = time.time()
            if now - last_presence_check > 3.0:
                last_presence_check = now
                cfg = self.get_config()
                current_paths = {d.get("path") for d in core.pen_interfaces(cfg)}
                if not opened_paths.intersection(current_paths):
                    app_log("device removed; reopening session")
                    self._set_status("waiting", "语音笔已断开，正在等待重新插入", opened=0)
                    break
            if not saw_data:
                time.sleep(0.005)

    def _keyboard_hotkey_loop(self) -> None:
        was_down = {}
        while not self._stop.is_set():
            if not self._keyboard_hook_failed.wait(0.2):
                continue
            cfg = self.get_config()
            if not cfg.get("keyboard_hotkey_state_sync", True):
                time.sleep(0.2)
                continue
            try:
                hotkey = cfg.get("voice_hotkey", "Right Alt")
                vks = tuple(parse_hotkey(hotkey))
                down = all(bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000) for vk in vks)
                previous = was_down.get(vks, False)
                if down and not previous:
                    result = self._handle_external_voice_hotkey(cfg, True)
                    if (
                        result != "synthetic_ignored"
                        and cfg.get("keyboard_hotkey_mic_refresh", True)
                    ):
                        core.refresh_v60_mic(f"keyboard_hotkey={hotkey}", cfg)
                elif not down and previous and cfg.get("voice_trigger_mode") == "hold":
                    self._handle_external_voice_hotkey(cfg, False)
                was_down[vks] = down
                time.sleep(max(0.01, int(cfg.get("keyboard_hotkey_poll_ms", 25)) / 1000.0))
            except Exception as exc:
                app_log(f"keyboard monitor error: {exc}")
                time.sleep(1.0)


class ManagedEngineProxy:
    """Config/status facade for a Hanvon role owned by Remote Bridge Hub."""

    def __init__(self, cfg: dict, hub_port: int):
        self._config = copy.deepcopy(cfg)
        self.hub_port = hub_port
        self._message = "由遥控器中心管理"

    def _send_restart(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.sendto(b"RESTART:hanvon", ("127.0.0.1", self.hub_port))
            self._message = "已通知中心重启汉王桥接"
        except OSError:
            self._message = "设置已保存；遥控器中心未响应"

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def restart(self) -> None:
        self._send_restart()

    def update_config(self, cfg: dict) -> None:
        self._config = copy.deepcopy(cfg)
        self._send_restart()

    def get_config(self) -> dict:
        return copy.deepcopy(self._config)

    def status(self) -> dict:
        return {
            "state": "connected",
            "message": self._message,
            "opened": "中心",
            "last_event": "",
            "updated_at": core.ts(),
        }


class ManagedTrayProxy:
    def update_status(self, _status: dict) -> None:
        return

    def stop(self) -> None:
        return


class SettingsWindow:
    def __init__(
        self,
        root: tk.Tk,
        engine: BridgeEngine | ManagedEngineProxy,
        tray: "TrayController | ManagedTrayProxy",
        cfg: dict,
        managed: bool = False,
    ):
        self.root = root
        self.engine = engine
        self.tray = tray
        self.managed = managed
        self.cfg = copy.deepcopy(cfg)
        self.action_vars: dict[str, tk.StringVar] = {}
        self.custom_vars: dict[str, tk.StringVar] = {}
        self.status_vars = {
            "version": tk.StringVar(value=f"版本: v{APP_VERSION}    {SUPPORTED_OS_NOTE}"),
            "state": tk.StringVar(value="状态: 正在启动"),
            "opened": tk.StringVar(value="HID 接口: 0"),
            "last_event": tk.StringVar(value="最近动作: -"),
            "config": tk.StringVar(value=f"配置: {CONFIG_PATH}"),
        }
        self.startup_var = tk.BooleanVar(value=is_startup_enabled())
        self.start_minimized_var = tk.BooleanVar(value=bool(self.cfg.get("start_minimized", False)))
        self.keyboard_hotkey_var = tk.StringVar(value=self.cfg.get("keyboard_hotkey_refresh", "Right Alt"))
        self.keyboard_hotkey_enabled_var = tk.BooleanVar(
            value=bool(self.cfg.get("keyboard_hotkey_mic_refresh", True))
        )
        self.voice_enabled_var = tk.BooleanVar(
            value=bool(self.cfg.get("voice_shortcut_enabled", True))
        )
        self.voice_hotkey_var = tk.StringVar(
            value=str(self.cfg.get("voice_hotkey", "Right Alt"))
        )
        self.voice_mode_var = tk.StringVar(
            value=(
                "按住型"
                if self.cfg.get("voice_trigger_mode") == "hold"
                else "开关型"
            )
        )
        self.capture_status_var = tk.StringVar(
            value="按录入后，直接按目标单键或组合键"
        )
        self.capture = KeyboardShortcutCapture(
            self.root,
            self._capture_complete,
            self._capture_failed,
            thread_name="hanvon-shortcut-capture",
        )
        self.log_unknown_var = tk.BooleanVar(value=bool(self.cfg.get("log_unknown", False)))
        self._build()
        self.refresh_from_config(self.cfg)
        self._poll_status()

    def _build(self) -> None:
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("760x640")
        self.root.minsize(700, 590)
        self.root.protocol("WM_DELETE_WINDOW", self.hide)

        header = ttk.Frame(self.root, padding=(14, 10, 14, 0))
        header.pack(fill="x")
        ttk.Label(header, text=APP_NAME, font=("Microsoft YaHei UI", 14, "bold")).pack(side="left")
        ttk.Label(header, text=f"v{APP_VERSION} · {SUPPORTED_OS_NOTE}", foreground="#666").pack(side="right")

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=12, pady=10)

        self.status_page = ttk.Frame(notebook, padding=16)
        self.mapping_page = ttk.Frame(notebook, padding=16)
        self.basic_page = ttk.Frame(notebook, padding=16)
        self.help_page = ttk.Frame(notebook, padding=0)
        notebook.add(self.status_page, text="状态")
        notebook.add(self.mapping_page, text="按键设置")
        notebook.add(self.basic_page, text="基础设置")
        notebook.add(self.help_page, text="使用说明")

        self._build_status_page()
        self._build_mapping_page()
        self._build_basic_page()
        self._build_help_page()

    def _build_status_page(self) -> None:
        for key in ["version", "state", "opened", "last_event", "config"]:
            ttk.Label(self.status_page, textvariable=self.status_vars[key], anchor="w").pack(fill="x", pady=4)
        buttons = ttk.Frame(self.status_page)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="重启桥接", command=self.engine.restart).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="打开日志目录", command=lambda: open_folder(APPDATA)).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="最小化到托盘", command=self.hide).pack(side="left")

        note = (
            f"当前版本是绿色版 v{APP_VERSION}。设备没插好时软件不会退出，会在后台等语音笔重新上线。"
            "如果改了麦克风握手相关参数，点一次“重启桥接”让新参数生效。"
        )
        ttk.Label(self.status_page, text=note, wraplength=640, foreground="#555").pack(fill="x", pady=(24, 0))

    def _build_mapping_page(self) -> None:
        ttk.Label(
            self.mapping_page,
            text="语音输入（Voice Input）",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w")
        voice_row = ttk.Frame(self.mapping_page)
        voice_row.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(
            voice_row,
            text="启用语音快捷键（Voice Hotkey）",
            variable=self.voice_enabled_var,
        ).pack(side="left")
        ttk.Entry(
            voice_row,
            textvariable=self.voice_hotkey_var,
            width=22,
        ).pack(side="left", padx=(12, 8))
        self.capture_button = ttk.Button(
            voice_row,
            text="按真实键盘录入",
            command=self.toggle_capture,
        )
        self.capture_button.pack(side="left")
        ttk.Combobox(
            voice_row,
            textvariable=self.voice_mode_var,
            values=("开关型", "按住型"),
            state="readonly",
            width=8,
        ).pack(side="left", padx=(12, 0))
        ttk.Label(
            self.mapping_page,
            textvariable=self.capture_status_var,
            foreground="#666",
        ).pack(anchor="w", pady=(7, 0))
        ttk.Label(
            self.mapping_page,
            text="开关型（Toggle）：按一次开始、再按一次结束；按住型（Hold）：按下保持、再次按键释放。",
            foreground="#666",
        ).pack(anchor="w", pady=(3, 0))
        ttk.Label(
            self.mapping_page,
            text=(
                "V60 语音使用说明（V60 Voice）\n"
                "1. 轻按一次麦克风键，开始语音输入\n"
                "2. 再轻按一次麦克风键，结束并提交输入"
            ),
            justify="left",
            wraplength=660,
            foreground="#365F91",
        ).pack(anchor="w", pady=(9, 0))

        ttk.Separator(self.mapping_page).pack(fill="x", pady=(16, 12))
        ttk.Label(self.mapping_page, text="其他笔键").pack(anchor="w")
        grid = ttk.Frame(self.mapping_page)
        grid.pack(fill="x", pady=(8, 0))
        ttk.Label(grid, text="笔键", width=12).grid(row=0, column=0, sticky="w", pady=6)
        ttk.Label(grid, text="动作", width=24).grid(row=0, column=1, sticky="w", pady=6)
        ttk.Label(grid, text="自定义热键", width=28).grid(row=0, column=2, sticky="w", pady=6)

        labels = list(ACTION_LABELS.values())
        for row, (key, label) in enumerate(PEN_KEYS[1:], start=1):
            ttk.Label(grid, text=label).grid(row=row, column=0, sticky="w", pady=6)
            action_var = tk.StringVar()
            custom_var = tk.StringVar()
            self.action_vars[key] = action_var
            self.custom_vars[key] = custom_var
            combo = ttk.Combobox(grid, textvariable=action_var, values=labels, state="readonly", width=22)
            combo.grid(row=row, column=1, sticky="we", padx=(0, 10), pady=6)
            ttk.Entry(grid, textvariable=custom_var, width=28).grid(row=row, column=2, sticky="we", pady=6)
        grid.columnconfigure(2, weight=1)

        ttk.Checkbutton(
            self.mapping_page,
            text="监测这个语音快捷键并提前刷新语音笔麦克风",
            variable=self.keyboard_hotkey_enabled_var,
        ).pack(anchor="w", pady=(14, 0))

        buttons = ttk.Frame(self.mapping_page)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="保存设置", command=self.save).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="恢复默认按键", command=self.reset_mappings).pack(side="left")

    def _build_basic_page(self) -> None:
        if self.managed:
            ttk.Label(
                self.basic_page,
                text="当前由遥控器中心统一管理开机启动、后台运行和退出。这里仅保存汉王自己的按键配置。",
                wraplength=620,
                foreground="#555",
            ).pack(anchor="w", pady=6)
            buttons = ttk.Frame(self.basic_page)
            buttons.pack(fill="x", pady=(18, 0))
            ttk.Button(buttons, text="保存基础设置", command=self.save).pack(side="left", padx=(0, 8))
            ttk.Button(buttons, text="关闭设置", command=self.root.destroy).pack(side="left")
            return
        ttk.Checkbutton(self.basic_page, text="开机自启", variable=self.startup_var).pack(anchor="w", pady=6)
        ttk.Checkbutton(self.basic_page, text="启动后最小化到托盘", variable=self.start_minimized_var).pack(anchor="w", pady=6)
        ttk.Checkbutton(self.basic_page, text="记录未知 HID 报文（排查按键时才打开）", variable=self.log_unknown_var).pack(anchor="w", pady=6)

        buttons = ttk.Frame(self.basic_page)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text="保存基础设置", command=self.save).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="打开配置目录", command=lambda: open_folder(APPDATA)).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="退出软件", command=self.exit_app).pack(side="left")

    def _build_help_page(self) -> None:
        text = scrolledtext.ScrolledText(self.help_page, wrap="word", font=("Microsoft YaHei UI", 10), padx=14, pady=14)
        text.pack(fill="both", expand=True)
        text.insert("1.0", self._help_text())
        text.configure(state="disabled")

    def _help_text(self) -> str:
        return f"""\
{APP_NAME} v{APP_VERSION}
{SUPPORTED_OS_NOTE}

一、这个软件做什么
本软件用于汉王 V60 / Ai Pointer 语音笔。它不依赖原厂字幕软件，通过纯 HID 方式保持语音笔麦克风会话，并把笔上的三个键映射成你需要的热键或动作。

二、第一次使用
1. 插入语音笔 USB 接收器。
2. 打开 HanvonPenBridge.exe。
3. 右下角托盘出现图标后，打开“状态”页看是否显示“语音笔已连接”。
4. 打开你常用的语音输入软件，并在设置中录入它的语音快捷键。
5. 按一下语音笔麦克风键开始说话，再按一下结束。

三、按键设置
软件支持三个笔键独立配置：
- 麦克风键
- 上翻页键
- 下翻页键

麦克风键可以自定义语音快捷键，并选择“开关型”或“按住型”。其他笔键可以设置为：
- 禁用
- 右 Alt 键（Right Alt）
- 回车键（Enter）
- 退格键（Backspace）
- Ctrl + 退格键（Ctrl + Backspace）
- 移到末尾后删除
- 鼠标左键点击
- 点击后按回车键（Enter）
- 自定义热键

自定义热键写法示例：
- 右 Alt
- Alt
- Ctrl + Alt + V
- F8
- Ctrl + Shift + 空格键

四、常见问题
1. 状态显示未识别到语音笔：
   拔下接收器再插上，软件会自动等待，不需要反复打开。

2. 按键没有反应：
   检查按键设置是否被设为“禁用”，再确认目标输入软件是否在前台。

3. 麦克风没信号：
   先点“重启桥接”，再按一次语音笔麦克风键。仍不行时换一个 USB 口。

4. 热键冲突：
   到“按键设置”把对应笔键改成别的热键，例如 F8 或 Ctrl + Alt + V。

5. 想关闭软件：
   右下角托盘图标右键，点“退出”；或在“基础设置”里点“退出软件”。

五、分享说明
当前是绿色版 v{APP_VERSION}，暂时只支持 Windows。分享给别人时，把整个文件夹发给对方即可。配置会写入对方自己的用户目录，不会污染软件目录。
"""

    def refresh_from_config(self, cfg: dict) -> None:
        self.cfg = copy.deepcopy(cfg)
        mappings = self.cfg.get("pen_mappings", {})
        for key, default_action in {"pageup": "tail_backspace", "pagedown": "click_enter"}.items():
            mapping = mappings.get(key, _normalize_mapping(default_action))
            if mapping.get("type") == "disabled":
                action_id = "disabled"
            elif mapping.get("type") == "hotkey":
                action_id = "custom_hotkey"
            else:
                action_id = mapping.get("value", default_action)
            self.action_vars[key].set(ACTION_LABELS.get(action_id, ACTION_LABELS[default_action]))
            self.custom_vars[key].set(mapping.get("custom", ""))
        voice_hotkey = str(self.cfg.get("voice_hotkey", "Right Alt"))
        self.voice_enabled_var.set(bool(self.cfg.get("voice_shortcut_enabled", True)))
        self.voice_hotkey_var.set(voice_hotkey)
        self.voice_mode_var.set(
            "按住型" if self.cfg.get("voice_trigger_mode") == "hold" else "开关型"
        )
        self.keyboard_hotkey_var.set(voice_hotkey)
        self.keyboard_hotkey_enabled_var.set(
            bool(self.cfg.get("keyboard_hotkey_mic_refresh", True))
        )
        self.start_minimized_var.set(bool(self.cfg.get("start_minimized", False)))
        self.log_unknown_var.set(bool(self.cfg.get("log_unknown", False)))
        self.startup_var.set(is_startup_enabled())

    def collect_config(self) -> dict:
        cfg = copy.deepcopy(self.cfg)
        mappings = copy.deepcopy(cfg.get("pen_mappings", {}))
        for key, default_action in {"pageup": "tail_backspace", "pagedown": "click_enter"}.items():
            label = self.action_vars[key].get()
            action_id = ACTION_IDS_BY_LABEL.get(label, default_action)
            mapping = _normalize_mapping(action_id)
            custom = self.custom_vars[key].get().strip()
            if action_id == "custom_hotkey":
                parse_hotkey(custom)
                mapping["custom"] = custom
                mapping["value"] = custom
            mappings[key] = mapping
        voice_hotkey = self.voice_hotkey_var.get().strip() or "Right Alt"
        parse_hotkey(voice_hotkey)
        voice_mode = "hold" if self.voice_mode_var.get() == "按住型" else "toggle"
        cfg["pen_mappings"] = mappings
        cfg["voice_shortcut_enabled"] = bool(self.voice_enabled_var.get())
        cfg["voice_hotkey"] = voice_hotkey
        cfg["voice_trigger_mode"] = voice_mode
        cfg["keyboard_hotkey_refresh"] = voice_hotkey
        cfg["keyboard_hotkey_mic_refresh"] = bool(
            self.keyboard_hotkey_enabled_var.get()
        )
        cfg["start_minimized"] = bool(self.start_minimized_var.get())
        cfg["log_unknown"] = bool(self.log_unknown_var.get())
        cfg["auto_start"] = bool(self.startup_var.get())
        cfg["app_version"] = APP_VERSION
        return cfg

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
        hotkey = tokens_to_display(tokens)
        parse_hotkey(hotkey)
        self.voice_hotkey_var.set(hotkey)
        self.voice_enabled_var.set(True)
        self.capture_button.configure(text="按真实键盘录入")
        self.capture_status_var.set(f"已录入 {hotkey}，等待保存")

    def _capture_failed(self, error: str) -> None:
        self.capture.cancel()
        self.capture_button.configure(text="按真实键盘录入")
        self.capture_status_var.set("录入失败，可以重试")
        messagebox.showerror(APP_NAME, error)

    def save(self) -> None:
        try:
            cfg = self.collect_config()
            save_app_config(cfg)
            if not self.managed:
                install_startup(bool(self.startup_var.get()))
            self.cfg = cfg
            self.engine.update_config(cfg)
            messagebox.showinfo(APP_NAME, "设置已保存。桥接会自动按新设置重启。")
        except Exception as exc:
            messagebox.showerror(APP_NAME, f"保存失败：{exc}")

    def reset_mappings(self) -> None:
        defaults = default_config()
        cfg = copy.deepcopy(self.cfg)
        cfg["pen_mappings"] = defaults["pen_mappings"]
        cfg["voice_shortcut_enabled"] = True
        cfg["voice_hotkey"] = defaults["voice_hotkey"]
        cfg["voice_trigger_mode"] = defaults["voice_trigger_mode"]
        self.refresh_from_config(cfg)

    def _poll_status(self) -> None:
        status = self.engine.status()
        state_text = {
            "starting": "正在启动",
            "waiting": "等待语音笔",
            "connected": "已连接",
            "error": "异常",
            "stopped": "已退出",
        }.get(status.get("state"), status.get("state", "-"))
        self.status_vars["state"].set(f"状态: {state_text} - {status.get('message', '')}")
        self.status_vars["opened"].set(f"HID 接口: {status.get('opened', 0)}")
        self.status_vars["last_event"].set(f"最近动作: {status.get('last_event') or '-'}")
        self.tray.update_status(status)
        self.root.after(1000, self._poll_status)

    def show(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def hide(self) -> None:
        self.root.withdraw()

    def exit_app(self) -> None:
        self.tray.stop()
        self.engine.stop()
        self.root.after(150, self.root.destroy)


class TrayController:
    def __init__(self):
        self.icon: pystray.Icon | None = None
        self.window: SettingsWindow | None = None
        self._last_state = None

    def bind_window(self, window: SettingsWindow) -> None:
        self.window = window

    def start(self) -> None:
        menu = pystray.Menu(
            pystray.MenuItem("打开设置", self._show),
            pystray.MenuItem("重启桥接", self._restart),
            pystray.MenuItem("打开日志目录", self._open_logs),
            pystray.MenuItem("退出", self._exit),
        )
        self.icon = pystray.Icon(APP_ID, self._make_icon("waiting"), f"{APP_NAME} v{APP_VERSION}", menu)
        threading.Thread(target=self.icon.run, name="hanvon-tray", daemon=True).start()

    def _make_icon(self, state: str) -> Image.Image:
        color = {
            "connected": "#2fa84f",
            "waiting": "#d9a300",
            "error": "#d94141",
            "stopped": "#777777",
            "starting": "#3a78d8",
        }.get(state, "#3a78d8")
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=14, fill="#1f2937")
        draw.ellipse((20, 14, 44, 38), fill=color)
        draw.rounded_rectangle((28, 34, 36, 50), radius=4, fill=color)
        draw.rectangle((22, 48, 42, 53), fill=color)
        return image

    def update_status(self, status: dict) -> None:
        if not self.icon:
            return
        state = status.get("state", "starting")
        if state != self._last_state:
            self._last_state = state
            self.icon.icon = self._make_icon(state)
        self.icon.title = f"{APP_NAME} v{APP_VERSION} - {status.get('message', '')}"

    def _call_ui(self, fn) -> None:
        if self.window:
            self.window.root.after(0, fn)

    def _show(self, icon=None, item=None) -> None:
        self._call_ui(self.window.show)

    def _restart(self, icon=None, item=None) -> None:
        if self.window:
            self.window.engine.restart()

    def _open_logs(self, icon=None, item=None) -> None:
        open_folder(APPDATA)

    def _exit(self, icon=None, item=None) -> None:
        self._call_ui(self.window.exit_app)

    def stop(self) -> None:
        if self.icon:
            self.icon.stop()


def acquire_single_instance() -> bool:
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\HanvonPenBridgeApp")
    if ctypes.windll.kernel32.GetLastError() == 183:
        return False
    globals()["_APP_MUTEX"] = mutex
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} {APP_VERSION}")
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--managed-settings", action="store_true")
    parser.add_argument("--hub-port", type=int, default=DEFAULT_HUB_PORT)
    args = parser.parse_args(argv)
    if os.name != "nt":
        messagebox.showerror(APP_NAME, "当前版本暂时只支持 Windows。")
        return 1
    if not args.managed_settings and not acquire_single_instance():
        return 0

    cfg = load_app_config()
    core.LOG = LOG_PATH
    core.CONFIG = CONFIG_PATH
    root = tk.Tk()
    if args.managed_settings:
        engine = ManagedEngineProxy(cfg, args.hub_port)
        tray = ManagedTrayProxy()
        window = SettingsWindow(root, engine, tray, cfg, managed=True)
    else:
        engine = BridgeEngine(cfg)
        engine.start()
        tray = TrayController()
        window = SettingsWindow(root, engine, tray, cfg)
        tray.bind_window(window)
        tray.start()

    if (
        not args.managed_settings
        and (
            args.minimized
            or cfg.get("start_minimized", False)
            or not cfg.get("show_window_on_start", True)
        )
    ):
        root.withdraw()

    try:
        root.mainloop()
    finally:
        tray.stop()
        engine.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
