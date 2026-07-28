#!/usr/bin/env python3
"""Central VB-CABLE mixer with on-demand physical microphone capture.

The output side stays ready so Xiaomi PCM can arrive immediately. Physical
microphone InputStreams only exist between an OPEN and matching CLOSE command.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import queue
import select
import socket
import threading
import time

import numpy as np
import sounddevice as sd


DEFAULT_OUTPUT_NAME = "CABLE Input (VB-Audio Virtual Cable)"
DEFAULT_PCM_PORT = int(os.environ.get("REMOTE_BRIDGE_PCM_PORT", "30680"))
DEFAULT_CONTROL_PORT = int(os.environ.get("REMOTE_BRIDGE_AUDIO_CONTROL_PORT", "30681"))
EXIT_AUDIO_DEVICE_UNAVAILABLE = 20


class AudioDeviceUnavailable(RuntimeError):
    """The Windows audio endpoint required for voice routing is unavailable."""


def ignore_windows_udp_connreset(endpoint: socket.socket) -> None:
    """Keep UDP alive when a timed-out client closes before our late reply."""
    if os.name != "nt" or not hasattr(socket, "SIO_UDP_CONNRESET"):
        return
    try:
        endpoint.ioctl(socket.SIO_UDP_CONNRESET, False)
    except OSError:
        pass


def find_output_device(name: str) -> int:
    return find_device(name, input_device=False)


def find_input_device(name: str) -> int:
    return find_device(name, input_device=True)


def find_device(name: str, input_device: bool) -> int:
    exact: list[int] = []
    partial: list[int] = []
    needle = name.casefold()
    try:
        devices = sd.query_devices()
    except Exception as exc:
        raise AudioDeviceUnavailable(f"无法读取 Windows 音频设备：{exc}") from None
    for index, item in enumerate(devices):
        channels = int(item["max_input_channels" if input_device else "max_output_channels"])
        if channels < 1:
            continue
        candidate = str(item["name"])
        if input_device and "cable output" in candidate.casefold():
            continue
        if candidate.casefold() == needle:
            exact.append(index)
        elif needle in candidate.casefold():
            partial.append(index)
    matches = exact or partial
    if not matches:
        kind = "microphone" if input_device else "virtual microphone playback device"
        raise AudioDeviceUnavailable(f"{kind} not found: {name}")
    for preferred_api in (
        "Windows WASAPI",
        "Windows WDM-KS",
        "Windows DirectSound",
        "MME",
    ):
        for index in matches:
            hostapi = sd.query_hostapis(sd.query_devices(index)["hostapi"])["name"]
            if hostapi == preferred_api:
                return index
    return matches[0]


def process_is_alive(pid: int) -> bool:
    if not pid:
        return True
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    query_limited_information = 0x1000
    still_active = 259
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.restype = ctypes.c_void_p
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if not handle:
        return False
    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


class MicrophoneSource:
    def __init__(self, input_device: int, label: str) -> None:
        self.input_device = input_device
        self.label = label
        self.frames = 0
        self.status_events = 0
        self.peak = 0.0
        self.current_peak = 0.0
        self.signal_seen = False
        self.last_signal_at: float | None = None
        self.dropped = 0
        self._chunks: queue.Queue[np.ndarray] = queue.Queue(maxsize=160)
        self._current = np.empty(0, dtype=np.int16)
        self._offset = 0
        sd.check_input_settings(
            device=input_device, channels=1, dtype="int16", samplerate=48000
        )
        self.stream = sd.InputStream(
            samplerate=48000,
            blocksize=0,
            device=input_device,
            channels=1,
            dtype="int16",
            latency="low",
            callback=self._callback,
        )

    def _callback(self, indata, frames, _time_info, status) -> None:
        if status:
            self.status_events += 1
        self.frames += frames
        if not indata.size:
            return
        chunk = indata[:, 0].copy()
        self.current_peak = float(np.max(np.abs(chunk.astype(np.int32)))) / 32768.0
        self.peak = max(self.peak, self.current_peak)
        if self.current_peak >= 0.001:
            self.signal_seen = True
            self.last_signal_at = time.monotonic()
        try:
            self._chunks.put_nowait(chunk)
        except queue.Full:
            self.dropped += 1
            try:
                self._chunks.get_nowait()
                self._chunks.put_nowait(chunk)
            except (queue.Empty, queue.Full):
                pass

    def pull(self, frames: int) -> np.ndarray:
        result = np.zeros(frames, dtype=np.int16)
        written = 0
        while written < frames:
            if self._offset >= self._current.size:
                try:
                    self._current = self._chunks.get_nowait()
                    self._offset = 0
                except queue.Empty:
                    break
            available = self._current.size - self._offset
            take = min(frames - written, available)
            result[written : written + take] = self._current[
                self._offset : self._offset + take
            ]
            self._offset += take
            written += take
        return result

    def start(self) -> None:
        self.stream.start()

    def close(self) -> None:
        try:
            self.stream.stop()
        finally:
            self.stream.close()

    def stats(self) -> dict:
        silence_ms = None
        if self.last_signal_at is not None:
            silence_ms = max(0.0, (time.monotonic() - self.last_signal_at) * 1000.0)
        return {
            "frames": self.frames,
            "peak": self.peak,
            "current_peak": self.current_peak,
            "signal_seen": self.signal_seen,
            "silence_ms": silence_ms,
        }


class PacketOutput:
    def __init__(self, device: int) -> None:
        self._chunks: queue.Queue[np.ndarray] = queue.Queue(maxsize=160)
        self._current = np.empty(0, dtype=np.int16)
        self._offset = 0
        self._sources: dict[str, MicrophoneSource] = {}
        self._sources_lock = threading.Lock()
        self.dropped = 0
        self.underflows = 0
        self._reset_packet_stats()
        self.stream = sd.OutputStream(
            samplerate=48000,
            blocksize=0,
            device=device,
            channels=1,
            dtype="int16",
            latency="low",
            callback=self._callback,
        )

    def start(self) -> None:
        self.stream.start()

    def close(self) -> None:
        try:
            self.stream.stop()
        finally:
            self.stream.close()

    def _reset_packet_stats(self) -> None:
        self.packet_chunks = 0
        self.packet_samples = 0
        self.packet_peak = 0
        self.packet_signal_chunks = 0
        self.packet_sum_squares = 0.0
        self.packet_started_at: float | None = None
        self.packet_last_at: float | None = None
        self._packet_dropped_start = self.dropped
        self._packet_underflows_start = self.underflows

    def packet_stats(self, reset: bool = False) -> dict:
        rms = (
            (self.packet_sum_squares / self.packet_samples) ** 0.5
            if self.packet_samples
            else 0.0
        )
        wall_ms = (
            max(0.0, ((self.packet_last_at or time.monotonic()) - self.packet_started_at) * 1000.0)
            if self.packet_started_at is not None
            else 0.0
        )
        result = {
            "chunks": self.packet_chunks,
            "samples": self.packet_samples,
            "audio_ms": self.packet_samples * 1000.0 / 48000.0,
            "wall_ms": wall_ms,
            "peak": self.packet_peak,
            "rms": rms,
            "signal_chunks": self.packet_signal_chunks,
            "dropped": self.dropped - self._packet_dropped_start,
            "underflows": self.underflows - self._packet_underflows_start,
        }
        if reset:
            self._reset_packet_stats()
        return result

    def put(self, payload: bytes) -> bool:
        if not payload or len(payload) % 2:
            return False
        samples = np.frombuffer(payload, dtype="<i2").copy()
        first_chunk = self.packet_chunks == 0
        now = time.monotonic()
        if first_chunk:
            self.packet_started_at = now
        self.packet_last_at = now
        pcm32 = samples.astype(np.int32)
        peak = int(np.max(np.abs(pcm32))) if pcm32.size else 0
        pcm64 = pcm32.astype(np.float64)
        self.packet_chunks += 1
        self.packet_samples += int(samples.size)
        self.packet_peak = max(self.packet_peak, peak)
        self.packet_sum_squares += float(np.dot(pcm64, pcm64))
        if peak >= 33:
            self.packet_signal_chunks += 1
        try:
            self._chunks.put_nowait(samples)
        except queue.Full:
            self.dropped += 1
            try:
                self._chunks.get_nowait()
                self._chunks.put_nowait(samples)
            except (queue.Empty, queue.Full):
                pass
        return first_chunk

    def clear(self) -> None:
        self._current = np.empty(0, dtype=np.int16)
        self._offset = 0
        try:
            while True:
                self._chunks.get_nowait()
        except queue.Empty:
            pass

    def set_source(self, owner: str, source: MicrophoneSource) -> None:
        with self._sources_lock:
            self._sources[owner] = source

    def remove_source(self, owner: str) -> MicrophoneSource | None:
        with self._sources_lock:
            return self._sources.pop(owner, None)

    def source_stats(self, owner: str) -> dict:
        with self._sources_lock:
            source = self._sources.get(owner)
        return source.stats() if source is not None else {}

    def _callback(self, outdata, frames, _time_info, status) -> None:
        mixed = np.zeros(frames, dtype=np.int32)
        if status.output_underflow:
            self.underflows += 1
        written = 0
        while written < frames:
            if self._offset >= self._current.size:
                try:
                    self._current = self._chunks.get_nowait()
                    self._offset = 0
                except queue.Empty:
                    break
            available = self._current.size - self._offset
            take = min(frames - written, available)
            mixed[written : written + take] += self._current[
                self._offset : self._offset + take
            ].astype(np.int32)
            self._offset += take
            written += take
        with self._sources_lock:
            sources = tuple(self._sources.values())
        for source in sources:
            mixed += source.pull(frames).astype(np.int32)
        outdata[:, 0] = np.clip(mixed, -32768, 32767).astype(np.int16)


class AudioRouter:
    def __init__(self, output_name: str, pcm_port: int, control_port: int, parent_pid: int) -> None:
        device = find_output_device(output_name)
        sd.check_output_settings(
            device=device, channels=1, dtype="int16", samplerate=48000
        )
        self.output = PacketOutput(device)
        self.endpoint = str(sd.query_devices(device)["name"])
        self.parent_pid = parent_pid
        self.sessions: dict[str, dict] = {}
        self.pcm = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ignore_windows_udp_connreset(self.pcm)
        self.pcm.bind(("127.0.0.1", pcm_port))
        self.control = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ignore_windows_udp_connreset(self.control)
        self.control.bind(("127.0.0.1", control_port))
        self.pcm_peer: tuple[str, int] | None = None

    def _finish_pcm_session(self, reason: str) -> None:
        stats = self.output.packet_stats(reset=True)
        if not stats["chunks"]:
            self.pcm_peer = None
            return
        peer = (
            f"{self.pcm_peer[0]}:{self.pcm_peer[1]}"
            if self.pcm_peer is not None
            else "?"
        )
        print(
            f"PCM SESSION CLOSED reason={reason} peer={peer} "
            f"chunks={stats['chunks']} samples={stats['samples']} "
            f"audio_ms={stats['audio_ms']:.0f} wall_ms={stats['wall_ms']:.0f} "
            f"peak={stats['peak']} rms={stats['rms']:.1f} "
            f"signal_chunks={stats['signal_chunks']} dropped={stats['dropped']} "
            f"underflows={stats['underflows']}",
            flush=True,
        )
        self.pcm_peer = None

    def _reply(self, peer, payload: dict) -> None:
        try:
            self.control.sendto(
                json.dumps(payload, ensure_ascii=False).encode("utf-8"), peer
            )
        except OSError:
            pass

    def _close_owner(self, owner: str, reason: str) -> bool:
        session = self.sessions.pop(owner, None)
        source = self.output.remove_source(owner)
        if source is None:
            return False
        try:
            source.close()
        except Exception as exc:
            print(f"SOURCE CLOSE WARNING owner={owner} error={exc}", flush=True)
        print(
            f"SOURCE CLOSED owner={owner} device={session.get('device') if session else '?'} "
            f"reason={reason} frames={source.frames} peak={source.peak:.6f}",
            flush=True,
        )
        return True

    def _open_source(self, request: dict) -> dict:
        owner = str(request.get("owner") or "").strip()
        device_name = str(request.get("device") or "").strip()
        token = str(request.get("token") or "").strip()
        client_pid = int(request.get("client_pid") or 0)
        max_session_ms = max(
            0,
            min(int(request.get("max_session_ms") or 0), 86_400_000),
        )
        if not owner or not device_name or not token or client_pid <= 0:
            raise ValueError("open requires owner, device, token and client_pid")
        existing = self.sessions.get(owner)
        if existing and existing.get("token") == token:
            existing["close_at"] = None
            existing["expires_at"] = (
                existing["opened_at"] + max_session_ms / 1000.0
                if max_session_ms
                else None
            )
            return {"reused": True, "device": existing["device"]}
        if existing:
            self._close_owner(owner, "replaced")
        started = time.perf_counter()
        input_device = find_input_device(device_name)
        source = MicrophoneSource(input_device, device_name)
        source.start()
        self.output.set_source(owner, source)
        opened_at = time.monotonic()
        self.sessions[owner] = {
            "device": device_name,
            "token": token,
            "client_pid": client_pid,
            "opened_at": opened_at,
            "close_at": None,
            "expires_at": (
                opened_at + max_session_ms / 1000.0 if max_session_ms else None
            ),
        }
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        print(
            f"SOURCE OPEN owner={owner} device={device_name} pid={client_pid} "
            f"elapsed_ms={elapsed_ms:.1f}",
            flush=True,
        )
        return {"reused": False, "device": device_name, "elapsed_ms": elapsed_ms}

    def _handle_control(self, payload: bytes, peer) -> None:
        request_id = None
        try:
            request = json.loads(payload.decode("utf-8"))
            request_id = request.get("request_id")
            op = str(request.get("op") or "")
            if op == "open":
                details = self._open_source(request)
            elif op == "close":
                owner = str(request.get("owner") or "")
                token = str(request.get("token") or "")
                session = self.sessions.get(owner)
                if session and session.get("token") == token:
                    tail_ms = max(0, min(int(request.get("tail_ms") or 0), 1000))
                    if tail_ms:
                        session["close_at"] = time.monotonic() + tail_ms / 1000.0
                        details = {"scheduled": True, "tail_ms": tail_ms}
                    else:
                        details = {"closed": self._close_owner(owner, "client")}
                else:
                    details = {"closed": False, "stale": True}
            elif op == "close_owner":
                owner = str(request.get("owner") or "")
                details = {"closed": self._close_owner(owner, "client_owner")}
            elif op == "status":
                details = {
                    "output": self.endpoint,
                    "sources": {
                        owner: {
                            "device": session["device"],
                            "client_pid": session["client_pid"],
                            "opened_ms": int(
                                (time.monotonic() - session["opened_at"]) * 1000
                            ),
                            "expires_in_ms": (
                                max(
                                    0,
                                    int(
                                        (session["expires_at"] - time.monotonic())
                                        * 1000
                                    ),
                                )
                                if session.get("expires_at") is not None
                                else None
                            ),
                            **self.output.source_stats(owner),
                        }
                        for owner, session in self.sessions.items()
                    },
                }
            else:
                raise ValueError(f"unsupported operation: {op}")
            self._reply(peer, {"ok": True, "request_id": request_id, **details})
        except Exception as exc:
            print(f"CONTROL ERROR {type(exc).__name__}: {exc}", flush=True)
            self._reply(
                peer,
                {"ok": False, "request_id": request_id, "error": str(exc)},
            )

    def _expire_sessions(self) -> None:
        now = time.monotonic()
        for owner, session in tuple(self.sessions.items()):
            close_at = session.get("close_at")
            expires_at = session.get("expires_at")
            if close_at is not None and now >= close_at:
                self._close_owner(owner, "tail_elapsed")
            elif expires_at is not None and now >= expires_at:
                self._close_owner(owner, "max_session_elapsed")
            elif not process_is_alive(int(session.get("client_pid") or 0)):
                self._close_owner(owner, "client_exited")

    def run(self) -> int:
        self.output.start()
        print(
            f"AUDIO ROUTER READY pcm={self.pcm.getsockname()[1]} "
            f"control={self.control.getsockname()[1]} output={self.endpoint}",
            flush=True,
        )
        last_parent_check = time.monotonic()
        try:
            while True:
                readable, _, _ = select.select((self.pcm, self.control), (), (), 0.05)
                for endpoint in readable:
                    try:
                        payload, peer = endpoint.recvfrom(65535)
                    except ConnectionResetError as exc:
                        print(f"UDP CLIENT RESET ignored: {exc}", flush=True)
                        continue
                    except OSError as exc:
                        if getattr(exc, "winerror", None) == 10054:
                            print(f"UDP CLIENT RESET ignored: {exc}", flush=True)
                            continue
                        raise
                    if endpoint is self.control:
                        self._handle_control(payload, peer)
                    elif payload == b"PING":
                        self.pcm.sendto(b"PONG", peer)
                    elif payload == b"CLEAR":
                        self._finish_pcm_session("clear")
                        self.output.clear()
                    elif payload == b"END":
                        self._finish_pcm_session("client_end")
                    elif payload not in {b"STOP", b""}:
                        first_chunk = self.output.put(payload)
                        if first_chunk:
                            self.pcm_peer = peer
                            print(
                                f"PCM SESSION OPEN peer={peer[0]}:{peer[1]}",
                                flush=True,
                            )
                        stats = self.output.packet_stats()
                        if stats["chunks"] in (1, 10) or stats["chunks"] % 200 == 0:
                            print(
                                f"PCM AUDIO chunks={stats['chunks']} "
                                f"audio_ms={stats['audio_ms']:.0f} peak={stats['peak']} "
                                f"rms={stats['rms']:.1f} dropped={stats['dropped']}",
                                flush=True,
                            )
                self._expire_sessions()
                now = time.monotonic()
                if now - last_parent_check >= 1.0:
                    last_parent_check = now
                    if self.parent_pid and not process_is_alive(self.parent_pid):
                        print("AUDIO ROUTER parent exited", flush=True)
                        return 0
        finally:
            for owner in tuple(self.sessions):
                self._close_owner(owner, "router_exit")
            self._finish_pcm_session("router_exit")
            self.output.close()
            self.pcm.close()
            self.control.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-device", default=DEFAULT_OUTPUT_NAME)
    parser.add_argument("--pcm-port", type=int, default=DEFAULT_PCM_PORT)
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT)
    parser.add_argument("--parent-pid", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        router = AudioRouter(
            args.output_device,
            args.pcm_port,
            args.control_port,
            args.parent_pid,
        )
    except AudioDeviceUnavailable as exc:
        print(f"AUDIO ROUTER UNAVAILABLE: {exc}", flush=True)
        return EXIT_AUDIO_DEVICE_UNAVAILABLE
    return router.run()


if __name__ == "__main__":
    raise SystemExit(main())
