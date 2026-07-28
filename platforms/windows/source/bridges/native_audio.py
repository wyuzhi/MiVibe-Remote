#!/usr/bin/env python3
"""Direct Windows microphone sessions for standalone hardware bridges.

The standalone T1 and V60 products do not mix audio into VB-CABLE. Their USB
microphones are exposed by Windows directly, so the bridge only verifies that
the matching capture endpoint exists and tracks the shortcut session. The
customer's chosen voice application opens the native endpoint itself.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
import winreg

from bridges.audio_client import AudioRouterError


MMDEVICES_CAPTURE = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Capture"
)
PKEY_DEVICE_FRIENDLY_NAME = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
PKEY_ENDPOINT_FRIENDLY_NAME = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"


def active_capture_endpoint_names() -> list[str]:
    """Return active Windows capture endpoint labels without opening audio."""

    if os.name != "nt":
        return []
    names: list[str] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, MMDEVICES_CAPTURE) as root:
            index = 0
            while True:
                try:
                    endpoint_id = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(root, endpoint_id) as endpoint:
                        state, _ = winreg.QueryValueEx(endpoint, "DeviceState")
                    if int(state) != 1:
                        continue
                    with winreg.OpenKey(root, endpoint_id + r"\Properties") as props:
                        parts = []
                        for property_name in (
                            PKEY_DEVICE_FRIENDLY_NAME,
                            PKEY_ENDPOINT_FRIENDLY_NAME,
                        ):
                            try:
                                value, _ = winreg.QueryValueEx(props, property_name)
                            except OSError:
                                continue
                            if isinstance(value, str) and value.strip():
                                parts.append(value.strip())
                    label = " ".join(dict.fromkeys(parts)).strip()
                    if label:
                        names.append(label)
                except (OSError, TypeError, ValueError):
                    continue
    except OSError:
        return []
    return names


def find_active_capture_endpoint(device: str) -> str | None:
    needle = str(device).strip().casefold()
    if not needle:
        return None
    names = active_capture_endpoint_names()
    exact = [name for name in names if name.casefold() == needle]
    partial = [name for name in names if needle in name.casefold()]
    matches = exact or partial
    return matches[0] if matches else None


class NativeAudioSessionClient:
    """AudioRouterClient-compatible tracker for a native USB microphone."""

    def __init__(self, owner: str, **_ignored) -> None:
        self.owner = str(owner)
        self._lock = threading.RLock()
        self._sessions: dict[str, dict] = {}

    def open(
        self,
        device: str,
        token: str | None = None,
        max_session_ms: int = 0,
    ) -> str:
        endpoint = find_active_capture_endpoint(device)
        if endpoint is None:
            raise AudioRouterError(f"Windows 未找到设备自带麦克风：{device}")
        session_token = token or uuid.uuid4().hex
        with self._lock:
            self._sessions[session_token] = {
                "device": str(device),
                "endpoint": endpoint,
                "client_pid": os.getpid(),
                "opened_at": time.monotonic(),
                "max_session_ms": max(0, int(max_session_ms)),
            }
        return session_token

    def close(self, token: str, tail_ms: int = 0) -> dict:
        del tail_ms
        with self._lock:
            closed = self._sessions.pop(str(token), None) is not None
        return {"closed": closed, "scheduled": False, "transport": "native"}

    def close_owner(self, *, timeout: float | None = None) -> dict:
        del timeout
        with self._lock:
            closed = len(self._sessions)
            self._sessions.clear()
        return {"closed": closed, "transport": "native"}

    def status(self) -> dict:
        now = time.monotonic()
        with self._lock:
            sessions = list(self._sessions.values())
        source = None
        if sessions:
            latest = sessions[-1]
            source = {
                "device": latest["device"],
                "endpoint": latest["endpoint"],
                "client_pid": latest["client_pid"],
                "opened_ms": int((now - latest["opened_at"]) * 1000),
                "native": True,
                "signal_seen": None,
                "silence_ms": None,
            }
        return {
            "ok": True,
            "transport": "native",
            "sources": {self.owner: source} if source is not None else {},
        }


def standalone_native_audio_enabled() -> bool:
    return os.environ.get("REMOTE_BRIDGE_AUDIO_TRANSPORT", "").casefold() == "native"
