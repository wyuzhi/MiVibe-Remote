from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from bridges import audio_client
from bridges.audio import audio_router
from bridges.t1 import app as t1_app
from bridges import raw_input_bridge as bridge_core
from bridges.xiaomi import xiaomi_config


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        return int(endpoint.getsockname()[1])


class DelayedOpenServer:
    def __init__(self, delays: list[float]):
        self.port = free_udp_port()
        self.delays = list(delays)
        self.requests: list[dict] = []
        self.error: BaseException | None = None
        self.ready = threading.Event()
        self.done = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self.thread.start()
        if not self.ready.wait(1.0):
            raise RuntimeError("delayed UDP test server did not start")

    def _run(self) -> None:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
                audio_router.ignore_windows_udp_connreset(server)
                server.bind(("127.0.0.1", self.port))
                server.settimeout(1.0)
                self.ready.set()
                for delay in self.delays:
                    while True:
                        try:
                            payload, peer = server.recvfrom(4096)
                            break
                        except ConnectionResetError:
                            continue
                    request = json.loads(payload.decode("utf-8"))
                    self.requests.append(request)
                    time.sleep(delay)
                    server.sendto(
                        json.dumps(
                            {
                                "ok": True,
                                "request_id": request["request_id"],
                                "reused": len(self.requests) > 1,
                            }
                        ).encode("utf-8"),
                        peer,
                    )
        except BaseException as exc:  # surfaced in the test thread
            self.error = exc
            self.ready.set()
        finally:
            self.done.set()


class FakeRouter:
    def __init__(self, fail_open: bool = False, stale_close: bool = False):
        self.fail_open = fail_open
        self.stale_close = stale_close
        self.close_owner_calls = 0

    def open(self, _device: str, token=None, max_session_ms: int = 0) -> str:
        if self.fail_open:
            raise audio_client.AudioRouterError("simulated open failure")
        self.max_session_ms = max_session_ms
        return token or "test-token"

    def close(self, _token: str, tail_ms: int = 0) -> dict:
        if self.stale_close:
            return {"ok": True, "closed": False, "stale": True}
        return {"ok": True, "closed": True, "tail_ms": tail_ms}

    def close_owner(self, timeout=None) -> dict:
        self.close_owner_calls += 1
        return {"ok": True, "closed": True}

    def status(self) -> dict:
        return {"ok": True, "sources": {"t1": {"signal_seen": True}}}


class T1ReliabilityTests(unittest.TestCase):
    def _bridge(self, root: Path) -> bridge_core.T1Bridge:
        config_path = root / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "device_match": ["VID_1915&PID_1025"],
                    "button_aliases": {"voice": ["hid:02-CF-00"]},
                    "button_bindings": {},
                    "bindings": {},
                    "learn_log": "logs/learn_events.jsonl",
                    "action_log": "logs/action_events.jsonl",
                }
            ),
            encoding="utf-8",
        )
        bridge = bridge_core.T1Bridge(
            config_path,
            learn=False,
            dry_run=False,
            verbose=False,
            control_port=free_udp_port(),
        )
        bridge._start_audio_watchdog = lambda *_args, **_kwargs: None
        return bridge

    @staticmethod
    def _voice_action() -> dict:
        return {
            "type": "hotkey_down",
            "keys": ["rightalt"],
            "state_id": "voice_input_shortcut",
            "audio_source": "Mic Device",
            "audio_tail_ms": 120,
            "audio_max_hold_ms": 300_000,
            "audio_trigger_mode": "toggle_hotkey",
            "second_press_stops": True,
        }

    def test_slow_open_600_1200_and_5600_ms_succeeds(self) -> None:
        original_port = audio_client.CONTROL_PORT
        try:
            for delay, open_timeout in ((0.6, 1.8), (1.2, 1.8), (5.6, 6.5)):
                with self.subTest(delay=delay):
                    server = DelayedOpenServer([delay])
                    server.start()
                    audio_client.CONTROL_PORT = server.port
                    client = audio_client.AudioRouterClient(
                        "t1", timeout=0.2, open_timeout=open_timeout
                    )
                    token = client.open("Mic Device", token="stable-token")
                    self.assertEqual(token, "stable-token")
                    self.assertTrue(server.done.wait(2.0))
                    self.assertIsNone(server.error)
                    self.assertEqual(server.requests[0]["token"], "stable-token")
        finally:
            audio_client.CONTROL_PORT = original_port

    def test_open_retry_reuses_the_same_token(self) -> None:
        server = DelayedOpenServer([0.12, 0.0])
        server.start()
        original_port = audio_client.CONTROL_PORT
        audio_client.CONTROL_PORT = server.port
        try:
            client = audio_client.AudioRouterClient(
                "t1", timeout=0.05, open_timeout=0.08
            )
            token = client.open("Mic Device", token="idempotent-token")
            self.assertEqual(token, "idempotent-token")
            self.assertTrue(server.done.wait(2.0))
            self.assertIsNone(server.error)
            self.assertEqual(len(server.requests), 2)
            self.assertEqual(
                {request["token"] for request in server.requests},
                {"idempotent-token"},
            )
        finally:
            audio_client.CONTROL_PORT = original_port

    def test_open_failure_never_toggles_or_marks_voice_active(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bridge = self._bridge(Path(temp))
            bridge.audio_router = FakeRouter(fail_open=True)
            with mock.patch.object(bridge_core, "send_hotkey") as send:
                bridge.run_action(
                    {"event_id": "hid:02-CF-00"},
                    self._voice_action(),
                )
            send.assert_not_called()
            self.assertFalse(bridge.active_hotkeys)
            self.assertFalse(bridge.audio_sessions)
            records = [
                json.loads(line)
                for line in bridge.action_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(records[-1]["voice_event"], "start_failed")

    def test_second_press_closes_stale_session_by_owner_and_logs_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bridge = self._bridge(root)
            fake_router = FakeRouter(stale_close=True)
            bridge.audio_router = fake_router
            action = self._voice_action()
            with mock.patch.object(bridge_core, "send_hotkey") as send:
                bridge.run_action({"event_id": "hid:02-CF-00"}, action)
                self.assertIn("voice_input_shortcut", bridge.active_hotkeys)
                bridge.run_action({"event_id": "hid:02-CF-00"}, action)
            self.assertEqual(send.call_count, 2)
            self.assertFalse(bridge.active_hotkeys)
            self.assertFalse(bridge.audio_sessions)
            self.assertEqual(fake_router.close_owner_calls, 1)
            runtime = json.loads(
                (root / "t1_runtime_state.json").read_text(encoding="utf-8")
            )
            self.assertFalse(runtime["active"])
            records = [
                json.loads(line)
                for line in bridge.action_log.read_text(encoding="utf-8").splitlines()
            ]
            stopped = [record for record in records if record.get("voice_event") == "stopped"]
            self.assertEqual(stopped[-1]["reason"], "second_press")

    def test_control_port_reports_and_stops_active_voice(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bridge = self._bridge(Path(temp))
            bridge.audio_router = FakeRouter()
            original_port = t1_app.T1_CONTROL_PORT
            t1_app.T1_CONTROL_PORT = bridge.control_port
            bridge._start_control_listener()
            try:
                with mock.patch.object(bridge_core, "send_hotkey") as send:
                    bridge.run_action(
                        {"event_id": "hid:02-CF-00"},
                        self._voice_action(),
                    )
                    status = t1_app.t1_control_request("status")
                    self.assertTrue(status["voice_active"])
                    stopped = t1_app.t1_control_request("stop_voice", timeout=2.0)
                    self.assertEqual(stopped["stopped"], 1)
                    self.assertFalse(stopped["voice_active"])
                self.assertEqual(send.call_count, 2)
            finally:
                bridge._stop_control_listener()
                t1_app.T1_CONTROL_PORT = original_port

    def test_fifty_start_stop_cycles_leave_no_t1_session(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bridge = self._bridge(Path(temp))
            bridge.audio_router = FakeRouter()
            action = self._voice_action()
            with (
                mock.patch.object(bridge_core, "send_hotkey") as send,
                mock.patch("builtins.print"),
            ):
                for _ in range(50):
                    bridge.run_action({"event_id": "hid:02-CF-00"}, action)
                    bridge.run_action({"event_id": "hid:02-CF-00"}, action)
                    self.assertFalse(bridge.active_hotkeys)
                    self.assertFalse(bridge.audio_sessions)
            self.assertEqual(send.call_count, 100)

    def test_stale_active_state_is_recovered_after_forced_exit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bridge = self._bridge(root)
            fake_router = FakeRouter()
            bridge.audio_router = fake_router
            bridge.runtime_state_path.write_text(
                json.dumps(
                    {
                        "active": True,
                        "state_id": "voice_input_shortcut",
                        "keys": ["rightalt"],
                        "pid": 12345,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(bridge_core, "send_hotkey") as send:
                bridge._recover_stale_state()
            send.assert_called_once_with(["rightalt"], 70)
            self.assertEqual(fake_router.close_owner_calls, 1)
            recovered = json.loads(
                bridge.runtime_state_path.read_text(encoding="utf-8")
            )
            self.assertFalse(recovered["active"])
            records = [
                json.loads(line)
                for line in bridge.action_log.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(records[-1]["voice_event"], "recovered")

    def test_action_logs_stay_inside_t1_appdata_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "iPazzPortRemoteBridge"
            root.mkdir()
            bridge = self._bridge(root)
            self.assertEqual(bridge.root, root)
            self.assertEqual(bridge.action_log, root / "logs" / "action_events.jsonl")
            self.assertEqual(bridge.audio_router.open_timeout, 8.0)
            self.assertEqual(bridge.audio_router.open_retry_timeout, 2.0)

    def test_router_hard_expiry_precedes_pid_check(self) -> None:
        router = audio_router.AudioRouter.__new__(audio_router.AudioRouter)
        router.sessions = {
            "t1": {
                "close_at": None,
                "expires_at": time.monotonic() - 0.01,
                "client_pid": 1,
            }
        }
        closed: list[tuple[str, str]] = []
        router._close_owner = lambda owner, reason: closed.append((owner, reason)) or True
        router._expire_sessions()
        self.assertEqual(closed, [("t1", "max_session_elapsed")])

    def test_atomic_config_save_creates_last_good(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "config.json"
            data = {"button_aliases": {}, "button_bindings": {}, "bindings": {}}
            t1_app.save_json(path, data)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), data)
            last_good = path.with_name("config.last-good.json")
            self.assertEqual(json.loads(last_good.read_text(encoding="utf-8")), data)
            self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_unreachable_keyboard_only_button_is_reported_unsupported(self) -> None:
        config = {
            "listen_keyboard": False,
            "listen_consumer": True,
            "button_aliases": {
                "up": ["kbd:VK_26:SC_048:E0:down"],
                "voice": ["hid:02-CF-00"],
            },
        }
        self.assertFalse(t1_app.button_runtime_supported(config, "up"))
        self.assertTrue(t1_app.button_runtime_supported(config, "voice"))

    def test_left_and_right_win_names_are_supported(self) -> None:
        self.assertEqual(bridge_core.resolve_vk("leftwin"), 0x5B)
        self.assertEqual(bridge_core.resolve_vk("rightwin"), 0x5C)
        self.assertEqual(bridge_core.resolve_vk("lwin"), 0x5B)
        self.assertEqual(bridge_core.resolve_vk("rwin"), 0x5C)

    def test_every_default_xiaomi_hotkey_is_resolvable(self) -> None:
        for button_id, actions in xiaomi_config.DEFAULT_BUTTON_BINDINGS.items():
            for action in actions:
                if action.get("type") != "hotkey":
                    continue
                for key in action.get("keys", []):
                    with self.subTest(button=button_id, key=key):
                        self.assertIsInstance(bridge_core.resolve_vk(key), int)


if __name__ == "__main__":
    unittest.main(verbosity=2)
