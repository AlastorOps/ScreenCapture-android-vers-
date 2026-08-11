from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from androidlink.ui.themes import palette

_QSS_DIR = Path(__file__).parent / "qss"


def _mix(color: QColor, background: QColor, alpha_percent: int) -> QColor:
    ratio = alpha_percent / 100.0
    r = int(color.red() * ratio + background.red() * (1 - ratio))
    g = int(color.green() * ratio + background.green() * (1 - ratio))
    b = int(color.blue() * ratio + background.blue() * (1 - ratio))
    return QColor(r, g, b)


def _readable_text_for(accent: QColor, p: palette.Palette) -> str:
    """Picks light or dark text for text painted on top of the accent color
    itself (e.g. the primary button), based on the accent's own luminance --
    independent of the active preset, since a user-chosen accent can be
    light or dark under any theme (e.g. a dark purple accent under a light
    preset still needs light text on it, not the preset's own dark text)."""
    # ITU-R BT.601 perceptual luma.
    luma = 0.299 * accent.red() + 0.587 * accent.green() + 0.114 * accent.blue()
    return p.bg_window if luma > 150 else p.text_primary if not p.is_dark else "#f5f5f5"


class ThemeManager:
    """Owns the app-wide QSS stylesheet and the palette.py module state that
    hand-painted widgets (ToggleSwitch/StatusDot/VideoRenderWidget) read
    live from paintEvent(). apply_theme() is the single place both are kept
    in sync, so nothing else in the app needs its own theme-change wiring.
    """

    def __init__(self, app: QApplication) -> None:
        self._app = app
        self._base_template = (_QSS_DIR / "base.qss.tmpl").read_text(encoding="utf-8")
        self._accent_template = (_QSS_DIR / "accent.qss.tmpl").read_text(encoding="utf-8")
        self._current_accent = palette.DEFAULT_ACCENT
        self._current_theme: str = palette.DARK.id

    @property
    def current_accent(self) -> str:
        return self._current_accent

    @property
    def current_theme(self) -> str:
        return self._current_theme

    def set_theme(self, theme_id: str) -> None:
        """Convenience for callers that only ever change the preset (the
        Settings dialog's Theme combo) without also touching the accent."""
        self.apply_theme(self._current_accent, theme_id)

    def apply_theme(self, accent_hex: str, theme_id: str | None = None) -> None:
        """theme_id=None keeps whatever preset is already active -- lets
        existing callers that only ever dealt with accent color
        (main_window.py's live accent preview, every test that predates
        multiple presets) keep calling this with a single argument."""
        self._current_accent = accent_hex
        if theme_id is not None:
            self._current_theme = theme_id

        palette.set_theme(self._current_theme)
        palette.set_accent(accent_hex)
        p = palette.current()

        accent = QColor(accent_hex)
        # Under a dark preset, lighten on hover (moving toward the bright
        # panel text); under a light preset that would blow a light accent
        # out toward white with no contrast left, so darken instead.
        accent_hover = accent.lighter(115) if p.is_dark else accent.darker(110)
        accent_muted = _mix(accent, QColor(p.bg_panel), 35)
        accent_contrast_text = _readable_text_for(accent, p)

        base_qss = (
            self._base_template.replace("{bg_window}", p.bg_window)
            .replace("{bg_panel}", p.bg_panel)
            .replace("{bg_elevated}", p.bg_elevated)
            .replace("{border}", p.border)
            .replace("{text_primary}", p.text_primary)
            .replace("{text_secondary}", p.text_secondary)
            .replace("{text_muted}", p.text_muted)
        )
        accent_qss = (
            self._accent_template.replace("{accent_hover}", accent_hover.name())
            .replace("{accent_muted}", accent_muted.name())
            .replace("{accent_contrast_text}", accent_contrast_text)
            .replace("{bg_elevated}", p.bg_elevated)
            .replace("{border}", p.border)
            .replace("{text_muted}", p.text_muted)
            .replace("{accent}", accent.name())
        )

        self._app.setStyleSheet(base_qss + "\n" + accent_qss)
        self._repaint_all_widgets()

    def _repaint_all_widgets(self) -> None:
        """Forces every existing widget to repaint immediately so hand-
        painted widgets (which don't participate in the QSS above) pick up
        the new palette.py state right away instead of waiting for their
        next unrelated repaint. setStyleSheet() alone only guarantees this
        for widgets that are actually styled by a stylesheet rule."""
        for widget in self._app.allWidgets():
            widget.update()
