#!/usr/bin/env python3
"""Independent T1 remote bridge entrypoint."""

from __future__ import annotations

import os
import sys


APP_VERSION = "1.0.0"

os.environ.setdefault("REMOTE_BRIDGE_AUDIO_TRANSPORT", "native")
os.environ.setdefault("REMOTE_BRIDGE_T1_VERSION", APP_VERSION)
os.environ.setdefault("REMOTE_BRIDGE_T1_CONTROL_PORT", "31682")


def main(argv: list[str] | None = None) -> int:
    from bridges.t1 import app

    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) >= 2 and arguments[0] == "--role":
        role = arguments[1]
        rest = arguments[2:]
        if role != "t1-worker":
            raise ValueError(f"T1 独立包不支持内部角色：{role}")
        return app.main(["--bridge", *rest])
    if "--autorun" not in arguments:
        arguments.insert(0, "--autorun")
    return app.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
