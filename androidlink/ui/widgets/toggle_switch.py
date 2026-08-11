from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from androidlink.ui.themes import palette

_WIDTH = 40
_HEIGHT = 20
_MARGIN = 2


class ToggleSwitch(QWidget):
    """A ● ON / ○ OFF style toggle switch (see prompt.md section 13)."""

    toggled = Signal(bool)

    def __init__(self, checked: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(_WIDTH, _HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, checked: bool) -> None:
        if checked == self._checked:
            return
        self._checked = checked
        self.update()
        self.toggled.emit(self._checked)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if self.isEnabled() and event.button() == Qt.MouseButton.LeftButton:
            self.setChecked(not self._checked)
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        p = palette.current()
        track_rect = QRectF(0, 0, _WIDTH, _HEIGHT)
        if not self.isEnabled():
            track_color = QColor(p.bg_elevated)
        elif self._checked:
            # Read live rather than cached -- previously this widget
            # captured palette.DEFAULT_ACCENT once at construction and never
            # updated it, so every toggle switch in the app stayed the
            # default blue regardless of the user's chosen accent color
            # (the matching QSS rule for it was dead: a hand-painted QWidget
            # doesn't apply stylesheet background-color from a property
            # selector without QStyle involvement).
            track_color = QColor(palette.current_accent())
        else:
            track_color = QColor(p.border)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track_rect, _HEIGHT / 2, _HEIGHT / 2)

        knob_diameter = _HEIGHT - 2 * _MARGIN
        knob_x = _WIDTH - _MARGIN - knob_diameter if self._checked else _MARGIN
        knob_color = QColor(p.text_muted) if not self.isEnabled() else QColor(p.bg_window)
        painter.setBrush(knob_color)
        painter.drawEllipse(QRectF(knob_x, _MARGIN, knob_diameter, knob_diameter))
