# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all


source = Path(SPECPATH).resolve()
assets = source / "bridges" / "xiaomi" / "assets"
frida_gadget = assets / "frida-gadget-17.15.3-windows-x86_64.dll.xz"

if not frida_gadget.is_file():
    raise SystemExit(
        "Missing verified Frida Gadget asset. Run scripts/fetch-third-party.ps1 first."
    )

winrt_datas, winrt_binaries, winrt_hiddenimports = collect_all(
    "winrt", include_py_files=False
)

datas = [
    (str(source / "bridges" / "t1" / "config.json"), "bridges/t1"),
    (
        str(source / "bridges" / "hanvon" / "voice_typing_hid_config.json"),
        "bridges/hanvon",
    ),
    (str(frida_gadget), "bridges/xiaomi/assets"),
    *winrt_datas,
]

a = Analysis(
    [str(source / "remote_bridge_hub.py")],
    pathex=[str(source)],
    binaries=[*winrt_binaries],
    datas=datas,
    hiddenimports=[
        "pystray._win32",
        "PIL._tkinter_finder",
        "psutil._pswindows",
        "psutil._psutil_windows",
        "bridges.audio.audio_router",
        "bridges.audio_client",
        "bridges.raw_input_bridge",
        "bridges.native_audio",
        "bridges.physical_hotkey_monitor",
        "bridges.t1.app",
        "bridges.hanvon.hanvon_pen_app",
        "bridges.hanvon.hanvon_headless",
        "bridges.xiaomi.atvv_live_bridge",
        "bridges.xiaomi.atvv_record",
        "bridges.xiaomi.xiaomi_settings",
        "bridges.xiaomi.hid_report_tap",
        "bridges.xiaomi.hid_tap_runtime",
        "bridges.xiaomi.hid_tap_injector",
        *winrt_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "licensing",
        "customer_license",
    ],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RemoteBridgeHub",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RemoteBridgeHub",
)
