"""Guided first-launch setup (prompt.md section 18). Shows live pass/warn/
fail status for the things AndroidLink actually needs, with plain-language
guidance for anything that isn't ready yet.

Deliberately has no "Fix Automatically" button: every real fix here is
either installing third-party software (ADB, OBS/Unity Capture, a virtual
audio cable) or a physical action on the phone itself (accepting the "Allow
USB debugging?" prompt) -- nothing this app could silently do on the user's
behalf without violating prompt.md section 25/37 (never silently install
drivers or modify security-sensitive Android settings; no fake-functional
controls). "Recheck" re-runs the real checks instead.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.setup.checks import CheckStatus, SetupCheck, run_setup_checks
from androidlink.ui.widgets.status_dot import StatusDot, StatusState

_STATUS_MAP = {
    CheckStatus.OK: StatusState.CONNECTED,
    CheckStatus.WARNING: StatusState.CONNECTING,
    CheckStatus.ERROR: StatusState.ERROR,
    CheckStatus.INFO: StatusState.UNKNOWN,
}


class SetupWizardDialog(QDialog):
    def __init__(
        self,
        device_manager: DeviceManager,
        settings_manager: SettingsManager,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Android Setup")
        self.setMinimumWidth(480)

        self._device_manager = device_manager
        self._settings_manager = settings_manager

        layout = QVBoxLayout(self)

        title = QLabel("ANDROID SETUP")
        title.setProperty("role", "panel-title")
        layout.addWidget(title)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 8, 0, 8)
        self._rows_layout.setSpacing(6)
        layout.addWidget(self._rows_container)

        guide_title = QLabel("SETUP GUIDE")
        guide_title.setProperty("role", "muted")
        layout.addWidget(guide_title)

        self._guidance_label = QLabel("Everything looks good.")
        self._guidance_label.setProperty("role", "muted")
        self._guidance_label.setWordWrap(True)
        layout.addWidget(self._guidance_label)

        layout.addStretch(1)

        buttons_row = QHBoxLayout()
        recheck_button = QPushButton("Recheck")
        recheck_button.clicked.connect(self._run_checks)
        buttons_row.addWidget(recheck_button)
        buttons_row.addStretch(1)
        self._dont_show_checkbox = QCheckBox("Don't show this again")
        buttons_row.addWidget(self._dont_show_checkbox)
        close_button = QPushButton("Close")
        close_button.setProperty("role", "primary")
        close_button.clicked.connect(self._on_close)
        buttons_row.addWidget(close_button)
        layout.addLayout(buttons_row)

        device_manager.devices_changed.connect(self._run_checks)
        device_manager.adb_available_changed.connect(self._run_checks)

        self._run_checks()

    def _run_checks(self, *_args) -> None:
        self._render(run_setup_checks(self._device_manager))

    def _render(self, checks: list[SetupCheck]) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        guidance_lines = []
        for check in checks:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)

            dot = StatusDot(_STATUS_MAP[check.status])
            label = QLabel(check.label)
            detail = QLabel(check.detail)
            detail.setProperty("role", "muted")

            row_layout.addWidget(dot)
            row_layout.addWidget(label)
            row_layout.addStretch(1)
            row_layout.addWidget(detail)
            self._rows_layout.addWidget(row)

            if check.guidance and check.status in (CheckStatus.WARNING, CheckStatus.ERROR):
                guidance_lines.append(f"• {check.label}: {check.guidance}")

        self._guidance_label.setText(
            "\n".join(guidance_lines) if guidance_lines else "Everything looks good."
        )

    def _on_close(self) -> None:
        if self._dont_show_checkbox.isChecked():
            self._settings_manager.settings.general.setup_wizard_completed = True
            self._settings_manager.save()
        self.accept()
