#!/usr/bin/env python3
"""Shared per-user configuration for the Xiaomi remote bridge."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re


APPDATA = Path(os.environ.get("APPDATA", str(Path.home()))) / os.environ.get(
    "REMOTE_BRIDGE_XIAOMI_APP_ID", "MiVibeRemote"
)
CONFIG_PATH = APPDATA / "xiaomi.json"
KEYS_CONFIG_PATH = APPDATA / "xiaomi_keys.json"

APP_VERSION = "0.1.1"
APP_VERSION = os.environ.get("REMOTE_BRIDGE_XIAOMI_VERSION", APP_VERSION)
MAPPING_SCHEMA_VERSION = 1

DEFAULT_VOICE_HOTKEY = ("rightalt",)
VIBE_CODING_VOICE_TRIGGER_MODE = "hold"

HOTKEY_VK = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
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
    "leftwin": 0x5B,
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
    "leftshift": 0xA0,
    "rightshift": 0xA1,
    "leftctrl": 0xA2,
    "rightctrl": 0xA3,
    "leftalt": 0xA4,
    "rightalt": 0xA5,
    "volume_mute": 0xAD,
    "volume_down": 0xAE,
    "volume_up": 0xAF,
    "media_next": 0xB0,
    "media_prev": 0xB1,
    "media_stop": 0xB2,
    "media_play_pause": 0xB3,
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
}

HOTKEY_ALIASES = {
    "control": "ctrl",
    "left control": "leftctrl",
    "right control": "rightctrl",
    "left ctrl": "leftctrl",
    "right ctrl": "rightctrl",
    "left shift": "leftshift",
    "right shift": "rightshift",
    "left alt": "leftalt",
    "right alt": "rightalt",
    "windows": "win",
    "left win": "leftwin",
    "right win": "rightwin",
    "lwin": "leftwin",
    "rwin": "rightwin",
    "return": "enter",
    "escape": "esc",
    "page up": "pageup",
    "page down": "pagedown",
    "volume up": "volume_up",
    "volume down": "volume_down",
    "volume mute": "volume_mute",
}

DEFAULT_ADDRESS = ""

BUTTONS = (
    ("power", "电源键"),
    ("mic", "麦克风键"),
    ("up", "上键"),
    ("left", "左键"),
    ("ok", "确定键"),
    ("right", "右键"),
    ("down", "下键"),
    ("back", "返回键"),
    ("volume_up", "音量 +"),
    ("home", "主页键"),
    ("volume_down", "音量 -"),
    ("menu", "菜单键"),
    ("tv", "TV 键"),
)

BUTTON_ALIASES = {
    "up": ["kbd:VK_26:SC_048:E0:down", "kbd:VK_26:SC_048:N:down"],
    "down": ["kbd:VK_28:SC_050:E0:down", "kbd:VK_28:SC_050:N:down"],
    "left": ["kbd:VK_25:SC_04B:E0:down", "kbd:VK_25:SC_04B:N:down"],
    "right": ["kbd:VK_27:SC_04D:E0:down", "kbd:VK_27:SC_04D:N:down"],
    "ok": ["kbd:VK_0D:SC_01C:N:down"],
    "back": ["kbd:VK_A6:SC_000:E0:down", "kbd:VK_08:SC_00E:N:down"],
    "home": ["kbd:VK_AC:SC_000:E0:down", "kbd:VK_24:SC_047:E0:down"],
    "menu": ["kbd:VK_5D:SC_05D:E0:down"],
    "tv": ["kbd:VK_C0:SC_029:N:down"],
    "power": ["kbd:VK_FF:SC_05E:E0:down"],
    "volume_up": ["kbd:VK_AF:SC_000:E0:down"],
    "volume_down": ["kbd:VK_AE:SC_000:E0:down"],
    "mic": [],
}


DEFAULT_BUTTON_BINDINGS = {
    "power": [{"type": "hotkey", "keys": ["esc"]}],
    "mic": [{"type": "hotkey", "keys": list(DEFAULT_VOICE_HOTKEY)}],
    "up": [{"type": "hotkey", "keys": ["up"]}],
    "left": [{"type": "hotkey", "keys": ["left"]}],
    "ok": [{"type": "hotkey", "keys": ["enter"]}],
    "right": [{"type": "hotkey", "keys": ["right"]}],
    "down": [{"type": "hotkey", "keys": ["down"]}],
    "back": [{"type": "hotkey", "keys": ["backspace"], "hold_ms": 20}],
    "volume_up": [{"type": "hotkey", "keys": ["volume_up"]}],
    "home": [{"type": "hotkey", "keys": ["leftwin", "d"]}],
    "volume_down": [{"type": "hotkey", "keys": ["volume_down"]}],
    "menu": [{"type": "hotkey", "keys": ["shift", "f10"]}],
    "tv": [{"type": "hotkey", "keys": ["alt", "esc"]}],
}

CODEX_START_COMMAND = (
    "$app = Get-StartApps | Where-Object { $_.Name -in @('Codex', 'ChatGPT') } "
    "| Select-Object -First 1; "
    "if ($app) { Start-Process ('shell:AppsFolder\\' + $app.AppID) } "
    "else { try { Start-Process 'codex:' -ErrorAction Stop } "
    "catch { Start-Process 'codex.exe' } }"
)


def vibe_coding_button_bindings() -> dict:
    bindings = copy.deepcopy(DEFAULT_BUTTON_BINDINGS)
    bindings["power"] = [
        {
            "type": "command",
            "args": [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                CODEX_START_COMMAND,
            ],
            "label": "打开 Codex",
        }
    ]
    bindings["menu"] = [{"type": "hotkey", "keys": ["esc"]}]
    return bindings


def default_config() -> dict:
    return {
        "version": APP_VERSION,
        "address": DEFAULT_ADDRESS,
        "gain_db": 10.0,
        "retry_delay": 3.0,
        "voice_shortcut_enabled": True,
        "voice_hotkey": "+".join(DEFAULT_VOICE_HOTKEY),
        "voice_trigger_mode": VIBE_CODING_VOICE_TRIGGER_MODE,
        "raw_mapping_enabled": True,
        "tv_action_ready_delay": 2.0,
        "special_key_hook_enabled": True,
        "hid_report_tap_enabled": True,
        "back_repeat_delay": 0.28,
        "back_repeat_interval": 0.04,
        "volume_repeat_delay": 0.40,
        "volume_repeat_interval": 0.12,
    }


def default_keys_config() -> dict:
    return {
        "profile_name": "Xiaomi remote isolated mapping",
        "mapping_schema_version": MAPPING_SCHEMA_VERSION,
        "device_match": [],
        "allow_all_devices_for_actions": False,
        "listen_keyboard": True,
        "listen_mouse": False,
        "listen_consumer": True,
        "dedupe_hid_reports": True,
        "learn_log": "xiaomi-keys/learn_events.jsonl",
        "action_log": "xiaomi-keys/action_events.jsonl",
        "handle_key_up": False,
        "handle_mouse_move": False,
        "button_aliases": copy.deepcopy(BUTTON_ALIASES),
        "button_bindings": vibe_coding_button_bindings(),
        "bindings": {},
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_hotkey_token(raw: str) -> str:
    value = str(raw).strip().lower()
    return HOTKEY_ALIASES.get(value, value.replace(" ", ""))


def normalize_bluetooth_address(value: str) -> str:
    compact = re.sub(r"[^0-9a-fA-F]", "", str(value))
    if len(compact) != 12:
        raise ValueError(f"蓝牙地址格式无效：{value}")
    compact = compact.upper()
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def device_token_from_address(value: str) -> str:
    return normalize_bluetooth_address(value).replace(":", "").casefold()


def apply_remote_identity(config: dict, keys_config: dict, address: str) -> str:
    normalized = normalize_bluetooth_address(address)
    config["address"] = normalized
    keys_config["device_match"] = [device_token_from_address(normalized)]
    keys_config["allow_all_devices_for_actions"] = False
    return normalized


def hotkey_tokens(value: str | list[str] | tuple[str, ...]) -> list[str]:
    raw_values = value if isinstance(value, (list, tuple)) else str(value).replace("＋", "+").split("+")
    result: list[str] = []
    for raw in raw_values:
        token = normalize_hotkey_token(str(raw))
        if token and token not in result:
            result.append(token)
    return result


def resolve_hotkey_virtual_keys(value: str | list[str] | tuple[str, ...]) -> list[int]:
    result: list[int] = []
    for token in hotkey_tokens(value):
        if token.startswith("vk_"):
            try:
                virtual_key = int(token[3:], 16)
            except ValueError as exc:
                raise ValueError(f"无法识别按键：{token}") from exc
        elif token.startswith("f") and token[1:].isdigit():
            number = int(token[1:])
            virtual_key = 0x6F + number if 1 <= number <= 24 else None
        elif len(token) == 1 and token.isalnum():
            virtual_key = ord(token.upper())
        else:
            virtual_key = HOTKEY_VK.get(token)
        if virtual_key is None:
            raise ValueError(f"无法识别按键：{token}")
        if not 0 <= virtual_key <= 0xFF:
            raise ValueError(f"按键编码超出 Windows 支持范围：{token}")
        if virtual_key not in result:
            result.append(virtual_key)
    if not result:
        raise ValueError("语音快捷键不能为空")
    return result


def voice_hotkey_from_configs(config: dict, keys_config: dict) -> list[str]:
    configured = hotkey_tokens(config.get("voice_hotkey", ""))
    mic_actions = keys_config.get("button_bindings", {}).get("mic", [])
    if isinstance(mic_actions, dict):
        mic_actions = [mic_actions]
    mapped: list[str] = []
    for action in mic_actions if isinstance(mic_actions, list) else []:
        if isinstance(action, dict) and action.get("type") == "hotkey":
            mapped = hotkey_tokens(action.get("keys", []))
            if mapped:
                break

    default = list(DEFAULT_VOICE_HOTKEY)
    if mapped and configured and mapped != configured:
        # Older versions stored this setting twice. Preserve the non-default side
        # during migration; when both sides are custom, the visible button mapping wins.
        if mapped == default and configured != default:
            chosen = configured
        else:
            chosen = mapped
    else:
        chosen = mapped or configured or default
    resolve_hotkey_virtual_keys(chosen)
    return chosen


def load_config(path: Path = CONFIG_PATH) -> dict:
    defaults = default_config()
    config = defaults.copy()
    if path.exists():
        loaded = _read_json(path)
        if isinstance(loaded, dict):
            config.update(loaded)
    # These timings were internal defaults rather than user-facing settings.
    # Upgrade only the known slower defaults so an explicitly tuned value is
    # still preserved.
    if config.get("back_repeat_delay") == 0.45:
        config["back_repeat_delay"] = 0.28
    if config.get("back_repeat_interval") in (0.10, 0.045):
        config["back_repeat_interval"] = 0.04
    config = {key: config.get(key, value) for key, value in defaults.items()}
    config["version"] = APP_VERSION
    save_config(config, path)
    return config


def save_config(config: dict, path: Path = CONFIG_PATH) -> None:
    _write_json(path, config)


def load_keys_config(path: Path = KEYS_CONFIG_PATH) -> dict:
    config = default_keys_config()
    loaded_schema = MAPPING_SCHEMA_VERSION
    if path.exists():
        loaded = _read_json(path)
        if isinstance(loaded, dict):
            loaded_schema = int(loaded.get("mapping_schema_version", 0) or 0)
            config.update(loaded)
    device_match = config.get("device_match", [])
    config["device_match"] = [
        str(token).strip().casefold()
        for token in device_match
        if str(token).strip()
    ]
    config["allow_all_devices_for_actions"] = False
    config["listen_keyboard"] = True
    config["listen_mouse"] = False
    aliases = config.setdefault("button_aliases", {})
    for key, values in BUTTON_ALIASES.items():
        aliases.setdefault(key, copy.deepcopy(values))
    bindings = config.setdefault("button_bindings", {})
    if loaded_schema < MAPPING_SCHEMA_VERSION:
        for button_id, actions in DEFAULT_BUTTON_BINDINGS.items():
            bindings.setdefault(button_id, copy.deepcopy(actions))
    back_actions = bindings.get("back", [])
    if isinstance(back_actions, dict):
        back_actions = [back_actions]
    if isinstance(back_actions, list):
        for action in back_actions:
            if not isinstance(action, dict) or "hold_ms" in action:
                continue
            if action.get("type") == "hotkey" and action.get("keys") == [
                "backspace"
            ]:
                action["hold_ms"] = 20
    config["mapping_schema_version"] = MAPPING_SCHEMA_VERSION
    config.setdefault("bindings", {})
    save_keys_config(config, path)
    return config


def save_keys_config(config: dict, path: Path = KEYS_CONFIG_PATH) -> None:
    _write_json(path, config)
