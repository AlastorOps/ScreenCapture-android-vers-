"""The Camera Live Preview (Status panel) reuses VideoRenderWidget wholesale
rather than duplicating its paint logic -- same real-frame painting, aspect-
ratio-preserving letterboxing (no stretching), theme-aware background, and
resize behavior already used for the main screen mirror (streaming/
renderer.py). Only two things differ from that main preview: it must never
steal keyboard focus from the main screen's control input, and it fills
whatever space the Status panel dock actually has (Expanding, no maximum
height) rather than the fixed size of a full window.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QWidget

from androidlink.streaming.renderer import VideoRenderWidget

# A floor, not a cap -- large enough that the preview reads as a real
# picture rather than a thumbnail even in an unresized/default-height Status
# dock; growing beyond this as the dock is resized is handled by the
# Expanding size policy below, not a maximum.
_MIN_HEIGHT = 220


class CameraPreviewWidget(VideoRenderWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumHeight(_MIN_HEIGHT)
        # Claims the Status panel's full available width and any leftover
        # vertical space beyond its other, fixed-size rows (see
        # status_panel.py's _build_camera_preview_section(), which gives
        # this widget the stretch factor) -- VideoRenderWidget.paintEvent()'s
        # own aspect-ratio-preserving letterboxing (compute_video_rect())
        # keeps the actual image itself from ever stretching, however large
        # this widget's box gets.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
