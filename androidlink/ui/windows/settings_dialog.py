from typing import Callable

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QPushButton,
    QWidget,
)

from androidlink.settings.manager import SettingsManager


class SettingsDialog(QDialog):
    """General settings: Theme + Accent Color only (Phase 1 scope).

    Later phases add Streaming / Audio / Camera / Microphone / Recording /
    Device / Diagnostics sections (see prompt.md section 27).
    """

    def __init__(
        self,
        settings_manager: SettingsManager,
        on_accent_changed: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(360)

        self._settings_manager = settings_manager
        self._on_accent_changed = on_accent_changed
        self._original_accent = settings_manager.settings.general.accent_color
        self._pending_accent = self._original_accent

        layout = QFormLayout(self)

        theme_combo = QComboBox()
        theme_combo.addItem("Dark")
        theme_combo.setEnabled(False)
        theme_combo.setToolTip("Additional themes are not implemented yet")
        layout.addRow("Theme", theme_combo)

        self._accent_button = QPushButton()
        self._update_accent_button()
        self._accent_button.clicked.connect(self._pick_accent_color)
        layout.addRow("Accent Color", self._accent_button)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self._cancel)
        layout.addRow(buttons)

    def _update_accent_button(self) -> None:
        self._accent_button.setText(self._pending_accent)
        self._accent_button.setStyleSheet(
            f"background-color: {self._pending_accent}; color: #0e0f12;"
        )

    def _pick_accent_color(self) -> None:
        color = QColorDialog.getColor(QColor(self._pending_accent), self, "Choose Accent Color")
        if color.isValid():
            self._pending_accent = color.name()
            self._update_accent_button()
            self._on_accent_changed(self._pending_accent)

    def _accept(self) -> None:
        self._settings_manager.settings.general.accent_color = self._pending_accent
        self._settings_manager.save()
        self.accept()

    def _cancel(self) -> None:
        if self._pending_accent != self._original_accent:
            self._on_accent_changed(self._original_accent)
        self.reject()
