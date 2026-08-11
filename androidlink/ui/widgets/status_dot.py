from enum import Enum

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from androidlink.ui.themes import palette

_DIAMETER = 8


class StatusState(Enum):
    UNKNOWN = "unknown"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


def _state_color(state: "StatusState") -> str:
    # Resolved at paint time (not cached at import time) so a theme switch
    # is reflected immediately -- see palette.py's module docstring.
    p = palette.current()
    return {
        StatusState.UNKNOWN: p.text_muted,
        StatusState.DISCONNECTED: p.text_muted,
        StatusState.CONNECTING: p.warning,
        StatusState.CONNECTED: p.success,
        StatusState.ERROR: p.error,
    }[state]


class StatusDot(QWidget):
    def __init__(self, state: StatusState = StatusState.UNKNOWN, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setFixedSize(_DIAMETER, _DIAMETER)

    def setState(self, state: StatusState) -> None:
        self._state = state
        self.update()

    def state(self) -> StatusState:
        return self._state

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_state_color(self._state)))
        painter.drawEllipse(QRectF(0, 0, _DIAMETER, _DIAMETER))
