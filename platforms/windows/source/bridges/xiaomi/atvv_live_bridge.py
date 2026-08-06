#!/usr/bin/env python3
"""Bridge a Xiaomi ATVV voice remote into a Windows virtual microphone.

The remote sends 16 kHz IMA/DVI ADPCM through the Android TV Voice-over-BLE
GATT service.  This process decodes it, upsamples it to 48 kHz, and writes it
to the playback side of the installed VB-Audio Virtual Cable loopback.
Applications record the matching ``CABLE Output`` endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid

from winrt.windows.devices.bluetooth import BluetoothCacheMode, BluetoothLEDevice
from winrt.windows.devices.bluetooth.genericattributeprofile import (
    GattClientCharacteristicConfigurationDescriptorValue as CccdValue,
    GattDeviceService,
    GattWriteOption,
)
from winrt.windows.devices.enumeration import DeviceInformation
from winrt.windows.storage.streams import DataReader

from .atvv_record import (
    GET_CAPS_V10,
    VOICE_SERVICE_UUID,
    VOICE_AUDIO_UUID,
    VOICE_CONTROL_UUID,
    VOICE_TX_UUID,
    AdpcmDecoder,
    address_to_int,
    bytes_buffer,
    discover_atvv,
    postprocess,
    write_command,
)
from .xiaomi_config import (
    BUTTON_ALIASES,
    CONFIG_PATH,
    KEYS_CONFIG_PATH,
    DEFAULT_ADDRESS,
    DEFAULT_VOICE_HOTKEY,
    HOTKEY_VK,
    apply_remote_identity,
    cycle_preset_configuration,
    device_token_from_address,
    load_config,
    load_keys_config,
    resolve_hotkey_virtual_keys,
    hotkey_injection_method,
    save_config,
    save_keys_config,
    voice_hotkey_from_configs,
)
from .hid_report_tap import XiaomiHidReportTap
from bridges.audio_client import PCM_PORT, ROUTER_HOST


_MUTEX_HANDLE = None
_RUNTIME_LOG = None
TV_EVENT_IDS = frozenset(BUTTON_ALIASES["tv"])
HID_SERVICE_UUID = "00001812-0000-1000-8000-00805f9b34fb"
HID_REPORT_UUID = "00002a4d-0000-1000-8000-00805f9b34fb"
HID_REPORT_REFERENCE_UUID = "00002908-0000-1000-8000-00805f9b34fb"
HID_CONTROL_POINT_UUID = "00002a4c-0000-1000-8000-00805f9b34fb"
HID_PROTOCOL_MODE_UUID = "00002a4e-0000-1000-8000-00805f9b34fb"
XIAOMI_2_PRO_HARDWARE_TOKEN = "dev_vid&012717_pid&32b8"
XIAOMI_REMOTE_NAMES = frozenset(
    {
        "mi rc",
        "rc001",
        "rc003",
        "xiaomi bluetooth remote 2",
        "xiaomi bluetooth remote 2 pro",
        "小米蓝牙语音遥控器",
    }
)
INTERFACE_ADDRESS_RE = re.compile(
    r"[_-]([0-9a-f]{12})(?:[#\\]|$)", re.IGNORECASE
)


def xiaomi_candidate_from_interface(name: str, interface_id: str) -> dict | None:
    folded_id = str(interface_id).casefold()
    folded_name = str(name).strip().casefold()
    match = INTERFACE_ADDRESS_RE.search(folded_id)
    if match is None:
        return None
    token = match.group(1).casefold()
    address = ":".join(token[index : index + 2] for index in range(0, 12, 2)).upper()
    return {
        "name": str(name).strip() or "MI RC",
        "address": address,
        "device_token": token,
        "interface_id": str(interface_id),
        "hardware_match": XIAOMI_2_PRO_HARDWARE_TOKEN in folded_id,
        "known_name": folded_name in XIAOMI_REMOTE_NAMES,
    }


async def discover_xiaomi_2_pro_candidates() -> list[dict]:
    selector = GattDeviceService.get_device_selector_from_uuid(
        uuid.UUID(VOICE_SERVICE_UUID)
    )
    interfaces = await DeviceInformation.find_all_async_aqs_filter(selector)
    by_token: dict[str, dict] = {}
    for interface in interfaces:
        candidate = xiaomi_candidate_from_interface(interface.name, interface.id)
        if candidate is None:
            continue
        existing = by_token.get(candidate["device_token"])
        if existing is None or (
            candidate["hardware_match"] and not existing["hardware_match"]
        ):
            by_token[candidate["device_token"]] = candidate
    return sorted(
        by_token.values(),
        key=lambda item: (not item["hardware_match"], item["device_token"]),
    )


def choose_xiaomi_2_pro_candidate(
    candidates: list[dict], configured_address: str
) -> dict | None:
    try:
        configured_token = device_token_from_address(configured_address)
    except ValueError:
        configured_token = ""
    for candidate in candidates:
        if candidate["device_token"] == configured_token:
            return candidate
    if len(candidates) == 1:
        return candidates[0]
    hardware_matches = [item for item in candidates if item["hardware_match"]]
    if len(hardware_matches) == 1:
        return hardware_matches[0]
    return None


def discover_and_apply_xiaomi_identity(
    config: dict,
    keys_config: dict,
    config_path: Path,
    keys_config_path: Path = KEYS_CONFIG_PATH,
    explicit_address: str = "",
) -> str:
    if explicit_address:
        address = apply_remote_identity(config, keys_config, explicit_address)
        save_config(config, config_path)
        save_keys_config(keys_config, keys_config_path)
        print(f"XIAOMI DEVICE explicit address={address}", flush=True)
        return address

    try:
        candidates = asyncio.run(discover_xiaomi_2_pro_candidates())
    except Exception as exc:
        print(
            f"XIAOMI DEVICE discovery warning {type(exc).__name__}: {exc}",
            flush=True,
        )
        candidates = []
    candidate = choose_xiaomi_2_pro_candidate(
        candidates, str(config.get("address", ""))
    )
    if candidate is None:
        configured = str(config.get("address", "")).strip()
        if len(candidates) > 1:
            print(
                f"XIAOMI DEVICE multiple candidates={len(candidates)}; "
                "请仅保留当前使用的小米遥控器配对后重启",
                flush=True,
            )
        else:
            print("XIAOMI DEVICE not found; 请先在 Windows 中配对 MI RC", flush=True)
        return configured

    address = apply_remote_identity(config, keys_config, candidate["address"])
    # The optional WUDF/Frida compatibility tap is verified only for RC003.
    # RC001 and other ATVV-compatible Xiaomi remotes use the normal Raw Input
    # mapping path instead of attempting an incompatible elevated injection.
    config["hid_tap_compatible"] = bool(candidate["hardware_match"])
    save_config(config, config_path)
    save_keys_config(keys_config, keys_config_path)
    print(
        f"XIAOMI DEVICE AUTO name={candidate['name']} address={address} "
        f"filter={candidate['device_token']}",
        flush=True,
    )
    return address


def configure_pythonw_logging() -> None:
    global _RUNTIME_LOG
    if sys.stdout is not None and sys.stderr is not None:
        return
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _RUNTIME_LOG = (log_dir / "runtime_pythonw.log").open(
        "a", encoding="utf-8", buffering=1
    )
    sys.stdout = _RUNTIME_LOG
    sys.stderr = _RUNTIME_LOG


def acquire_single_instance() -> bool:
    global _MUTEX_HANDLE
    if os.name != "nt":
        return True
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel32.CreateMutexW(None, False, "Local\\XiaomiRemoteMicBridge")
    if not handle:
        return True
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _MUTEX_HANDLE = handle
    return True


class XiaomiTvActionGate:
    """Ignore TV-key actions until the ATVV bridge has been ready for a moment."""

    def __init__(self, ready_delay: float = 2.0):
        self.ready_delay = max(0.0, float(ready_delay))
        self._ready_at: float | None = None
        self._last_block_log = 0.0
        self._lock = threading.Lock()

    def mark_connecting(self) -> None:
        with self._lock:
            self._ready_at = None

    def mark_ready(self) -> None:
        with self._lock:
            self._ready_at = time.monotonic() + self.ready_delay
        print(
            f"XIAOMI TV ACTION GUARD armed_after={self.ready_delay:.1f}s",
            flush=True,
        )

    def is_ready(self) -> bool:
        with self._lock:
            ready_at = self._ready_at
        return ready_at is not None and time.monotonic() >= ready_at

    def __call__(self, event: dict, _action: dict) -> bool:
        if event.get("event_id") not in TV_EVENT_IDS:
            return True
        now = time.monotonic()
        with self._lock:
            ready_at = self._ready_at
            allowed = ready_at is not None and now >= ready_at
            should_log = not allowed and now - self._last_block_log >= 0.5
            if should_log:
                self._last_block_log = now
        if should_log:
            state = "connecting" if ready_at is None else "ready_delay"
            print(f"XIAOMI TV ACTION BLOCKED state={state}", flush=True)
        return allowed


class KbdLlHookStruct(ctypes.Structure):
    _fields_ = [
        ("vk_code", wintypes.DWORD),
        ("scan_code", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra_info", ctypes.c_size_t),
    ]


class XiaomiSpecialKeyHook:
    """Run configured Xiaomi actions and suppress only correlated originals."""

    WH_KEYBOARD_LL = 13
    HC_ACTION = 0
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    WM_QUIT = 0x0012
    LLKHF_INJECTED = 0x10
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    VK_BACK = 0x08
    VK_SHIFT = 0x10
    VK_RETURN = 0x0D
    VK_ESCAPE = 0x1B
    VK_ALT = 0x12
    VK_HOME = 0x24
    VK_LEFT = 0x25
    VK_UP = 0x26
    VK_RIGHT = 0x27
    VK_DOWN = 0x28
    VK_LWIN = 0x5B
    VK_APPS = 0x5D
    VK_SLEEP = 0x5F
    VK_F5 = 0x74
    VK_F10 = 0x79
    VK_VOLUME_MUTE = 0xAD
    VK_VOLUME_DOWN = 0xAE
    VK_VOLUME_UP = 0xAF
    VK_BROWSER_BACK = 0xA6
    VK_BROWSER_HOME = 0xAC
    VK_OEM_3 = 0xC0
    VK_UNKNOWN_FF = 0xFF
    TV_SCAN_CODE = 0x29
    POWER_SCAN_CODE = 0x5E
    EXTRA_INFO = 0x584D4952
    DIRECT_USAGES = {
        "ok": 0x28,
        "tv": 0x35,
        "home": 0x4A,
        "right": 0x4F,
        "left": 0x50,
        "down": 0x51,
        "up": 0x52,
        "menu": 0x65,
        "power": 0x66,
        "volume_mute": 0x7F,
        "volume_up": 0x80,
        "volume_down": 0x81,
        "back": 0xF1,
    }
    USAGE_BUTTONS = {usage: name for name, usage in DIRECT_USAGES.items()}
    WAIT_FOR_DIRECT_SIGNAL = frozenset({"tv", "home", "menu", "power"})

    def __init__(
        self,
        action_gate: XiaomiTvActionGate,
        enabled: bool = True,
        back_repeat_delay: float = 0.28,
        back_repeat_interval: float = 0.04,
        volume_repeat_delay: float = 0.40,
        volume_repeat_interval: float = 0.12,
        button_bindings: dict | None = None,
        preset_cycle_handler=None,
    ):
        self.action_gate = action_gate
        self.enabled = enabled and os.name == "nt"
        self.back_repeat_delay = max(0.20, float(back_repeat_delay))
        self.back_repeat_interval = max(0.04, float(back_repeat_interval))
        self.volume_repeat_delay = max(0.20, float(volume_repeat_delay))
        self.volume_repeat_interval = max(0.04, float(volume_repeat_interval))
        self.button_bindings = button_bindings if isinstance(button_bindings, dict) else {}
        self.preset_cycle_handler = preset_cycle_handler
        self._bridge_core = None
        self._bridge_core_lock = threading.Lock()
        self.user32 = ctypes.windll.user32
        self.kernel32 = ctypes.windll.kernel32
        self.hook = None
        self.thread_id = 0
        self.direct_active_usages: set[int] = set()
        self.direct_state_lock = threading.Lock()
        self.key_send_lock = threading.Lock()
        self.back_repeat_generation = 0
        self.volume_repeat_generation = 0
        self.stop_event = threading.Event()
        self.direct_signal_lock = threading.Lock()
        self.direct_signal_times: dict[str, float] = {}
        self.direct_signal_events = {
            name: threading.Event() for name in (*self.DIRECT_USAGES, "mic")
        }
        # Some Xiaomi 2 Pro firmware exposes the physical microphone button
        # to Windows as F5 in addition to starting the ATVV voice session.
        # Remember a correlated key-down so its eventual key-up and repeats
        # are swallowed too, without ever intercepting an ordinary F5 key.
        self.voice_f5_down_suppressed = False
        self.proc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        )
        self.proc = self.proc_type(self._callback)
        self.user32.SetWindowsHookExW.argtypes = (
            ctypes.c_int,
            self.proc_type,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        )
        self.user32.SetWindowsHookExW.restype = wintypes.HHOOK
        self.user32.CallNextHookEx.argtypes = (
            wintypes.HHOOK,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        self.user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self.user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
        self.user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        self.user32.PostThreadMessageW.argtypes = (
            wintypes.DWORD,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        self.user32.PostThreadMessageW.restype = wintypes.BOOL
        self.kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        self.kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self.kernel32.GetCurrentThreadId.restype = wintypes.DWORD
        self.thread: threading.Thread | None = None

    def _call_next(self, code: int, wparam: int, lparam: int) -> int:
        return int(self.user32.CallNextHookEx(self.hook, code, wparam, lparam))

    def _first_button_action(self, name: str) -> dict | None:
        actions = self.button_bindings.get(name, [])
        if isinstance(actions, dict):
            actions = [actions]
        if not isinstance(actions, list):
            return None
        return next(
            (
                action
                for action in actions
                if isinstance(action, dict)
                and action.get("type") not in {None, "none", "log"}
            ),
            None,
        )

    def _load_bridge_core(self):
        with self._bridge_core_lock:
            if self._bridge_core is not None:
                return self._bridge_core
            from bridges import raw_input_bridge as bridge_core

            self._bridge_core = bridge_core
            return bridge_core

    def _perform_button_action(self, name: str) -> bool:
        action = self._first_button_action(name)
        if action is None:
            return False
        try:
            action_type = str(action.get("type", "hotkey"))
            log_keys: list[str] = []
            log_injection = "-"
            if action_type == "preset_cycle":
                if self.preset_cycle_handler is None:
                    return False
                preset = self.preset_cycle_handler()
                print(
                    f"XIAOMI PRESET CYCLE active={preset}",
                    flush=True,
                )
                return True
            with self.key_send_lock:
                if action_type == "command":
                    arguments = action.get("args", [])
                    if not isinstance(arguments, list) or not arguments:
                        raise ValueError("command action requires a non-empty args list")
                    subprocess.Popen(
                        [str(argument) for argument in arguments],
                        cwd=action.get("cwd") or None,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                else:
                    core = self._load_bridge_core()
                    if action_type == "hotkey":
                        keys = list(action.get("keys", []))
                        injection = str(
                            action.get("injection") or hotkey_injection_method(keys)
                        )
                        log_keys = [str(key) for key in keys]
                        log_injection = injection
                        if injection == "scan_code":
                            core.send_scan_code_hotkey(
                                keys,
                                int(action.get("hold_ms", 120)),
                            )
                        else:
                            core.send_hotkey(
                                keys,
                                int(action.get("hold_ms", 70)),
                            )
                    elif action_type == "key":
                        log_keys = [str(action.get("key", ""))]
                        core.send_hotkey(log_keys)
                    elif action_type == "text":
                        core.send_text(str(action.get("text", "")))
                    else:
                        print(
                            f"XIAOMI MAPPING unsupported_action={action_type} key={name}",
                            flush=True,
                        )
                        return False
            print(
                f"XIAOMI MAPPING DONE key={name} action={action_type} "
                f"keys={'+'.join(log_keys) or '-'} injection={log_injection}",
                flush=True,
            )
            return True
        except Exception as exc:
            print(
                f"XIAOMI MAPPING ERROR key={name} {type(exc).__name__}: {exc}",
                flush=True,
            )
            return False

    def _send_button_action(self, name: str) -> bool:
        if self._first_button_action(name) is None:
            return False

        threading.Thread(
            target=self._perform_button_action,
            args=(name,),
            name=f"xiaomi-mapping-{name}",
            daemon=True,
        ).start()
        return True

    def _cancel_back_repeat(self) -> None:
        with self.direct_state_lock:
            self.back_repeat_generation += 1

    def _start_back_repeat(self) -> None:
        with self.direct_state_lock:
            self.back_repeat_generation += 1
            generation = self.back_repeat_generation

        def worker() -> None:
            if self.stop_event.wait(self.back_repeat_delay):
                return
            repeated = 0
            while not self.stop_event.is_set():
                with self.direct_state_lock:
                    active = (
                        generation == self.back_repeat_generation
                        and 0xF1 in self.direct_active_usages
                    )
                if not active or not self.action_gate.is_ready():
                    break
                self._perform_button_action("back")
                repeated += 1
                if self.stop_event.wait(self.back_repeat_interval):
                    break
            if repeated:
                print(
                    f"XIAOMI HID DIRECT back_repeat stopped repeats={repeated}",
                    flush=True,
                )

        threading.Thread(
            target=worker,
            name="xiaomi-backspace-repeat",
            daemon=True,
        ).start()

    def _cancel_volume_repeat(self) -> None:
        with self.direct_state_lock:
            self.volume_repeat_generation += 1

    def _start_volume_repeat(self, usage: int, name: str) -> None:
        with self.direct_state_lock:
            self.volume_repeat_generation += 1
            generation = self.volume_repeat_generation

        def worker() -> None:
            if self.stop_event.wait(self.volume_repeat_delay):
                return
            repeated = 0
            while not self.stop_event.is_set():
                with self.direct_state_lock:
                    active = (
                        generation == self.volume_repeat_generation
                        and usage in self.direct_active_usages
                    )
                if not active or not self.action_gate.is_ready():
                    break
                self._perform_button_action(name)
                repeated += 1
                if self.stop_event.wait(self.volume_repeat_interval):
                    break
            if repeated:
                print(
                    f"XIAOMI HID DIRECT {name}_repeat stopped repeats={repeated}",
                    flush=True,
                )

        threading.Thread(
            target=worker,
            name=f"xiaomi-{name}-repeat",
            daemon=True,
        ).start()

    def _direct_name(self, usage: int) -> str | None:
        # RC003 report ID 1 is an array of three 16-bit Keyboard-page usages.
        # 0xF1 is the Linux/Android KEY_BACK extension that Windows kbdhid drops.
        return self.USAGE_BUTTONS.get(usage)

    def _mark_direct_signal(self, name: str) -> None:
        event = self.direct_signal_events.get(name)
        if event is None:
            return
        with self.direct_signal_lock:
            self.direct_signal_times[name] = time.monotonic()
        event.set()

    def mark_voice_signal(self) -> None:
        """Correlate the firmware's stray F5 with a real ATVV mic request."""

        self._mark_direct_signal("mic")

    def _should_suppress_voice_f5(self, wparam: int) -> bool:
        is_down = wparam in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN)
        is_up = wparam in (self.WM_KEYUP, self.WM_SYSKEYUP)
        if not is_down and not is_up:
            return False
        if is_up:
            matched = self.voice_f5_down_suppressed
            self.voice_f5_down_suppressed = False
            return matched
        if self.voice_f5_down_suppressed:
            return True
        if not self.action_gate.is_ready():
            return False
        matched = self._wait_for_direct_signal("mic", timeout=0.08)
        if matched:
            self.voice_f5_down_suppressed = True
        return matched

    def _direct_name_active(self, name: str) -> bool:
        usage = self.DIRECT_USAGES.get(name)
        if usage is None:
            return False
        with self.direct_state_lock:
            return usage in self.direct_active_usages

    def _direct_signal_recent(self, name: str, window: float = 0.30) -> bool:
        with self.direct_signal_lock:
            occurred_at = self.direct_signal_times.get(name, 0.0)
        return time.monotonic() - occurred_at <= window

    def _wait_for_direct_signal(self, name: str, timeout: float = 0.06) -> bool:
        if self._direct_name_active(name) or self._direct_signal_recent(name):
            return True
        event = self.direct_signal_events[name]
        event.clear()
        if self._direct_name_active(name) or self._direct_signal_recent(name):
            return True
        event.wait(timeout)
        return self._direct_name_active(name) or self._direct_signal_recent(name)

    def handle_direct_hid_report(self, report_id: int, payload: bytes) -> None:
        if report_id != 1:
            return
        # GATT Report characteristics normally omit the report ID. Accept an
        # included ID as well so firmware variants do not shift every usage.
        if len(payload) == 7 and payload[0] == report_id:
            payload = payload[1:]
        if not payload or len(payload) % 2:
            print(
                f"XIAOMI HID DIRECT malformed report={report_id} data={payload.hex()}",
                flush=True,
            )
            return
        active = {
            int.from_bytes(payload[index : index + 2], "little")
            for index in range(0, len(payload), 2)
        }
        active.discard(0)
        with self.direct_state_lock:
            pressed = active - self.direct_active_usages
            released = self.direct_active_usages - active
            self.direct_active_usages = active

        for usage in sorted(pressed):
            name = self._direct_name(usage)
            if name is None:
                print(f"XIAOMI HID DIRECT usage=0x{usage:04X} ignored", flush=True)
                continue
            self._mark_direct_signal(name)
            if self.action_gate.is_ready():
                triggered = self._send_button_action(name)
                if triggered and usage == 0xF1:
                    self._start_back_repeat()
                elif triggered and usage in (0x80, 0x81):
                    self._start_volume_repeat(usage, name)
                print(
                    f"XIAOMI HID DIRECT key={name} usage=0x{usage:04X} "
                    f"mapped={str(triggered).lower()}",
                    flush=True,
                )
            else:
                print(
                    f"XIAOMI HID DIRECT key={name} usage=0x{usage:04X} blocked_not_ready",
                    flush=True,
                )
        for usage in sorted(released):
            name = self._direct_name(usage)
            if name is not None:
                self._mark_direct_signal(name)
                if usage == 0xF1:
                    self._cancel_back_repeat()
                elif usage in (0x80, 0x81):
                    self._cancel_volume_repeat()
                print(
                    f"XIAOMI HID DIRECT key={name} usage=0x{usage:04X} released",
                    flush=True,
                )

    def reset_direct_hid_state(self) -> None:
        with self.direct_state_lock:
            self.direct_active_usages.clear()
            self.back_repeat_generation += 1
            self.volume_repeat_generation += 1
        self.voice_f5_down_suppressed = False
        with self.direct_signal_lock:
            self.direct_signal_times.pop("mic", None)
        self.direct_signal_events["mic"].clear()

    def _callback(self, code: int, wparam: int, lparam: int) -> int:
        if code != self.HC_ACTION:
            return self._call_next(code, wparam, lparam)
        info = ctypes.cast(lparam, ctypes.POINTER(KbdLlHookStruct)).contents
        if info.flags & self.LLKHF_INJECTED or info.extra_info == self.EXTRA_INFO:
            return self._call_next(code, wparam, lparam)

        if info.vk_code == self.VK_F5:
            if self._should_suppress_voice_f5(wparam):
                if wparam in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
                    print(
                        "XIAOMI SPECIAL KEY mic firmware_f5_suppressed",
                        flush=True,
                    )
                return 1
            return self._call_next(code, wparam, lparam)

        key_name = None
        if info.vk_code == self.VK_OEM_3 and info.scan_code == self.TV_SCAN_CODE:
            key_name = "tv"
        elif info.vk_code == self.VK_BROWSER_BACK:
            key_name = "back"
        elif info.vk_code in (self.VK_BROWSER_HOME, self.VK_HOME):
            key_name = "home"
        elif info.vk_code == self.VK_APPS:
            key_name = "menu"
        elif info.vk_code == self.VK_RETURN:
            key_name = "ok"
        elif info.vk_code == self.VK_LEFT:
            key_name = "left"
        elif info.vk_code == self.VK_RIGHT:
            key_name = "right"
        elif info.vk_code == self.VK_UP:
            key_name = "up"
        elif info.vk_code == self.VK_DOWN:
            key_name = "down"
        elif info.vk_code == self.VK_VOLUME_MUTE:
            key_name = "volume_mute"
        elif info.vk_code == self.VK_VOLUME_UP:
            key_name = "volume_up"
        elif info.vk_code == self.VK_VOLUME_DOWN:
            key_name = "volume_down"
        elif info.vk_code in (self.VK_SLEEP, self.VK_UNKNOWN_FF) or (
            info.scan_code == self.POWER_SCAN_CODE
        ):
            key_name = "power"
        if key_name is None:
            return self._call_next(code, wparam, lparam)

        # The HidOverGatt tap emits the configured replacement. Suppress the
        # Windows translation only when the same remote usage was just seen;
        # an ordinary physical keyboard event therefore passes through.
        if self._first_button_action(key_name) is None:
            return self._call_next(code, wparam, lparam)
        timeout = 0.06 if key_name in self.WAIT_FOR_DIRECT_SIGNAL else 0.015
        matched = self._wait_for_direct_signal(key_name, timeout)
        if not matched:
            return self._call_next(code, wparam, lparam)
        if wparam in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
            print(
                f"XIAOMI SPECIAL KEY {key_name} original_suppressed",
                flush=True,
            )
        return 1

    def _run(self) -> None:
        self.thread_id = int(self.kernel32.GetCurrentThreadId())
        module = self.kernel32.GetModuleHandleW(None)
        self.hook = self.user32.SetWindowsHookExW(
            self.WH_KEYBOARD_LL, self.proc, module, 0
        )
        if not self.hook:
            print(
                f"XIAOMI SPECIAL KEYS ERROR SetWindowsHookExW={ctypes.get_last_error()}",
                flush=True,
            )
            return
        print(
            "XIAOMI SPECIAL KEYS READY mapping=configurable "
            "repeat=back,volume suppress_original=device-correlated",
            flush=True,
        )
        message = wintypes.MSG()
        while self.user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))
        self.user32.UnhookWindowsHookEx(self.hook)
        self.hook = None

    def start(self) -> None:
        if not self.enabled:
            print("XIAOMI SPECIAL KEYS disabled", flush=True)
            return
        self.thread = threading.Thread(
            target=self._run,
            name="xiaomi-special-key-hook",
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.reset_direct_hid_state()
        if self.thread_id:
            self.user32.PostThreadMessageW(self.thread_id, self.WM_QUIT, 0, 0)


class XiaomiGattHidSession:
    """Read RC003 input reports directly when Windows HID is disabled."""

    def __init__(self, service):
        self.service = service
        self.subscriptions: list[tuple[object, object]] = []

    @staticmethod
    async def _write_byte(characteristic, value: int, label: str) -> None:
        try:
            status = await characteristic.write_value_with_option_async(
                bytes_buffer(bytes((value,))),
                GattWriteOption.WRITE_WITHOUT_RESPONSE,
            )
            print(
                f"XIAOMI HID DIRECT write={label} value={value} status={int(status)}",
                flush=True,
            )
        except Exception as exc:
            print(
                f"XIAOMI HID DIRECT write_warning={label} "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    @staticmethod
    async def _report_reference(characteristic) -> tuple[int, int]:
        try:
            result = await characteristic.get_descriptors_with_cache_mode_async(
                BluetoothCacheMode.UNCACHED
            )
            for descriptor in result.descriptors:
                if str(descriptor.uuid).casefold() != HID_REPORT_REFERENCE_UUID:
                    continue
                value_result = await descriptor.read_value_with_cache_mode_async(
                    BluetoothCacheMode.UNCACHED
                )
                if int(value_result.status) != 0:
                    continue
                value = buffer_bytes(value_result.value)
                if len(value) >= 2:
                    return value[0], value[1]
        except Exception as exc:
            print(
                f"XIAOMI HID DIRECT report_reference_warning "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
        return 0, 0

    @classmethod
    async def open(cls, device, events: asyncio.Queue[tuple[str, bytes]]):
        service = None
        try:
            services_result = await device.get_gatt_services_with_cache_mode_async(
                BluetoothCacheMode.UNCACHED
            )
            if int(services_result.status) != 0:
                print(
                    f"XIAOMI HID DIRECT unavailable services_status="
                    f"{int(services_result.status)}",
                    flush=True,
                )
                return None
            service = next(
                (
                    item
                    for item in services_result.services
                    if str(item.uuid).casefold() == HID_SERVICE_UUID
                ),
                None,
            )
            if service is None:
                print("XIAOMI HID DIRECT unavailable service_not_found", flush=True)
                return None

            chars_result = await service.get_characteristics_with_cache_mode_async(
                BluetoothCacheMode.UNCACHED
            )
            if int(chars_result.status) != 0:
                print(
                    f"XIAOMI HID DIRECT unavailable characteristics_status="
                    f"{int(chars_result.status)}; windows_hid_active=true",
                    flush=True,
                )
                service.close()
                return None

            session = cls(service)
            loop = asyncio.get_running_loop()
            for characteristic in chars_result.characteristics:
                char_uuid = str(characteristic.uuid).casefold()
                props = int(characteristic.characteristic_properties)
                if char_uuid == HID_PROTOCOL_MODE_UUID and props & (0x04 | 0x08):
                    await cls._write_byte(characteristic, 1, "protocol_report_mode")
                elif char_uuid == HID_CONTROL_POINT_UUID and props & (0x04 | 0x08):
                    await cls._write_byte(characteristic, 1, "exit_suspend")

                if char_uuid != HID_REPORT_UUID or not props & (0x10 | 0x20):
                    continue
                report_id, report_type = await cls._report_reference(characteristic)
                handle = int(characteristic.attribute_handle)
                print(
                    f"XIAOMI HID DIRECT report handle={handle} id={report_id} "
                    f"type={report_type} properties=0x{props:02X}",
                    flush=True,
                )
                if report_type not in (0, 1):
                    continue

                def handler(_sender, args, *, current_report_id=report_id):
                    payload = buffer_bytes(args.characteristic_value)
                    loop.call_soon_threadsafe(
                        events.put_nowait,
                        (f"hid:{current_report_id}", payload),
                    )

                token = characteristic.add_value_changed(handler)
                cccd = CccdValue.NOTIFY if props & 0x10 else CccdValue.INDICATE
                status = await characteristic.write_client_characteristic_configuration_descriptor_async(
                    cccd
                )
                if int(status) != 0:
                    characteristic.remove_value_changed(token)
                    print(
                        f"XIAOMI HID DIRECT subscribe_failed handle={handle} "
                        f"status={int(status)}",
                        flush=True,
                    )
                    continue
                session.subscriptions.append((characteristic, token))

            if not session.subscriptions:
                service.close()
                print("XIAOMI HID DIRECT unavailable no_input_reports", flush=True)
                return None
            print(
                f"XIAOMI HID DIRECT READY reports={len(session.subscriptions)} "
                "back=usage_0xF1->Backspace tv=usage_0x35->Alt+Esc",
                flush=True,
            )
            return session
        except Exception as exc:
            if service is not None:
                try:
                    service.close()
                except Exception:
                    pass
            print(
                f"XIAOMI HID DIRECT unavailable {type(exc).__name__}: {exc}",
                flush=True,
            )
            return None

    async def close(self) -> None:
        for characteristic, token in self.subscriptions:
            try:
                characteristic.remove_value_changed(token)
                await characteristic.write_client_characteristic_configuration_descriptor_async(
                    CccdValue.NONE
                )
            except Exception:
                pass
        self.subscriptions.clear()
        self.service.close()


def start_raw_mapping_thread(
    enabled: bool, action_guard: XiaomiTvActionGate
) -> threading.Thread | None:
    """Run device-filtered Raw Input mapping in this process.

    It lives in a daemon thread so terminating the Xiaomi bridge cannot leave a
    second keyboard-mapping process behind.
    """

    if not enabled:
        print("XIAOMI KEY MAPPING disabled", flush=True)
        return None
    mapping_config = load_keys_config(KEYS_CONFIG_PATH)
    device_filter = ",".join(mapping_config.get("device_match", [])) or "none"
    def run_mapping() -> None:
        try:
            from bridges import raw_input_bridge as bridge_core

            print(
                f"XIAOMI KEY MAPPING READY config={KEYS_CONFIG_PATH} "
                f"device_filter={device_filter} keyboard_isolated=true",
                flush=True,
            )
            bridge_core.main(
                [
                    "--config",
                    str(KEYS_CONFIG_PATH),
                    # The standalone T1 worker owns 30682. The embedded Xiaomi
                    # mapper only needs Raw Input, so bind its unused control
                    # listener to an ephemeral port instead of disabling the
                    # whole mapping thread with WSAEADDRINUSE.
                    "--control-port",
                    "0",
                ],
                action_guard=action_guard,
            )
        except Exception as exc:
            print(f"XIAOMI KEY MAPPING ERROR {type(exc).__name__}: {exc}", flush=True)

    thread = threading.Thread(
        target=run_mapping,
        name="xiaomi-device-specific-key-mapping",
        daemon=True,
    )
    thread.start()
    return thread


def should_start_raw_mapping(
    raw_mapping_enabled: bool,
    hid_tap_started: bool,
    hid_tap_fallback_required: bool = False,
) -> bool:
    """Use Raw Input whenever the optional Frida HID tap did not start."""

    return not bool(hid_tap_started) and (
        bool(raw_mapping_enabled) or bool(hid_tap_fallback_required)
    )


def buffer_bytes(buffer) -> bytes:
    reader = DataReader.from_buffer(buffer)
    try:
        data = bytearray(reader.unconsumed_buffer_length)
        reader.read_bytes(data)
        return bytes(data)
    finally:
        reader.close()


class VoiceShortcut:
    """Emit a configurable voice-input shortcut as a tap or held chord."""

    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002

    VK = HOTKEY_VK
    EXTENDED_VKS = {
        0x21,
        0x22,
        0x23,
        0x24,
        0x25,
        0x26,
        0x27,
        0x28,
        0x2C,
        0x2D,
        0x2E,
        0x5B,
        0x5C,
        0x5D,
        0xA3,
        0xA5,
        0xAD,
        0xAE,
        0xAF,
        0xB0,
        0xB1,
        0xB2,
        0xB3,
    }

    def __init__(self, hotkey: str, enabled: bool = True) -> None:
        self.enabled = enabled and os.name == "nt"
        self.pressed = False
        self.hotkey = hotkey.strip()
        self.virtual_keys = self._parse_hotkey(self.hotkey) if self.enabled else []
        if self.enabled:
            self.user32 = ctypes.windll.user32
            self.user32.keybd_event.argtypes = (
                ctypes.c_ubyte,
                ctypes.c_ubyte,
                ctypes.c_ulong,
                ctypes.c_size_t,
            )
            self.user32.keybd_event.restype = None

    @classmethod
    def _parse_hotkey(cls, value: str) -> list[int]:
        return resolve_hotkey_virtual_keys(value)

    def _key(self, virtual_key: int, key_up: bool) -> None:
        scan_code = self.user32.MapVirtualKeyW(virtual_key, 0)
        flags = self.KEYEVENTF_EXTENDEDKEY if virtual_key in self.EXTENDED_VKS else 0
        if key_up:
            flags |= self.KEYEVENTF_KEYUP
        self.user32.keybd_event(virtual_key, scan_code, flags, 0)

    def press(self) -> None:
        if not self.enabled or self.pressed:
            return
        for virtual_key in self.virtual_keys:
            self._key(virtual_key, False)
        self.pressed = True
        print(f"VOICE SHORTCUT DOWN shortcut={self.hotkey}", flush=True)

    def tap(self, hold_ms: int = 70) -> None:
        """Send one completed shortcut chord."""

        if not self.enabled or self.pressed:
            return
        for virtual_key in self.virtual_keys:
            self._key(virtual_key, False)
        time.sleep(max(30, min(int(hold_ms), 200)) / 1000.0)
        for virtual_key in reversed(self.virtual_keys):
            self._key(virtual_key, True)
        print(f"VOICE SHORTCUT TAP shortcut={self.hotkey}", flush=True)

    def release(self) -> None:
        if not self.enabled or not self.pressed:
            return
        for virtual_key in reversed(self.virtual_keys):
            self._key(virtual_key, True)
        self.pressed = False
        print("VOICE SHORTCUT UP submit=true", flush=True)


class VoicePcmStats:
    """Per-press PCM evidence for customer logs."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.frames = 0
        self.samples = 0
        self.peak = 0
        self.sum_squares = 0

    def add(self, samples: list[int]) -> None:
        if not samples:
            return
        self.frames += 1
        self.samples += len(samples)
        self.peak = max(self.peak, max(abs(sample) for sample in samples))
        self.sum_squares += sum(sample * sample for sample in samples)

    def summary(self, sample_rate: int = 16000) -> dict:
        audio_ms = self.samples * 1000.0 / sample_rate if sample_rate else 0.0
        rms = (self.sum_squares / self.samples) ** 0.5 if self.samples else 0.0
        if not self.frames:
            result = "empty"
        elif audio_ms < 500.0:
            result = "too_short"
        elif self.peak < 33:
            result = "silent"
        else:
            result = "signal"
        return {
            "frames": self.frames,
            "samples": self.samples,
            "audio_ms": audio_ms,
            "peak": self.peak,
            "rms": rms,
            "result": result,
        }


class UdpPcmOutput:
    """Upsample PCM and feed the hub-owned central audio router."""

    def __init__(self) -> None:
        self._previous = 0
        self._have_previous = False
        self.sent_packets = 0
        self.dropped_chunks = 0
        self.underflows = 0
        self.sample_rate = 48000
        self.peer = (ROUTER_HOST, PCM_PORT)
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(0.15)
        for _ in range(80):
            try:
                self.socket.sendto(b"PING", self.peer)
                response, _ = self.socket.recvfrom(64)
                if response == b"PONG":
                    break
            except (socket.timeout, OSError):
                time.sleep(0.05)
        else:
            self.close()
            raise TimeoutError("central audio router did not become ready")

    def clear(self) -> None:
        self._have_previous = False
        try:
            self.socket.sendto(b"CLEAR", self.peer)
        except OSError:
            pass

    def end_session(self) -> None:
        try:
            self.socket.sendto(b"END", self.peer)
        except OSError:
            pass

    def push_16k(self, samples: list[int]) -> None:
        if not samples:
            return
        output = [0] * (len(samples) * 3)
        previous = self._previous if self._have_previous else samples[0]
        cursor = 0
        for current in samples:
            delta = current - previous
            output[cursor] = previous + round(delta / 3.0)
            output[cursor + 1] = previous + round(delta * (2.0 / 3.0))
            output[cursor + 2] = current
            cursor += 3
            previous = current
        self._previous = samples[-1]
        self._have_previous = True
        payload = struct.pack(f"<{len(output)}h", *output)
        try:
            self.socket.sendto(payload, self.peer)
            self.sent_packets += 1
        except OSError:
            self.dropped_chunks += 1

    def close(self) -> None:
        try:
            self.socket.sendto(b"CLEAR", self.peer)
        except OSError:
            pass
        self.socket.close()


async def bridge_once(
    address: str,
    gain_db: float,
    voice_shortcut_enabled: bool,
    voice_hotkey: str,
    voice_trigger_mode: str,
    stop_event: asyncio.Event,
    action_guard: XiaomiTvActionGate,
    special_keys: XiaomiSpecialKeyHook,
) -> None:
    action_guard.mark_connecting()
    print(f"CONNECTING remote={address}", flush=True)
    device = await BluetoothLEDevice.from_bluetooth_address_async(address_to_int(address))
    if device is None:
        raise RuntimeError(f"paired BLE device not found: {address}")
    print(f"CONNECTED remote={device.name}; discovering ATVV", flush=True)
    service = None
    output: UdpPcmOutput | None = None
    audio_token = None
    control_token = None
    audio = None
    control = None
    hid_session: XiaomiGattHidSession | None = None
    session_id: int | None = None
    mic_opened = False
    voice_shortcut = VoiceShortcut(voice_hotkey, voice_shortcut_enabled)

    try:
        service, chars = await discover_atvv(device)
        print("ATVV DISCOVERED", flush=True)
        tx = chars[VOICE_TX_UUID]
        audio = chars[VOICE_AUDIO_UUID]
        control = chars[VOICE_CONTROL_UUID]
        loop = asyncio.get_running_loop()
        events: asyncio.Queue[tuple[str, bytes]] = asyncio.Queue()

        def make_handler(channel: str):
            def handler(_sender, args):
                payload = buffer_bytes(args.characteristic_value)
                loop.call_soon_threadsafe(events.put_nowait, (channel, payload))

            return handler

        audio_token = audio.add_value_changed(make_handler("audio"))
        control_token = control.add_value_changed(make_handler("control"))
        for characteristic, label in ((audio, "audio"), (control, "control")):
            status = await characteristic.write_client_characteristic_configuration_descriptor_async(
                CccdValue.NOTIFY
            )
            if int(status) != 0:
                raise RuntimeError(f"subscribe {label} failed: {status}")

        # With the normal Windows HID child enabled this reports access denied;
        # XiaomiHidReportTap handles 0xF1 before kbdhid drops it.  Keep this
        # direct path as a fallback for machines intentionally using generic
        # GATT instead of the Microsoft HID driver.
        hid_session = await XiaomiGattHidSession.open(device, events)

        # PortAudio and WinRT GATT deadlock if initialized in one process on
        # this machine, so the hub owns PortAudio in a separate router role.
        output = UdpPcmOutput()
        print(
            f"READY remote={device.name} audio_router={ROUTER_HOST}:{PCM_PORT} "
            f"rate={output.sample_rate}; press and hold the remote microphone button",
            flush=True,
        )
        action_guard.mark_ready()
        await write_command(tx, GET_CAPS_V10, "GET_CAPS")

        decoder = AdpcmDecoder()
        frame_size = 120
        sample_rate = 16000
        pending = bytearray()
        pending_sync: tuple[int, int] | None = None
        streaming = False
        frames_seen = 0
        session_stats = VoicePcmStats()
        session_sent_start = output.sent_packets
        session_drop_start = output.dropped_chunks
        last_mic_off_at: float | None = None

        while not stop_event.is_set():
            try:
                channel, payload = await asyncio.wait_for(events.get(), timeout=0.5)
            except asyncio.TimeoutError:
                if int(device.connection_status) == 0:
                    raise ConnectionError("remote disconnected")
                continue

            if channel == "control":
                if not payload:
                    continue
                opcode = payload[0]
                if opcode == 0x0B and len(payload) >= 7:
                    frame_size = int.from_bytes(payload[5:7], "big") or 120
                    codec = payload[3]
                    sample_rate = 16000 if codec & 0x02 else 8000
                    print(
                        f"CAPS version={payload[1]}.{payload[2]} codec=0x{codec:02x} "
                        f"sample_rate={sample_rate} frame_size={frame_size}",
                        flush=True,
                    )
                    if sample_rate != 16000:
                        raise RuntimeError("this bridge currently requires ATVV 16 kHz audio")
                elif opcode == 0x08:
                    special_keys.mark_voice_signal()
                    await write_command(tx, bytes((0x0C, 0x00)), "MIC_OPEN")
                    mic_opened = True
                elif opcode == 0x04:
                    special_keys.mark_voice_signal()
                    streaming = True
                    last_mic_off_at = None
                    session_id = payload[3] if len(payload) >= 4 else None
                    pending.clear()
                    # RC003 restarts its encoder at predictor/index 0 for each
                    # physical HTT session but sends no AUDIO_SYNC packet.
                    # Without this empirical reset, the second button press
                    # inherits the first session's state and saturates at DC.
                    decoder.reset(0, 0)
                    pending_sync = None
                    output.clear()
                    session_stats.reset()
                    session_sent_start = output.sent_packets
                    session_drop_start = output.dropped_chunks
                    if voice_trigger_mode == "toggle" and voice_shortcut.enabled:
                        voice_shortcut.tap()
                        print("VOICE TOGGLE START", flush=True)
                    else:
                        voice_shortcut.press()
                    print(f"MIC ON session={session_id}", flush=True)
                elif opcode == 0x00:
                    streaming = False
                    pending.clear()
                    # Let final decoded packets clear the virtual cable before
                    # stopping the active voice-input session.
                    await asyncio.sleep(0.12)
                    output.end_session()
                    if voice_trigger_mode == "toggle" and voice_shortcut.enabled:
                        voice_shortcut.tap()
                        print("VOICE TOGGLE STOP submit=true", flush=True)
                    else:
                        voice_shortcut.release()
                    session_result = session_stats.summary(sample_rate)
                    last_mic_off_at = time.monotonic()
                    print(
                        f"MIC OFF session={session_id} frames={session_result['frames']} "
                        f"total_frames={frames_seen} audio_ms={session_result['audio_ms']:.0f} "
                        f"peak={session_result['peak']} rms={session_result['rms']:.1f} "
                        f"sent={output.sent_packets - session_sent_start} "
                        f"send_drop={output.dropped_chunks - session_drop_start} "
                        f"result={session_result['result']}",
                        flush=True,
                    )
                elif opcode == 0x0A and len(payload) >= 7:
                    predictor = int.from_bytes(payload[4:6], "big", signed=True)
                    step_index = payload[6]
                    pending.clear()
                    pending_sync = (predictor, step_index)
                continue

            if channel.startswith("hid:"):
                try:
                    report_id = int(channel.partition(":")[2])
                except ValueError:
                    report_id = 0
                special_keys.handle_direct_hid_report(report_id, payload)
                continue

            if not streaming:
                # Some firmwares race AUDIO_START and the first RX callback.
                # Accept a real first frame, but never reopen a just-finished
                # session with packets that arrived during the drain delay.
                if (
                    last_mic_off_at is not None
                    and time.monotonic() - last_mic_off_at < 0.3
                ):
                    continue
                streaming = True
                session_id = None
                session_stats.reset()
                session_sent_start = output.sent_packets
                session_drop_start = output.dropped_chunks
                output.clear()
                print("MIC ON session=implicit_audio_race", flush=True)
            pending.extend(payload)
            while len(pending) >= frame_size:
                frame = bytes(pending[:frame_size])
                del pending[:frame_size]
                if pending_sync is not None:
                    decoder.reset(*pending_sync)
                    pending_sync = None
                samples = decoder.decode_bytes(frame)
                samples = postprocess(samples, gain_db)
                session_stats.add(samples)
                output.push_16k(samples)
                frames_seen += 1
                if frames_seen in (1, 10) or frames_seen % 200 == 0:
                    session_result = session_stats.summary(sample_rate)
                    print(
                        f"AUDIO frames={frames_seen} sent={output.sent_packets} "
                        f"send_drop={output.dropped_chunks} "
                        f"session_frames={session_result['frames']} "
                        f"peak={session_result['peak']} rms={session_result['rms']:.1f}",
                        flush=True,
                    )
    finally:
        action_guard.mark_connecting()
        special_keys.reset_direct_hid_state()
        voice_shortcut.release()
        if mic_opened and service is not None:
            try:
                close_id = session_id or 0
                await write_command(tx, bytes((0x0D, close_id)), "MIC_CLOSE")
            except Exception as exc:
                print(f"MIC_CLOSE warning: {exc}", flush=True)
        try:
            if output is not None:
                output.close()
        except Exception:
            pass
        for characteristic, token in ((audio, audio_token), (control, control_token)):
            if characteristic is None or token is None:
                continue
            try:
                characteristic.remove_value_changed(token)
                await characteristic.write_client_characteristic_configuration_descriptor_async(
                    CccdValue.NONE
                )
            except Exception:
                pass
        if hid_session is not None:
            await hid_session.close()
        if service is not None:
            service.close()
        device.close()


async def run(
    args: argparse.Namespace,
    action_guard: XiaomiTvActionGate,
    special_keys: XiaomiSpecialKeyHook,
) -> int:
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signame in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, signame, None)
        if sig is not None:
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except (NotImplementedError, RuntimeError):
                pass

    if not args.address:
        # Keep Raw Input button mapping alive, but do not feed an empty address
        # into WinRT and create a noisy reconnect loop.  Pair the remote and use
        # the host's Restart bridge action to repeat ATVV discovery.
        print(
            "VOICE BRIDGE WAITING: no Xiaomi ATVV address; "
            "pair RC001 in Windows Bluetooth settings, then restart bridge",
            flush=True,
        )
        await stop_event.wait()
        return 0

    while not stop_event.is_set():
        try:
            await bridge_once(
                args.address,
                args.gain_db,
                not args.no_voice_shortcut,
                args.voice_hotkey,
                args.voice_trigger_mode,
                stop_event,
                action_guard,
                special_keys,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"BRIDGE ERROR {type(exc).__name__}: {exc}", flush=True)
            if args.once:
                return 2
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=args.retry_delay)
            except asyncio.TimeoutError:
                print("reconnecting...", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_pythonw_logging()
    if not acquire_single_instance():
        return 0
    print(f"--- bridge start {time.strftime('%Y-%m-%d %H:%M:%S')} ---", flush=True)
    config_parser = argparse.ArgumentParser(add_help=False)
    config_parser.add_argument("--config", default=str(CONFIG_PATH))
    config_args, _ = config_parser.parse_known_args(argv)
    config_path = Path(config_args.config).resolve()
    config = load_config(config_path)
    keys_config = load_keys_config(KEYS_CONFIG_PATH)
    try:
        configured_voice_keys = voice_hotkey_from_configs(config, keys_config)
    except ValueError as exc:
        configured_voice_keys = list(DEFAULT_VOICE_HOTKEY)
        print(
            f"VOICE SHORTCUT CONFIG INVALID error={exc}; fallback=RightAlt",
            flush=True,
        )
    configured_voice_hotkey = "+".join(configured_voice_keys)
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(config_path))
    parser.add_argument("--address", default=config.get("address", DEFAULT_ADDRESS))
    parser.add_argument("--gain-db", type=float, default=float(config.get("gain_db", 10.0)))
    parser.add_argument(
        "--retry-delay", type=float, default=float(config.get("retry_delay", 3.0))
    )
    parser.add_argument("--no-voice-shortcut", action="store_true")
    parser.add_argument(
        "--voice-hotkey", default=configured_voice_hotkey
    )
    parser.add_argument(
        "--voice-trigger-mode",
        choices=("toggle", "hold"),
        default=str(config.get("voice_trigger_mode", "hold")),
    )
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    raw_argv = list(argv or [])
    explicit_address = ""
    for index, item in enumerate(raw_argv):
        if item == "--address" and index + 1 < len(raw_argv):
            explicit_address = raw_argv[index + 1]
            break
        if item.startswith("--address="):
            explicit_address = item.split("=", 1)[1]
            break
    args.address = discover_and_apply_xiaomi_identity(
        config,
        keys_config,
        config_path,
        explicit_address=explicit_address,
    )
    try:
        resolve_hotkey_virtual_keys(args.voice_hotkey)
    except ValueError as exc:
        print(
            f"VOICE SHORTCUT ARGUMENT INVALID value={args.voice_hotkey!r} "
            f"error={exc}; fallback=RightAlt",
            flush=True,
        )
        args.voice_hotkey = "+".join(DEFAULT_VOICE_HOTKEY)
    if not bool(config.get("voice_shortcut_enabled", True)):
        args.no_voice_shortcut = True
    hid_tap_enabled = bool(config.get("hid_report_tap_enabled", True)) and bool(
        config.get("hid_tap_compatible", False)
    )
    action_guard = XiaomiTvActionGate(config.get("tv_action_ready_delay", 2.0))
    def cycle_runtime_preset() -> str:
        preset = cycle_preset_configuration(config, keys_config)
        save_config(config, config_path)
        save_keys_config(keys_config, KEYS_CONFIG_PATH)
        special_keys.button_bindings = keys_config.get("button_bindings", {})
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.sendto(b"RESTART:xiaomi", ("127.0.0.1", 28690))
        except OSError:
            pass
        return preset

    special_keys = XiaomiSpecialKeyHook(
        action_guard,
        bool(config.get("special_key_hook_enabled", True)),
        float(config.get("back_repeat_delay", 0.28)),
        float(config.get("back_repeat_interval", 0.04)),
        float(config.get("volume_repeat_delay", 0.40)),
        float(config.get("volume_repeat_interval", 0.12)),
        keys_config.get("button_bindings", {}),
        cycle_runtime_preset,
    )
    special_keys.start()
    hid_report_tap = XiaomiHidReportTap(
        special_keys.handle_direct_hid_report,
        hid_tap_enabled,
    )
    hid_tap_started = hid_report_tap.start()
    hid_tap_fallback_required = (
        hid_tap_enabled and not hid_report_tap.dependency_available
    )
    start_raw_mapping_thread(
        should_start_raw_mapping(
            bool(config.get("raw_mapping_enabled", True)),
            hid_tap_started,
            hid_tap_fallback_required,
        ),
        action_guard,
    )
    try:
        return asyncio.run(run(args, action_guard, special_keys))
    except KeyboardInterrupt:
        return 130
    finally:
        hid_report_tap.stop()
        special_keys.stop()


if __name__ == "__main__":
    raise SystemExit(main())
