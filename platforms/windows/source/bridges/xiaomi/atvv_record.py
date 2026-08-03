#!/usr/bin/env python3
"""Record the Xiaomi MI RC microphone through Google ATVV on Windows.

The remote is a BLE HID device, but its microphone is not a Windows audio
endpoint. Audio is delivered as IMA/DVI ADPCM notifications on the Android TV
Voice-over-BLE GATT service. This probe performs the host handshake, responds
to the physical microphone button, decodes the stream, and writes a WAV file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from pathlib import Path
import re
import struct
import time
import wave

from winrt.windows.devices.bluetooth import BluetoothCacheMode, BluetoothLEDevice
from winrt.windows.devices.bluetooth.genericattributeprofile import (
    GattClientCharacteristicConfigurationDescriptorValue as CccdValue,
    GattWriteOption,
)
from winrt.windows.storage.streams import DataReader, DataWriter


VOICE_SERVICE_UUID = "ab5e0001-5a21-4f05-bc7d-af01f617b664"
VOICE_TX_UUID = "ab5e0002-5a21-4f05-bc7d-af01f617b664"
VOICE_AUDIO_UUID = "ab5e0003-5a21-4f05-bc7d-af01f617b664"
VOICE_CONTROL_UUID = "ab5e0004-5a21-4f05-bc7d-af01f617b664"

GET_CAPS_V10 = bytes((0x0A, 0x01, 0x00, 0x00, 0x03, 0x03))

STEP_TABLE = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130,
    143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
    494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411,
    1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026,
    4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
    11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623,
    27086, 29794, 32767,
)
INDEX_TABLE = (-1, -1, -1, -1, 2, 4, 6, 8)


class AdpcmDecoder:
    def __init__(self) -> None:
        self.predictor = 0
        self.step_index = 0

    def reset(self, predictor: int, step_index: int) -> None:
        self.predictor = max(-32768, min(32767, int(predictor)))
        self.step_index = max(0, min(88, int(step_index)))

    def decode_nibble(self, nibble: int) -> int:
        step = STEP_TABLE[self.step_index]
        diff = step >> 3
        if nibble & 1:
            diff += step >> 2
        if nibble & 2:
            diff += step >> 1
        if nibble & 4:
            diff += step
        self.predictor += -diff if nibble & 8 else diff
        self.predictor = max(-32768, min(32767, self.predictor))
        self.step_index += INDEX_TABLE[nibble & 7]
        self.step_index = max(0, min(88, self.step_index))
        return self.predictor

    def decode_bytes(self, data: bytes) -> list[int]:
        samples: list[int] = []
        for value in data:
            samples.append(self.decode_nibble(value >> 4))
            samples.append(self.decode_nibble(value & 0x0F))
        return samples


def address_to_int(address: str) -> int:
    compact = re.sub(r"[^0-9a-fA-F]", "", str(address))
    if len(compact) != 12:
        raise ValueError(f"invalid Bluetooth address: {address!r}")
    return int(compact, 16)


def buffer_bytes(buffer) -> bytes:
    reader = DataReader.from_buffer(buffer)
    try:
        data = bytearray(reader.unconsumed_buffer_length)
        reader.read_bytes(data)
        return bytes(data)
    finally:
        reader.close()


def bytes_buffer(data: bytes):
    writer = DataWriter()
    try:
        writer.write_bytes(data)
        return writer.detach_buffer()
    finally:
        writer.close()


def postprocess(samples: list[int], gain_db: float) -> list[int]:
    if len(samples) >= 3:
        original = samples[:]
        for index in range(1, len(samples) - 1):
            samples[index] = (
                original[index - 1] + 2 * original[index] + original[index + 1]
            ) >> 2
    gain = 10.0 ** (gain_db / 20.0)
    return [max(-32768, min(32767, round(sample * gain))) for sample in samples]


async def discover_atvv(device: BluetoothLEDevice):
    services_result = await device.get_gatt_services_with_cache_mode_async(
        BluetoothCacheMode.UNCACHED
    )
    if int(services_result.status) != 0:
        raise RuntimeError(f"GATT service discovery failed: {services_result.status}")
    service = next(
        (
            item
            for item in services_result.services
            if str(item.uuid).casefold() == VOICE_SERVICE_UUID
        ),
        None,
    )
    if service is None:
        raise RuntimeError("ATVV service not found")
    chars_result = await service.get_characteristics_with_cache_mode_async(
        BluetoothCacheMode.UNCACHED
    )
    if int(chars_result.status) != 0:
        raise RuntimeError(
            f"GATT characteristic discovery failed: {chars_result.status}"
        )
    chars = {str(char.uuid).casefold(): char for char in chars_result.characteristics}
    for uuid in (VOICE_TX_UUID, VOICE_AUDIO_UUID, VOICE_CONTROL_UUID):
        if uuid not in chars:
            raise RuntimeError(f"ATVV characteristic not found: {uuid}")
    return service, chars


def parse_caps(data: bytes) -> dict | None:
    if len(data) < 7 or data[0] != 0x0B:
        return None
    version = int.from_bytes(data[1:3], "big")
    if version >= 0x0100:
        codecs = data[3]
        interaction = data[4]
        frame_size = int.from_bytes(data[5:7], "big")
        # A few remotes advertise the v1 version while returning the legacy
        # two-byte codec field. Accept that layout instead of failing.
        if codecs == 0 and len(data) >= 9 and data[4] & 0x03:
            codecs = data[4]
            interaction = 0x03
    else:
        if len(data) < 9:
            return None
        codecs = data[4]
        interaction = 0x00
        frame_size = int.from_bytes(data[5:7], "big")
    selected_codec = 0x02 if codecs & 0x02 else 0x01
    return {
        "version": version,
        "codecs": codecs,
        "interaction": interaction,
        "frame_size": frame_size,
        "selected_codec": selected_codec,
        "sample_rate": 16000 if selected_codec == 0x02 else 8000,
    }


async def write_command(tx, data: bytes, label: str) -> None:
    status = await tx.write_value_with_option_async(
        bytes_buffer(data), GattWriteOption.WRITE_WITHOUT_RESPONSE
    )
    print(f"TX {label}: {data.hex('-')} status={status}", flush=True)
    if int(status) != 0:
        raise RuntimeError(f"{label} write failed: {status}")


async def record(
    address: str,
    duration: float,
    output: Path,
    event_log: Path,
    gain_db: float,
    auto_open: bool,
) -> int:
    output.parent.mkdir(parents=True, exist_ok=True)
    event_log.parent.mkdir(parents=True, exist_ok=True)
    event_log.write_text("", encoding="utf-8")

    device = await BluetoothLEDevice.from_bluetooth_address_async(address_to_int(address))
    if device is None:
        raise RuntimeError(f"Paired BLE device not found: {address}")
    print(
        f"device={device.name} address={address} connection_status={device.connection_status}",
        flush=True,
    )
    service, chars = await discover_atvv(device)
    tx = chars[VOICE_TX_UUID]
    audio = chars[VOICE_AUDIO_UUID]
    control = chars[VOICE_CONTROL_UUID]
    loop = asyncio.get_running_loop()
    events: asyncio.Queue[tuple[str, float, bytes]] = asyncio.Queue()
    start = time.perf_counter()

    def make_handler(channel: str):
        def handler(_sender, args):
            payload = buffer_bytes(args.characteristic_value)
            elapsed = time.perf_counter() - start
            loop.call_soon_threadsafe(events.put_nowait, (channel, elapsed, payload))

        return handler

    audio_token = audio.add_value_changed(make_handler("audio"))
    control_token = control.add_value_changed(make_handler("control"))
    wav: wave.Wave_write | None = None
    caps: dict | None = None
    decoder = AdpcmDecoder()
    decoder_synced = False
    mic_open = False
    audio_frames = 0
    pcm_samples = 0
    peak = 0
    sum_squares = 0

    try:
        for char, label in ((audio, "audio"), (control, "control")):
            status = await char.write_client_characteristic_configuration_descriptor_async(
                CccdValue.NOTIFY
            )
            print(f"subscribed {label}: status={status}", flush=True)
            if int(status) != 0:
                raise RuntimeError(f"subscribe {label} failed: {status}")

        await write_command(tx, GET_CAPS_V10, "GET_CAPS")
        deadline = loop.time() + duration
        auto_open_at = loop.time() + 1.5 if auto_open else None
        print(
            f"listening_for={duration:.1f}s; press and hold the physical microphone button",
            flush=True,
        )

        while loop.time() < deadline:
            if auto_open_at is not None and loop.time() >= auto_open_at and not mic_open:
                version = caps["version"] if caps else 0x0100
                codec = caps["selected_codec"] if caps else 0x02
                command = bytes((0x0C, 0x00)) if version >= 0x0100 else bytes((0x0C, 0x00, codec))
                await write_command(tx, command, "MIC_OPEN(auto)")
                mic_open = True
                auto_open_at = None

            timeout = min(0.25, max(0.01, deadline - loop.time()))
            try:
                channel, elapsed, payload = await asyncio.wait_for(
                    events.get(), timeout=timeout
                )
            except asyncio.TimeoutError:
                continue

            record_data = {
                "elapsed_ms": round(elapsed * 1000, 3),
                "channel": channel,
                "length": len(payload),
                "hex": payload.hex("-"),
            }
            with event_log.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record_data, ensure_ascii=False) + "\n")

            if channel == "control":
                print(f"CTL {payload.hex('-')}", flush=True)
                if not payload:
                    continue
                opcode = payload[0]
                if opcode == 0x0B:
                    caps = parse_caps(payload)
                    print(f"CAPS {caps}", flush=True)
                elif opcode == 0x08:
                    version = caps["version"] if caps else 0x0100
                    codec = caps["selected_codec"] if caps else 0x02
                    command = bytes((0x0C, 0x00)) if version >= 0x0100 else bytes((0x0C, 0x00, codec))
                    await write_command(tx, command, "MIC_OPEN(button)")
                    mic_open = True
                elif opcode == 0x04:
                    if len(payload) >= 3:
                        codec = payload[2]
                        if caps is None:
                            caps = {
                                "version": 0x0100,
                                "codecs": codec,
                                "interaction": payload[1] if len(payload) > 1 else 0,
                                "frame_size": 120,
                                "selected_codec": codec,
                                "sample_rate": 16000 if codec == 0x02 else 8000,
                            }
                        else:
                            caps["selected_codec"] = codec
                            caps["sample_rate"] = 16000 if codec == 0x02 else 8000
                    if wav is None:
                        sample_rate = caps["sample_rate"] if caps else 16000
                        wav = wave.open(str(output), "wb")
                        wav.setnchannels(1)
                        wav.setsampwidth(2)
                        wav.setframerate(sample_rate)
                        print(f"WAV opened sample_rate={sample_rate}", flush=True)
                elif opcode == 0x0A and len(payload) >= 7:
                    predictor = int.from_bytes(payload[4:6], "big", signed=True)
                    decoder.reset(predictor, payload[6])
                    decoder_synced = True
                    print(
                        f"AUDIO_SYNC codec={payload[1]} seq={int.from_bytes(payload[2:4], 'big')}"
                        f" predictor={predictor} step_index={payload[6]}",
                        flush=True,
                    )
                continue

            audio_frames += 1
            if caps is None:
                print("audio_before_caps_ignored", flush=True)
                continue
            if caps["version"] >= 0x0100:
                samples = decoder.decode_bytes(payload)
            else:
                if len(payload) < 6:
                    continue
                predictor = int.from_bytes(payload[3:5], "big", signed=True)
                decoder.reset(predictor, payload[5])
                decoder_synced = True
                samples = [predictor, *decoder.decode_bytes(payload[6:])]
            if wav is None:
                wav = wave.open(str(output), "wb")
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(caps["sample_rate"])
            samples = postprocess(samples, gain_db)
            wav.writeframesraw(b"".join(struct.pack("<h", sample) for sample in samples))
            pcm_samples += len(samples)
            if samples:
                peak = max(peak, max(abs(sample) for sample in samples))
                sum_squares += sum(sample * sample for sample in samples)
            if audio_frames <= 3 or audio_frames % 50 == 0:
                print(
                    f"AUDIO frame={audio_frames} bytes={len(payload)}"
                    f" samples={len(samples)} synced={decoder_synced}",
                    flush=True,
                )

        rms = math.sqrt(sum_squares / pcm_samples) if pcm_samples else 0.0
        print(
            f"RESULT audio_frames={audio_frames} pcm_samples={pcm_samples}"
            f" peak={peak} rms={rms:.2f} wav={output}",
            flush=True,
        )
        return 0 if audio_frames and pcm_samples else 3
    finally:
        if mic_open:
            try:
                version = caps["version"] if caps else 0x0100
                close_cmd = bytes((0x0D, 0x00)) if version >= 0x0100 else bytes((0x0D,))
                await write_command(tx, close_cmd, "MIC_CLOSE")
            except Exception as exc:
                print(f"mic_close_warning={exc}", flush=True)
        if wav is not None:
            wav.close()
        for char, token in ((audio, audio_token), (control, control_token)):
            try:
                char.remove_value_changed(token)
                await char.write_client_characteristic_configuration_descriptor_async(
                    CccdValue.NONE
                )
            except Exception as exc:
                print(f"notification_cleanup_warning={exc}", flush=True)
        service.close()
        device.close()


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--address",
        required=True,
        help="已在 Windows 中配对的小米遥控器蓝牙地址，例如 AA:BB:CC:DD:EE:FF",
    )
    parser.add_argument("--duration", type=float, default=45.0)
    parser.add_argument("--gain-db", type=float, default=10.0)
    parser.add_argument("--auto-open", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=root / "logs" / f"mi_rc_voice_{timestamp}.wav"
    )
    parser.add_argument(
        "--event-log", type=Path, default=root / "logs" / f"mi_rc_voice_{timestamp}.jsonl"
    )
    args = parser.parse_args()
    return asyncio.run(
        record(
            address=args.address,
            duration=args.duration,
            output=args.output.resolve(),
            event_log=args.event_log.resolve(),
            gain_db=args.gain_db,
            auto_open=args.auto_open,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
