# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


source = Path(SPECPATH).resolve()
datas = [
    (
        str(source / "bridges" / "hanvon" / "voice_typing_hid_config.json"),
        "bridges/hanvon",
    )
]

a = Analysis(
    [str(source / "standalone" / "v60_main.py")],
    pathex=[str(source)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "pystray._win32",
        "PIL._tkinter_finder",
        "hid",
    ],
    excludes=[
        "bridges.xiaomi",
        "bridges.t1",
        "bridges.audio.audio_router",
        "licensing",
        "customer_license",
        "numpy",
        "sounddevice",
        "winrt",
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
    name="V60PenBridge",
    console=False,
    debug=False,
    strip=False,
    upx=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="V60PenBridge",
)
