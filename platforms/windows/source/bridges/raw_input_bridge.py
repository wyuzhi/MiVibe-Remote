#!/usr/bin/env python3
"""
Shared Windows Raw Input bridge used by hardware-specific launchers.

Listens to the USB receiver through Windows Raw Input and runs configured
actions for matched device events. It is additive: it does not suppress the
remote's original key or mouse event.
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import webbrowser

from bridges.audio_client import AudioRouterClient, AudioRouterError


if os.name != "nt":
    raise SystemExit("Raw Input bridge currently supports Windows only.")

RAW_INPUT_NAME = os.environ.get("REMOTE_BRIDGE_RAW_INPUT_NAME", "iPazzPort")
RAW_INPUT_ID = os.environ.get("REMOTE_BRIDGE_RAW_INPUT_ID", "iPazzPortBridge")
RAW_INPUT_OWNER = os.environ.get("REMOTE_BRIDGE_RAW_INPUT_OWNER", "t1")


user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = wintypes.LPARAM
ULONG_PTR = wintypes.WPARAM

WM_INPUT = 0x00FF
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
DEFAULT_T1_CONTROL_PORT = int(
    os.environ.get("REMOTE_BRIDGE_T1_CONTROL_PORT", "30682")
)
RIDI_DEVICENAME = 0x20000007
RIDI_DEVICEINFO = 0x2000000B
RID_INPUT = 0x10000003
RIDEV_INPUTSINK = 0x00000100

RIM_TYPEMOUSE = 0
RIM_TYPEKEYBOARD = 1
RIM_TYPEHID = 2

RI_KEY_MAKE = 0
RI_KEY_BREAK = 1
RI_KEY_E0 = 2
RI_KEY_E1 = 4

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

RI_MOUSE_LEFT_BUTTON_DOWN = 0x0001
RI_MOUSE_LEFT_BUTTON_UP = 0x0002
RI_MOUSE_RIGHT_BUTTON_DOWN = 0x0004
RI_MOUSE_RIGHT_BUTTON_UP = 0x0008
RI_MOUSE_MIDDLE_BUTTON_DOWN = 0x0010
RI_MOUSE_MIDDLE_BUTTON_UP = 0x0020
RI_MOUSE_BUTTON_4_DOWN = 0x0040
RI_MOUSE_BUTTON_4_UP = 0x0080
RI_MOUSE_BUTTON_5_DOWN = 0x0100
RI_MOUSE_BUTTON_5_UP = 0x0200
RI_MOUSE_WHEEL = 0x0400
RI_MOUSE_HWHEEL = 0x0800

INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", wintypes.USHORT),
        ("usUsage", wintypes.USHORT),
        ("dwFlags", wintypes.DWORD),
        ("hwndTarget", wintypes.HWND),
    ]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [
        ("dwType", wintypes.DWORD),
        ("dwSize", wintypes.DWORD),
        ("hDevice", wintypes.HANDLE),
        ("wParam", wintypes.WPARAM),
    ]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [
        ("MakeCode", wintypes.USHORT),
        ("Flags", wintypes.USHORT),
        ("Reserved", wintypes.USHORT),
        ("VKey", wintypes.USHORT),
        ("Message", wintypes.UINT),
        ("ExtraInformation", wintypes.ULONG),
    ]


class RAWMOUSE_BUTTONS(ctypes.Structure):
    _fields_ = [
        ("usButtonFlags", wintypes.USHORT),
        ("usButtonData", wintypes.USHORT),
    ]


class RAWMOUSE_BUTTON_UNION(ctypes.Union):
    _fields_ = [
        ("ulButtons", wintypes.ULONG),
        ("buttons", RAWMOUSE_BUTTONS),
    ]


class RAWMOUSE(ctypes.Structure):
    _anonymous_ = ("button_union",)
    _fields_ = [
        ("usFlags", wintypes.USHORT),
        ("button_union", RAWMOUSE_BUTTON_UNION),
        ("ulRawButtons", wintypes.ULONG),
        ("lLastX", wintypes.LONG),
        ("lLastY", wintypes.LONG),
        ("ulExtraInformation", wintypes.ULONG),
    ]


class RAWINPUTDEVICELIST(ctypes.Structure):
    _fields_ = [
        ("hDevice", wintypes.HANDLE),
        ("dwType", wintypes.DWORD),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", INPUT_UNION)]


WNDPROC = ctypes.WINFUNCTYPE(
    LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HANDLE),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HANDLE),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


user32.RegisterRawInputDevices.argtypes = [
    ctypes.POINTER(RAWINPUTDEVICE),
    wintypes.UINT,
    wintypes.UINT,
]
user32.RegisterRawInputDevices.restype = wintypes.BOOL

user32.GetRawInputData.argtypes = [
    wintypes.HANDLE,
    wintypes.UINT,
    wintypes.LPVOID,
    ctypes.POINTER(wintypes.UINT),
    wintypes.UINT,
]
user32.GetRawInputData.restype = wintypes.UINT

user32.GetRawInputDeviceInfoW.argtypes = [
    wintypes.HANDLE,
    wintypes.UINT,
    wintypes.LPVOID,
    ctypes.POINTER(wintypes.UINT),
]
user32.GetRawInputDeviceInfoW.restype = wintypes.UINT

user32.GetRawInputDeviceList.argtypes = [
    ctypes.POINTER(RAWINPUTDEVICELIST),
    ctypes.POINTER(wintypes.UINT),
    wintypes.UINT,
]
user32.GetRawInputDeviceList.restype = wintypes.UINT

user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT

user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
user32.MapVirtualKeyW.restype = wintypes.UINT

user32.DefWindowProcW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
]
user32.DefWindowProcW.restype = LRESULT


VK = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12,
    "leftshift": 0xA0,
    "rightshift": 0xA1,
    "leftctrl": 0xA2,
    "rightctrl": 0xA3,
    "leftalt": 0xA4,
    "rightalt": 0xA5,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "printscreen": 0x2C,
    "insert": 0x2D,
    "delete": 0x2E,
    "win": 0x5B,
    "lwin": 0x5B,
    "leftwin": 0x5B,
    "rwin": 0x5C,
    "rightwin": 0x5C,
    "apps": 0x5D,
    "num0": 0x60,
    "num1": 0x61,
    "num2": 0x62,
    "num3": 0x63,
    "num4": 0x64,
    "num5": 0x65,
    "num6": 0x66,
    "num7": 0x67,
    "num8": 0x68,
    "num9": 0x69,
    "multiply": 0x6A,
    "add": 0x6B,
    "subtract": 0x6D,
    "decimal": 0x6E,
    "divide": 0x6F,
    "minus": 0xBD,
    "-": 0xBD,
    "plus": 0xBB,
    "=": 0xBB,
    ";": 0xBA,
    ",": 0xBC,
    ".": 0xBE,
    "/": 0xBF,
    "`": 0xC0,
    "[": 0xDB,
    "\\": 0xDC,
    "]": 0xDD,
    "'": 0xDE,
    "volume_mute": 0xAD,
    "volume_down": 0xAE,
    "volume_up": 0xAF,
    "media_next": 0xB0,
    "media_prev": 0xB1,
    "media_stop": 0xB2,
    "media_play_pause": 0xB3,
}

EXTENDED_VKS = {
    0x21,  # page up
    0x22,  # page down
    0x23,  # end
    0x24,  # home
    0x25,  # left
    0x26,  # up
    0x27,  # right
    0x28,  # down
    0x2C,  # print screen
    0x2D,  # insert
    0x2E,  # delete
    0x5B,  # left win
    0x5C,  # right win
    0x5D,  # apps
    0xA3,  # right ctrl
    0xA5,  # right alt
}

for i in range(1, 25):
    VK[f"f{i}"] = 0x70 + i - 1
for code in range(ord("a"), ord("z") + 1):
    VK[chr(code)] = code - 32
for code in range(ord("0"), ord("9") + 1):
    VK[chr(code)] = code


def last_error_message(prefix: str) -> str:
    err = ctypes.get_last_error()
    return f"{prefix}; winerr={err}"


def signed_short(value: int) -> int:
    return ctypes.c_short(value).value


def now_ms() -> int:
    return int(time.time() * 1000)


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def append_jsonl(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def get_device_name(hdevice: int) -> str:
    if not hdevice:
        return ""
    size = wintypes.UINT(0)
    user32.GetRawInputDeviceInfoW(hdevice, RIDI_DEVICENAME, None, ctypes.byref(size))
    if not size.value:
        return ""
    buf = ctypes.create_unicode_buffer(size.value + 1)
    result = user32.GetRawInputDeviceInfoW(
        hdevice, RIDI_DEVICENAME, buf, ctypes.byref(size)
    )
    if result == ctypes.c_uint(-1).value:
        return ""
    return buf.value


def get_raw_input(lparam: int) -> tuple[RAWINPUTHEADER, bytes] | None:
    size = wintypes.UINT(0)
    header_size = ctypes.sizeof(RAWINPUTHEADER)
    result = user32.GetRawInputData(
        lparam, RID_INPUT, None, ctypes.byref(size), header_size
    )
    if result == ctypes.c_uint(-1).value or not size.value:
        return None
    buf = ctypes.create_string_buffer(size.value)
    result = user32.GetRawInputData(
        lparam, RID_INPUT, buf, ctypes.byref(size), header_size
    )
    if result == ctypes.c_uint(-1).value:
        return None
    data = bytes(buf.raw[: size.value])
    header = RAWINPUTHEADER.from_buffer_copy(data[:header_size])
    return header, data[header_size:]


def parse_keyboard(header: RAWINPUTHEADER, body: bytes) -> dict:
    raw = RAWKEYBOARD.from_buffer_copy(body[: ctypes.sizeof(RAWKEYBOARD)])
    state = "up" if raw.Message in (WM_KEYUP, WM_SYSKEYUP) else "down"
    ext = "E1" if raw.Flags & RI_KEY_E1 else ("E0" if raw.Flags & RI_KEY_E0 else "N")
    event_id = f"kbd:VK_{raw.VKey:02X}:SC_{raw.MakeCode:03X}:{ext}:{state}"
    return {
        "kind": "keyboard",
        "event_id": event_id,
        "state": state,
        "vkey": raw.VKey,
        "make_code": raw.MakeCode,
        "flags": raw.Flags,
        "message": raw.Message,
        "device": get_device_name(header.hDevice),
    }


def parse_mouse(header: RAWINPUTHEADER, body: bytes) -> list[dict]:
    raw = RAWMOUSE.from_buffer_copy(body[: ctypes.sizeof(RAWMOUSE)])
    flags = raw.buttons.usButtonFlags
    data = raw.buttons.usButtonData
    device = get_device_name(header.hDevice)
    events: list[dict] = []

    button_pairs = [
        (RI_MOUSE_LEFT_BUTTON_DOWN, "mouse:LEFT:down", "LEFT", "down"),
        (RI_MOUSE_LEFT_BUTTON_UP, "mouse:LEFT:up", "LEFT", "up"),
        (RI_MOUSE_RIGHT_BUTTON_DOWN, "mouse:RIGHT:down", "RIGHT", "down"),
        (RI_MOUSE_RIGHT_BUTTON_UP, "mouse:RIGHT:up", "RIGHT", "up"),
        (RI_MOUSE_MIDDLE_BUTTON_DOWN, "mouse:MIDDLE:down", "MIDDLE", "down"),
        (RI_MOUSE_MIDDLE_BUTTON_UP, "mouse:MIDDLE:up", "MIDDLE", "up"),
        (RI_MOUSE_BUTTON_4_DOWN, "mouse:X1:down", "X1", "down"),
        (RI_MOUSE_BUTTON_4_UP, "mouse:X1:up", "X1", "up"),
        (RI_MOUSE_BUTTON_5_DOWN, "mouse:X2:down", "X2", "down"),
        (RI_MOUSE_BUTTON_5_UP, "mouse:X2:up", "X2", "up"),
    ]
    for mask, event_id, button, state in button_pairs:
        if flags & mask:
            events.append(
                {
                    "kind": "mouse",
                    "event_id": event_id,
                    "button": button,
                    "state": state,
                    "device": device,
                }
            )

    if flags & RI_MOUSE_WHEEL:
        amount = signed_short(data)
        events.append(
            {
                "kind": "mouse",
                "event_id": f"mouse:WHEEL:{amount}",
                "wheel": amount,
                "device": device,
            }
        )
    if flags & RI_MOUSE_HWHEEL:
        amount = signed_short(data)
        events.append(
            {
                "kind": "mouse",
                "event_id": f"mouse:HWHEEL:{amount}",
                "wheel": amount,
                "device": device,
            }
        )

    if not events and (raw.lLastX or raw.lLastY):
        events.append(
            {
                "kind": "mouse_move",
                "event_id": "mouse:MOVE",
                "dx": raw.lLastX,
                "dy": raw.lLastY,
                "device": device,
            }
        )
    return events


def parse_hid(header: RAWINPUTHEADER, body: bytes) -> dict:
    size_hid = int.from_bytes(body[0:4], "little")
    count = int.from_bytes(body[4:8], "little")
    raw = body[8 : 8 + size_hid * count]
    report_hex = raw.hex("-").upper()
    return {
        "kind": "hid",
        "event_id": f"hid:{report_hex}",
        "size_hid": size_hid,
        "count": count,
        "raw_hex": report_hex,
        "device": get_device_name(header.hDevice),
    }


def key_input(vk: int, key_up: bool = False) -> INPUT:
    flags = KEYEVENTF_KEYUP if key_up else 0
    if vk in EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=ki))


def send_vk(vk: int, key_up: bool = False) -> None:
    inp = key_input(vk, key_up)
    sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if sent != 1:
        raise OSError(last_error_message("SendInput failed"))


def send_hotkey(keys: list[str], hold_ms: int = 70) -> None:
    vks = [resolve_vk(k) for k in keys]
    for vk in vks:
        send_vk(vk, False)
        time.sleep(0.01)
    if hold_ms > 0:
        time.sleep(min(hold_ms, 1000) / 1000)
    for vk in reversed(vks):
        send_vk(vk, True)
        time.sleep(0.01)


def scan_code_input(vk: int, key_up: bool = False) -> INPUT:
    """Build a hardware-like keyboard event for side-specific shortcuts."""
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    if not scan:
        raise ValueError(f"No keyboard scan code for virtual key 0x{vk:02X}")
    # MAPVK_VK_TO_VSC may encode E0/E1 in the high byte on newer Windows.
    # KEYBDINPUT carries that prefix through KEYEVENTF_EXTENDEDKEY instead.
    scan &= 0xFF
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0)
    if vk in EXTENDED_VKS:
        flags |= KEYEVENTF_EXTENDEDKEY
    return INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(0, scan, flags, 0, 0)))


def send_scan_code_vk(vk: int, key_up: bool = False) -> None:
    inp = scan_code_input(vk, key_up)
    sent = user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
    if sent != 1:
        raise OSError(last_error_message("SendInput scan code failed"))


def send_scan_code_hotkey(keys: list[str], hold_ms: int = 120) -> None:
    """Send a chord as physical scan codes so left/right modifiers survive."""
    vks = [resolve_vk(key) for key in keys]
    for vk in vks:
        send_scan_code_vk(vk, False)
        time.sleep(0.015)
    if hold_ms > 0:
        time.sleep(min(hold_ms, 1000) / 1000)
    for vk in reversed(vks):
        send_scan_code_vk(vk, True)
        time.sleep(0.015)


def send_hotkey_down(keys: list[str]) -> None:
    for vk in [resolve_vk(k) for k in keys]:
        send_vk(vk, False)
        time.sleep(0.01)


def send_hotkey_up(keys: list[str]) -> None:
    for vk in reversed([resolve_vk(k) for k in keys]):
        send_vk(vk, True)
        time.sleep(0.01)


def send_text(text: str) -> None:
    inputs = []
    for ch in text:
        code = ord(ch)
        inputs.append(
            INPUT(
                INPUT_KEYBOARD,
                INPUT_UNION(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, 0)),
            )
        )
        inputs.append(
            INPUT(
                INPUT_KEYBOARD,
                INPUT_UNION(
                    ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)
                ),
            )
        )
    if not inputs:
        return
    array_type = INPUT * len(inputs)
    sent = user32.SendInput(len(inputs), array_type(*inputs), ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError(last_error_message("SendInput unicode failed"))


def resolve_vk(name: str) -> int:
    key = str(name).strip().lower()
    if key.startswith("vk_"):
        return int(key[3:], 16)
    if key in VK:
        return VK[key]
    if len(key) == 1 and key.isprintable():
        return VK.get(key.lower(), ord(key.upper()))
    raise ValueError(f"Unknown key name: {name}")


def as_action_list(actions) -> list[dict]:
    if not actions:
        return []
    if isinstance(actions, dict):
        return [actions]
    if isinstance(actions, list):
        return [a for a in actions if isinstance(a, dict)]
    return []


def as_event_id_list(value) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []
    result = []
    for item in values:
        event_id = str(item).strip()
        if event_id and not event_id.startswith("REPLACE_"):
            result.append(event_id)
    return result


class T1Bridge:
    def __init__(
        self,
        config_path: Path,
        learn: bool,
        dry_run: bool,
        verbose: bool,
        action_guard=None,
        action_handlers: dict | None = None,
        control_port: int = DEFAULT_T1_CONTROL_PORT,
    ):
        self.config_path = config_path
        self.root = config_path.parent
        self.config = load_json(config_path)
        self.learn = learn
        self.dry_run = dry_run
        self.verbose = verbose
        self.action_guard = action_guard
        self.action_handlers = (
            action_handlers if isinstance(action_handlers, dict) else {}
        )
        self.current_mode = self.config.get("initial_mode", "default")
        self.device_match = [
            str(s).lower() for s in self.config.get("device_match", []) if str(s).strip()
        ]
        self.allow_all_devices_for_actions = bool(
            self.config.get("allow_all_devices_for_actions", False)
        )
        learn_log = self.config.get("learn_log", "logs/learn_events.jsonl")
        action_log = self.config.get("action_log", "logs/action_events.jsonl")
        self.learn_log = self.resolve_path(learn_log)
        self.action_log = self.resolve_path(action_log)
        self.last_action_at: dict[str, int] = {}
        self.last_hid_event_by_device: dict[str, str] = {}
        self.active_hotkeys: set[str] = set()
        self.active_hotkey_keys: dict[str, list[str]] = {}
        self.active_hotkey_modes: dict[str, str] = {}
        self.audio_sessions: dict[str, str] = {}
        self.voice_started_at: dict[str, int] = {}
        self.audio_release_monitors: set[str] = set()
        self.audio_state_lock = threading.RLock()
        # The T1 USB microphone can take over five seconds to wake from a cold
        # state. Keep the longer first wait T1-only; Hanvon and Xiaomi retain
        # the shared client's existing two-second behavior.
        if os.environ.get("REMOTE_BRIDGE_AUDIO_TRANSPORT", "").casefold() == "native":
            # Keep the native-endpoint helper out of Xiaomi-only builds. The
            # shared Raw Input mapper does not need it unless launched as T1.
            from bridges.native_audio import NativeAudioSessionClient

            self.audio_router = NativeAudioSessionClient(RAW_INPUT_OWNER)
        else:
            self.audio_router = AudioRouterClient(
                RAW_INPUT_OWNER,
                open_timeout=8.0,
                open_retry_timeout=2.0,
            )
        self.control_port = int(control_port)
        self.control_socket: socket.socket | None = None
        self.control_stop = threading.Event()
        self.started_at = time.monotonic()
        self.runtime_state_path = self.root / "t1_runtime_state.json"
        self._add_default_voice_audio_source()
        self._wndproc = WNDPROC(self.wndproc)
        self.hwnd = None

    def _add_default_voice_audio_source(self) -> None:
        """Migrate old PTT mappings in memory without touching custom keys."""
        voice_actions = self.config.get("button_bindings", {}).get("voice", [])
        if isinstance(voice_actions, dict):
            voice_actions = [voice_actions]
        state_ids: set[str] = set()
        for action in voice_actions if isinstance(voice_actions, list) else []:
            if action.get("type") == "hotkey_down":
                action.setdefault("audio_source", "Mic Device")
                action.setdefault("audio_tail_ms", 120)
                action.setdefault("audio_release_mode", "signal_end")
                action.setdefault("audio_trigger_mode", "toggle_hotkey")
                state_ids.add(str(action.get("state_id") or json.dumps(action.get("keys", []))))
        for actions in self.config.get("bindings", {}).values():
            if isinstance(actions, dict):
                actions = [actions]
            if not isinstance(actions, list):
                continue
            for action in actions:
                state_id = str(action.get("state_id") or json.dumps(action.get("keys", [])))
                if action.get("type") == "hotkey_up" and state_id in state_ids:
                    action.setdefault("audio_source", "Mic Device")
                    action.setdefault("audio_tail_ms", 120)
                    action.setdefault("audio_release_mode", "signal_end")
                    action.setdefault("audio_trigger_mode", "toggle_hotkey")

    def _write_runtime_state(
        self,
        active: bool,
        *,
        state_id: str = "",
        keys: list[str] | None = None,
        reason: str = "",
    ) -> None:
        data = {
            "active": bool(active),
            "state_id": state_id,
            "keys": list(keys or []),
            "pid": os.getpid(),
            "updated_at_ms": now_ms(),
            "reason": reason,
        }
        self.runtime_state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.runtime_state_path.with_name(
            f".{self.runtime_state_path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            temp_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp_path, self.runtime_state_path)
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _record_voice_lifecycle(
        self,
        event: str,
        state_id: str,
        *,
        reason: str = "",
        duration_ms: int | None = None,
        details: str = "",
    ) -> None:
        record = {
            "ts_ms": now_ms(),
            "event_id": f"{RAW_INPUT_OWNER}:voice_lifecycle",
            "mode": self.current_mode,
            "voice_event": event,
            "state_id": state_id,
            "reason": reason,
            "duration_ms": duration_ms,
            "details": details,
            "dry_run": self.dry_run,
        }
        try:
            append_jsonl(self.action_log, record)
        except OSError as exc:
            print(f"VOICE LOG WRITE WARNING: {exc}", flush=True)

    def _close_audio_session(
        self,
        state_id: str,
        token: str,
        *,
        tail_ms: int = 0,
    ) -> bool:
        try:
            result = self.audio_router.close(token, tail_ms=tail_ms)
            if result.get("closed") or result.get("scheduled"):
                return True
            print(
                f"AUDIO CLOSE STALE state={state_id}; closing owner",
                flush=True,
            )
        except (AudioRouterError, OSError) as exc:
            print(f"AUDIO CLOSE WARNING state={state_id}: {exc}", flush=True)
        try:
            result = self.audio_router.close_owner(timeout=1.5)
            return bool(result.get("closed"))
        except (AudioRouterError, OSError) as exc:
            print(f"AUDIO OWNER CLOSE WARNING state={state_id}: {exc}", flush=True)
            return False

    def _stop_all_voice(self, reason: str) -> int:
        with self.audio_state_lock:
            state_ids = tuple(self.active_hotkeys)
        stopped = 0
        for state_id in state_ids:
            with self.audio_state_lock:
                action = {
                    "keys": list(self.active_hotkey_keys.get(state_id, [])),
                    "audio_trigger_mode": self.active_hotkey_modes.get(
                        state_id, "toggle_hotkey"
                    ),
                    "audio_tail_ms": 0,
                }
            if self._stop_active_hotkey(state_id, action, reason):
                stopped += 1
        try:
            self.audio_router.close_owner(timeout=1.5)
        except (AudioRouterError, OSError) as exc:
            print(f"AUDIO OWNER CLEANUP WARNING: {exc}", flush=True)
        with self.audio_state_lock:
            if not self.active_hotkeys:
                try:
                    self._write_runtime_state(False, reason=reason)
                except OSError as exc:
                    print(f"RUNTIME STATE WRITE WARNING: {exc}", flush=True)
        return stopped

    def _recover_stale_state(self) -> None:
        try:
            self.audio_router.close_owner(timeout=1.5)
        except (AudioRouterError, OSError) as exc:
            print(f"AUDIO STARTUP CLEANUP WARNING: {exc}", flush=True)
        state: dict = {}
        try:
            if self.runtime_state_path.exists():
                loaded = json.loads(
                    self.runtime_state_path.read_text(encoding="utf-8-sig")
                )
                if isinstance(loaded, dict):
                    state = loaded
        except (OSError, json.JSONDecodeError) as exc:
            print(f"RUNTIME STATE WARNING: {exc}", flush=True)
        if state.get("active"):
            keys = [str(key) for key in state.get("keys", []) if str(key)]
            state_id = str(state.get("state_id") or "voice_input_shortcut")
            if keys:
                try:
                    send_hotkey(keys, 70)
                    self._record_voice_lifecycle(
                        "recovered",
                        state_id,
                        reason="stale_worker_state",
                    )
                    print(
                        f"VOICE RECOVERED state={state_id} previous_pid={state.get('pid')}",
                        flush=True,
                    )
                except OSError as exc:
                    print(f"VOICE RECOVERY WARNING state={state_id}: {exc}", flush=True)
        try:
            self._write_runtime_state(False, reason="startup_clean")
        except OSError as exc:
            print(f"RUNTIME STATE WRITE WARNING: {exc}", flush=True)

    def _control_status(self) -> dict:
        with self.audio_state_lock:
            states = sorted(self.active_hotkeys)
            started_values = [
                self.voice_started_at[state_id]
                for state_id in states
                if state_id in self.voice_started_at
            ]
        started_at_ms = min(started_values) if started_values else None
        return {
            "pid": os.getpid(),
            "voice_active": bool(states),
            "states": states,
            "voice_started_at_ms": started_at_ms,
            "uptime_ms": int((time.monotonic() - self.started_at) * 1000),
        }

    def _start_control_listener(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(("127.0.0.1", self.control_port))
        server.settimeout(0.25)
        self.control_socket = server
        self.control_stop.clear()

        def listen() -> None:
            while not self.control_stop.is_set():
                try:
                    payload, peer = server.recvfrom(4096)
                except socket.timeout:
                    continue
                except OSError:
                    break
                request_id = None
                try:
                    request = json.loads(payload.decode("utf-8"))
                    request_id = request.get("request_id")
                    op = str(request.get("op") or "")
                    if op == "status":
                        details = self._control_status()
                    elif op == "stop_voice":
                        details = {
                            "pid": os.getpid(),
                            "stopped": self._stop_all_voice("manual_stop"),
                            **self._control_status(),
                        }
                    elif op == "shutdown":
                        stopped = self._stop_all_voice("worker_shutdown")
                        details = {
                            "pid": os.getpid(),
                            "stopped": stopped,
                            "shutting_down": True,
                        }
                    else:
                        raise ValueError(f"unsupported Raw Input control operation: {op}")
                    response = {"ok": True, "request_id": request_id, **details}
                except Exception as exc:
                    response = {
                        "ok": False,
                        "request_id": request_id,
                        "error": str(exc),
                    }
                try:
                    server.sendto(
                        json.dumps(response, ensure_ascii=False).encode("utf-8"),
                        peer,
                    )
                except OSError:
                    pass
                if response.get("shutting_down"):
                    if self.hwnd:
                        user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)
                    break

        threading.Thread(
            target=listen,
            name=f"{RAW_INPUT_ID}-control-listener",
            daemon=True,
        ).start()

    def _stop_control_listener(self) -> None:
        self.control_stop.set()
        server = self.control_socket
        self.control_socket = None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass

    def _start_audio_watchdog(
        self,
        state_id: str,
        token: str,
        action: dict,
    ) -> None:
        max_hold_ms = max(10_000, int(action.get("audio_max_hold_ms", 300_000)))

        def monitor() -> None:
            missing_checks = 0
            router_errors = 0
            reason = ""
            while True:
                with self.audio_state_lock:
                    if self.audio_sessions.get(state_id) != token:
                        return
                    started_at_ms = self.voice_started_at.get(state_id, now_ms())
                if now_ms() - started_at_ms >= max_hold_ms:
                    reason = "max_hold_timeout"
                    break
                try:
                    source = self.audio_router.status().get("sources", {}).get(
                        RAW_INPUT_OWNER
                    )
                    router_errors = 0
                    missing_checks = 0 if source is not None else missing_checks + 1
                except (AudioRouterError, OSError):
                    router_errors += 1
                if missing_checks >= 4:
                    reason = "audio_session_lost"
                    break
                if router_errors >= 20:
                    reason = "audio_router_unavailable"
                    break
                time.sleep(0.5)
            self._stop_active_hotkey(state_id, action, reason)

        threading.Thread(
            target=monitor,
            name=f"{RAW_INPUT_ID}-audio-watchdog-{state_id}",
            daemon=True,
        ).start()

    def _start_signal_release_monitor(
        self, state_id: str, keys: list[str], token: str, action: dict
    ) -> None:
        with self.audio_state_lock:
            if state_id in self.audio_release_monitors:
                return
            self.audio_release_monitors.add(state_id)

        silence_ms = max(250, int(action.get("audio_release_silence_ms", 800)))
        min_hold_ms = max(0, int(action.get("audio_release_min_hold_ms", 1500)))
        start_timeout_ms = max(1000, int(action.get("audio_signal_start_timeout_ms", 5000)))
        max_hold_ms = max(start_timeout_ms, int(action.get("audio_max_hold_ms", 600000)))

        def monitor() -> None:
            started = time.monotonic()
            signal_seen = False
            reason = "unknown"
            try:
                while True:
                    with self.audio_state_lock:
                        if self.audio_sessions.get(state_id) != token:
                            return
                    elapsed_ms = (time.monotonic() - started) * 1000.0
                    try:
                        source = self.audio_router.status().get("sources", {}).get(
                            RAW_INPUT_OWNER, {}
                        )
                        signal_seen = signal_seen or bool(source.get("signal_seen"))
                        source_silence_ms = source.get("silence_ms")
                        if (
                            elapsed_ms >= min_hold_ms
                            and
                            signal_seen
                            and source_silence_ms is not None
                            and float(source_silence_ms) >= silence_ms
                        ):
                            reason = "signal_ended"
                            break
                    except (AudioRouterError, OSError):
                        pass
                    if not signal_seen and elapsed_ms >= start_timeout_ms:
                        reason = "no_signal_timeout"
                        break
                    if elapsed_ms >= max_hold_ms:
                        reason = "max_hold_timeout"
                        break
                    time.sleep(0.05)
            finally:
                with self.audio_state_lock:
                    self.audio_release_monitors.discard(state_id)
                    should_stop = self.audio_sessions.get(state_id) == token
                if should_stop:
                    self._stop_active_hotkey(state_id, action, reason)
                print(
                    f"AUDIO CLOSED state={state_id} reason={reason} "
                    f"signal_seen={signal_seen}",
                    flush=True,
                )

        threading.Thread(
            target=monitor,
            name=f"{RAW_INPUT_ID}-audio-release-{state_id}",
            daemon=True,
        ).start()

    def _stop_active_hotkey(
        self, state_id: str, action: dict, reason: str
    ) -> bool:
        with self.audio_state_lock:
            if state_id not in self.active_hotkeys:
                return False
            token = self.audio_sessions.pop(state_id, None)
            keys = self.active_hotkey_keys.pop(
                state_id, list(action.get("keys", []))
            )
            trigger_mode = self.active_hotkey_modes.pop(
                state_id, str(action.get("audio_trigger_mode") or "latched_hold")
            )
            self.active_hotkeys.discard(state_id)
            started_at_ms = self.voice_started_at.pop(state_id, None)
            self.audio_release_monitors.discard(state_id)
            has_remaining_state = bool(self.active_hotkeys)
        audio_closed = True
        if token:
            audio_closed = self._close_audio_session(
                state_id,
                token,
                tail_ms=max(0, min(int(action.get("audio_tail_ms", 120)), 1000)),
            )
        hotkey_released = True
        try:
            if trigger_mode == "toggle_hotkey":
                send_hotkey(keys, 70)
            else:
                send_hotkey_up(keys)
        except OSError as exc:
            hotkey_released = False
            print(f"VOICE HOTKEY RELEASE WARNING state={state_id}: {exc}", flush=True)
        if not has_remaining_state:
            try:
                self._write_runtime_state(False, state_id=state_id, reason=reason)
            except OSError as exc:
                print(f"RUNTIME STATE WRITE WARNING: {exc}", flush=True)
        duration_ms = now_ms() - started_at_ms if started_at_ms is not None else None
        self._record_voice_lifecycle(
            "stopped",
            state_id,
            reason=reason,
            duration_ms=duration_ms,
            details=(
                f"audio_closed={audio_closed} hotkey_released={hotkey_released} "
                f"trigger_mode={trigger_mode}"
            ),
        )
        print(
            f"VOICE STOP state={state_id} reason={reason} mode={trigger_mode} "
            f"duration_ms={duration_ms}",
            flush=True,
        )
        return True

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        if not path.is_absolute():
            path = self.root / path
        return path

    def should_accept(self, device_name: str) -> bool:
        if not self.device_match:
            return self.allow_all_devices_for_actions
        low = device_name.lower()
        return any(token in low for token in self.device_match)

    def bindings(self) -> dict:
        result = dict(self.config.get("bindings", {}))
        self.expand_button_bindings(
            result,
            self.config.get("button_aliases", {}),
            self.config.get("button_bindings", {}),
        )
        modes = self.config.get("modes", {})
        mode_config = modes.get(self.current_mode, {})
        result.update(mode_config.get("bindings", {}))
        self.expand_button_bindings(
            result,
            self.config.get("button_aliases", {}),
            mode_config.get("button_bindings", {}),
        )
        return result

    def expand_button_bindings(
        self, result: dict, aliases: dict, button_bindings: dict
    ) -> None:
        if not isinstance(aliases, dict) or not isinstance(button_bindings, dict):
            return
        for button_name, actions in button_bindings.items():
            event_ids = as_event_id_list(aliases.get(button_name))
            if not event_ids:
                continue
            action_list = as_action_list(actions)
            if not action_list:
                continue
            for event_id in event_ids:
                current = result.get(event_id, [])
                if isinstance(current, dict):
                    current = [current]
                elif not isinstance(current, list):
                    current = []
                result[event_id] = current + action_list

    def on_event(self, event: dict) -> None:
        event["ts_ms"] = now_ms()
        device = event.get("device", "")
        event_id = event.get("event_id", "")

        if self.verbose or self.learn:
            print(json.dumps(event, ensure_ascii=False), flush=True)

        if self.learn and event.get("kind") != "mouse_move":
            append_jsonl(self.learn_log, event)

        if (
            event.get("kind") == "hid"
            and not self.learn
            and self.config.get("dedupe_hid_reports", True)
        ):
            device_key = event.get("device", "")
            last_event_id = self.last_hid_event_by_device.get(device_key)
            self.last_hid_event_by_device[device_key] = event_id
            if last_event_id == event_id:
                return

        if not self.should_accept(device):
            return

        if event.get("state") == "up" and not self.config.get("handle_key_up", False):
            return
        if event.get("kind") == "mouse_move" and not self.config.get("handle_mouse_move", False):
            return

        actions = self.bindings().get(event_id, [])
        if isinstance(actions, dict):
            actions = [actions]
        for action in actions:
            if self.action_guard is not None:
                try:
                    if not self.action_guard(event, action):
                        continue
                except Exception as exc:
                    print(
                        f"ACTION GUARD ERROR {type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    continue
            self.run_action(event, action)

    def run_action(self, event: dict, action: dict) -> None:
        kind = action.get("type")
        cooldown_ms = int(action.get("cooldown_ms", 0) or 0)
        if cooldown_ms > 0:
            action_key = (
                event.get("event_id", "")
                + ":"
                + json.dumps(action, ensure_ascii=False, sort_keys=True)
            )
            ts = now_ms()
            if ts - self.last_action_at.get(action_key, 0) < cooldown_ms:
                return
            self.last_action_at[action_key] = ts
        if kind in {"hotkey_down", "hotkey_up"}:
            state_id = str(action.get("state_id") or json.dumps(action.get("keys", [])))
            with self.audio_state_lock:
                state_is_active = state_id in self.active_hotkeys
            if kind == "hotkey_down" and state_is_active:
                if action.get("second_press_stops") and not self.dry_run:
                    self._stop_active_hotkey(state_id, action, "second_press")
                return
            if kind == "hotkey_up" and not state_is_active:
                return
        record = {
            "ts_ms": now_ms(),
            "event_id": event.get("event_id"),
            "mode": self.current_mode,
            "action": action,
            "dry_run": self.dry_run,
        }
        append_jsonl(self.action_log, record)
        if self.verbose:
            print("ACTION " + json.dumps(record, ensure_ascii=False), flush=True)
        if self.dry_run:
            return

        if kind == "hotkey":
            send_hotkey(action.get("keys", []), int(action.get("hold_ms", 70)))
        elif kind == "hotkey_down":
            state_id = str(action.get("state_id") or json.dumps(action.get("keys", [])))
            audio_source = str(action.get("audio_source") or "").strip()
            token: str | None = None
            if audio_source:
                try:
                    max_session_ms = max(
                        10_000,
                        min(int(action.get("audio_max_hold_ms", 300_000)), 3_600_000),
                    )
                    token = self.audio_router.open(
                        audio_source,
                        max_session_ms=max_session_ms,
                    )
                    print(f"AUDIO OPEN state={state_id} source={audio_source}", flush=True)
                except (AudioRouterError, OSError) as exc:
                    print(f"AUDIO OPEN WARNING state={state_id}: {exc}", flush=True)
                    self._record_voice_lifecycle(
                        "start_failed",
                        state_id,
                        reason="audio_open_failed",
                        details=str(exc),
                    )
                    # Never toggle Typeless or mark voice active when the
                    # microphone route was not confirmed.
                    return
            trigger_mode = str(action.get("audio_trigger_mode") or "hold_hotkey")
            keys = list(action.get("keys", []))
            started_at_ms = now_ms()
            with self.audio_state_lock:
                self.active_hotkeys.add(state_id)
                self.active_hotkey_keys[state_id] = keys
                self.active_hotkey_modes[state_id] = trigger_mode
                self.voice_started_at[state_id] = started_at_ms
                if token:
                    self.audio_sessions[state_id] = token
                try:
                    if trigger_mode == "toggle_hotkey":
                        send_hotkey(keys, 70)
                    else:
                        send_hotkey_down(keys)
                except OSError as exc:
                    self.active_hotkeys.discard(state_id)
                    self.active_hotkey_keys.pop(state_id, None)
                    self.active_hotkey_modes.pop(state_id, None)
                    self.voice_started_at.pop(state_id, None)
                    self.audio_sessions.pop(state_id, None)
                    if token:
                        self._close_audio_session(state_id, token)
                    self._record_voice_lifecycle(
                        "start_failed",
                        state_id,
                        reason="hotkey_send_failed",
                        details=str(exc),
                    )
                    raise
                if audio_source:
                    try:
                        self._write_runtime_state(
                            True,
                            state_id=state_id,
                            keys=keys,
                            reason="voice_started",
                        )
                    except OSError as exc:
                        print(f"RUNTIME STATE WRITE WARNING: {exc}", flush=True)
            if audio_source:
                self._record_voice_lifecycle(
                    "started",
                    state_id,
                    reason="button_press",
                    details=f"source={audio_source} trigger_mode={trigger_mode}",
                )
                self._start_audio_watchdog(state_id, token, action)
        elif kind == "hotkey_up":
            state_id = str(action.get("state_id") or json.dumps(action.get("keys", [])))
            with self.audio_state_lock:
                token = self.audio_sessions.get(state_id)
            if token and action.get("audio_release_mode") == "signal_end":
                self._start_signal_release_monitor(
                    state_id, list(action.get("keys", [])), token, action
                )
                print(f"AUDIO WAITING FOR SIGNAL END state={state_id}", flush=True)
                return
            self._stop_active_hotkey(state_id, action, "key_release")
        elif kind == "key":
            send_hotkey([action.get("key")])
        elif kind == "text":
            send_text(str(action.get("text", "")))
        elif kind == "command":
            subprocess.Popen(action.get("args", []), cwd=action.get("cwd") or None)
        elif kind == "shell":
            subprocess.Popen(str(action.get("command", "")), shell=True)
        elif kind == "open_url":
            webbrowser.open(str(action.get("url", "")))
        elif kind == "set_mode":
            self.current_mode = str(action.get("mode", "default"))
            print(f"mode={self.current_mode}", flush=True)
        elif kind == "toggle_mode":
            modes = action.get("modes", ["default"])
            if not modes:
                return
            self.current_mode = modes[(modes.index(self.current_mode) + 1) % len(modes)] if self.current_mode in modes else modes[0]
            print(f"mode={self.current_mode}", flush=True)
        elif kind in self.action_handlers:
            self.action_handlers[kind]()
        elif kind == "log":
            print(str(action.get("message", event.get("event_id"))), flush=True)
        else:
            print(f"Unknown action type: {kind}", flush=True)

    def wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_INPUT:
            parsed = get_raw_input(lparam)
            if parsed:
                header, body = parsed
                try:
                    if header.dwType == RIM_TYPEKEYBOARD:
                        self.on_event(parse_keyboard(header, body))
                    elif header.dwType == RIM_TYPEMOUSE:
                        for event in parse_mouse(header, body):
                            self.on_event(event)
                    elif header.dwType == RIM_TYPEHID:
                        self.on_event(parse_hid(header, body))
                except Exception as exc:
                    print(f"event parse/action error: {exc}", file=sys.stderr, flush=True)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def create_window(self) -> int:
        hinstance = kernel32.GetModuleHandleW(None)
        class_name = f"{RAW_INPUT_ID}HiddenWindow"
        wndclass = WNDCLASS()
        wndclass.lpfnWndProc = self._wndproc
        wndclass.hInstance = hinstance
        wndclass.lpszClassName = class_name
        atom = user32.RegisterClassW(ctypes.byref(wndclass))
        if not atom:
            err = ctypes.get_last_error()
            if err != 1410:  # class already exists
                raise OSError(last_error_message("RegisterClassW failed"))
        hwnd = user32.CreateWindowExW(
            0,
            class_name,
            f"{RAW_INPUT_NAME} Bridge",
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            hinstance,
            None,
        )
        if not hwnd:
            raise OSError(last_error_message("CreateWindowExW failed"))
        self.hwnd = hwnd
        return hwnd

    def register_raw_input(self) -> None:
        entries = []
        if self.learn or self.config.get("listen_keyboard", False):
            entries.append(RAWINPUTDEVICE(0x01, 0x06, RIDEV_INPUTSINK, self.hwnd))
        if self.learn or self.config.get("listen_mouse", False):
            entries.append(RAWINPUTDEVICE(0x01, 0x02, RIDEV_INPUTSINK, self.hwnd))
        if self.config.get("listen_consumer", True):
            entries.append(RAWINPUTDEVICE(0x0C, 0x01, RIDEV_INPUTSINK, self.hwnd))
        if not entries:
            raise RuntimeError("No raw input devices configured.")
        devices = (RAWINPUTDEVICE * len(entries))(*entries)
        ok = user32.RegisterRawInputDevices(
            devices, len(devices), ctypes.sizeof(RAWINPUTDEVICE)
        )
        if not ok:
            raise OSError(last_error_message("RegisterRawInputDevices failed"))

    def run(self) -> None:
        self.create_window()
        try:
            self.register_raw_input()
            self._start_control_listener()
            self._recover_stale_state()
            print(f"{RAW_INPUT_NAME} bridge running.", flush=True)
            print(f"config={self.config_path}", flush=True)
            print(f"control=127.0.0.1:{self.control_port}", flush=True)
            print(f"learn={self.learn} dry_run={self.dry_run} mode={self.current_mode}", flush=True)
            if not self.device_match:
                if self.allow_all_devices_for_actions:
                    print("WARNING: device_match is empty and allow_all_devices_for_actions=true.", flush=True)
                    print("Actions may react to keyboard/mouse/other remotes.", flush=True)
                else:
                    print("SAFE MODE: device_match is empty, so no actions will run.", flush=True)
                    print("Learning still records events. Add the receiver VID/PID to device_match before run mode.", flush=True)

            msg = wintypes.MSG()
            while True:
                result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if result == 0:
                    break
                if result == -1:
                    raise OSError(last_error_message("GetMessageW failed"))
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._stop_all_voice("worker_exit")
            self._stop_control_listener()


def list_devices() -> None:
    count = wintypes.UINT(0)
    result = user32.GetRawInputDeviceList(None, ctypes.byref(count), ctypes.sizeof(RAWINPUTDEVICELIST))
    if result == ctypes.c_uint(-1).value:
        raise OSError(last_error_message("GetRawInputDeviceList count failed"))
    if not count.value:
        print("No raw input devices found.")
        return
    array_type = RAWINPUTDEVICELIST * count.value
    devices = array_type()
    result = user32.GetRawInputDeviceList(devices, ctypes.byref(count), ctypes.sizeof(RAWINPUTDEVICELIST))
    if result == ctypes.c_uint(-1).value:
        raise OSError(last_error_message("GetRawInputDeviceList failed"))
    type_name = {RIM_TYPEMOUSE: "mouse", RIM_TYPEKEYBOARD: "keyboard", RIM_TYPEHID: "hid"}
    for item in devices:
        print(json.dumps({
            "type": type_name.get(item.dwType, str(item.dwType)),
            "device": get_device_name(item.hDevice),
        }, ensure_ascii=False))


def default_config_path() -> Path:
    return Path(__file__).resolve().parent / "t1" / "config.json"


def main(
    argv: list[str] | None = None,
    action_guard=None,
    action_handlers: dict | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=f"{RAW_INPUT_NAME} Raw Input bridge")
    parser.add_argument("--config", default=str(default_config_path()), help="mapping JSON path")
    parser.add_argument("--learn", action="store_true", help="log all non-move events for button learning")
    parser.add_argument("--dry-run", action="store_true", help="log actions but do not send input/run commands")
    parser.add_argument("--verbose", action="store_true", help="print raw events/actions")
    parser.add_argument("--list-devices", action="store_true", help="print current raw input devices and exit")
    parser.add_argument(
        "--control-port",
        type=int,
        default=DEFAULT_T1_CONTROL_PORT,
        help="local Raw Input status and graceful-shutdown UDP port",
    )
    args = parser.parse_args(argv)

    if args.list_devices:
        list_devices()
        return 0

    bridge = T1Bridge(
        Path(args.config).resolve(),
        args.learn,
        args.dry_run,
        args.verbose,
        action_guard=action_guard,
        action_handlers=action_handlers,
        control_port=args.control_port,
    )
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
