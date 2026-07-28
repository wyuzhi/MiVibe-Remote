#!/usr/bin/env python3
"""Read RC003 usages dropped inside Microsoft's HidOverGatt host.

Windows receives the report but exposes different subsets of it depending on
the usage.  This module attaches a small, read-only Frida probe to the RC003
HidOverGatt WUDF host and forwards the complete set of known front-button
press/release edges to the configurable mapping layer.
"""

from __future__ import annotations

import os
import json
import socket
import threading
import time
from typing import Callable
import winreg

# Kept only so the retired source-mode implementation below cannot be called
# accidentally.  Production uses the focused x64 Gadget and never imports the
# full frida-python runtime.
frida = None

from . import hid_tap_runtime
from .hid_tap_injector import launch_elevated_injector


BTHLE_ENUM_KEY = r"SYSTEM\CurrentControlSet\Enum\BTHLEDevice"
HID_SERVICE_PREFIX = "{00001812-0000-1000-8000-00805f9b34fb}"
RC003_HARDWARE_TOKEN = "dev_vid&012717_pid&32b8_rev&00a4"
WUDF_DIAGNOSTIC_SUFFIX = r"Device Parameters\WUDFDiagnosticInfo"
BACK_USAGE = 0x00F1
OK_USAGE = 0x0028
TV_USAGE = 0x0035
HOME_USAGE = 0x004A
RIGHT_USAGE = 0x004F
LEFT_USAGE = 0x0050
DOWN_USAGE = 0x0051
UP_USAGE = 0x0052
MENU_USAGE = 0x0065
POWER_USAGE = 0x0066
VOLUME_MUTE_USAGE = 0x007F
VOLUME_UP_USAGE = 0x0080
VOLUME_DOWN_USAGE = 0x0081
FORWARDED_USAGES = frozenset(
    {
        BACK_USAGE,
        OK_USAGE,
        TV_USAGE,
        HOME_USAGE,
        RIGHT_USAGE,
        LEFT_USAGE,
        DOWN_USAGE,
        UP_USAGE,
        MENU_USAGE,
        POWER_USAGE,
        VOLUME_MUTE_USAGE,
        VOLUME_UP_USAGE,
        VOLUME_DOWN_USAGE,
    }
)
USAGE_NAMES = {
    BACK_USAGE: "back",
    OK_USAGE: "ok",
    TV_USAGE: "tv",
    HOME_USAGE: "home",
    RIGHT_USAGE: "right",
    LEFT_USAGE: "left",
    DOWN_USAGE: "down",
    UP_USAGE: "up",
    MENU_USAGE: "menu",
    POWER_USAGE: "power",
    VOLUME_MUTE_USAGE: "volume_mute",
    VOLUME_UP_USAGE: "volume_up",
    VOLUME_DOWN_USAGE: "volume_down",
}


HOOK_JS = hid_tap_runtime.GADGET_SCRIPT


def decode_rc003_ioctl_output(data: bytes) -> bytes | None:
    """Extract the six-byte report payload from HidOverGatt's IOCTL buffer."""

    # Verified on RC003: 3-byte HidOverGatt prefix followed by three little-
    # endian 16-bit Keyboard-page usages (report ID 1 is represented by prefix).
    if len(data) != 9 or data[:3] != b"\x01\x00\x00":
        return None
    return data[3:9]


def payload_usages(payload: bytes) -> set[int]:
    if len(payload) != 6:
        return set()
    return {
        int.from_bytes(payload[index : index + 2], "little")
        for index in range(0, len(payload), 2)
    } - {0}


def find_rc003_hidogatt_host_pid() -> int | None:
    """Locate the WUDFHost assigned to the paired RC003 HID service."""

    if os.name != "nt":
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, BTHLE_ENUM_KEY) as root:
            service_index = 0
            while True:
                try:
                    service_name = winreg.EnumKey(root, service_index)
                except OSError:
                    break
                service_index += 1
                folded = service_name.casefold()
                if not folded.startswith(HID_SERVICE_PREFIX):
                    continue
                if RC003_HARDWARE_TOKEN not in folded:
                    continue
                with winreg.OpenKey(root, service_name) as service_key:
                    instance_index = 0
                    while True:
                        try:
                            instance_name = winreg.EnumKey(service_key, instance_index)
                        except OSError:
                            break
                        instance_index += 1
                        diagnostic_path = (
                            f"{service_name}\\{instance_name}\\{WUDF_DIAGNOSTIC_SUFFIX}"
                        )
                        try:
                            with winreg.OpenKey(
                                root, diagnostic_path
                            ) as diagnostic_key:
                                value, _ = winreg.QueryValueEx(
                                    diagnostic_key, "HostPid"
                                )
                            pid = int(value)
                            if pid > 0:
                                return pid
                        except (OSError, TypeError, ValueError):
                            continue
    except OSError:
        return None
    return None


class XiaomiHidReportTap:
    """Keep a focused report hook attached and emit selected key edges."""

    def __init__(
        self,
        report_handler: Callable[[int, bytes], None],
        enabled: bool = True,
        retry_delay: float = 2.0,
        heartbeat_timeout: float = 15.0,
    ) -> None:
        self.report_handler = report_handler
        self.enabled = bool(enabled) and os.name == "nt"
        self.retry_delay = max(0.5, float(retry_delay))
        self.heartbeat_timeout = max(10.0, float(heartbeat_timeout))
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.active_usages: set[int] = set()
        self._state_lock = threading.Lock()
        self._last_wait_log = 0.0

    @property
    def dependency_available(self) -> bool:
        return hid_tap_runtime.gadget_archive_available()

    def _release_active(self) -> None:
        with self._state_lock:
            was_active = bool(self.active_usages)
            self.active_usages.clear()
        if was_active:
            self.report_handler(1, b"\x00" * 6)

    def _handle_ioctl_output(self, data: bytes) -> None:
        payload = decode_rc003_ioctl_output(data)
        if payload is None:
            return
        active = payload_usages(payload) & FORWARDED_USAGES
        with self._state_lock:
            previous = self.active_usages
            if active == previous:
                return
            pressed = active - previous
            released = previous - active
            self.active_usages = set(active)
        if not pressed and not released:
            return
        # The low-level keyboard hook correlates and suppresses Windows'
        # translation of these same device edges, so every front button can
        # use one device-specific configuration path without double-triggering.
        ordered = sorted(active)
        filtered = b"".join(value.to_bytes(2, "little") for value in ordered)
        filtered = (filtered + b"\x00" * 6)[:6]
        self.report_handler(1, filtered)
        changes = [f"{USAGE_NAMES[value]}=down" for value in sorted(pressed)]
        changes.extend(
            f"{USAGE_NAMES[value]}=up" for value in sorted(released)
        )
        print(
            f"XIAOMI HID TAP {' '.join(changes)} raw={data.hex()}",
            flush=True,
        )

    def _run_frida_legacy(self) -> None:
        while not self.stop_event.is_set():
            pid = find_rc003_hidogatt_host_pid()
            if pid is None:
                now = time.monotonic()
                if now - self._last_wait_log >= 30.0:
                    self._last_wait_log = now
                    print("XIAOMI HID TAP waiting_for_rc003_host", flush=True)
                self.stop_event.wait(self.retry_delay)
                continue

            session = None
            script = None
            detached = threading.Event()
            hook_loaded = threading.Event()
            activity_lock = threading.Lock()
            last_heartbeat: list[float | None] = [None]
            io_verified = threading.Event()
            detached_reason: list[str] = ["unknown"]

            def mark_heartbeat() -> None:
                with activity_lock:
                    last_heartbeat[0] = time.monotonic()

            def on_detached(*args) -> None:
                if args:
                    detached_reason[0] = str(args[0])
                detached.set()

            def on_message(message, data) -> None:
                if message.get("type") != "send":
                    print(f"XIAOMI HID TAP frida_message={message}", flush=True)
                    return
                payload = message.get("payload") or {}
                kind = payload.get("kind")
                if kind == "ready":
                    hook_loaded.set()
                elif kind == "gatt_read" and data is not None:
                    io_verified.set()
                    self._handle_ioctl_output(bytes(data))
                elif kind == "heartbeat":
                    mark_heartbeat()
                elif kind == "error":
                    print(
                        f"XIAOMI HID TAP hook_error={payload.get('message')}",
                        flush=True,
                    )

            try:
                session = frida.attach(pid)
                session.on("detached", on_detached)
                script = session.create_script(HOOK_JS)
                script.on("message", on_message)
                script.load()
                if not hook_loaded.wait(3.0):
                    raise RuntimeError("hook did not become ready")
                print(
                    f"XIAOMI HID TAP ATTACHED pid={pid} awaiting_io=true "
                    f"forwarded_usages={len(FORWARDED_USAGES)} "
                    "mapping=configurable",
                    flush=True,
                )
                attached_at = time.monotonic()
                heartbeat_announced = False
                io_announced = False
                next_host_check = attached_at
                while not self.stop_event.wait(0.5):
                    if detached.is_set():
                        print(
                            "XIAOMI HID TAP DETACHED "
                            f"pid={pid} reason={detached_reason[0]}",
                            flush=True,
                        )
                        break
                    now = time.monotonic()
                    if now >= next_host_check:
                        next_host_check = now + 2.0
                        current_pid = find_rc003_hidogatt_host_pid()
                        if current_pid != pid:
                            print(
                                "XIAOMI HID TAP HOST CHANGED "
                                f"old_pid={pid} new_pid={current_pid}",
                                flush=True,
                            )
                            break
                    with activity_lock:
                        heartbeat_at = last_heartbeat[0]
                    if heartbeat_at is None:
                        if now - attached_at >= self.heartbeat_timeout:
                            print(
                                "XIAOMI HID TAP UNHEALTHY "
                                f"pid={pid} reason=agent_heartbeat_missing",
                                flush=True,
                            )
                            break
                    elif not heartbeat_announced:
                        heartbeat_announced = True
                        print(
                            f"XIAOMI HID TAP HEALTHY pid={pid} "
                            "agent_heartbeat=true "
                            f"forwarded_usages={len(FORWARDED_USAGES)} "
                            "mapping=configurable",
                            flush=True,
                        )
                    elif now - heartbeat_at >= self.heartbeat_timeout:
                        print(
                            "XIAOMI HID TAP UNHEALTHY "
                            f"pid={pid} reason=agent_heartbeat_stale "
                            f"age={now - heartbeat_at:.1f}s",
                            flush=True,
                        )
                        break
                    if io_verified.is_set() and not io_announced:
                        io_announced = True
                        print(
                            f"XIAOMI HID TAP READY pid={pid} "
                            "io_verified=true "
                            f"forwarded_usages={len(FORWARDED_USAGES)} "
                            "mapping=configurable",
                            flush=True,
                        )
            except Exception as exc:
                print(
                    f"XIAOMI HID TAP retry {type(exc).__name__}: {exc}",
                    flush=True,
                )
            finally:
                self._release_active()
                if script is not None:
                    try:
                        script.unload()
                    except Exception:
                        pass
                if session is not None:
                    try:
                        session.detach()
                    except Exception:
                        pass
            if not self.stop_event.is_set():
                self.stop_event.wait(self.retry_delay)

    def _run(self) -> None:
        """Serve the small x64 Gadget socket and request one UAC injection."""

        injection_attempted_pid: int | None = None
        while not self.stop_event.is_set():
            pid = find_rc003_hidogatt_host_pid()
            if pid is None:
                self.stop_event.wait(self.retry_delay)
                continue
            if pid != injection_attempted_pid:
                injection_attempted_pid = None

            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                server.bind(("127.0.0.1", hid_tap_runtime.HID_TAP_PORT))
                server.listen(1)
                server.settimeout(1.0)
                if injection_attempted_pid is None:
                    try:
                        if not hid_tap_runtime.gadget_archive_available():
                            raise FileNotFoundError("verified RC003 Gadget asset is missing")
                        if not launch_elevated_injector(pid):
                            raise PermissionError("UAC injection was declined")
                        injection_attempted_pid = pid
                    except Exception as exc:
                        print(
                            f"XIAOMI HID TAP injection retry {type(exc).__name__}: {exc}",
                            flush=True,
                        )
                        self.stop_event.wait(self.retry_delay)
                        continue
                try:
                    client, _address = server.accept()
                except socket.timeout:
                    continue
                client.settimeout(1.0)
                print(
                    f"XIAOMI HID TAP ATTACHED pid={pid} awaiting_io=true "
                    f"forwarded_usages={len(FORWARDED_USAGES)} mapping=configurable",
                    flush=True,
                )
                buffer = b""
                last_heartbeat = time.monotonic()
                io_verified = False
                try:
                    while not self.stop_event.is_set():
                        if find_rc003_hidogatt_host_pid() != pid:
                            print(
                                f"XIAOMI HID TAP HOST CHANGED old_pid={pid}",
                                flush=True,
                            )
                            injection_attempted_pid = None
                            break
                        try:
                            chunk = client.recv(65536)
                        except socket.timeout:
                            chunk = None
                        if chunk == b"":
                            break
                        if chunk:
                            buffer += chunk
                            while b"\n" in buffer:
                                line, buffer = buffer.split(b"\n", 1)
                                try:
                                    message = json.loads(line.decode("utf-8"))
                                except (UnicodeDecodeError, json.JSONDecodeError):
                                    continue
                                kind = message.get("kind")
                                if kind == "heartbeat" or kind == "ready":
                                    last_heartbeat = time.monotonic()
                                elif kind == "gatt_read":
                                    raw = message.get("raw", "")
                                    try:
                                        data = bytes.fromhex(raw)
                                    except (TypeError, ValueError):
                                        data = b""
                                    if data:
                                        io_verified = True
                                        self._handle_ioctl_output(data)
                                elif kind == "error":
                                    print(
                                        f"XIAOMI HID TAP hook_error={message.get('message')}",
                                        flush=True,
                                    )
                        if time.monotonic() - last_heartbeat >= self.heartbeat_timeout:
                            print(
                                f"XIAOMI HID TAP UNHEALTHY pid={pid} "
                                "reason=agent_heartbeat_stale",
                                flush=True,
                            )
                            break
                        if io_verified:
                            print(
                                f"XIAOMI HID TAP READY pid={pid} io_verified=true "
                                f"forwarded_usages={len(FORWARDED_USAGES)} mapping=configurable",
                                flush=True,
                            )
                            io_verified = False
                finally:
                    try:
                        client.close()
                    except OSError:
                        pass
                    self._release_active()
            finally:
                server.close()
            if not self.stop_event.is_set():
                self.stop_event.wait(0.5)

    def start(self) -> bool:
        if not self.enabled:
            print("XIAOMI HID TAP disabled", flush=True)
            return False
        if not self.dependency_available:
            print("XIAOMI HID TAP unavailable verified_gadget_not_installed", flush=True)
            return False
        self.thread = threading.Thread(
            target=self._run,
            name="xiaomi-hidogatt-report-tap",
            daemon=True,
        )
        self.thread.start()
        return True

    def stop(self) -> None:
        self.stop_event.set()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(timeout=3.0)
