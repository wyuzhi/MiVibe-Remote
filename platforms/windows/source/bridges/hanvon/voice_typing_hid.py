# -*- coding: utf-8 -*-
"""汉王 V60 语音笔桥接 —— 无 DLL 版（彻底解决 kwma_x64.dll 堆损坏崩溃）。

设计要点
========
- 完全不加载厂商 `kwma_x64.dll`，改用 hidapi 直接读取笔的标准 HID 接口拿按键。
  没有厂商 DLL → 没有 native heap corruption(0xc0000374) → 不再崩溃 → 不再需要看门狗。
- 按键动作与旧版完全一致：
    麦克风键 -> 可配置语音输入快捷键
    上翻页键 -> 回到行尾再 Backspace 删一个字
    下翻页键 -> 当前鼠标位置左键点击后回车
- 按键 -> 报文 的映射（hid_actions）需要先用 `hid_probe.py listen` 抓一次码填进配置。
  抓码前本文件可正常启动，只是按键暂不触发动作（会在日志里打印未知报文，便于补码）。

运行
====
  python voice_typing_hid.py run      # 正式运行（托盘）
  python voice_typing_hid.py learn 40 # 学习模式：监听 40 秒，把每个键的“按下报文”打印出来

麦克风常开
==========
  启动时用纯 hidapi 向 MI_05 发送 kwma_x64.dll 的开麦握手复刻版：
  动态令牌(当前秒 + MSVC rand + 校验) -> 常量初始化 -> 开麦命令。
  全程不加载 DLL，当前进程保持 MI_05 handle 存活。
"""
import ctypes
import datetime as dt
import json
import sys
import threading
import time
from pathlib import Path

import hid

PEN_VIDS = {0x0611, 0x1915}
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
CONFIG = ROOT / "voice_typing_hid_config.json"
LOG = ROOT / "voice_typing_hid.log"

DEFAULT_CONFIG = {
    "click_enter_delay_ms": 80,
    "debounce_ms": 250,
    "enable_mic_on_start": True,
    "mic_open_delay_ms": 80,
    "mic_open_repeat_dynamic": 1,
    "mic_session_keepalive_ms": 200,
    "mic_session_warmup_ms": 1000,
    "refresh_mic_before_pen_hotkey": True,
    "keyboard_hotkey_mic_refresh": True,
    "keyboard_hotkey_vk": "0xA5",
    "keyboard_hotkey_vks": ["0xA5"],
    "keyboard_hotkey_poll_ms": 25,
    "keyboard_hotkey_debounce_ms": 500,
    # 抓码确认(2026-06-23)：笔按键全部来自 iface=5(usage_page 0xff00)，
    # 报文格式 = 0b 30 58 00 10 [键码] [状态]，键码在 data[5]，状态 data[6](01按下/00松开)。
    # 键码 -> 逻辑键（与老 DLL 键号一致：mic=23 pageup=19 pagedown=20）
    "hid_keycodes": {"23": "mic", "19": "pageup", "20": "pagedown"},
    "log_unknown": False,
    # 逻辑键 -> 实际动作
    "key_to_action": {
        "mic": "right_alt",
        "pageup": "tail_backspace",
        "pagedown": "click_enter",
    },
    # 只监听这些 usage_page 的接口（厂商0xff00 / 消费0x000c / 系统0x0001-0x80）；为空=全部非键鼠
    "listen_usage_pages": ["0xff00", "0xff01", "0x000c", "0x0001"],
}


def ts() -> str:
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{ts()}] {msg}\n")


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG.exists():
        try:
            cfg.update(json.loads(CONFIG.read_text(encoding="utf-8-sig")))
        except Exception as exc:
            log(f"config load error: {exc}")
    else:
        CONFIG.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


# ---------------- SendInput 机制（从旧 tray.py 移植，保持行为一致） ----------------
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort), ("wParamH", ctypes.c_ushort)]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", INPUT_UNION)]


INPUT_KEYBOARD, INPUT_MOUSE = 1, 0
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP, KEYEVENTF_SCANCODE = 0x0001, 0x0002, 0x0008
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004


def _scan(scan, up=False, extended=False):
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if extended else 0)
    return INPUT(INPUT_KEYBOARD, INPUT_UNION(ki=KEYBDINPUT(0, scan, flags, 0, 0)))


def _mouse(flags):
    return INPUT(INPUT_MOUSE, INPUT_UNION(mi=MOUSEINPUT(0, 0, 0, flags, 0, 0)))


def _send(items):
    ctypes.windll.user32.SendInput(len(items), (INPUT * len(items))(*items), ctypes.sizeof(INPUT))


def do_right_alt():
    _send((_scan(0x38, extended=True), _scan(0x38, up=True, extended=True)))


def do_win_h():
    _send(
        (
            _scan(0x5B, extended=True),
            _scan(0x23),
            _scan(0x23, up=True),
            _scan(0x5B, up=True, extended=True),
        )
    )


def do_enter():
    _send((_scan(0x1C), _scan(0x1C, up=True)))


def do_left_click():
    _send((_mouse(MOUSEEVENTF_LEFTDOWN), _mouse(MOUSEEVENTF_LEFTUP)))


def do_tail_backspace():
    # Ctrl 不动, End 回行尾, 再 Backspace 一次（与旧版一致）
    _send((_scan(0x1D), _scan(0x4F, extended=True), _scan(0x4F, up=True, extended=True),
           _scan(0x1D, up=True), _scan(0x0E), _scan(0x0E, up=True)))


ACTIONS = {
    "right_alt": do_right_alt,
    "win_h": do_win_h,
    "tail_backspace": do_tail_backspace,
    "click_enter": lambda: (do_left_click(), time.sleep(0.08), do_enter()),
}


# ---------------- HID 读取 ----------------
def pen_interfaces(cfg):
    want = {int(x, 16) for x in cfg.get("listen_usage_pages", [])}
    out = []
    for d in hid.enumerate():
        if d["vendor_id"] not in PEN_VIDS:
            continue
        up = d["usage_page"]
        # 跳过纯键盘(0x01/0x06)与鼠标(0x01/0x02)的通用接口——它们发标准键值，不在我们要拦的特殊键里
        if up == 0x0001 and d["usage"] in (0x02, 0x06):
            continue
        if want and up not in want:
            continue
        out.append(d)
    return out


# hidapi 有新旧两套 API：新版 hid.Device(path=...).read(n,timeout)；旧版 hid.device().open_path()/read(n)
HID_NEW = hasattr(hid, "Device")


def _open(path):
    if HID_NEW:
        h = hid.Device(path=path)
        h.nonblocking = True
        return h
    h = hid.device()
    h.open_path(path)
    h.set_nonblocking(1)
    return h


def _read(h):
    try:
        return h.read(64, timeout=10) if HID_NEW else h.read(64)
    except Exception:
        return None


def _close(h):
    try:
        h.close()
    except Exception:
        pass


# ---------------- V60 纯 HID 开麦 ----------------
def _b33(*head):
    return bytes(list(head) + [0] * (33 - len(head)))


def _msvc_rand_next(state):
    state = (state * 214013 + 2531011) & 0xFFFFFFFF
    return state, (state >> 16) & 0x7FFF


def _signed_trunc_div(value, divisor):
    if value & 0x80000000:
        value -= 0x100000000
    return value // divisor if value >= 0 else -((-value) // divisor)


def _make_mic_dynamic_report(seed=None):
    if seed is None:
        seed = int(time.time())
    state = seed & 0xFFFFFFFF
    state, r1 = _msvc_rand_next(state)
    state, r2 = _msvc_rand_next(state)
    token = ((r1 << 16) | r2) & 0xFFFFFFFF
    check = (token + _signed_trunc_div(token, 200) * 0x38) & 0xFF
    return _b33(
        0x00, 0x06, 0x00, 0x00, 0x00, 0x00, 0x02, 0x05, 0x01,
        check, token & 0xFF, (token >> 8) & 0xFF, (token >> 16) & 0xFF, (token >> 24) & 0xFF,
    ), seed, token


MIC_CMD_CONST = _b33(0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x03, 0x18, 0x01)
MIC_CMD_ON = _b33(0x00, 0x06, 0x00, 0x00, 0x00, 0x00, 0x08, 0x04, 0x00, 0x01)
MIC_CMD_AUDIO_REFRESH = _b33(0x00, 0x06, 0x00, 0x00, 0x00, 0x00, 0x03, 0x0A, 0x01)
_mic_keepalive_started = False
_mic_handle = None
_mic_write_lock = threading.Lock()
_mic_last_refresh = 0.0


def _is_v60_mic_iface(d):
    return (
        d.get("vendor_id") == 0x0611
        and d.get("product_id") == 0x3001
        and d.get("interface_number") == 5
        and d.get("usage_page") == 0xFF00
    )


def _write_report(h, report):
    with _mic_write_lock:
        return h.write(report)


def _report_hex(data):
    return " ".join(f"{b:02x}" for b in data)


def _wait_for_prefix(h, name, prefix, timeout_s=1.0, required=True):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        data = _read(h)
        if not data:
            time.sleep(0.01)
            continue
        data = bytes(data)
        if data.startswith(prefix):
            log(f"pure HID mic {name} ack ok: {_report_hex(data)}")
            return True
        if not is_idle(data):
            log(f"pure HID mic {name} read nonmatch: {_report_hex(data)}")
    level = "timeout" if required else "no ack"
    log(f"pure HID mic {name} {level}: expected {_report_hex(prefix)}")
    return False


def _start_mic_keepalive(h, cfg):
    global _mic_keepalive_started
    interval_ms = int(cfg.get("mic_session_keepalive_ms", 200))
    if interval_ms <= 0:
        log("pure HID mic session keepalive disabled by config")
        return
    if _mic_keepalive_started:
        return
    _mic_keepalive_started = True
    interval = max(0.05, interval_ms / 1000.0)

    def loop():
        tick = 0
        while True:
            time.sleep(interval)
            try:
                n = _write_report(h, MIC_CMD_CONST)
                tick += 1
                if tick % 10 == 0:
                    _write_report(h, MIC_CMD_AUDIO_REFRESH)
                    _write_report(h, MIC_CMD_ON)
                if tick == 1 or tick % 50 == 0:
                    log(f"pure HID mic session keepalive write={n} interval_ms={interval_ms}")
            except Exception as exc:
                log(f"pure HID mic session keepalive stopped: {exc}")
                break

    threading.Thread(target=loop, name="v60-mic-session-keepalive", daemon=True).start()
    log(f"pure HID mic session keepalive started interval_ms={interval_ms}")


def refresh_v60_mic(reason, cfg=None):
    """Re-send the short mic activation burst before external voice input."""
    global _mic_last_refresh
    h = _mic_handle
    if h is None:
        log(f"pure HID mic refresh skipped reason={reason}: MI_05 not ready")
        return False
    debounce_ms = int((cfg or {}).get("keyboard_hotkey_debounce_ms", 500))
    now = time.time()
    if now - _mic_last_refresh < max(0.05, debounce_ms / 1000.0):
        return False
    _mic_last_refresh = now
    try:
        n1 = _write_report(h, MIC_CMD_AUDIO_REFRESH)
        n2 = _write_report(h, MIC_CMD_ON)
        log(f"pure HID mic refresh reason={reason} writes=[{n1}, {n2}]")
        return True
    except Exception as exc:
        log(f"pure HID mic refresh error reason={reason}: {exc}")
        return False


def _parse_vk(value, default=0xA5):
    try:
        if isinstance(value, int):
            return value
        return int(str(value), 0)
    except Exception:
        return default


def _start_keyboard_hotkey_monitor(cfg):
    if not cfg.get("keyboard_hotkey_mic_refresh", True):
        log("keyboard hotkey mic refresh disabled by config")
        return
    raw_vks = cfg.get("keyboard_hotkey_vks") or [cfg.get("keyboard_hotkey_vk", "0xA5")]
    if not isinstance(raw_vks, list):
        raw_vks = [raw_vks]
    vks = []
    for raw in raw_vks:
        vk = _parse_vk(raw)
        if vk not in vks:
            vks.append(vk)
    poll_s = max(0.01, int(cfg.get("keyboard_hotkey_poll_ms", 25)) / 1000.0)

    def loop():
        was_down = {vk: False for vk in vks}
        while True:
            try:
                for vk in vks:
                    down = bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
                    if down and not was_down.get(vk, False):
                        refresh_v60_mic(f"keyboard_vk=0x{vk:02x}", cfg)
                    was_down[vk] = down
            except Exception as exc:
                log(f"keyboard hotkey monitor stopped: {exc}")
                break
            time.sleep(poll_s)

    threading.Thread(target=loop, name="v60-keyboard-hotkey-mic-refresh", daemon=True).start()
    keys = ",".join(f"0x{vk:02x}" for vk in vks)
    log(f"keyboard hotkey mic refresh started vks={keys} poll_ms={int(poll_s * 1000)}")


def enable_v60_mic(opened, cfg):
    global _mic_handle
    if not cfg.get("enable_mic_on_start", True):
        log("pure HID mic enable disabled by config")
        return
    target = next(((d, h) for d, h in opened if _is_v60_mic_iface(d)), None)
    if not target:
        log("pure HID mic enable skipped: V60 MI_05 not open")
        return
    _, h = target
    _mic_handle = h
    delay = float(cfg.get("mic_open_delay_ms", 80)) / 1000.0
    repeat = max(1, int(cfg.get("mic_open_repeat_dynamic", 1)))
    try:
        writes = []
        acks = []
        seed = 0
        token = 0
        for _ in range(repeat):
            dynamic, seed, token = _make_mic_dynamic_report()
            writes.append(_write_report(h, dynamic))
            acks.append(_wait_for_prefix(h, "dynamic", b"\x06\x00\x00\x00\x00\x02\x05\x11"))
            time.sleep(delay)
        writes.append(_write_report(h, MIC_CMD_CONST))
        _wait_for_prefix(h, "constant", b"\x01\x00\x00\x00\x00\x03\x18\x01", timeout_s=0.25, required=False)
        _start_mic_keepalive(h, cfg)
        warmup = max(0.0, float(cfg.get("mic_session_warmup_ms", 1000)) / 1000.0)
        if warmup:
            log(f"pure HID mic session warmup before mic_on {warmup:.3f}s")
            time.sleep(warmup)
        time.sleep(delay)
        writes.append(_write_report(h, MIC_CMD_ON))
        acks.append(_wait_for_prefix(h, "mic_on", b"\x06\x00\x00\x00\x00\x08\x04\x10\x01"))
        log(f"pure HID mic enable sent seed={seed} token=0x{token:08x} writes={writes} acks={acks}")
    except Exception as exc:
        log(f"pure HID mic enable error: {exc}")


def open_interfaces(devs):
    opened = []
    for d in devs:
        try:
            opened.append((d, _open(d["path"])))
        except Exception as exc:
            log(f"open skip iface={d['interface_number']} up={d['usage_page']:#06x}: {exc}")
    return opened


def sig(d, data):
    """接口签名 + 报文hex，作为 hid_actions 的匹配键。"""
    return f"{d['usage_page']:#06x}:" + " ".join(f"{b:02x}" for b in data)


def is_idle(data):
    # 报文除可能的 report-id 外全 0 视为“松开/空闲”
    return all(b == 0 for b in data) or all(b == 0 for b in data[1:])


def learn(seconds=40):
    cfg = load_config()
    devs = pen_interfaces(cfg)
    opened = open_interfaces(devs)
    print(f"已打开 {len(opened)} 个接口，学习 {seconds} 秒。请依次按 麦克风/上翻页/下翻页，每个 3 下。\n")
    end = time.time() + seconds
    last = {}
    seen = {}
    while time.time() < end:
        for d, h in opened:
            data = _read(h)
            if data and not is_idle(data):
                s = sig(d, data)
                if last.get(id(h)) != s:
                    last[id(h)] = s
                    seen[s] = seen.get(s, 0) + 1
                    print(f"[{time.strftime('%H:%M:%S')}] iface={d['interface_number']} {s}")
            elif data:
                last[id(h)] = None
        time.sleep(0.005)
    for _, h in opened:
        _close(h)
    print("\n=== 出现过的“按下报文”（次数）===")
    for s, n in sorted(seen.items(), key=lambda kv: -kv[1]):
        print(f"  x{n}  {s}")
    print("\n把上面对应 麦克风/上翻页/下翻页 的那 3 条，填进 config 的 hid_actions: { \"<报文>\": \"mic|pageup|pagedown\" }")


def parse_button(data):
    """解析笔按键报文。返回 (keycode, pressed) 或 None。
    格式: 0b 30 58 00 10 [keycode] [state]  (state 1=按下 0=松开)"""
    if len(data) >= 7 and data[0] == 0x0b and data[4] == 0x10:
        return data[5], (data[6] == 0x01)
    return None


def run():
    cfg = load_config()
    keycodes = {int(k): v for k, v in cfg.get("hid_keycodes", {}).items()}
    key_to_action = cfg.get("key_to_action", {})
    debounce = float(cfg.get("debounce_ms", 250)) / 1000.0
    log_unknown = cfg.get("log_unknown", False)

    devs = pen_interfaces(cfg)
    opened = open_interfaces(devs)
    log(f"started (no-DLL); opened {len(opened)} hid interfaces; keycodes={keycodes}")
    if not opened:
        log("ERROR: 没有可读的笔 HID 接口，退出。")
        return
    enable_v60_mic(opened, cfg)
    _start_keyboard_hotkey_monitor(cfg)

    held = {}        # id(h) -> 当前按住的 keycode，用于检测“按下沿”
    last_fire = {}
    while True:
        saw_data = False
        for d, h in opened:
            data = _read(h)
            if not data:
                continue
            saw_data = True
            btn = parse_button(data)
            if btn is None:
                if log_unknown and not is_idle(data):
                    log(f"unknown report iface={d['interface_number']} {sig(d, data)}")
                continue
            keycode, pressed = btn
            if not pressed:
                held[id(h)] = None      # 松开
                continue
            if held.get(id(h)) == keycode:
                continue                 # 仍按住同一键，去重
            held[id(h)] = keycode
            logical = keycodes.get(keycode)
            if not logical:
                if log_unknown:
                    log(f"unknown keycode={keycode} iface={d['interface_number']}")
                continue
            now = time.time()
            if now - last_fire.get(logical, 0.0) < debounce:
                continue
            last_fire[logical] = now
            action_name = key_to_action.get(logical)
            fn = ACTIONS.get(action_name)
            if fn:
                try:
                    if logical == "mic" and cfg.get("refresh_mic_before_pen_hotkey", True):
                        refresh_v60_mic("pen_mic_key", cfg)
                    fn()
                    log(f"action {action_name} <- {logical}(key={keycode})")
                except Exception as exc:
                    log(f"action error {logical}: {exc}")
        if not saw_data:
            time.sleep(0.005)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "run"
    if mode == "learn":
        learn(int(sys.argv[2]) if len(sys.argv) > 2 else 40)
    else:
        # 单实例
        m = ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\HanvonPenVoiceBridgeHID")
        if ctypes.windll.kernel32.GetLastError() == 183:
            log("already running; exit")
            raise SystemExit(0)
        run()
