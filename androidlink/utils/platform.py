import os
import subprocess
import sys
from pathlib import Path

from platformdirs import user_config_dir, user_pictures_dir, user_videos_dir

APP_NAME = "AndroidLink"

# androidlink/utils/platform.py -> androidlink/ -> repo root, in dev mode.
_REPO_ROOT = Path(__file__).resolve().parents[2]


def get_resource_path(relative_path: str) -> Path:
    """Resolve a bundled resource, whether running from source or from a
    PyInstaller-frozen executable (see packaging/androidlink.spec `datas`)."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
    else:
        base = _REPO_ROOT
    return base / relative_path


def get_app_data_dir() -> Path:
    path = Path(user_config_dir(APP_NAME, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_logs_dir() -> Path:
    path = get_app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_recordings_dir() -> Path:
    """Default PC-side recording save location (prompt.md section 14).
    Not yet user-configurable via Settings -- that's part of the full
    Settings page deferred to Phase 9 (prompt.md section 27's "Recording:
    Save location"); the underlying storage location is real, just not yet
    exposed as a preference."""
    path = Path(user_videos_dir()) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_screenshots_dir() -> Path:
    path = Path(user_pictures_dir()) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def open_path_in_explorer(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", str(path)], check=False)
