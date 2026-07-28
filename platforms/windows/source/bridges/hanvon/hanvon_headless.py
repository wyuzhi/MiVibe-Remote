#!/usr/bin/env python3
"""Headless Hanvon bridge role used by Remote Bridge Hub."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import signal
import socket
import threading
import time

from . import hanvon_pen_app as app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--control-port", type=int, default=30683)
    args = parser.parse_args(argv)
    mutex = ctypes.windll.kernel32.CreateMutexW(
        None, False, "Global\\RemoteBridgeHubHanvon"
    )
    if ctypes.windll.kernel32.GetLastError() == 183:
        return 0

    app.core.CONFIG = app.CONFIG_PATH
    config = app.load_app_config()
    engine = app.BridgeEngine(config)
    stop_event = threading.Event()
    control_stop = threading.Event()
    control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    control.bind(("127.0.0.1", args.control_port))
    control.settimeout(0.25)

    def stop(_signum=None, _frame=None):
        stop_event.set()

    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is not None:
            try:
                signal.signal(signum, stop)
            except (ValueError, OSError):
                pass

    def control_loop() -> None:
        while not control_stop.is_set():
            try:
                payload, peer = control.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            request_id = None
            shutting_down = False
            try:
                request = json.loads(payload.decode("utf-8"))
                request_id = request.get("request_id")
                op = str(request.get("op") or "")
                if op == "status":
                    details = {
                        "pid": os.getpid(),
                        "voice_active": engine._voice_is_active(),
                        "audio_active": engine._audio_is_active(),
                    }
                elif op == "shutdown":
                    shutting_down = True
                    details = {
                        "pid": os.getpid(),
                        "shutting_down": True,
                    }
                else:
                    raise ValueError(f"unsupported Hanvon control operation: {op}")
                response = {"ok": True, "request_id": request_id, **details}
            except Exception as exc:
                response = {
                    "ok": False,
                    "request_id": request_id,
                    "error": str(exc),
                }
            try:
                control.sendto(
                    json.dumps(response, ensure_ascii=False).encode("utf-8"),
                    peer,
                )
            except OSError:
                pass
            if shutting_down:
                stop_event.set()
                break

    app.app_log("headless role started by Remote Bridge Hub")
    engine.start()
    threading.Thread(
        target=control_loop,
        name="hanvon-control-listener",
        daemon=True,
    ).start()
    try:
        while not stop_event.wait(0.5):
            pass
    finally:
        engine.stop()
        time.sleep(0.5)
        control_stop.set()
        control.close()
        app.app_log("headless role stopped")
        ctypes.windll.kernel32.CloseHandle(mutex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
