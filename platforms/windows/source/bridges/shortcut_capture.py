#!/usr/bin/env python3
"""Shared Windows physical-keyboard shortcut capture for settings windows."""

from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes


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
        "ctrl": 10, "leftctrl": 10, "rightctrl": 11,
        "shift": 20, "leftshift": 20, "rightshift": 21,
        "alt": 30, "leftalt": 30, "rightalt": 31,
        "leftwin": 40, "rightwin": 41,
    }
    NAMED_KEYS = {
        0x08: "backspace", 0x09: "tab", 0x0D: "enter", 0x13: "pause",
        0x14: "capslock", 0x1B: "esc", 0x20: "space", 0x21: "pageup",
        0x22: "pagedown", 0x23: "end", 0x24: "home", 0x25: "left",
        0x26: "up", 0x27: "right", 0x28: "down", 0x2C: "printscreen",
        0x2D: "insert", 0x2E: "delete", 0x5D: "apps", 0x6A: "multiply",
        0x6B: "add", 0x6D: "subtract", 0x6E: "decimal", 0x6F: "divide",
        0xAD: "volume_mute", 0xAE: "volume_down", 0xAF: "volume_up",
        0xB0: "media_next", 0xB1: "media_prev", 0xB2: "media_stop",
        0xB3: "media_play_pause", 0xBA: ";", 0xBB: "=", 0xBC: ",",
        0xBD: "-", 0xBE: ".", 0xBF: "/", 0xC0: "`", 0xDB: "[",
        0xDC: "\\", 0xDD: "]", 0xDE: "'",
    }

    def __init__(self, root, on_result, on_error, thread_name="shortcut-capture"):
        self.root = root
        self.on_result = on_result
        self.on_error = on_error
        self.thread_name = thread_name
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
        if 0x60 <= vk <= 0x69:
            return f"num{vk - 0x60}"
        if 0x70 <= vk <= 0x87:
            return f"f{vk - 0x6F}"
        return cls.NAMED_KEYS.get(vk, f"vk_{vk:02x}")

    def start(self) -> None:
        if os.name != "nt":
            self.on_error("当前系统不支持 Windows 键盘捕获")
            return
        previous = self.thread
        self.cancel()
        if previous and previous.is_alive() and previous is not threading.current_thread():
            previous.join(timeout=0.5)
        self.active = True
        self.captured = False
        self.blocked_vks.clear()
        self.active_modifiers.clear()
        self.modifier_history.clear()
        self.thread = threading.Thread(target=self._run, name=self.thread_name, daemon=True)
        self.thread.start()

    def cancel(self) -> None:
        self.active = False
        if self.thread_id and os.name == "nt":
            try:
                ctypes.windll.user32.PostThreadMessageW(self.thread_id, self.WM_QUIT, 0, 0)
            except Exception:
                pass

    def _ordered_modifiers(self, values) -> list[dict]:
        return sorted(values, key=lambda item: self.MODIFIER_ORDER.get(item["token"], 99))

    def _finish(self, tokens: list[str], info, modifiers: list[dict]) -> None:
        self.captured = True
        result = {
            "tokens": tokens,
            "capture": {
                "source": "keyboard_hook",
                "vk": int(info.vk_code),
                "scan_code": int(info.scan_code),
                "extended": bool(info.flags & self.LLKHF_EXTENDED),
                "modifiers": [dict(item) for item in modifiers],
            },
        }
        self.root.after(0, lambda: self.on_result(result))

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
                modifiers = self._ordered_modifiers(self.active_modifiers.values())
                self._finish(
                    [*[item["token"] for item in modifiers], self.key_token(vk)],
                    info,
                    modifiers,
                )
        else:
            self.blocked_vks.discard(vk)
            released = self.active_modifiers.pop(vk, None)
            if released is not None and not self.captured and not self.active_modifiers:
                modifiers = self._ordered_modifiers(self.modifier_history.values())
                self._finish([item["token"] for item in modifiers], info, modifiers[:-1])
            if self.captured and not self.blocked_vks:
                self.active = False
                user32.PostThreadMessageW(self.thread_id, self.WM_QUIT, 0, 0)
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
                ctypes.c_int, proc_type, wintypes.HINSTANCE, wintypes.DWORD
            )
            user32.SetWindowsHookExW.restype = wintypes.HHOOK
            user32.CallNextHookEx.argtypes = (
                wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
            )
            user32.CallNextHookEx.restype = ctypes.c_ssize_t
            user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
            user32.PostThreadMessageW.argtypes = (
                wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
            )
            kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
            kernel32.GetModuleHandleW.restype = wintypes.HMODULE
            self.hook = user32.SetWindowsHookExW(
                self.WH_KEYBOARD_LL, self.proc, kernel32.GetModuleHandleW(None), 0
            )
            if not self.hook:
                raise OSError("键盘钩子启动失败")
            message = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        except Exception as exc:
            self.root.after(0, lambda e=str(exc): self.on_error(e))
        finally:
            if self.hook:
                try:
                    ctypes.windll.user32.UnhookWindowsHookEx(self.hook)
                except Exception:
                    pass
            self.hook = None
            self.thread_id = 0
            self.active = False


def tokens_to_display(tokens: list[str]) -> str:
    names = {
        "ctrl": "Ctrl", "leftctrl": "左 Ctrl", "rightctrl": "右 Ctrl",
        "shift": "Shift", "leftshift": "左 Shift", "rightshift": "右 Shift",
        "alt": "Alt", "leftalt": "左 Alt", "rightalt": "右 Alt",
        "leftwin": "左 Win", "rightwin": "右 Win", "esc": "退出键（Esc）",
        "enter": "回车键（Enter）", "space": "空格键（Space）", "tab": "制表键（Tab）",
        "pageup": "上翻页键（Page Up）", "pagedown": "下翻页键（Page Down）",
        "backspace": "退格键（Backspace）", "delete": "删除键（Delete）", "insert": "插入键（Insert）",
        "home": "起始键（Home）", "end": "结束键（End）",
        "left": "左方向键（Left）", "right": "右方向键（Right）",
        "up": "上方向键（Up）", "down": "下方向键（Down）",
    }
    return "+".join(names.get(token, token.upper() if len(token) == 1 else token) for token in tokens)
