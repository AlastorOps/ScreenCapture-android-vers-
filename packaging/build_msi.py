"""Builds dist/AndroidLink.msi -- a full wizard-style Windows Installer
package (installer information page, an important-notice page, a features
page, a requirements page, an install-location picker, a confirmation page,
and a real Uninstall.exe dropped into the install folder) driven by
packaging/androidlink.wxs.

Prerequisites this script drives automatically:
  1. dist/AndroidLink.exe must already exist -- build it first:
       pip install -e ".[build]"
       pyinstaller packaging/androidlink.spec --distpath dist --workpath build --noconfirm
  2. The WiX Toolset v3 binaries (candle.exe/light.exe) -- downloaded
     automatically into packaging/.wix-tools/ on first run if not already
     present (a standalone binaries zip, no installation/admin rights
     needed, nothing added to PATH or the registry).
  3. dist/Uninstall.exe -- built here from packaging/uninstall_stub.py via
     PyInstaller, so the installed app folder has a real, double-clickable
     uninstaller (see that module's docstring for how it avoids needing to
     know its own MSI ProductCode ahead of time).

Usage:
    python packaging/build_msi.py
"""

import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGING_DIR = REPO_ROOT / "packaging"
DIST_DIR = REPO_ROOT / "dist"
BUILD_DIR = REPO_ROOT / "build"
EXE_PATH = DIST_DIR / "AndroidLink.exe"
UNINSTALL_EXE_PATH = DIST_DIR / "Uninstall.exe"
MSI_PATH = DIST_DIR / "AndroidLink.msi"
WXS_PATH = PACKAGING_DIR / "androidlink.wxs"
UNINSTALL_STUB_PATH = PACKAGING_DIR / "uninstall_stub.py"

WIX_TOOLS_DIR = PACKAGING_DIR / ".wix-tools"
WIX_BIN_DIR = WIX_TOOLS_DIR / "bin"
WIX_DOWNLOAD_URL = "https://github.com/wixtoolset/wix3/releases/download/wix3141rtm/wix314-binaries.zip"

# Fixed forever, identifies "this product" across versions so WiX's
# <MajorUpgrade> can detect and replace an older install -- never change
# this once a build has shipped. ProductCode (Product/@Id="*" in the .wxs)
# is regenerated every build instead, which is what's *supposed* to
# change every version.
UPGRADE_CODE = "{6B2F9F0E-6C2D-4B7B-9C0B-6E2C7B9E7A31}"


def _read_project_version() -> str:
    pyproject = REPO_ROOT / "pyproject.toml"
    match = re.search(r'^version\s*=\s*"([\d.]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE)
    if match is None:
        print(f"warning: could not read version from {pyproject}; using 0.1.0", file=sys.stderr)
        return "0.1.0"
    return match.group(1)


def _ensure_wix_tools() -> tuple[Path, Path]:
    candle = WIX_BIN_DIR / "candle.exe"
    light = WIX_BIN_DIR / "light.exe"
    if candle.exists() and light.exists():
        return candle, light

    print("WiX Toolset not found locally -- downloading standalone binaries "
          f"(one-time, ~40MB) from {WIX_DOWNLOAD_URL} ...")
    WIX_TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = WIX_TOOLS_DIR / "wix314-binaries.zip"
    urllib.request.urlretrieve(WIX_DOWNLOAD_URL, zip_path)
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(WIX_BIN_DIR)
    zip_path.unlink()

    if not candle.exists() or not light.exists():
        print(f"error: WiX download did not produce candle.exe/light.exe under {WIX_BIN_DIR}", file=sys.stderr)
        raise SystemExit(1)
    return candle, light


def _build_uninstall_exe() -> None:
    print("Building Uninstall.exe ...")
    icon_path = REPO_ROOT / "androidlink" / "assets" / "icons" / "androidlink.ico"
    args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile", "--noconsole", "--name", "Uninstall",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR / "uninstall"),
        "--specpath", str(BUILD_DIR / "uninstall"),
        "--noconfirm",
    ]
    if icon_path.exists():
        args += ["--icon", str(icon_path)]
    args.append(str(UNINSTALL_STUB_PATH))
    subprocess.run(args, check=True, cwd=REPO_ROOT)


def main() -> None:
    if not EXE_PATH.exists():
        print(
            f"error: {EXE_PATH} not found.\n"
            f"Build it first:\n"
            f"  pip install -e \".[build]\"\n"
            f"  pyinstaller packaging/androidlink.spec --distpath dist --workpath build --noconfirm",
            file=sys.stderr,
        )
        raise SystemExit(1)

    candle, light = _ensure_wix_tools()
    _build_uninstall_exe()

    product_version = _read_project_version()
    wixobj_path = BUILD_DIR / "androidlink.wixobj"
    BUILD_DIR.mkdir(parents=True, exist_ok=True)

    print("Compiling androidlink.wxs ...")
    subprocess.run(
        [
            str(candle),
            "-arch", "x64",
            f"-dProductVersion={product_version}",
            f"-dUpgradeCode={UPGRADE_CODE}",
            f"-dDistDir={DIST_DIR}",
            "-ext", "WixUIExtension",
            "-out", str(wixobj_path),
            str(WXS_PATH),
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    print("Linking AndroidLink.msi ...")
    MSI_PATH.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            str(light),
            "-ext", "WixUIExtension",
            "-cultures:en-us",
            "-out", str(MSI_PATH),
            str(wixobj_path),
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    print(f"Built {MSI_PATH} (ProductVersion {product_version})")


if __name__ == "__main__":
    main()
