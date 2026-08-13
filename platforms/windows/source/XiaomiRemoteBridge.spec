# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all


source = Path(SPECPATH).resolve()
assets = source / "bridges" / "xiaomi" / "assets"
frida_gadget = assets / "frida-gadget-17.15.3-windows-x86_64.dll.xz"
app_icon = assets / "MiVibeRemote.ico"
vendor = source.parent / "delivery" / "vendor" / "winsparkle"
winsparkle_dll = vendor / "WinSparkle.dll"
update_config = Path(os.environ.get("MIVIBE_UPDATE_CONFIG_PATH", ""))

if not frida_gadget.is_file():
    raise SystemExit(
        "Missing verified Frida Gadget asset. Run scripts/fetch-third-party.ps1 first."
    )
if not winsparkle_dll.is_file():
    raise SystemExit(
        "Missing verified WinSparkle asset. Run scripts/fetch-third-party.ps1 first."
    )
if not update_config.is_file():
    raise SystemExit("Missing generated online update configuration.")

winrt_datas, winrt_binaries, winrt_hiddenimports = collect_all(
    "winrt", include_py_files=False
)

datas = [
    (str(frida_gadget), "bridges/xiaomi/assets"),
    (str(update_config), "update"),
    *winrt_datas,
]

a = Analysis(
    [str(source / "standalone" / "xiaomi_main.py")],
    pathex=[str(source)],
    binaries=[(str(winsparkle_dll), "."), *winrt_binaries],
    datas=datas,
    hiddenimports=[
        "pystray._win32",
        "PIL._tkinter_finder",
        "psutil._pswindows",
        "psutil._psutil_windows",
        "bridges.audio.audio_router",
        "bridges.xiaomi.atvv_live_bridge",
        "bridges.xiaomi.atvv_record",
        "bridges.xiaomi.xiaomi_settings",
        "bridges.xiaomi.hid_report_tap",
        "bridges.xiaomi.hid_tap_runtime",
        "bridges.xiaomi.hid_tap_injector",
        "bridges.raw_input_bridge",
        # WinRT projection extensions resolve these two namespaces at runtime.
        # They must be explicit because they are separate wheel distributions,
        # not children shipped by winrt-runtime.
        "winrt.windows.foundation",
        "winrt.windows.foundation.collections",
        "numpy",
        "sounddevice",
        "asyncio",
        "signal",
        "struct",
        *winrt_hiddenimports,
    ],
    excludes=[
        "bridges.t1",
        "bridges.hanvon",
        "bridges.native_audio",
        "licensing",
        "customer_license",
        "frida",
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
    name="MiVibeRemote",
    console=False,
    debug=False,
    strip=False,
    upx=False,
    icon=str(app_icon),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="MiVibeRemote",
)
