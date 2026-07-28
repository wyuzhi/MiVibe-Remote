#!/usr/bin/env python3
"""Independent Hanvon V60 voice-pen bridge entrypoint."""

from __future__ import annotations

import os
import sys


APP_VERSION = "1.0.0"

os.environ.setdefault("REMOTE_BRIDGE_AUDIO_TRANSPORT", "native")
os.environ.setdefault("REMOTE_BRIDGE_V60_APP_NAME", "V60语音笔桥接")
os.environ.setdefault("REMOTE_BRIDGE_V60_VERSION", APP_VERSION)


def main(argv: list[str] | None = None) -> int:
    from bridges.hanvon import hanvon_pen_app

    return hanvon_pen_app.main(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())
