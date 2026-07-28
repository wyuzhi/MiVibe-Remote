# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


source = Path(SPECPATH).resolve()
datas = [(str(source / "bridges" / "t1" / "config.json"), "bridges/t1")]

a = Analysis(
    [str(source / "standalone" / "t1_main.py")],
    pathex=[str(source)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "pystray._win32",
        "PIL._tkinter_finder",
        "bridges.raw_input_bridge",
    ],
    excludes=[
        "bridges.xiaomi",
        "bridges.hanvon",
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
    name="T1RemoteBridge",
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
    name="T1RemoteBridge",
)
