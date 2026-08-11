import numpy as np
from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QWidget

from androidlink.input.touch_mapper import (
    clamp_widget_point_to_frame,
    compute_video_rect,
    map_widget_point_to_frame,
)
from androidlink.ui.themes import palette


class VideoRenderWidget(QWidget):
    """Paints decoded RGB frames, preserving aspect ratio, no stretching.

    Frame decoding happens off the UI thread (see streaming/transport.py);
    this widget only ever receives already-decoded numpy arrays via
    set_frame() (called through a queued Qt signal/slot connection so it
    always executes on the GUI thread) and repaints — no decode work here.

    The numpy array backing the current QImage is kept alive as an instance
    attribute rather than copied into Qt-owned memory, to avoid an extra
    full-frame copy on every frame (prompt.md section 34: minimize copies).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frame_buffer: np.ndarray | None = None
        self._image: QImage | None = None
        self.setMinimumSize(1, 1)
        # Focusable-by-click so KeyboardInputHandler (input/keyboard.py) only
        # receives key events while this widget is the focused one.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_frame(self, frame: np.ndarray) -> None:
        if not frame.flags["C_CONTIGUOUS"]:
            frame = np.ascontiguousarray(frame)

        height, width, _channels = frame.shape
        self._frame_buffer = frame  # keep alive: QImage below is a view, not a copy
        self._image = QImage(
            frame.data, width, height, frame.strides[0], QImage.Format.Format_RGB888
        )
        self.update()

    def clear_frame(self) -> None:
        self._frame_buffer = None
        self._image = None
        self.update()

    def has_frame(self) -> bool:
        return self._image is not None

    def frame_size(self) -> QSize:
        return self._image.size() if self._image is not None else QSize()

    def map_to_frame(self, widget_pos: QPointF) -> QPointF | None:
        """Widget-local pixel position -> video frame coordinates, or None
        if outside the letterboxed video image (see input/touch_mapper.py)."""
        return map_widget_point_to_frame(widget_pos, self.size(), self.frame_size())

    def clamp_to_frame(self, widget_pos: QPointF) -> QPointF | None:
        """Like map_to_frame, but clamps into the video image instead of
        returning None — used while dragging, so a drag doesn't cancel just
        because the cursor strayed into the letterbox padding."""
        return clamp_widget_point_to_frame(widget_pos, self.size(), self.frame_size())

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(palette.BG_WINDOW))

        if self._image is None:
            return

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        target_rect = compute_video_rect(self.size(), self._image.size())
        painter.drawImage(target_rect, self._image)
