from pathlib import Path


project_root = Path(SPECPATH)
datas = [(str(project_root / "kiosk/templates"), "kiosk/templates"),
         (str(project_root / "kiosk/static/css"), "kiosk/static/css"),
         (str(project_root / "kiosk/static/js"), "kiosk/static/js"),
         (str(project_root / "kiosk/static/img"), "kiosk/static/img"),
         (str(project_root / "kiosk/translations"), "kiosk/translations"),
         # The installed server publishes native delivery views with the same
         # renderer bytes the client reports; both must be present in the build.
         (str(project_root / "kiosk/publication/renderer.py"), "kiosk/publication"),
         (str(project_root / "kiosk/publication/renderer_assets"), "kiosk/publication/renderer_assets"),
         (str(project_root / "tools/certificate_crypto.ps1"), "tools"),
         (str(project_root / "tools/certificate_crypto.cs"), "tools")]
hiddenimports = ["kiosk.publication.renderer", "kiosk.display.cache", "kiosk.delivery.publication"]
executables = []
analyses = []
for entry, name, console in (("launcher.py", "KioskLauncher", False),
                              ("launcher_service.py", "KioskService", False),
                              ("certificates_cli.py", "KioskCertificates", True),
                              ("launcher_maintenance.py", "KioskMaintenance", True)):
    analysis = Analysis([str(project_root / entry)], pathex=[str(project_root)], binaries=[], datas=datas,
                        hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False, optimize=0)
    analyses.append(analysis)
    executables.append(EXE(PYZ(analysis.pure), analysis.scripts, [], exclude_binaries=True, name=name, debug=False,
                           bootloader_ignore_signals=False, strip=False, upx=False, console=console))
coll = COLLECT(*executables, *[items for analysis in analyses for items in (analysis.binaries, analysis.datas)],
               strip=False, upx=False, name="KioskLauncher")
