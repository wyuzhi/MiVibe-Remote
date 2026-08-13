"""WinSparkle integration for the standalone Windows application.

Only the public update verification key and HTTPS appcast URL are packaged in
the application.  Update signing keys and download credentials must never be
written to this module or its generated configuration file.
"""

from __future__ import annotations

import base64
import ctypes
from dataclasses import dataclass
import json
import os
from pathlib import Path
import queue
import sys
import threading
from typing import Callable
from urllib.parse import urlparse


UPDATE_CHECK_INTERVAL_SECONDS = 24 * 60 * 60


class MainThreadShutdownBridge:
    """Hand a native updater shutdown request to the application's UI thread."""

    def __init__(self, logger: Callable[[str], None], timeout: float = 15.0) -> None:
        self.logger = logger
        self.timeout = timeout
        self._requests: queue.SimpleQueue[threading.Event] = queue.SimpleQueue()

    def request_and_wait(self) -> None:
        completed = threading.Event()
        self._requests.put(completed)
        if not completed.wait(timeout=self.timeout):
            self.logger(
                "online update shutdown timed out; "
                "installer will use its process fallback"
            )

    def dispatch_one(self, callback: Callable[[threading.Event], None]) -> bool:
        try:
            completion = self._requests.get_nowait()
        except queue.Empty:
            return False
        callback(completion)
        return True


@dataclass(frozen=True)
class UpdateConfig:
    appcast_url: str = ""
    ed25519_public_key: str = ""
    automatic_check_interval: int = UPDATE_CHECK_INTERVAL_SECONDS
    disabled_reason: str = ""

    @property
    def enabled(self) -> bool:
        return bool(
            self.appcast_url
            and self.ed25519_public_key
            and not self.disabled_reason
        )


def bundled_resource_root() -> Path:
    """Return PyInstaller's data root, or a useful source-tree fallback."""

    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[1]


def _validated_config(payload: object) -> UpdateConfig:
    if not isinstance(payload, dict):
        return UpdateConfig(disabled_reason="更新配置格式无效")

    appcast_url = str(payload.get("appcast_url", "")).strip()
    public_key = str(payload.get("ed25519_public_key", "")).strip()
    if not appcast_url and not public_key:
        return UpdateConfig(disabled_reason="当前安装包未配置在线更新服务")
    if not appcast_url or not public_key:
        return UpdateConfig(disabled_reason="在线更新配置不完整")

    parsed_url = urlparse(appcast_url)
    if parsed_url.scheme.lower() != "https" or not parsed_url.netloc:
        return UpdateConfig(disabled_reason="更新地址不是有效的 HTTPS 地址")
    if (
        parsed_url.username
        or parsed_url.password
        or parsed_url.query
        or parsed_url.fragment
    ):
        return UpdateConfig(disabled_reason="更新地址不得包含凭证、查询参数或片段")
    try:
        decoded_key = base64.b64decode(public_key, validate=True)
    except (ValueError, TypeError):
        return UpdateConfig(disabled_reason="更新签名公钥格式无效")
    if len(decoded_key) != 32:
        return UpdateConfig(disabled_reason="更新签名公钥长度无效")

    try:
        interval = int(
            payload.get(
                "automatic_check_interval",
                UPDATE_CHECK_INTERVAL_SECONDS,
            )
        )
    except (TypeError, ValueError):
        interval = UPDATE_CHECK_INTERVAL_SECONDS
    interval = max(3600, interval)
    return UpdateConfig(appcast_url, public_key, interval)


def load_update_config(path: Path | None = None) -> UpdateConfig:
    config_path = path or bundled_resource_root() / "update" / "update_config.json"
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return UpdateConfig(disabled_reason="当前安装包未配置在线更新服务")
    except (OSError, UnicodeError, json.JSONDecodeError):
        return UpdateConfig(disabled_reason="无法读取在线更新配置")
    return _validated_config(payload)


class WinSparkleUpdater:
    """Small lifecycle-safe wrapper around WinSparkle's C API."""

    def __init__(
        self,
        app_name: str,
        app_version: str,
        logger: Callable[[str], None],
        request_shutdown: Callable[[], None],
        can_shutdown: Callable[[], bool] | None = None,
        *,
        config: UpdateConfig | None = None,
        dll_path: Path | None = None,
        dll_loader: Callable[[str], object] | None = None,
    ) -> None:
        self.app_name = app_name
        self.app_version = app_version
        self.logger = logger
        self.request_shutdown = request_shutdown
        self.can_shutdown = can_shutdown or (lambda: True)
        self.config = config or load_update_config()
        self.dll_path = dll_path or bundled_resource_root() / "WinSparkle.dll"
        self.dll_loader = dll_loader
        self.dll: object | None = None
        self.initialized = False
        self.disabled_reason = self.config.disabled_reason
        self._can_shutdown_callback: object | None = None
        self._shutdown_request_callback: object | None = None

    @property
    def available(self) -> bool:
        return self.config.enabled and not self.disabled_reason

    def _load_dll(self) -> object:
        if self.dll_loader is not None:
            return self.dll_loader(str(self.dll_path))
        if os.name != "nt":
            raise OSError("WinSparkle is only available on Windows")
        # WinSparkle's public API uses the C calling convention.
        return ctypes.CDLL(str(self.dll_path))

    @staticmethod
    def _configure_api(dll: object) -> None:
        dll.win_sparkle_set_app_details.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
        ]
        dll.win_sparkle_set_app_details.restype = None
        dll.win_sparkle_set_appcast_url.argtypes = [ctypes.c_char_p]
        dll.win_sparkle_set_appcast_url.restype = None
        dll.win_sparkle_set_eddsa_public_key.argtypes = [ctypes.c_char_p]
        dll.win_sparkle_set_eddsa_public_key.restype = ctypes.c_int
        dll.win_sparkle_set_registry_path.argtypes = [ctypes.c_char_p]
        dll.win_sparkle_set_registry_path.restype = None
        dll.win_sparkle_set_automatic_check_for_updates.argtypes = [ctypes.c_int]
        dll.win_sparkle_set_automatic_check_for_updates.restype = None
        dll.win_sparkle_set_update_check_interval.argtypes = [ctypes.c_int]
        dll.win_sparkle_set_update_check_interval.restype = None
        dll.win_sparkle_init.argtypes = []
        dll.win_sparkle_init.restype = None
        dll.win_sparkle_cleanup.argtypes = []
        dll.win_sparkle_cleanup.restype = None
        dll.win_sparkle_check_update_with_ui.argtypes = []
        dll.win_sparkle_check_update_with_ui.restype = None

    def initialize(self) -> bool:
        if self.initialized:
            return True
        if not self.config.enabled:
            self.disabled_reason = self.config.disabled_reason
            self.logger(f"online updates disabled: {self.disabled_reason}")
            return False
        if not self.dll_path.is_file() and self.dll_loader is None:
            self.disabled_reason = "安装包缺少 WinSparkle 更新组件"
            self.logger(f"online updates disabled: missing {self.dll_path}")
            return False

        try:
            dll = self._load_dll()
            self._configure_api(dll)
            can_shutdown_type = ctypes.CFUNCTYPE(ctypes.c_int)
            shutdown_request_type = ctypes.CFUNCTYPE(None)

            @can_shutdown_type
            def can_shutdown() -> int:
                try:
                    return int(bool(self.can_shutdown()))
                except Exception as exc:
                    self.logger(
                        "online update shutdown check failed: "
                        f"{type(exc).__name__}: {exc}"
                    )
                    return 0

            @shutdown_request_type
            def shutdown_request() -> None:
                try:
                    self.request_shutdown()
                except Exception as exc:
                    # Exceptions must never escape a ctypes callback into native code.
                    self.logger(
                        "online update shutdown request failed: "
                        f"{type(exc).__name__}: {exc}"
                    )

            self._can_shutdown_callback = can_shutdown
            self._shutdown_request_callback = shutdown_request
            dll.win_sparkle_set_can_shutdown_callback.argtypes = [
                can_shutdown_type
            ]
            dll.win_sparkle_set_can_shutdown_callback.restype = None
            dll.win_sparkle_set_shutdown_request_callback.argtypes = [
                shutdown_request_type
            ]
            dll.win_sparkle_set_shutdown_request_callback.restype = None
            dll.win_sparkle_set_app_details(
                "MiVibe",
                self.app_name,
                self.app_version,
            )
            dll.win_sparkle_set_registry_path(
                b"Software\\MiVibe\\MiVibe Remote\\Updates"
            )
            dll.win_sparkle_set_appcast_url(
                self.config.appcast_url.encode("utf-8")
            )
            key_result = dll.win_sparkle_set_eddsa_public_key(
                self.config.ed25519_public_key.encode("ascii")
            )
            if key_result != 1:
                raise ValueError("WinSparkle rejected the Ed25519 public key")
            dll.win_sparkle_set_automatic_check_for_updates(1)
            dll.win_sparkle_set_update_check_interval(
                self.config.automatic_check_interval
            )
            dll.win_sparkle_set_can_shutdown_callback(can_shutdown)
            dll.win_sparkle_set_shutdown_request_callback(shutdown_request)
            dll.win_sparkle_init()
            self.dll = dll
            self.initialized = True
            self.disabled_reason = ""
            self.logger(
                "online updates initialized "
                f"interval={self.config.automatic_check_interval}s"
            )
            return True
        except Exception as exc:
            self.dll = None
            self.disabled_reason = "在线更新组件初始化失败"
            self.logger(
                "online update initialization failed: "
                f"{type(exc).__name__}: {exc}"
            )
            return False

    def check_with_ui(self) -> bool:
        if not self.initialized or self.dll is None:
            return False
        try:
            self.dll.win_sparkle_check_update_with_ui()
            return True
        except Exception as exc:
            self.logger(
                f"manual update check failed: {type(exc).__name__}: {exc}"
            )
            return False

    def cleanup(self) -> None:
        if not self.initialized or self.dll is None:
            return
        dll = self.dll
        self.initialized = False
        self.dll = None
        try:
            dll.win_sparkle_cleanup()
        except Exception as exc:
            self.logger(f"online update cleanup failed: {type(exc).__name__}: {exc}")
        finally:
            self._can_shutdown_callback = None
            self._shutdown_request_callback = None
