#!/usr/bin/env python3
"""Shared per-user configuration for the Xiaomi remote bridge."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import threading


APPDATA = Path(os.environ.get("APPDATA", str(Path.home()))) / os.environ.get(
    "REMOTE_BRIDGE_XIAOMI_APP_ID", "MiVibeRemote"
)
CONFIG_PATH = APPDATA / "xiaomi.json"
KEYS_CONFIG_PATH = APPDATA / "xiaomi_keys.json"

APP_VERSION = "0.1.20"
APP_VERSION = os.environ.get("REMOTE_BRIDGE_XIAOMI_VERSION", APP_VERSION)
MAPPING_SCHEMA_VERSION = 3

CODEX_VOICE_HOTKEY = ("rightalt",)
CODEX_VOICE_TRIGGER_MODE = "hold"
WORKBUDDY_VOICE_HOTKEY = ("ctrl", "d")
WORKBUDDY_VOICE_TRIGGER_MODE = "toggle"
WECHAT_VOICE_HOTKEY = ("ctrl", "win")
WECHAT_VOICE_TRIGGER_MODE = "hold"
QIANWEN_VOICE_HOTKEY = ("rightctrl",)
QIANWEN_VOICE_TRIGGER_MODE = "toggle"
DEFAULT_VOICE_HOTKEY = CODEX_VOICE_HOTKEY
PRESET_ORDER = ("codex", "workbuddy", "wechat", "qianwen")
SIDED_MODIFIER_KEYS = frozenset(
    {
        "leftctrl",
        "rightctrl",
        "leftshift",
        "rightshift",
        "leftalt",
        "rightalt",
    }
)

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
    "menu": [
        "kbd:VK_5D:SC_05D:E0:down",
        "kbd:VK_5D:SC_05D:N:down",
        "kbd:VK_5D:SC_000:E0:down",
    ],
    "tv": [
        "kbd:VK_C0:SC_029:N:down",
        "kbd:VK_C0:SC_029:E0:down",
    ],
    "power": ["kbd:VK_FF:SC_05E:E0:down"],
    "volume_up": [
        "kbd:VK_AF:SC_000:E0:down",
        "kbd:VK_AF:SC_000:N:down",
    ],
    "volume_down": [
        "kbd:VK_AE:SC_000:E0:down",
        "kbd:VK_AE:SC_000:N:down",
    ],
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

WORKBUDDY_START_COMMAND = (
    "$app = Get-StartApps | Where-Object { $_.Name -eq 'WorkBuddy' } "
    "| Select-Object -First 1; "
    "if ($app) { Start-Process ('shell:AppsFolder\\' + $app.AppID) } "
    "else { try { Start-Process 'workbuddy:' -ErrorAction Stop } "
    "catch { Start-Process 'WorkBuddy.exe' } }"
)

WECHAT_START_COMMAND = (
    "$app = Get-StartApps | Where-Object { $_.Name -in @('微信', 'WeChat') } "
    "| Select-Object -First 1; "
    "if ($app) { Start-Process ('shell:AppsFolder\\' + $app.AppID) } "
    "else { $paths = @("
    "(Join-Path $env:ProgramFiles 'Tencent\\WeChat\\WeChat.exe'), "
    "(Join-Path ${env:ProgramFiles(x86)} 'Tencent\\WeChat\\WeChat.exe'), "
    "(Join-Path $env:LOCALAPPDATA 'Tencent\\WeChat\\WeChat.exe')"
    ") | Where-Object { $_ -and (Test-Path $_) }; "
    "$exe = $paths | Select-Object -First 1; "
    "if ($exe) { Start-Process $exe } else { Start-Process 'WeChat.exe' } }"
)

QIANWEN_START_COMMAND = (
    "$app = Get-StartApps | Where-Object { $_.Name -in @('千问办公', 'QwenWork') } "
    "| Select-Object -First 1; "
    "if ($app) { Start-Process ('shell:AppsFolder\\' + $app.AppID) } "
    "else { try { Start-Process 'qwenwork:' -ErrorAction Stop } "
    "catch { Start-Process 'QwenWork.exe' } }"
)


def codex_button_bindings() -> dict:
    bindings = copy.deepcopy(DEFAULT_BUTTON_BINDINGS)
    bindings["mic"] = [
        {"type": "hotkey", "keys": list(CODEX_VOICE_HOTKEY)}
    ]
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


def workbuddy_button_bindings() -> dict:
    bindings = copy.deepcopy(DEFAULT_BUTTON_BINDINGS)
    bindings["mic"] = [
        {"type": "hotkey", "keys": list(WORKBUDDY_VOICE_HOTKEY)}
    ]
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
                WORKBUDDY_START_COMMAND,
            ],
            "label": "打开 WorkBuddy",
        }
    ]
    bindings["menu"] = [{"type": "hotkey", "keys": ["esc"]}]
    return bindings


def wechat_button_bindings() -> dict:
    bindings = copy.deepcopy(DEFAULT_BUTTON_BINDINGS)
    bindings["mic"] = [
        {"type": "hotkey", "keys": list(WECHAT_VOICE_HOTKEY)}
    ]
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
                WECHAT_START_COMMAND,
            ],
            "label": "打开微信",
        }
    ]
    bindings["menu"] = [{"type": "hotkey", "keys": ["esc"]}]
    return bindings


def qianwen_button_bindings() -> dict:
    bindings = copy.deepcopy(DEFAULT_BUTTON_BINDINGS)
    bindings["mic"] = [
        {"type": "hotkey", "keys": list(QIANWEN_VOICE_HOTKEY)}
    ]
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
                QIANWEN_START_COMMAND,
            ],
            "label": "打开千问办公",
        }
    ]
    bindings["menu"] = [{"type": "hotkey", "keys": ["esc"]}]
    return bindings


def preset_button_bindings(preset: str) -> dict:
    if preset == "workbuddy":
        return workbuddy_button_bindings()
    if preset == "wechat":
        return wechat_button_bindings()
    if preset == "qianwen":
        return qianwen_button_bindings()
    return codex_button_bindings()


def custom_preset_definitions(keys_config: dict) -> dict:
    definitions = keys_config.get("custom_presets", {})
    return definitions if isinstance(definitions, dict) else {}


def available_preset_order(keys_config: dict) -> tuple[str, ...]:
    return PRESET_ORDER + tuple(custom_preset_definitions(keys_config))


def saved_preset_button_bindings(keys_config: dict, preset: str) -> dict:
    """Return an independent saved profile, falling back to its factory preset."""

    profiles = keys_config.get("preset_bindings", {})
    if isinstance(profiles, dict):
        saved = profiles.get(preset)
        if isinstance(saved, dict):
            return copy.deepcopy(saved)
    return preset_button_bindings(preset)


def save_preset_button_bindings(
    keys_config: dict, preset: str, bindings: dict
) -> None:
    """Persist one preset without replacing mappings saved for other presets."""

    profiles = keys_config.setdefault("preset_bindings", {})
    if not isinstance(profiles, dict):
        profiles = {}
        keys_config["preset_bindings"] = profiles
    profiles[preset] = copy.deepcopy(bindings)


def next_preset(
    preset: str, order: tuple[str, ...] = PRESET_ORDER
) -> str:
    if not order:
        return PRESET_ORDER[0]
    try:
        index = order.index(preset)
    except ValueError:
        return order[0]
    return order[(index + 1) % len(order)]


def apply_preset_configuration(
    config: dict,
    keys_config: dict,
    preset: str,
    preserve_cycle_actions: bool = True,
) -> str:
    preset_order = available_preset_order(keys_config)
    if preset not in preset_order:
        preset = PRESET_ORDER[0]
    current_preset = str(config.get("active_preset", PRESET_ORDER[0]))
    current_bindings = keys_config.get("button_bindings", {})
    if current_preset in preset_order and isinstance(current_bindings, dict):
        save_preset_button_bindings(
            keys_config, current_preset, current_bindings
        )
        current_custom = custom_preset_definitions(keys_config).get(current_preset)
        if isinstance(current_custom, dict):
            current_custom["voice_hotkey"] = str(config.get("voice_hotkey", ""))
            current_custom["voice_trigger_mode"] = str(
                config.get("voice_trigger_mode", "hold")
            )
            current_custom["voice_shortcut_enabled"] = bool(
                config.get("voice_shortcut_enabled", True)
            )
    cycle_bindings = {}
    if preserve_cycle_actions and isinstance(current_bindings, dict):
        for button, actions in current_bindings.items():
            action_list = actions if isinstance(actions, list) else [actions]
            if any(
                isinstance(action, dict) and action.get("type") == "preset_cycle"
                for action in action_list
            ):
                cycle_bindings[button] = copy.deepcopy(actions)

    bindings = saved_preset_button_bindings(keys_config, preset)
    bindings.update(cycle_bindings)
    voice_profiles = {
        "codex": (CODEX_VOICE_HOTKEY, CODEX_VOICE_TRIGGER_MODE),
        "workbuddy": (WORKBUDDY_VOICE_HOTKEY, WORKBUDDY_VOICE_TRIGGER_MODE),
        "wechat": (WECHAT_VOICE_HOTKEY, WECHAT_VOICE_TRIGGER_MODE),
        "qianwen": (QIANWEN_VOICE_HOTKEY, QIANWEN_VOICE_TRIGGER_MODE),
    }
    custom_preset = custom_preset_definitions(keys_config).get(preset)
    if isinstance(custom_preset, dict):
        voice_hotkey = tuple(
            hotkey_tokens(custom_preset.get("voice_hotkey", ""))
        ) or DEFAULT_VOICE_HOTKEY
        voice_trigger_mode = str(
            custom_preset.get("voice_trigger_mode", "hold")
        )
        voice_shortcut_enabled = bool(
            custom_preset.get("voice_shortcut_enabled", True)
        )
    else:
        voice_hotkey, voice_trigger_mode = voice_profiles[preset]
        voice_shortcut_enabled = True
    config["active_preset"] = preset
    config["voice_shortcut_enabled"] = voice_shortcut_enabled
    config["voice_hotkey"] = "+".join(voice_hotkey)
    config["voice_trigger_mode"] = voice_trigger_mode
    keys_config["button_bindings"] = copy.deepcopy(bindings)
    save_preset_button_bindings(keys_config, preset, bindings)
    return preset


def cycle_preset_configuration(config: dict, keys_config: dict) -> str:
    order = available_preset_order(keys_config)
    return apply_preset_configuration(
        config,
        keys_config,
        next_preset(
            str(config.get("active_preset", PRESET_ORDER[0])), order
        ),
    )


def default_config() -> dict:
    return {
        "version": APP_VERSION,
        "address": DEFAULT_ADDRESS,
        "gain_db": 10.0,
        "retry_delay": 3.0,
        "voice_shortcut_enabled": True,
        "voice_hotkey": "+".join(DEFAULT_VOICE_HOTKEY),
        "voice_trigger_mode": CODEX_VOICE_TRIGGER_MODE,
        "active_preset": "codex",
        "raw_mapping_enabled": True,
        "tv_action_ready_delay": 2.0,
        "special_key_hook_enabled": True,
        "hid_report_tap_enabled": True,
        "hid_tap_compatible": False,
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
        "button_bindings": codex_button_bindings(),
        "preset_bindings": {
            preset: preset_button_bindings(preset) for preset in PRESET_ORDER
        },
        "custom_presets": {},
        "bindings": {},
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        temporary.write_text(payload, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


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


def hotkey_injection_method(value: str | list[str] | tuple[str, ...]) -> str:
    """Use scan codes when an app distinguishes the physical modifier side."""
    return (
        "scan_code"
        if any(token in SIDED_MODIFIER_KEYS for token in hotkey_tokens(value))
        else "virtual_key"
    )


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
        existing = aliases.get(key, [])
        if isinstance(existing, str):
            existing = [existing]
        elif not isinstance(existing, list):
            existing = []
        aliases[key] = existing + [
            value for value in values if value not in existing
        ]
    bindings = config.setdefault("button_bindings", {})
    if loaded_schema < 1:
        for button_id, actions in DEFAULT_BUTTON_BINDINGS.items():
            bindings.setdefault(button_id, copy.deepcopy(actions))
    profiles = config.get("preset_bindings", {})
    if not isinstance(profiles, dict):
        profiles = {}
    if loaded_schema < 2:
        # Schema 1 had only one global mapping. Treat it as the saved mapping
        # for the active preset; other profiles start from their own defaults.
        active_preset = "codex"
        try:
            sibling_config = load_config(path.with_name(CONFIG_PATH.name))
            configured = str(sibling_config.get("active_preset", "codex"))
            if configured in PRESET_ORDER:
                active_preset = configured
        except (OSError, ValueError, json.JSONDecodeError):
            pass
        profiles = {
            preset: preset_button_bindings(preset) for preset in PRESET_ORDER
        }
        profiles[active_preset] = copy.deepcopy(bindings)
    else:
        for preset in PRESET_ORDER:
            if not isinstance(profiles.get(preset), dict):
                profiles[preset] = preset_button_bindings(preset)
    custom_presets = config.get("custom_presets", {})
    if not isinstance(custom_presets, dict):
        custom_presets = {}
    sanitized_custom_presets = {}
    for preset, details in custom_presets.items():
        if not isinstance(details, dict):
            continue
        preset_id = str(preset).strip()
        name = str(details.get("name", "")).strip()
        if (
            not preset_id
            or not name
            or not isinstance(profiles.get(preset_id), dict)
        ):
            continue
        try:
            voice_hotkey = "+".join(
                hotkey_tokens(details.get("voice_hotkey", ""))
            )
            resolve_hotkey_virtual_keys(voice_hotkey)
        except ValueError:
            voice_hotkey = "+".join(DEFAULT_VOICE_HOTKEY)
        trigger_mode = str(details.get("voice_trigger_mode", "hold"))
        sanitized_custom_presets[preset_id] = {
            "name": name[:20],
            "voice_hotkey": voice_hotkey,
            "voice_trigger_mode": (
                trigger_mode if trigger_mode in {"toggle", "hold"} else "hold"
            ),
            "voice_shortcut_enabled": bool(
                details.get("voice_shortcut_enabled", True)
            ),
        }
    config["custom_presets"] = sanitized_custom_presets
    config["preset_bindings"] = profiles
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
