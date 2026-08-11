# PyInstaller spec for AndroidLink. Later phases (audio/camera/mic virtual
# devices) will add their own vendored binaries via Analysis.datas here.

from pathlib import Path

block_cipher = None

repo_root = Path(SPECPATH).parent

a = Analysis(
    [str(repo_root / "androidlink" / "app" / "main.py")],
    pathex=[str(repo_root)],
    binaries=[],
    datas=[
        (str(repo_root / "androidlink" / "ui" / "themes" / "qss"), "androidlink/ui/themes/qss"),
        (str(repo_root / "androidlink" / "vendor" / "scrcpy"), "androidlink/vendor/scrcpy"),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="AndroidLink",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    runtime_tmpdir=None,
)
