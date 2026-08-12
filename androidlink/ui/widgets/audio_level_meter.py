"""Real-time horizontal microphone level meter. Hand-painted like
StatusDot/ToggleSwitch/VideoRenderWidget (see themes/palette.py's module
docstring) -- reads palette.current()/current_accent() inside paintEvent()
rather than caching a color, so a theme or accent change is picked up on
the next repaint with no signal wiring needed, and never hardcodes a color
that would ignore the active theme.

Applies fast-attack/slow-release ballistics to whatever set_level() is
called with -- a standard, real VU-meter behavior (rise immediately to a
loud sound, decay gradually after it stops) that smooths *display* jitter
between successive real measurements. This is not fake/randomized movement:
every displayed value still chases an actually-measured level from
set_level() (see audio/level_meter.py's compute_rms_level()); it just
doesn't jump discontinuously between two real values.
"""

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from androidlink.ui.themes import palette

_ATTACK = 0.6  # fraction of the gap to a *higher* new level closed per update
_RELEASE = 0.15  # fraction of the gap to a *lower* new level closed per update
_VISIBLE_THRESHOLD = 0.002  # below this, treat as exactly silent (no sliver of fill)


class AudioLevelMeter(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._displayed_level = 0.0
        self.setMinimumHeight(10)
        self.setMaximumHeight(14)

    def set_level(self, level: float) -> None:
        """level: a real measured value in [0, 1] (see compute_rms_level()).
        Out-of-range input is clamped rather than trusted, since this always
        ends up on screen."""
        level = max(0.0, min(1.0, level))
        rate = _ATTACK if level > self._displayed_level else _RELEASE
        self._displayed_level += (level - self._displayed_level) * rate
        if self._displayed_level < _VISIBLE_THRESHOLD:
            self._displayed_level = 0.0
        self.update()

    def reset(self) -> None:
        """Snaps immediately to zero -- used when the mic is disabled/
        disconnected, where a lingering decay would misrepresent a signal
        that has actually stopped entirely rather than just gone quiet."""
        self._displayed_level = 0.0
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        p = palette.current()
        rect = QRectF(self.rect())
        radius = rect.height() / 2

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(p.bg_elevated))
        painter.drawRoundedRect(rect, radius, radius)

        if self._displayed_level > 0.0:
            filled_rect = QRectF(rect)
            filled_rect.setWidth(rect.width() * self._displayed_level)
            painter.setBrush(QColor(palette.current_accent()))
            painter.drawRoundedRect(filled_rect, radius, radius)
