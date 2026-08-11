from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

_QSS_DIR = Path(__file__).parent / "qss"


def _lighten(color: QColor, factor: int) -> QColor:
    return color.lighter(factor)


def _mix_with_background(color: QColor, alpha_percent: int) -> QColor:
    bg = QColor("#15171b")
    ratio = alpha_percent / 100.0
    r = int(color.red() * ratio + bg.red() * (1 - ratio))
    g = int(color.green() * ratio + bg.green() * (1 - ratio))
    b = int(color.blue() * ratio + bg.blue() * (1 - ratio))
    return QColor(r, g, b)


class ThemeManager:
    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._base_qss = (_QSS_DIR / "base.qss").read_text(encoding="utf-8")
        self._accent_template = (_QSS_DIR / "accent.qss.tmpl").read_text(encoding="utf-8")
        self._current_accent = "#7aa2f7"

    @property
    def current_accent(self) -> str:
        return self._current_accent

    def apply_theme(self, accent_hex: str) -> None:
        self._current_accent = accent_hex
        accent = QColor(accent_hex)
        accent_hover = _lighten(accent, 115)
        accent_muted = _mix_with_background(accent, 35)

        accent_qss = (
            self._accent_template.replace("{accent_hover}", accent_hover.name())
            .replace("{accent_muted}", accent_muted.name())
            .replace("{accent}", accent.name())
        )

        self._app.setStyleSheet(self._base_qss + "\n" + accent_qss)
