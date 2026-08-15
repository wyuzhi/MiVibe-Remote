from __future__ import annotations

import base64
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "source"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from standalone.windows_update import (
    MainThreadShutdownBridge,
    UPDATE_CHECK_INTERVAL_SECONDS,
    UpdateConfig,
    WinSparkleUpdater,
    load_update_config,
)


PUBLIC_KEY = base64.b64encode(bytes(range(32))).decode("ascii")


class WindowsUpdateTests(unittest.TestCase):
    def test_native_shutdown_request_is_dispatched_on_the_main_thread(self) -> None:
        logger = mock.Mock()
        bridge = MainThreadShutdownBridge(logger, timeout=1.0)
        main_thread = threading.get_ident()
        callback_threads: list[int] = []
        producer = threading.Thread(target=bridge.request_and_wait)

        producer.start()
        callback_completed = threading.Event()

        def finish_shutdown(completion: threading.Event) -> None:
            callback_threads.append(threading.get_ident())
            callback_completed.set()
            completion.set()

        self.assertTrue(bridge.dispatch_one(finish_shutdown))
        producer.join(timeout=1.0)

        self.assertFalse(producer.is_alive())
        self.assertTrue(callback_completed.is_set())
        self.assertEqual(callback_threads, [main_thread])
        self.assertFalse(bridge.dispatch_one(finish_shutdown))
        logger.assert_not_called()

    def test_valid_https_update_configuration_is_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "update_config.json"
            path.write_text(
                json.dumps(
                    {
                        "appcast_url": "https://updates.example.test/windows-appcast.xml",
                        "ed25519_public_key": PUBLIC_KEY,
                        "automatic_check_interval": 120,
                    }
                ),
                encoding="utf-8",
            )
            config = load_update_config(path)

        self.assertTrue(config.enabled)
        self.assertEqual(config.automatic_check_interval, 3600)

    def test_missing_or_untrusted_configuration_disables_updates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = load_update_config(Path(temp_dir) / "missing.json")
            self.assertFalse(missing.enabled)
            self.assertIn("未配置", missing.disabled_reason)

            path = Path(temp_dir) / "update_config.json"
            path.write_text(
                json.dumps(
                    {
                        "appcast_url": "http://updates.example.test/appcast.xml",
                        "ed25519_public_key": PUBLIC_KEY,
                    }
                ),
                encoding="utf-8",
            )
            insecure = load_update_config(path)

        self.assertFalse(insecure.enabled)
        self.assertIn("HTTPS", insecure.disabled_reason)

    def test_update_url_cannot_embed_a_download_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "update_config.json"
            path.write_text(
                json.dumps(
                    {
                        "appcast_url": (
                            "https://member-token@updates.example.test/"
                            "windows-appcast.xml?token=secret"
                        ),
                        "ed25519_public_key": PUBLIC_KEY,
                    }
                ),
                encoding="utf-8",
            )
            config = load_update_config(path)

        self.assertFalse(config.enabled)
        self.assertIn("凭证", config.disabled_reason)

    def test_winsparkle_is_configured_for_daily_signed_checks(self) -> None:
        config = UpdateConfig(
            "https://updates.example.test/windows-appcast.xml",
            PUBLIC_KEY,
            UPDATE_CHECK_INTERVAL_SECONDS,
        )
        dll = mock.MagicMock()
        dll.win_sparkle_set_eddsa_public_key.return_value = 1
        logger = mock.Mock()
        shutdown = mock.Mock()
        can_shutdown = mock.Mock(return_value=True)
        loader = mock.Mock(return_value=dll)
        updater = WinSparkleUpdater(
            "MiVibe Remote",
            "1.2.3",
            logger,
            shutdown,
            can_shutdown,
            config=config,
            dll_path=Path("WinSparkle.dll"),
            dll_loader=loader,
        )

        self.assertTrue(updater.initialize())
        loader.assert_called_once_with("WinSparkle.dll")
        dll.win_sparkle_set_app_details.assert_called_once_with(
            "MiVibe", "MiVibe Remote", "1.2.3"
        )
        dll.win_sparkle_set_appcast_url.assert_called_once_with(
            b"https://updates.example.test/windows-appcast.xml"
        )
        dll.win_sparkle_set_eddsa_public_key.assert_called_once_with(
            PUBLIC_KEY.encode("ascii")
        )
        dll.win_sparkle_set_automatic_check_for_updates.assert_called_once_with(1)
        dll.win_sparkle_set_update_check_interval.assert_called_once_with(
            UPDATE_CHECK_INTERVAL_SECONDS
        )
        dll.win_sparkle_init.assert_called_once_with()

        can_shutdown_callback = (
            dll.win_sparkle_set_can_shutdown_callback.call_args.args[0]
        )
        self.assertEqual(can_shutdown_callback(), 1)
        can_shutdown.assert_called_once_with()

        self.assertTrue(updater.check_with_ui())
        dll.win_sparkle_check_update_with_ui.assert_called_once_with()

        callback = dll.win_sparkle_set_shutdown_request_callback.call_args.args[0]
        callback()
        shutdown.assert_called_once_with()

        updater.cleanup()
        dll.win_sparkle_cleanup.assert_called_once_with()

    def test_update_install_waits_when_the_host_cannot_safely_exit(self) -> None:
        config = UpdateConfig(
            "https://updates.example.test/windows-appcast.xml",
            PUBLIC_KEY,
        )
        dll = mock.MagicMock()
        dll.win_sparkle_set_eddsa_public_key.return_value = 1
        updater = WinSparkleUpdater(
            "MiVibe Remote",
            "1.2.3",
            mock.Mock(),
            mock.Mock(),
            mock.Mock(return_value=False),
            config=config,
            dll_path=Path("WinSparkle.dll"),
            dll_loader=mock.Mock(return_value=dll),
        )

        self.assertTrue(updater.initialize())
        callback = dll.win_sparkle_set_can_shutdown_callback.call_args.args[0]
        self.assertEqual(callback(), 0)

    def test_rejected_public_key_never_starts_updater(self) -> None:
        config = UpdateConfig(
            "https://updates.example.test/windows-appcast.xml",
            PUBLIC_KEY,
        )
        dll = mock.MagicMock()
        dll.win_sparkle_set_eddsa_public_key.return_value = 0
        updater = WinSparkleUpdater(
            "MiVibe Remote",
            "1.2.3",
            mock.Mock(),
            mock.Mock(),
            config=config,
            dll_path=Path("WinSparkle.dll"),
            dll_loader=mock.Mock(return_value=dll),
        )

        self.assertFalse(updater.initialize())
        self.assertFalse(updater.initialized)
        dll.win_sparkle_init.assert_not_called()


if __name__ == "__main__":
    unittest.main()
