#!/usr/bin/env python3
"""Pass-through monitor for physical Windows hotkeys.

Unlike GetAsyncKeyState polling, the low-level keyboard event tells us whether
an edge came from SendInput. That lets V60 synchronize with real keyboard
presses without mistaking its own injected Right Alt for a second toggle.
"""

from __future__ import annotations

import ctypes
import os
import queue
import threading
from ctypes import wintypes
from collections.abc import Callable


class KbdLlHookStruct(ctypes.Structure):
    _fields_ = [
        ("vk_code", wintypes.DWORD),
        ("scan_code", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("extra_info", ctypes.c_size_t),
    ]


GENERIC_MODIFIERS = {
    0x10: frozenset((0x10, 0xA0, 0xA1)),
    0x11: frozenset((0x11, 0xA2, 0xA3)),
    0x12: frozenset((0x12, 0xA4, 0xA5)),
}


class PhysicalHotkeyState:
    """Pure state machine shared by the hook and deterministic tests."""

    def __init__(self) -> None:
        self.down_vks: set[int] = set()
        self.target: tuple[int, ...] = ()
        self.chord_down = False

    @staticmethod
    def _target_is_down(target_vk: int, down_vks: set[int]) -> bool:
        alternatives = GENERIC_MODIFIERS.get(int(target_vk))
        if alternatives is not None:
            return bool(alternatives.intersection(down_vks))
        return int(target_vk) in down_vks

    def feed(
        self,
        vk: int,
        is_down: bool,
        target: tuple[int, ...],
        *,
        injected: bool = False,
    ) -> bool | None:
        if injected:
            return None
        normalized = tuple(dict.fromkeys(int(item) for item in target))
        if normalized != self.target:
            self.target = normalized
            self.chord_down = False
        if is_down:
            self.down_vks.add(int(vk))
        else:
            self.down_vks.discard(int(vk))
        current = bool(normalized) and all(
            self._target_is_down(item, self.down_vks) for item in normalized
        )
        if current == self.chord_down:
            return None
        self.chord_down = current
        return current


class PhysicalHotkeyMonitor:
    WH_KEYBOARD_LL = 13
    HC_ACTION = 0
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    WM_QUIT = 0x0012
    LLKHF_INJECTED = 0x10

    def __init__(
        self,
        get_target_vks: Callable[[], tuple[int, ...]],
        on_edge: Callable[[bool], None],
        on_error: Callable[[str], None] | None = None,
        on_ready: Callable[[], None] | None = None,
        *,
        thread_name: str = "physical-hotkey-monitor",
    ) -> None:
        self.get_target_vks = get_target_vks
        self.on_edge = on_edge
        self.on_error = on_error or (lambda _message: None)
        self.on_ready = on_ready or (lambda: None)
        self.thread_name = thread_name
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.dispatch_thread: threading.Thread | None = None
        self.thread_id = 0
        self.hook = None
        self.proc = None
        self.state = PhysicalHotkeyState()
        self.events: queue.Queue[bool | None] = queue.Queue()

    def start(self) -> None:
        if os.name != "nt":
            self.on_error("当前系统不支持 Windows 实体热键监听")
            return
        self.stop_event.clear()
        self.dispatch_thread = threading.Thread(
            target=self._dispatch_loop,
            name=f"{self.thread_name}-dispatch",
            daemon=True,
        )
        self.dispatch_thread.start()
        self.thread = threading.Thread(
            target=self._run,
            name=self.thread_name,
            daemon=True,
        )
        self.thread.start()

    def stop(self) -> None:
        self.stop_event.set()
        self.events.put(None)
        if self.thread_id and os.name == "nt":
            try:
                ctypes.windll.user32.PostThreadMessageW(
                    self.thread_id, self.WM_QUIT, 0, 0
                )
            except Exception:
                pass

    def _dispatch_loop(self) -> None:
        while not self.stop_event.is_set():
            edge = self.events.get()
            if edge is None:
                return
            try:
                self.on_edge(bool(edge))
            except Exception as exc:
                self.on_error(f"实体热键状态处理失败: {exc}")

    def _callback(self, code: int, wparam: int, lparam: int) -> int:
        user32 = ctypes.windll.user32
        if code == self.HC_ACTION and not self.stop_event.is_set():
            info = ctypes.cast(lparam, ctypes.POINTER(KbdLlHookStruct)).contents
            is_down = int(wparam) in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN)
            is_up = int(wparam) in (self.WM_KEYUP, self.WM_SYSKEYUP)
            if is_down or is_up:
                edge = self.state.feed(
                    int(info.vk_code),
                    is_down,
                    self.get_target_vks(),
                    injected=bool(info.flags & self.LLKHF_INJECTED),
                )
                if edge is not None:
                    self.events.put(edge)
        # This monitor never suppresses a physical or injected key.
        return int(user32.CallNextHookEx(self.hook, code, wparam, lparam))

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
            user32.PostThreadMessageW.argtypes = (
                wintypes.DWORD,
                wintypes.UINT,
                wintypes.WPARAM,
                wintypes.LPARAM,
            )
            kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            self.hook = user32.SetWindowsHookExW(
                self.WH_KEYBOARD_LL,
                self.proc,
                kernel32.GetModuleHandleW(None),
                0,
            )
            if not self.hook:
                raise OSError("实体热键监听启动失败")
            self.on_ready()
            message = wintypes.MSG()
            while (
                not self.stop_event.is_set()
                and user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0
            ):
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self.on_error(str(exc))
        finally:
            if self.hook:
                try:
                    ctypes.windll.user32.UnhookWindowsHookEx(self.hook)
                except Exception:
                    pass
            self.hook = None
            self.thread_id = 0
