#!/usr/bin/env python3
"""Small UDP client shared by the T1 and Hanvon bridge roles."""

from __future__ import annotations

import json
import os
import socket
import uuid


ROUTER_HOST = "127.0.0.1"
PCM_PORT = int(os.environ.get("REMOTE_BRIDGE_PCM_PORT", "30680"))
CONTROL_PORT = int(os.environ.get("REMOTE_BRIDGE_AUDIO_CONTROL_PORT", "30681"))


class AudioRouterError(RuntimeError):
    pass


class AudioRouterClient:
    def __init__(
        self,
        owner: str,
        timeout: float = 0.35,
        open_timeout: float = 2.0,
        open_retry_timeout: float | None = None,
    ) -> None:
        self.owner = owner
        self.timeout = timeout
        self.open_timeout = max(float(open_timeout), float(timeout))
        self.open_retry_timeout = max(
            float(open_retry_timeout)
            if open_retry_timeout is not None
            else self.open_timeout,
            float(timeout),
        )

    def _request(self, payload: dict, *, timeout: float | None = None) -> dict:
        request_id = uuid.uuid4().hex
        message = {
            "owner": self.owner,
            "client_pid": os.getpid(),
            "request_id": request_id,
            **payload,
        }
        data = json.dumps(message, ensure_ascii=False).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            try:
                client.settimeout(self.timeout if timeout is None else float(timeout))
                client.sendto(data, (ROUTER_HOST, CONTROL_PORT))
                response, _ = client.recvfrom(4096)
            except socket.timeout as exc:
                raise AudioRouterError("音频路由未响应") from exc
            except (ConnectionResetError, OSError) as exc:
                raise AudioRouterError(f"音频路由通信失败: {exc}") from exc
        try:
            result = json.loads(response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AudioRouterError("音频路由返回了无效响应") from exc
        if result.get("request_id") != request_id:
            raise AudioRouterError("音频路由响应与请求不匹配")
        if not result.get("ok"):
            raise AudioRouterError(str(result.get("error") or "音频路由操作失败"))
        return result

    def open(
        self,
        device: str,
        token: str | None = None,
        max_session_ms: int = 0,
    ) -> str:
        session_token = token or uuid.uuid4().hex
        request = {
            "op": "open",
            "device": device,
            "token": session_token,
            "max_session_ms": max(0, min(int(max_session_ms), 86_400_000)),
        }
        last_error: AudioRouterError | None = None
        # OPEN can legitimately take over a second while Windows wakes the USB
        # microphone. Retry with the same token so a late first OPEN is reused,
        # never duplicated.
        for attempt_timeout in (self.open_timeout, self.open_retry_timeout):
            try:
                self._request(request, timeout=attempt_timeout)
                return session_token
            except AudioRouterError as exc:
                last_error = exc
        # A reply may have been lost after the router opened the source. Revoke
        # every session owned by this client before reporting failure.
        try:
            self.close_owner(timeout=max(1.0, min(self.open_retry_timeout, 2.0)))
        except AudioRouterError:
            pass
        raise last_error or AudioRouterError("音频路由打开失败")

    def close(self, token: str, tail_ms: int = 0) -> dict:
        result = self._request(
            {
                "op": "close",
                "token": token,
                "tail_ms": max(0, min(int(tail_ms), 1000)),
            }
        )
        return result

    def close_owner(self, *, timeout: float | None = None) -> dict:
        return self._request({"op": "close_owner"}, timeout=timeout)

    def status(self) -> dict:
        return self._request({"op": "status"})
