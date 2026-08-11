import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from androidlink.ui.panels.base_panel import BasePanel
from androidlink.ui.widgets.status_dot import StatusDot, StatusState

_METRICS = ["FPS", "Latency", "Bitrate", "Resolution"]


class StatusPanel(BasePanel):
    """Shows live streaming metrics and PC-side recording controls
    (prompt.md section 14).

    Phase 1 placeholder: the FPS/Latency/Bitrate/Resolution metrics render
    as em-dashes rather than fabricated numbers -- no measurement pipeline
    exists yet to back them (that's Phase 9's Diagnostics work, prompt.md
    section 20). Recording (Phase 8) is real: start/stop/pause and
    screenshot both require an active Cast session (there's nothing to
    record otherwise), enabled/reflected by RecordingController.
    """

    record_toggled = Signal(bool)
    pause_toggled = Signal(bool)
    screenshot_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Status", parent)

        for metric in _METRICS:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)

            label = QLabel(metric)
            label.setProperty("role", "muted")

            value = QLabel("—")
            value.setProperty("role", "mono")

            row_layout.addWidget(label)
            row_layout.addStretch(1)
            row_layout.addWidget(value)
            self.content_layout.addWidget(row)

        self.content_layout.addSpacing(12)
        self.content_layout.addWidget(self._build_recording_controls())
        self.content_layout.addStretch(1)

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._recording_start_time: float | None = None

    def _build_recording_controls(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        title = QLabel("RECORDING")
        title.setProperty("role", "muted")
        layout.addWidget(title)

        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        self._recording_dot = StatusDot(StatusState.DISCONNECTED)
        self._recording_status_label = QLabel("Idle")
        self._recording_status_label.setProperty("role", "mono")
        self._recording_timer_label = QLabel("00:00")
        self._recording_timer_label.setProperty("role", "mono")
        status_layout.addWidget(self._recording_dot)
        status_layout.addWidget(self._recording_status_label)
        status_layout.addStretch(1)
        status_layout.addWidget(self._recording_timer_label)
        layout.addWidget(status_row)

        buttons_row = QWidget()
        buttons_layout = QHBoxLayout(buttons_row)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        self._record_button = QPushButton("Record")
        self._record_button.setCheckable(True)
        self._record_button.setEnabled(False)
        self._record_button.toggled.connect(self._on_record_button_toggled)
        self._pause_button = QPushButton("Pause")
        self._pause_button.setCheckable(True)
        self._pause_button.setEnabled(False)
        self._pause_button.toggled.connect(self._on_pause_button_toggled)
        buttons_layout.addWidget(self._record_button)
        buttons_layout.addWidget(self._pause_button)
        layout.addWidget(buttons_row)

        self._screenshot_button = QPushButton("Screenshot")
        self._screenshot_button.setEnabled(False)
        self._screenshot_button.clicked.connect(self.screenshot_requested)
        layout.addWidget(self._screenshot_button)

        self._recording_message_label = QLabel()
        self._recording_message_label.setProperty("role", "muted")
        self._recording_message_label.setWordWrap(True)
        self._recording_message_label.hide()
        layout.addWidget(self._recording_message_label)

        return container

    def _on_record_button_toggled(self, checked: bool) -> None:
        self._pause_button.setEnabled(checked)
        if not checked:
            self._pause_button.blockSignals(True)
            self._pause_button.setChecked(False)
            self._pause_button.blockSignals(False)
        self.record_toggled.emit(checked)

    def _on_pause_button_toggled(self, checked: bool) -> None:
        self.pause_toggled.emit(checked)
        self._recording_status_label.setText("Paused" if checked else "Recording")
        self._recording_dot.setState(
            StatusState.DISCONNECTED if checked else StatusState.CONNECTED
        )

    def _tick_elapsed(self) -> None:
        if self._recording_start_time is None:
            return
        elapsed = int(time.monotonic() - self._recording_start_time)
        self._recording_timer_label.setText(f"{elapsed // 60:02d}:{elapsed % 60:02d}")

    def _reset_recording_ui(self) -> None:
        self._elapsed_timer.stop()
        self._recording_start_time = None
        self._recording_status_label.setText("Idle")
        self._recording_dot.setState(StatusState.DISCONNECTED)
        self._recording_timer_label.setText("00:00")

        self._record_button.blockSignals(True)
        self._record_button.setChecked(False)
        self._record_button.blockSignals(False)

        self._pause_button.blockSignals(True)
        self._pause_button.setChecked(False)
        self._pause_button.setEnabled(False)
        self._pause_button.blockSignals(False)

    def set_recording_available(self, available: bool) -> None:
        """Reflects whether Cast is active -- recording/screenshots require
        a live frame source."""
        self._record_button.setEnabled(available)
        self._screenshot_button.setEnabled(available)
        if not available:
            self._reset_recording_ui()
            self._recording_message_label.hide()

    def set_recording_state(self, state: str) -> None:
        self._recording_message_label.hide()
        self._recording_status_label.setText("Recording")
        self._recording_dot.setState(StatusState.CONNECTED)
        self._recording_start_time = time.monotonic()
        self._recording_timer_label.setText("00:00")
        self._elapsed_timer.start()

    def show_recording_error(self, message: str) -> None:
        self._reset_recording_ui()
        self._recording_message_label.setText(message)
        self._recording_message_label.show()

    def show_recording_saved(self, path: str) -> None:
        self._reset_recording_ui()
        self._recording_message_label.setText(f"Saved: {path}")
        self._recording_message_label.show()

    def show_screenshot_saved(self, path: str) -> None:
        self._recording_message_label.setText(f"Screenshot saved: {path}")
        self._recording_message_label.show()
