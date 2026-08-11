"""Parses scrcpy-server's `list_cameras=true` stdout output into structured
camera info (prompt.md section 11: "Detect all available cameras").

Derived from server/src/main/java/com/genymobile/scrcpy/util/LogUtils.java's
buildCameraListMessage(), which prints lines like:

    List of cameras:
        --camera-id=0    (back, 1920x1080, fps={30, 60}, zoom-range=1.0-8.0)
        --camera-id=1    (front, 1280x960, fps={30})

or "(none)" / "(access denied)" when there's nothing to report. The regex
search doesn't depend on line structure or scrcpy-server's own log-level
prefixes (e.g. "[server] INFO: ") since that framing isn't guaranteed to be
consistent across every line of a multi-line log message.
"""

import re
from dataclasses import dataclass

_CAMERA_ENTRY_RE = re.compile(
    r"--camera-id=(?P<id>\S+)\s*\(\s*(?P<facing>\w+),\s*(?P<width>\d+)x(?P<height>\d+)"
    r"(?:,\s*fps=\{(?P<fps>[^}]*)\})?"
)


@dataclass(frozen=True)
class CameraInfo:
    camera_id: str
    facing: str  # "front", "back", or "external"
    width: int
    height: int
    fps_options: tuple[int, ...]

    @property
    def display_name(self) -> str:
        return f"{self.facing.capitalize()} camera ({self.width}x{self.height})"


def parse_camera_list(output: str) -> list[CameraInfo]:
    cameras = []
    for match in _CAMERA_ENTRY_RE.finditer(output):
        fps_text = match.group("fps")
        fps_options = (
            tuple(sorted({int(x.strip()) for x in fps_text.split(",")})) if fps_text else ()
        )
        cameras.append(
            CameraInfo(
                camera_id=match.group("id"),
                facing=match.group("facing"),
                width=int(match.group("width")),
                height=int(match.group("height")),
                fps_options=fps_options,
            )
        )
    return cameras
