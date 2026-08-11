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


def get_recordings_dir(override: str | None = None) -> Path:
    """PC-side recording save location (prompt.md section 14). `override`
    is settings.recording.save_directory (prompt.md section 27's Recording
    > Save location, set via a real folder picker in the Settings dialog);
    when unset, falls back to the OS's Videos folder."""
    path = Path(override) if override else Path(user_videos_dir()) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_screenshots_dir(override: str | None = None) -> Path:
    """Same as get_recordings_dir(), but for PC-side screenshots. Settings
    has a single "Save location" that covers both (prompt.md section 27)
    rather than two separate pickers; screenshots go in a subfolder of it so
    an overridden directory doesn't mix videos and images together the way
    the separate default OS folders (Videos vs. Pictures) never did."""
    path = Path(override) / "Screenshots" if override else Path(user_pictures_dir()) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def open_path_in_explorer(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.run(["xdg-open", str(path)], check=False)
