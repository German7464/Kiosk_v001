from pathlib import Path


project_root = Path(SPECPATH)


a = Analysis(
    ["serve.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        (str(project_root / "kiosk" / "templates"), "kiosk/templates"),
        (str(project_root / "kiosk" / "static" / "css"), "kiosk/static/css"),
        (str(project_root / "kiosk" / "static" / "img"), "kiosk/static/img"),
        (str(project_root / "kiosk" / "static" / "js"), "kiosk/static/js"),
        (str(project_root / "kiosk" / "translations"), "kiosk/translations"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Kiosk_v001",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
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
    upx=True,
    upx_exclude=[],
    name="Kiosk_v001",
)
