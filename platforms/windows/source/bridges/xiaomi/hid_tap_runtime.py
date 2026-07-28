#!/usr/bin/env python3
"""Verified x64 Frida Gadget runtime for the RC003 HidOverGatt tap."""

from __future__ import annotations

from functools import lru_cache
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import subprocess
import threading
import winreg


GADGET_VERSION = "17.15.3"
GADGET_ARCHIVE_NAME = "frida-gadget-17.15.3-windows-x86_64.dll.xz"
GADGET_ARCHIVE_SHA256 = (
    "b566d70189b6d551ad8f4e0bea24de08a3d4c0f559bb35b2bdb67d45182240c2"
)
GADGET_DLL_NAME = "RemoteBridgeHidTap.dll"
GADGET_DLL_SHA256 = (
    "6fca4007b2284c765a6c15c967a741f536b5865bf83867326a54029a3b752748"
)
GADGET_CONFIG_NAME = "RemoteBridgeHidTap.config"
GADGET_SCRIPT_NAME = "xiaomi_hid_gadget.js"
HID_TAP_PORT = int(os.environ.get("REMOTE_BRIDGE_XIAOMI_HID_TAP_PORT", "30684"))

BTHLE_ENUM_KEY = r"SYSTEM\CurrentControlSet\Enum\BTHLEDevice"
HID_SERVICE_PREFIX = "{00001812-0000-1000-8000-00805f9b34fb}"
RC003_HARDWARE_TOKEN = "dev_vid&012717_pid&32b8_rev&00a4"
WUDF_DIAGNOSTIC_SUFFIX = r"Device Parameters\WUDFDiagnosticInfo"


GADGET_SCRIPT = r"""
const READ_CHARACTERISTIC_IOCTL = 0x80018483;
const EXPECTED_OUTPUT_LENGTH = 9;
const HEARTBEAT_INTERVAL_MS = 5000;
const RECONNECT_DELAY_MS = 1000;

let host = "127.0.0.1";
let port = 30684;
let connection = null;
let output = null;
let writeChain = Promise.resolve();
let reconnectTimer = null;
let hookInstalled = false;

function asciiBytes(text) {
  const result = [];
  for (let index = 0; index < text.length; index++) {
    result.push(text.charCodeAt(index) & 0xff);
  }
  return result;
}

function hex(pointer, length) {
  if (pointer.isNull() || length <= 0) return "";
  const bytes = new Uint8Array(pointer.readByteArray(length));
  let result = "";
  for (let index = 0; index < bytes.length; index++) {
    result += bytes[index].toString(16).padStart(2, "0");
  }
  return result;
}

function scheduleReconnect() {
  if (reconnectTimer !== null) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connectToHub();
  }, RECONNECT_DELAY_MS);
}

function markDisconnected(currentOutput) {
  if (output !== currentOutput) return;
  output = null;
  connection = null;
  scheduleReconnect();
}

function emit(payload) {
  const currentOutput = output;
  if (currentOutput === null) {
    scheduleReconnect();
    return;
  }
  const line = JSON.stringify(payload) + "\n";
  writeChain = writeChain
    .then(() => currentOutput.writeAll(asciiBytes(line)))
    .catch(() => markDisconnected(currentOutput));
}

async function connectToHub() {
  if (output !== null) return;
  try {
    const currentConnection = await Socket.connect({
      family: "ipv4",
      host: host,
      port: port
    });
    connection = currentConnection;
    output = currentConnection.output;
    emit({ kind: "ready", pid: Process.id, hook_installed: hookInstalled });
  } catch (_error) {
    connection = null;
    output = null;
    scheduleReconnect();
  }
}

function installHook() {
  if (hookInstalled) return;
  const ntdll = Process.findModuleByName("ntdll.dll");
  const target = ntdll ? ntdll.findExportByName("NtDeviceIoControlFile") : null;
  if (target === null) {
    emit({ kind: "error", message: "NtDeviceIoControlFile export not found" });
    return;
  }
  Interceptor.attach(target, {
    onEnter(args) {
      this.capture = args[5].toUInt32() === READ_CHARACTERISTIC_IOCTL;
      if (this.capture) {
        this.output = args[8];
        this.outputLength = args[9].toUInt32();
      }
    },
    onLeave(retval) {
      if (!this.capture || retval.toUInt32() !== 0 || this.output.isNull()) return;
      try {
        if (this.outputLength === EXPECTED_OUTPUT_LENGTH) {
          emit({
            kind: "gatt_read",
            raw: hex(this.output, this.outputLength)
          });
        }
      } catch (error) {
        emit({ kind: "error", message: String(error) });
      }
    }
  });
  hookInstalled = true;
}

setInterval(() => {
  if (output === null) {
    scheduleReconnect();
  } else {
    emit({ kind: "heartbeat", pid: Process.id });
  }
}, HEARTBEAT_INTERVAL_MS);

rpc.exports = {
  async init(_stage, parameters) {
    host = parameters.host || host;
    port = parameters.port || port;
    installHook();
    await connectToHub();
  }
};
""".strip() + "\n"


def gadget_config_text() -> str:
    return (
        json.dumps(
            {
                "interaction": {
                    "type": "script",
                    "path": GADGET_SCRIPT_NAME,
                    "parameters": {"host": "127.0.0.1", "port": HID_TAP_PORT},
                    "on_change": "ignore",
                },
                "runtime": "qjs",
                "teardown": "minimal",
            },
            indent=2,
        )
        + "\n"
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gadget_archive_path() -> Path:
    return Path(__file__).resolve().with_name("assets") / GADGET_ARCHIVE_NAME


@lru_cache(maxsize=1)
def gadget_archive_available() -> bool:
    archive = gadget_archive_path()
    try:
        return archive.is_file() and sha256_file(archive) == GADGET_ARCHIVE_SHA256
    except OSError:
        return False


def secure_runtime_directory() -> Path:
    program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    return (
        program_data
        / os.environ.get("REMOTE_BRIDGE_XIAOMI_RUNTIME_ID", "MiVibeRemote")
        / "hid-tap"
        / f"{GADGET_VERSION}-x64-{GADGET_DLL_SHA256[:12]}"
    )


def _write_verified_text(path: Path, content: str) -> None:
    encoded = content.encode("utf-8")
    if path.is_file():
        try:
            if path.read_bytes() == encoded:
                return
        except OSError:
            pass
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _lock_runtime_acl(path: Path) -> None:
    def apply(target: Path, *, directory: bool) -> None:
        suffix = "(OI)(CI)" if directory else ""
        command = [
            "icacls.exe",
            str(target),
            "/inheritance:r",
            "/grant:r",
            f"*S-1-5-18:{suffix}F",
            f"*S-1-5-32-544:{suffix}F",
            f"*S-1-5-32-545:{suffix}RX",
            "/C",
            "/Q",
        ]
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.returncode != 0:
            raise OSError(
                f"failed to secure Gadget runtime ACL: {completed.stdout.strip()}"
            )

    # Container inheritance flags are valid on directories, but applying them
    # directly to files produces inherited-only ACEs and can make the DLL
    # unreadable even to the elevated injector. Give each existing child an
    # effective file or directory ACL instead.
    apply(path, directory=True)
    for child in path.rglob("*"):
        apply(child, directory=child.is_dir())


def prepare_secure_runtime() -> Path:
    archive = gadget_archive_path()
    if not archive.is_file():
        raise FileNotFoundError(archive)
    archive_hash = sha256_file(archive)
    if archive_hash != GADGET_ARCHIVE_SHA256:
        raise RuntimeError(f"Gadget archive hash mismatch: {archive_hash}")

    destination = secure_runtime_directory()
    destination.mkdir(parents=True, exist_ok=True)
    # Repair runtimes created by older builds before attempting to hash them.
    _lock_runtime_acl(destination)
    dll_path = destination / GADGET_DLL_NAME
    if not dll_path.is_file() or sha256_file(dll_path) != GADGET_DLL_SHA256:
        temporary = dll_path.with_suffix(f".dll.{os.getpid()}.tmp")
        try:
            with lzma.open(archive, "rb") as source, temporary.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)
            dll_hash = sha256_file(temporary)
            if dll_hash != GADGET_DLL_SHA256:
                raise RuntimeError(f"Gadget DLL hash mismatch: {dll_hash}")
            os.replace(temporary, dll_path)
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    _write_verified_text(destination / GADGET_CONFIG_NAME, gadget_config_text())
    _write_verified_text(destination / GADGET_SCRIPT_NAME, GADGET_SCRIPT)
    _lock_runtime_acl(destination)
    return dll_path


def find_rc003_hidogatt_host_pid() -> int | None:
    """Locate the WUDFHost assigned to the paired RC003 HID service."""

    if os.name != "nt":
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, BTHLE_ENUM_KEY) as root:
            service_index = 0
            while True:
                try:
                    service_name = winreg.EnumKey(root, service_index)
                except OSError:
                    break
                service_index += 1
                folded = service_name.casefold()
                if not folded.startswith(HID_SERVICE_PREFIX):
                    continue
                if RC003_HARDWARE_TOKEN not in folded:
                    continue
                with winreg.OpenKey(root, service_name) as service_key:
                    instance_index = 0
                    while True:
                        try:
                            instance_name = winreg.EnumKey(service_key, instance_index)
                        except OSError:
                            break
                        instance_index += 1
                        diagnostic_path = (
                            f"{service_name}\\{instance_name}\\{WUDF_DIAGNOSTIC_SUFFIX}"
                        )
                        try:
                            with winreg.OpenKey(root, diagnostic_path) as diagnostic_key:
                                value, _ = winreg.QueryValueEx(diagnostic_key, "HostPid")
                            pid = int(value)
                            if pid > 0:
                                return pid
                        except (OSError, TypeError, ValueError):
                            continue
    except OSError:
        return None
    return None
