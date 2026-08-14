from __future__ import annotations

import json
import sys
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from bridges.audio import audio_router
from bridges.hanvon import hanvon_pen_app
from bridges.hanvon import voice_typing_hid as hanvon_core
from bridges import native_audio
from bridges.physical_hotkey_monitor import PhysicalHotkeyState
from bridges import raw_input_bridge as t1_core
from bridges.xiaomi import atvv_live_bridge as xiaomi_core
from bridges.xiaomi import hid_report_tap
from bridges.xiaomi import hid_tap_injector
from bridges.xiaomi import hid_tap_runtime
from bridges.xiaomi import xiaomi_config


class XiaomiCoreBehaviorTests(unittest.TestCase):
    def test_voice_shortcut_uses_checked_hardware_scan_code_edges(self) -> None:
        keyboard = mock.Mock()
        with mock.patch.object(xiaomi_core.os, "name", "nt"):
            shortcut = xiaomi_core.VoiceShortcut(
                "ctrl+win",
                keyboard=keyboard,
            )

        with mock.patch("builtins.print"):
            shortcut.press()
            shortcut.release()

        self.assertEqual(
            keyboard.send_scan_code_vk.call_args_list,
            [
                mock.call(0x11, False),
                mock.call(0x5B, False),
                mock.call(0x5B, True),
                mock.call(0x11, True),
            ],
        )
        self.assertFalse(shortcut.pressed)

    def test_voice_shortcut_does_not_claim_success_when_sendinput_fails(self) -> None:
        keyboard = mock.Mock()
        keyboard.send_scan_code_vk.side_effect = OSError("SendInput blocked")
        with mock.patch.object(xiaomi_core.os, "name", "nt"):
            shortcut = xiaomi_core.VoiceShortcut(
                "rightalt",
                keyboard=keyboard,
            )

        with (
            self.assertRaisesRegex(OSError, "SendInput blocked"),
            mock.patch("builtins.print") as output,
        ):
            shortcut.press()

        output.assert_not_called()
        self.assertFalse(shortcut.pressed)

    def test_voice_shortcut_rolls_back_a_partially_pressed_chord(self) -> None:
        keyboard = mock.Mock()
        keyboard.send_scan_code_vk.side_effect = [None, OSError("Win blocked"), None]
        with mock.patch.object(xiaomi_core.os, "name", "nt"):
            shortcut = xiaomi_core.VoiceShortcut(
                "ctrl+win",
                keyboard=keyboard,
            )

        with self.assertRaisesRegex(OSError, "Win blocked"):
            shortcut.press()

        self.assertEqual(
            keyboard.send_scan_code_vk.call_args_list,
            [
                mock.call(0x11, False),
                mock.call(0x5B, False),
                mock.call(0x11, True),
            ],
        )
        self.assertFalse(shortcut.pressed)

    def test_bluetooth_address_requires_exactly_six_octets(self) -> None:
        self.assertEqual(
            xiaomi_core.address_to_int("AA:BB:CC:DD:EE:FF"),
            0xAABBCCDDEEFF,
        )
        for invalid in ("", "AA:BB", "not-an-address"):
            with self.assertRaisesRegex(ValueError, "invalid Bluetooth address"):
                xiaomi_core.address_to_int(invalid)

    def test_rc001_atvv_service_is_discovered_without_rc003_hardware_id(self) -> None:
        candidate = xiaomi_core.xiaomi_candidate_from_interface(
            "RC001",
            r"\\?\BTHLEDevice#{ab5e0001-5a21-4f05-bc7d-af01f617b664}_AABBCCDDEEFF#",
        )
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["name"], "RC001")
        self.assertEqual(candidate["address"], "AA:BB:CC:DD:EE:FF")
        self.assertTrue(candidate["known_name"])
        self.assertFalse(candidate["hardware_match"])

    def test_codex_command_action_launches_without_loading_keyboard_mapper(self) -> None:
        hook = xiaomi_core.XiaomiSpecialKeyHook.__new__(
            xiaomi_core.XiaomiSpecialKeyHook
        )
        hook.button_bindings = {
            "home": [
                {
                    "type": "command",
                    "args": ["powershell.exe", "-Command", "Start-Process 'codex:'"],
                }
            ]
        }
        hook.key_send_lock = threading.Lock()
        hook._load_bridge_core = mock.Mock(
            side_effect=AssertionError("command actions do not need the keyboard mapper")
        )

        with (
            mock.patch.object(xiaomi_core.subprocess, "Popen") as launch,
            mock.patch("builtins.print"),
        ):
            handled = hook._perform_button_action("home")

        self.assertTrue(handled)
        launch.assert_called_once_with(
            ["powershell.exe", "-Command", "Start-Process 'codex:'"],
            cwd=None,
            creationflags=getattr(xiaomi_core.subprocess, "CREATE_NO_WINDOW", 0),
        )
        hook._load_bridge_core.assert_not_called()

    def test_preset_cycle_action_uses_runtime_handler_without_keyboard_mapper(self) -> None:
        hook = xiaomi_core.XiaomiSpecialKeyHook.__new__(
            xiaomi_core.XiaomiSpecialKeyHook
        )
        hook.button_bindings = {
            "tv": [{"type": "preset_cycle", "label": "循环切换预设"}]
        }
        hook.key_send_lock = threading.Lock()
        hook.preset_cycle_handler = mock.Mock(return_value="workbuddy")
        hook._load_bridge_core = mock.Mock(
            side_effect=AssertionError("preset cycling does not inject a keyboard key")
        )

        with mock.patch("builtins.print"):
            handled = hook._perform_button_action("tv")

        self.assertTrue(handled)
        hook.preset_cycle_handler.assert_called_once_with()
        hook._load_bridge_core.assert_not_called()

    def test_left_ctrl_mapping_uses_physical_scan_code_injection(self) -> None:
        hook = xiaomi_core.XiaomiSpecialKeyHook.__new__(
            xiaomi_core.XiaomiSpecialKeyHook
        )
        hook.button_bindings = {
            "power": [{"type": "hotkey", "keys": ["leftctrl", "z"]}]
        }
        hook.key_send_lock = threading.Lock()
        keyboard = mock.Mock()
        hook._load_bridge_core = mock.Mock(return_value=keyboard)

        with mock.patch("builtins.print") as output:
            handled = hook._perform_button_action("power")

        self.assertTrue(handled)
        keyboard.send_scan_code_hotkey.assert_called_once_with(
            ["leftctrl", "z"], 120
        )
        keyboard.send_hotkey.assert_not_called()
        self.assertIn("injection=scan_code", output.call_args_list[-1].args[0])

    def test_injector_declares_64_bit_windows_handle_signatures(self) -> None:
        source = Path(hid_tap_injector.__file__).read_text(encoding="utf-8")
        self.assertIn("kernel32.GetCurrentProcess.restype = wintypes.HANDLE", source)
        self.assertIn("advapi32.OpenProcessToken.argtypes", source)
        self.assertIn("kernel32.WriteProcessMemory.argtypes", source)
        self.assertIn("kernel32.CreateRemoteThread.argtypes", source)

    def test_gadget_acl_uses_effective_permissions_for_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir)
            dll = runtime / "gadget.dll"
            dll.write_bytes(b"verified")
            completed = mock.Mock(returncode=0, stdout="")
            with mock.patch.object(
                hid_tap_runtime.subprocess, "run", return_value=completed
            ) as invoked:
                hid_tap_runtime._lock_runtime_acl(runtime)

        commands = [call.args[0] for call in invoked.call_args_list]
        directory_command = next(
            command for command in commands if command[1] == str(runtime)
        )
        file_command = next(command for command in commands if command[1] == str(dll))
        self.assertIn("*S-1-5-32-545:(OI)(CI)RX", directory_command)
        self.assertIn("*S-1-5-32-545:RX", file_command)
        self.assertFalse(any("(OI)(CI)" in item for item in file_command))
        self.assertNotIn("/T", file_command)

    def test_embedded_mapping_does_not_claim_t1_control_port(self) -> None:
        cycle_handler = mock.Mock(return_value="workbuddy")
        with mock.patch.object(t1_core, "main") as mapping_main:
            thread = xiaomi_core.start_raw_mapping_thread(
                True, lambda *_args: True, cycle_handler
            )
            self.assertIsNotNone(thread)
            thread.join(timeout=1.0)

        mapping_main.assert_called_once()
        argv = mapping_main.call_args.args[0]
        self.assertEqual(argv[argv.index("--control-port") + 1], "0")
        self.assertIs(
            mapping_main.call_args.kwargs["action_handlers"]["preset_cycle"],
            cycle_handler,
        )

    def test_raw_mapping_dispatches_preset_cycle_handler(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = t1_core.T1Bridge.__new__(t1_core.T1Bridge)
            handler = mock.Mock(return_value="workbuddy")
            bridge.action_handlers = {"preset_cycle": handler}
            bridge.current_mode = "default"
            bridge.last_action_at = {}
            bridge.action_log = Path(temp_dir) / "actions.jsonl"
            bridge.verbose = False
            bridge.dry_run = False

            bridge.run_action(
                {"event_id": "kbd:VK_C0:SC_029:N:down"},
                {"type": "preset_cycle"},
            )

        handler.assert_called_once_with()

    def test_missing_gadget_falls_back_to_raw_mapping(self) -> None:
        tap = hid_report_tap.XiaomiHidReportTap(lambda _report_id, _data: None)
        with (
            mock.patch.object(hid_report_tap.hid_tap_runtime, "gadget_archive_available", return_value=False),
            mock.patch("builtins.print"),
        ):
            hid_tap_started = tap.start()
            dependency_available = tap.dependency_available
        self.assertFalse(hid_tap_started)
        self.assertIsNone(tap.thread)
        self.assertFalse(dependency_available)
        self.assertTrue(
            xiaomi_core.should_start_raw_mapping(
                False, hid_tap_started, hid_tap_fallback_required=True
            )
        )

    def test_raw_mapping_stays_off_when_hid_tap_started(self) -> None:
        self.assertFalse(xiaomi_core.should_start_raw_mapping(True, True))

    def test_default_back_repeat_matches_approved_fast_profile(self) -> None:
        config = xiaomi_config.default_config()
        keys = xiaomi_config.default_keys_config()
        self.assertEqual(config["back_repeat_delay"], 0.28)
        self.assertEqual(config["back_repeat_interval"], 0.04)
        self.assertFalse(config["hid_tap_compatible"])
        self.assertEqual(keys["button_bindings"]["back"][0]["hold_ms"], 20)

    def test_legacy_back_repeat_defaults_migrate_without_overwriting_custom(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "xiaomi.json"
            config_path.write_text(
                json.dumps(
                    {
                        "back_repeat_delay": 0.45,
                        "back_repeat_interval": 0.10,
                    }
                ),
                encoding="utf-8",
            )
            migrated = xiaomi_config.load_config(config_path)
            self.assertEqual(migrated["back_repeat_delay"], 0.28)
            self.assertEqual(migrated["back_repeat_interval"], 0.04)

            config_path.write_text(
                json.dumps(
                    {
                        "back_repeat_delay": 0.33,
                        "back_repeat_interval": 0.055,
                    }
                ),
                encoding="utf-8",
            )
            custom = xiaomi_config.load_config(config_path)
            self.assertEqual(custom["back_repeat_delay"], 0.33)
            self.assertEqual(custom["back_repeat_interval"], 0.055)

    def test_legacy_default_backspace_binding_gains_fast_hold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            keys_path = Path(temp_dir) / "xiaomi_keys.json"
            legacy = xiaomi_config.default_keys_config()
            legacy["button_bindings"]["back"] = [
                {"type": "hotkey", "keys": ["backspace"]}
            ]
            keys_path.write_text(json.dumps(legacy), encoding="utf-8")
            migrated = xiaomi_config.load_keys_config(keys_path)
            self.assertEqual(
                migrated["button_bindings"]["back"][0]["hold_ms"], 20
            )

    def test_hid_tap_requires_real_io_before_reporting_ready(self) -> None:
        self.assertIn("setInterval(() =>", hid_report_tap.HOOK_JS)
        self.assertIn('kind: "heartbeat"', hid_report_tap.HOOK_JS)
        self.assertIn("RECONNECT_DELAY_MS", hid_report_tap.HOOK_JS)
        source = Path(hid_report_tap.__file__).read_text(encoding="utf-8")
        self.assertIn("XIAOMI HID TAP ATTACHED", source)
        self.assertIn("XIAOMI HID TAP HEALTHY", source)
        self.assertIn("io_verified=true", source)

    def test_rc003_back_ioctl_reaches_configured_mapping_and_release(self) -> None:
        hook = xiaomi_core.XiaomiSpecialKeyHook.__new__(
            xiaomi_core.XiaomiSpecialKeyHook
        )
        hook.direct_state_lock = threading.Lock()
        hook.direct_active_usages = set()
        hook.action_gate = mock.Mock()
        hook.action_gate.is_ready.return_value = True
        hook._mark_direct_signal = mock.Mock()
        hook._send_button_action = mock.Mock(return_value=True)
        hook._start_back_repeat = mock.Mock()
        hook._cancel_back_repeat = mock.Mock()
        hook._start_volume_repeat = mock.Mock()
        hook._cancel_volume_repeat = mock.Mock()

        tap = hid_report_tap.XiaomiHidReportTap(hook.handle_direct_hid_report)
        with mock.patch("builtins.print"):
            tap._handle_ioctl_output(
                b"\x01\x00\x00\xF1\x00\x00\x00\x00\x00"
            )
            tap._handle_ioctl_output(b"\x01\x00\x00" + b"\x00" * 6)

        hook._send_button_action.assert_called_once_with("back")
        hook._start_back_repeat.assert_called_once_with()
        hook._cancel_back_repeat.assert_called_once_with()
        self.assertEqual(hook.direct_active_usages, set())

    def test_special_buttons_do_not_wait_for_voice_connection(self) -> None:
        hook = xiaomi_core.XiaomiSpecialKeyHook.__new__(
            xiaomi_core.XiaomiSpecialKeyHook
        )
        hook.direct_state_lock = threading.Lock()
        hook.direct_active_usages = set()
        hook.action_gate = mock.Mock()
        hook.action_gate.is_ready.return_value = False
        hook._mark_direct_signal = mock.Mock()
        hook._send_button_action = mock.Mock(return_value=True)
        hook._start_back_repeat = mock.Mock()
        hook._cancel_back_repeat = mock.Mock()
        hook._start_volume_repeat = mock.Mock()
        hook._cancel_volume_repeat = mock.Mock()

        with mock.patch("builtins.print"):
            hook.handle_direct_hid_report(1, b"\x80\x00\x00\x00\x00\x00")
            hook.handle_direct_hid_report(1, b"\x00" * 6)
            hook.handle_direct_hid_report(1, b"\x65\x00\x00\x00\x00\x00")

        self.assertEqual(
            hook._send_button_action.call_args_list,
            [mock.call("volume_up"), mock.call("menu")],
        )
        hook._start_volume_repeat.assert_called_once_with(0x80, "volume_up")

    def test_tv_keeps_only_its_short_startup_guard(self) -> None:
        hook = xiaomi_core.XiaomiSpecialKeyHook.__new__(
            xiaomi_core.XiaomiSpecialKeyHook
        )
        hook.direct_state_lock = threading.Lock()
        hook.direct_active_usages = set()
        hook.action_gate = mock.Mock()
        hook.action_gate.is_ready.return_value = False
        hook._mark_direct_signal = mock.Mock()
        hook._send_button_action = mock.Mock(return_value=True)
        hook._start_back_repeat = mock.Mock()
        hook._cancel_back_repeat = mock.Mock()
        hook._start_volume_repeat = mock.Mock()
        hook._cancel_volume_repeat = mock.Mock()

        with mock.patch("builtins.print"):
            hook.handle_direct_hid_report(1, b"\x35\x00\x00\x00\x00\x00")

        hook._send_button_action.assert_not_called()

    def test_tv_action_gate_blocks_until_ready_delay_expires(self) -> None:
        event_id = next(iter(xiaomi_core.TV_EVENT_IDS))
        gate = xiaomi_core.XiaomiTvActionGate(ready_delay=2.0)
        with mock.patch.object(xiaomi_core.time, "monotonic", return_value=10.0):
            gate.mark_ready()
        with mock.patch.object(xiaomi_core.time, "monotonic", return_value=11.9):
            self.assertFalse(gate({"event_id": event_id}, {}))
        with mock.patch.object(xiaomi_core.time, "monotonic", return_value=12.0):
            self.assertTrue(gate({"event_id": event_id}, {}))

    def test_tv_action_gate_never_blocks_unrelated_buttons(self) -> None:
        gate = xiaomi_core.XiaomiTvActionGate(ready_delay=60.0)
        self.assertTrue(gate({"event_id": "not-the-tv-button"}, {}))

    def test_voice_pcm_stats_distinguish_empty_short_silent_and_signal(self) -> None:
        stats = xiaomi_core.VoicePcmStats()
        self.assertEqual(stats.summary()["result"], "empty")

        stats.add([500, -500] * 80)
        self.assertEqual(stats.summary()["result"], "too_short")

        stats.reset()
        for _ in range(34):
            stats.add([0] * 240)
        self.assertEqual(stats.summary()["result"], "silent")

        stats.add([1200, -1200] * 120)
        summary = stats.summary()
        self.assertEqual(summary["result"], "signal")
        self.assertEqual(summary["peak"], 1200)
        self.assertGreater(summary["rms"], 0.0)


class AudioRouterBehaviorTests(unittest.TestCase):
    def test_missing_vb_cable_returns_known_exit_code_without_traceback(self) -> None:
        error = audio_router.AudioDeviceUnavailable(
            "virtual microphone playback device not found: CABLE Input (VB-Audio Virtual Cable)"
        )
        with (
            mock.patch.object(audio_router, "AudioRouter", side_effect=error),
            mock.patch("builtins.print") as printed,
        ):
            result = audio_router.main([])
        self.assertEqual(result, audio_router.EXIT_AUDIO_DEVICE_UNAVAILABLE)
        printed.assert_called_once()
        self.assertIn("AUDIO ROUTER UNAVAILABLE", printed.call_args.args[0])

    def test_direct_pcm_telemetry_records_signal_and_resets(self) -> None:
        output = audio_router.PacketOutput.__new__(audio_router.PacketOutput)
        output._chunks = audio_router.queue.Queue(maxsize=4)
        output._current = audio_router.np.empty(0, dtype=audio_router.np.int16)
        output._offset = 0
        output.dropped = 0
        output.underflows = 0
        output._reset_packet_stats()

        payload = audio_router.np.asarray([0, 1000, -2000, 500], dtype="<i2").tobytes()
        self.assertTrue(output.put(payload))
        self.assertFalse(output.put(payload))
        stats = output.packet_stats(reset=True)
        self.assertEqual(stats["chunks"], 2)
        self.assertEqual(stats["samples"], 8)
        self.assertEqual(stats["peak"], 2000)
        self.assertEqual(stats["signal_chunks"], 2)
        self.assertGreater(stats["rms"], 0.0)
        self.assertEqual(output.packet_stats()["chunks"], 0)


class HanvonCoreBehaviorTests(unittest.TestCase):
    @staticmethod
    def _engine(config: dict | None = None):
        cfg = {
            "voice_shortcut_enabled": True,
            "voice_hotkey": "Right Alt",
            "voice_trigger_mode": "toggle",
            "refresh_mic_before_pen_hotkey": True,
        }
        if config:
            cfg.update(config)
        engine = hanvon_pen_app.BridgeEngine.__new__(hanvon_pen_app.BridgeEngine)
        engine._config = cfg
        engine._config_lock = threading.Lock()
        engine._voice_lock = threading.RLock()
        engine._audio_lock = threading.Lock()
        engine._audio_token = None
        engine._voice_active = False
        engine._shortcut_ignore_until = 0.0
        engine._voice_shortcut_down = False
        engine._held_voice_hotkey = ""
        engine._audio_router = mock.Mock()
        engine._write_voice_runtime_state = mock.Mock()
        return engine

    def test_voice_shortcut_is_not_toggled_when_audio_route_fails(self) -> None:
        engine = self._engine()
        engine._open_pen_audio = mock.Mock(return_value=False)
        with (
            mock.patch.object(hanvon_pen_app, "send_hotkey") as send_hotkey,
            mock.patch.object(hanvon_pen_app.core, "refresh_v60_mic") as refresh_mic,
            mock.patch.object(hanvon_pen_app, "app_log"),
        ):
            result = engine._handle_voice_button(
                {
                    "voice_shortcut_enabled": True,
                    "voice_hotkey": "Right Alt",
                    "voice_trigger_mode": "toggle",
                    "refresh_mic_before_pen_hotkey": True,
                }
            )

        self.assertEqual(result, "voice_start_failed:audio_unavailable")
        send_hotkey.assert_not_called()
        refresh_mic.assert_not_called()

    def test_voice_start_rolls_back_audio_if_shortcut_send_fails(self) -> None:
        engine = self._engine()
        engine._open_pen_audio = mock.Mock(return_value=True)
        engine._close_pen_audio = mock.Mock()
        with (
            mock.patch.object(
                hanvon_pen_app,
                "send_hotkey",
                side_effect=OSError("simulated SendInput failure"),
            ),
            mock.patch.object(hanvon_pen_app.core, "refresh_v60_mic"),
        ):
            with self.assertRaises(OSError):
                engine._handle_voice_button(engine.get_config())

        engine._close_pen_audio.assert_called_once_with("shortcut_start_failed")
        self.assertFalse(engine._voice_active)

    def test_pen_button_uses_locked_current_voice_state(self) -> None:
        """A pen edge must not use a stale state sampled by its caller."""
        engine = self._engine()
        engine._voice_active = True
        engine._close_pen_audio = mock.Mock()
        with mock.patch.object(hanvon_pen_app, "send_hotkey") as send_hotkey:
            result = engine._handle_voice_button(engine.get_config())

        self.assertEqual(result, "voice_stop:toggle:Right Alt")
        send_hotkey.assert_called_once_with("Right Alt")
        engine._close_pen_audio.assert_called_once_with("second_press", tail_ms=120)
        self.assertFalse(engine._voice_active)

    def test_engine_shutdown_stops_toggle_before_closing_audio(self) -> None:
        engine = self._engine()
        engine._voice_active = True
        calls: list[str] = []
        engine._close_pen_audio = lambda *_args, **_kwargs: calls.append("audio_close")
        with mock.patch.object(
            hanvon_pen_app,
            "send_hotkey",
            side_effect=lambda _hotkey: calls.append("shortcut_stop"),
        ):
            engine._close_all_audio("engine_stop")

        self.assertEqual(calls, ["shortcut_stop", "audio_close"])
        self.assertFalse(engine._voice_active)

    def test_physical_keyboard_hotkey_updates_v60_audio_state(self) -> None:
        engine = self._engine()
        engine._open_pen_audio = mock.Mock(return_value=True)
        engine._close_pen_audio = mock.Mock()
        with mock.patch.object(hanvon_pen_app.core, "refresh_v60_mic"):
            started = engine._handle_external_voice_hotkey(engine.get_config(), True)
            stopped = engine._handle_external_voice_hotkey(engine.get_config(), True)

        self.assertEqual(started, "keyboard_start")
        self.assertEqual(stopped, "keyboard_stop")
        engine._open_pen_audio.assert_called_once_with()
        engine._close_pen_audio.assert_called_once_with(
            "keyboard_stop", tail_ms=120
        )
        self.assertFalse(engine._voice_active)

    def test_injected_right_alt_is_never_counted_as_a_physical_toggle(self) -> None:
        state = PhysicalHotkeyState()
        target = (0xA5,)
        self.assertIsNone(state.feed(0xA5, True, target, injected=True))
        self.assertIsNone(state.feed(0xA5, False, target, injected=True))
        self.assertTrue(state.feed(0xA5, True, target))
        self.assertIsNone(state.feed(0xA5, True, target))
        self.assertFalse(state.feed(0xA5, False, target))

    def test_generic_alt_target_accepts_physical_right_alt(self) -> None:
        state = PhysicalHotkeyState()
        self.assertTrue(state.feed(0xA5, True, (0x12,)))
        self.assertFalse(state.feed(0xA5, False, (0x12,)))

    def test_v60_standalone_mode_uses_native_microphone_tracker(self) -> None:
        with mock.patch.dict(
            "os.environ", {"REMOTE_BRIDGE_AUDIO_TRANSPORT": "native"}
        ):
            engine = hanvon_pen_app.BridgeEngine(hanvon_pen_app.default_config())
        self.assertIsInstance(engine._audio_router, native_audio.NativeAudioSessionClient)
    def test_lost_audio_session_stops_external_toggle_and_clears_state(self) -> None:
        engine = self._engine()
        engine._audio_token = "token-1"
        engine._voice_active = True
        with mock.patch.object(hanvon_pen_app, "send_hotkey") as send_hotkey:
            reconciled = engine._reconcile_lost_audio(
                "token-1", "audio_session_lost"
            )

        self.assertTrue(reconciled)
        send_hotkey.assert_called_once_with("Right Alt")
        self.assertIsNone(engine._audio_token)
        self.assertFalse(engine._voice_active)

    def test_v60_dynamic_microphone_report_is_stable_and_well_formed(self) -> None:
        report, seed, token = hanvon_core._make_mic_dynamic_report(1_700_000_000)
        self.assertEqual(seed, 1_700_000_000)
        self.assertEqual(token, 0x6F2E0403)
        self.assertEqual(len(report), 33)
        self.assertEqual(report[:9], bytes.fromhex("000600000000020501"))
        self.assertEqual(report[9:14], bytes.fromhex("3b03042e6f"))
        self.assertEqual(report[14:], bytes(19))

    def test_v60_microphone_interface_match_is_strict(self) -> None:
        interface = {
            "vendor_id": 0x0611,
            "product_id": 0x3001,
            "interface_number": 5,
            "usage_page": 0xFF00,
        }
        self.assertTrue(hanvon_core._is_v60_mic_iface(interface))
        for key in interface:
            changed = dict(interface)
            changed[key] = 0
            self.assertFalse(hanvon_core._is_v60_mic_iface(changed), key)


class NativeAudioBehaviorTests(unittest.TestCase):
    def test_native_session_tracks_endpoint_without_opening_a_virtual_cable(self) -> None:
        client = native_audio.NativeAudioSessionClient("hanvon")
        with mock.patch.object(
            native_audio,
            "active_capture_endpoint_names",
            return_value=["麦克风 (Ai Pointer)"],
        ):
            token = client.open("Ai Pointer")
        status = client.status()
        self.assertTrue(status["sources"]["hanvon"]["native"])
        self.assertEqual(status["sources"]["hanvon"]["endpoint"], "麦克风 (Ai Pointer)")
        self.assertTrue(client.close(token)["closed"])
        self.assertEqual(client.status()["sources"], {})

    def test_native_session_rejects_a_missing_device(self) -> None:
        client = native_audio.NativeAudioSessionClient("t1")
        with (
            mock.patch.object(native_audio, "active_capture_endpoint_names", return_value=[]),
            self.assertRaises(native_audio.AudioRouterError),
        ):
            client.open("Mic Device")


if __name__ == "__main__":
    unittest.main()
