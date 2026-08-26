from __future__ import annotations

import json
from pathlib import Path
import socket
import sys
import threading
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from bridges.xiaomi.xiaomi_settings import (  # noqa: E402
    SETTINGS_CONTROL_PORT_OFFSET,
    claim_settings_instance,
    send_hub_restart,
)


class XiaomiSettingsControlTests(unittest.TestCase):
    def test_save_waits_for_matching_bridge_restart_confirmation(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        server.bind(("127.0.0.1", 0))
        port = int(server.getsockname()[1])
        observed: dict[str, object] = {}

        def respond() -> None:
            payload, peer = server.recvfrom(4096)
            request = json.loads(payload.decode("utf-8"))
            observed.update(request)
            server.sendto(
                json.dumps(
                    {
                        "ok": True,
                        "request_id": request["request_id"],
                        "pid": 4321,
                    }
                ).encode("utf-8"),
                peer,
            )

        worker = threading.Thread(target=respond, daemon=True)
        worker.start()
        try:
            self.assertEqual(send_hub_restart(port, timeout=1.0), 4321)
            worker.join(timeout=1.0)
        finally:
            server.close()

        self.assertEqual(observed["op"], "restart")
        self.assertEqual(observed["bridge"], "xiaomi")
        self.assertTrue(observed["request_id"])

    def test_save_reports_when_bridge_does_not_confirm_restart(self) -> None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
        probe.close()

        with self.assertRaisesRegex(RuntimeError, "没有确认桥接重启"):
            send_hub_restart(port, timeout=0.05)

    def test_second_settings_instance_focuses_first_and_exits(self) -> None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        settings_port = int(probe.getsockname()[1])
        probe.close()
        hub_port = settings_port - SETTINGS_CONTROL_PORT_OFFSET

        first = claim_settings_instance(hub_port)
        self.assertIsNotNone(first)
        observed: list[bytes] = []

        def respond() -> None:
            assert first is not None
            payload, peer = first.recvfrom(256)
            observed.append(payload)
            first.sendto(b"OK show", peer)

        worker = threading.Thread(target=respond, daemon=True)
        worker.start()
        try:
            self.assertIsNone(claim_settings_instance(hub_port))
            worker.join(timeout=1.0)
        finally:
            assert first is not None
            first.close()

        self.assertEqual(observed, [b"SHOW"])


if __name__ == "__main__":
    unittest.main()
