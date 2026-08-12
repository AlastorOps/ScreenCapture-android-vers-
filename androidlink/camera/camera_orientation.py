"""Detects what rotation the camera preview needs to appear upright, and
keeps it correct as the phone itself is physically rotated while the camera
is active.

Two independent pieces of Android state are involved, both only available
via `adb shell dumpsys` (there is no dedicated scrcpy/ADB API for either,
and camera-mirroring sessions run with control=false -- see
protocol.py's build_camera_server_launch_args() -- so there is no live
wire-protocol channel carrying orientation events the way screen mirroring
has; this module exists because polling is the only option):

1. CameraCharacteristics.SENSOR_ORIENTATION (`dumpsys media.camera`) -- a
   FIXED property of one specific camera (0/90/180/270), the degrees its
   raw sensor buffer must be rotated clockwise to appear upright when the
   phone is held in its natural/default orientation. Detected once, at
   camera start.

    Camera 0 static information:
      Facing: back
      Orientation: 90
      ...

2. The device's CURRENT display rotation (`dumpsys input` / `dumpsys
   window displays`) -- changes live as the user physically rotates the
   phone. Polled periodically while the camera is active (see
   camera_session.py's _orientation_poll_timer) so the preview keeps
   adapting without requiring the camera session to restart.

Combining the two into "how much to rotate this frame right now" uses the
standard Camera2 formula (Android's CameraOrientationHelper /
Camera2BasicFragment.getOrientation() reference pattern), generalized to
non-zero device rotation:

    back-facing:  (sensor_orientation - device_rotation) % 360
    front-facing: (sensor_orientation + device_rotation) % 360

Mirrors device/display_info.py's approach throughout: parse only what's
actually there, and return None (never a guessed/fabricated value) when a
block/field can't be found -- callers must then fall back to "no
correction" for that piece rather than applying a fixed guess.

Caveat shared with display_info.py: OEM dumpsys output isn't guaranteed
identical across Android versions/vendors, and unlike the refresh-rate
detection there, this module's exact field names have not been verified
against a real device dump during development (no Android device with
`adb shell dumpsys media.camera`/`dumpsys input` access was available) --
degrading to "no rotation applied" is the safe failure mode if a given
device's real output doesn't match what's parsed here.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QProcess

logger = logging.getLogger(__name__)

_ADB_COMMAND_TIMEOUT_MS = 10_000
_VALID_DEGREES = (0, 90, 180, 270)


def _run_adb_shell(adb_path: Path, serial: str, args: list[str]) -> str | None:
    process = QProcess()
    process.start(str(adb_path), ["-s", serial, "shell", *args])
    if not process.waitForFinished(_ADB_COMMAND_TIMEOUT_MS):
        process.kill()
        return None
    if process.exitCode() != 0:
        return None
    return bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")


@dataclass(frozen=True)
class CameraStaticInfo:
    sensor_orientation_degrees: int  # one of _VALID_DEGREES
    facing: str  # "front", "back", or "external", as reported by dumpsys


def parse_camera_static_info(output: str, camera_id: str) -> CameraStaticInfo | None:
    block_re = re.compile(
        rf"Camera {re.escape(camera_id)} static information:(?P<body>.*?)"
        rf"(?=\nCamera \S+ static information:|\Z)",
        re.DOTALL,
    )
    block_match = block_re.search(output)
    if block_match is None:
        return None
    body = block_match.group("body")

    orientation_match = re.search(r"Orientation:\s*(\d+)", body)
    if orientation_match is None:
        return None
    degrees = int(orientation_match.group(1))
    if degrees not in _VALID_DEGREES:
        return None

    facing_match = re.search(r"Facing:\s*(\w+)", body)
    facing = facing_match.group(1).lower() if facing_match is not None else "back"

    return CameraStaticInfo(sensor_orientation_degrees=degrees, facing=facing)


def get_camera_static_info(adb_path: Path, serial: str, camera_id: str) -> CameraStaticInfo | None:
    """Blocking (like camera_session.py's other startup ADB calls) --
    intended to be called once from CameraClient.start(), which already
    runs on the worker thread, never the GUI thread."""
    output = _run_adb_shell(adb_path, serial, ["dumpsys", "media.camera"])
    if output is None:
        logger.info("`dumpsys media.camera` failed or timed out for camera %s", camera_id)
        return None

    info = parse_camera_static_info(output, camera_id)
    if info is None:
        logger.info(
            "Could not find sensor orientation for camera %s in `dumpsys media.camera` "
            "output; preview will show unrotated. Raw output for diagnosis:\n%s",
            camera_id,
            output,
        )
    return info


# ROTATION_0/90/180/270 (Android's Surface.ROTATION_* constants) -> degrees
# the device has been physically rotated counter-clockwise from its natural
# orientation. Two different dumpsys sources are tried because neither is
# universally documented as stable across Android versions/OEMs; the first
# match wins.
_SURFACE_ORIENTATION_RE = re.compile(r"SurfaceOrientation:\s*(\d+)")
_WINDOW_ROTATION_RE = re.compile(r"\bmRotation=(\d+)")


def parse_device_rotation_degrees(dumpsys_input: str | None, dumpsys_window: str | None) -> int | None:
    for output, pattern in ((dumpsys_input, _SURFACE_ORIENTATION_RE), (dumpsys_window, _WINDOW_ROTATION_RE)):
        if output is None:
            continue
        match = pattern.search(output)
        if match is not None:
            return (int(match.group(1)) % 4) * 90
    return None


def get_device_rotation_degrees(adb_path: Path, serial: str) -> int | None:
    """Blocking. Meant to be polled periodically (every couple of seconds,
    not per-frame) from the worker thread while a camera session is active
    -- see camera_session.py's _orientation_poll_timer -- so the preview
    keeps adapting as the phone is physically rotated, without needing a
    live wire-protocol event (camera-mirroring sessions have no control
    channel to carry one)."""
    dumpsys_input = _run_adb_shell(adb_path, serial, ["dumpsys", "input"])
    dumpsys_window = None
    if dumpsys_input is None or _SURFACE_ORIENTATION_RE.search(dumpsys_input) is None:
        dumpsys_window = _run_adb_shell(adb_path, serial, ["dumpsys", "window", "displays"])
    return parse_device_rotation_degrees(dumpsys_input, dumpsys_window)


def compute_preview_rotation_degrees(static_info: CameraStaticInfo, device_rotation_degrees: int) -> int:
    """The standard Camera2 "how much to rotate this buffer to look upright
    right now" formula (Android's CameraOrientationHelper /
    Camera2BasicFragment.getOrientation() reference pattern), generalized
    to the device's current rotation rather than assuming it's always 0
    (natural orientation) -- device_rotation_degrees=0 reduces this to
    exactly static_info.sensor_orientation_degrees for a back camera,
    matching the fixed baseline this module used before live rotation
    tracking existed."""
    if static_info.facing == "front":
        result = static_info.sensor_orientation_degrees + device_rotation_degrees
    else:
        result = static_info.sensor_orientation_degrees - device_rotation_degrees
    return result % 360
