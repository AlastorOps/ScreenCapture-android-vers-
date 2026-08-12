import time

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from androidlink.ui.panels.base_panel import BasePanel
from androidlink.ui.widgets.camera_preview import CameraPreviewWidget
from androidlink.ui.widgets.status_dot import StatusDot, StatusState

# key -> display label. GPU is listed but never updated -- see
# utils/system_stats.py's docstring for why (no reliable cross-vendor
# reading without a substantial PDH-counter implementation); shown as a
# permanent "—" with a tooltip rather than a fabricated number.
_STREAM_METRICS = [
    ("performance_quality", "Performance/Quality"),
    ("display_refresh", "Display Refresh (Active)"),
    ("max_supported_refresh", "Max Supported Refresh"),
    ("target_fps", "Target FPS"),
    ("stream_fps", "Stream FPS"),
    ("render_fps", "Render FPS"),
    ("dropped", "Dropped Frames"),
    ("late", "Late Frames"),
    ("decode", "Decode Latency"),
    ("bitrate", "Bitrate"),
    ("resolution", "Resolution"),
    ("codec", "Codec"),
]
_SYSTEM_METRICS = [
    ("cpu", "CPU"),
    ("ram", "RAM"),
    ("gpu", "GPU"),
]


def _format_bitrate(bps: float) -> str:
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f} Mbps"
    if bps >= 1_000:
        return f"{bps / 1_000:.0f} kbps"
    return f"{bps:.0f} bps"


class StatusPanel(BasePanel):
    """Shows real measured streaming/system metrics (prompt.md section 20:
    Diagnostics) and PC-side recording controls (prompt.md section 14).

    Every stream metric here is a genuinely measured value -- see
    streaming/transport.py's _emit_stats(), streaming/renderer.py's render
    FPS counter, and utils/system_stats.py's psutil sampler -- rendered as
    "—" only while there's nothing to measure (no active Cast session), per
    prompt.md section 33/34: never fabricate a number like "0 dropped
    frames". Recording: start/stop/pause and screenshot both require an
    active Cast session (there's nothing to record otherwise), enabled and
    reflected by RecordingController.
    """

    record_toggled = Signal(bool)
    pause_toggled = Signal(bool)
    screenshot_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Status", parent)

        self._value_labels: dict[str, QLabel] = {}
        for key, label_text in _STREAM_METRICS + _SYSTEM_METRICS:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)

            label = QLabel(label_text)
            label.setProperty("role", "muted")

            value = QLabel("—")
            value.setProperty("role", "mono")
            self._value_labels[key] = value

            row_layout.addWidget(label)
            row_layout.addStretch(1)
            row_layout.addWidget(value)
            self.content_layout.addWidget(row)

        self._value_labels["gpu"].setToolTip(
            "GPU usage isn't measured yet -- reliable cross-vendor readings "
            "on Windows need Performance Data Helper counter queries, not "
            "yet implemented"
        )

        self.content_layout.addSpacing(12)
        self.content_layout.addWidget(self._build_recording_controls())
        # stretch=1: the Camera Live Preview claims all leftover vertical
        # space in this dock (see _build_camera_preview_section()) instead
        # of a trailing addStretch(1) spacer leaving that space blank --
        # item 4/5: "use the available space efficiently" as the panel is
        # resized, not a small fixed preview with dead space below it.
        self.content_layout.addWidget(self._build_camera_preview_section(), stretch=1)

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._recording_start_time: float | None = None

    def set_stream_stats(self, sample) -> None:
        # One decimal place -- these are genuinely measured, sub-integer-
        # precise values (e.g. "164.7"), unlike the plain-integer Target FPS
        # below; rounding to a whole number would hide real jitter (prompt.md
        # section 33/34: report real measured behavior).
        self._value_labels["stream_fps"].setText(f"{sample.stream_fps:.1f}")
        self._value_labels["dropped"].setText(str(sample.dropped_frames))
        self._value_labels["late"].setText(str(sample.late_frames))
        self._value_labels["decode"].setText(f"{sample.decode_latency_ms:.1f} ms")
        self._value_labels["bitrate"].setText(_format_bitrate(sample.bitrate_bps))
        if sample.resolution is not None:
            self._value_labels["resolution"].setText(
                f"{sample.resolution[0]} × {sample.resolution[1]}"
            )
        if sample.codec is not None:
            suffix = ""
            if sample.hardware_decode is not None:
                suffix = " (HW)" if sample.hardware_decode else " (SW)"
            self._value_labels["codec"].setText(sample.codec.upper() + suffix)

    def set_render_fps(self, fps: float) -> None:
        self._value_labels["render_fps"].setText(f"{fps:.1f}")

    def set_performance_quality(self, value: int) -> None:
        """The Device panel's Performance<->Quality slider position (0 =
        full Performance, 100 = full Quality) -- a current setting, not a
        stream measurement, so unlike the rows below it's always shown
        (even before Cast is ever turned on) and reset_stream_stats() never
        blanks it back to "--" when casting stops."""
        self._value_labels["performance_quality"].setText(f"{value}%")

    def set_target_fps(self, fps: int) -> None:
        """The FPS actually requested from the encoder for the current cast
        session (resolve_streaming_profile()'s resolved max_fps, already
        capped at MAX_STREAM_FPS) -- a target, not a measurement, so it's
        shown as a plain integer rather than alongside the measured FPS
        rows' decimal precision."""
        self._value_labels["target_fps"].setText(str(fps))

    def set_display_refresh(self, hz: int | None) -> None:
        """The connected Android device's own real detected *active*
        display refresh rate (device/display_info.py) -- distinct from Max
        Supported Refresh below: a device idling at 60Hz active can still
        support 90/120Hz, and Automatic FPS targets the supported maximum,
        not this value (see streaming/controller.py's
        _resolve_automatic_fps())."""
        self._value_labels["display_refresh"].setText(f"{hz} Hz" if hz else "—")

    def set_max_supported_refresh(self, supported_hz: tuple[int, ...] | None) -> None:
        """The highest refresh rate the device's screen reports *supporting*
        (may be higher than the current active rate above) -- this, not the
        active rate, is what Automatic FPS actually starts at."""
        text = f"{max(supported_hz)} Hz" if supported_hz else "—"
        self._value_labels["max_supported_refresh"].setText(text)

    def set_system_stats(self, cpu_percent: float, ram_mb: float) -> None:
        self._value_labels["cpu"].setText(f"{cpu_percent:.0f}%")
        self._value_labels["ram"].setText(f"{ram_mb:.0f} MB")

    def reset_stream_stats(self) -> None:
        for key in (
            "display_refresh",
            "max_supported_refresh",
            "target_fps",
            "stream_fps",
            "render_fps",
            "dropped",
            "late",
            "decode",
            "bitrate",
            "resolution",
            "codec",
        ):
            self._value_labels[key].setText("—")

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

    def _build_camera_preview_section(self) -> QWidget:
        """The Camera Live Preview, directly under Screenshot in the Status
        panel's right-side bar -- the only place in the app a decoded
        camera frame is ever shown. Reuses the exact same real-frame render
        path as the main screen mirror (ui/widgets/camera_preview.py wraps
        streaming/renderer.py's VideoRenderWidget, which already preserves
        aspect ratio via letterboxing and scales cleanly as this dock is
        resized), fed by camera/camera_controller.py's _on_frame_available()
        -- never a placeholder image. "Camera: ..." and "Status: ..." below
        it are read-only summaries of the real selection/state; the actual
        camera/resolution/FPS selection controls stay in the Device panel's
        Camera feature row (prompt.md: preserve existing selection
        controls)."""
        container = QWidget()
        # Expanding vertically so this container -- not just the preview
        # widget nested inside it -- actually claims the stretch=1 leftover
        # space __init__ gives it in content_layout; a plain QWidget's
        # default Preferred policy would otherwise clamp back down to its
        # children's combined size hint regardless of how much room the
        # dock has.
        container.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(4)

        title = QLabel("CAMERA PREVIEW")
        title.setProperty("role", "muted")
        layout.addWidget(title)

        self._camera_preview_widget = CameraPreviewWidget()
        self._camera_preview_widget.setToolTip(
            "Live feed from the Android camera -- only active while Camera is on"
        )
        # stretch=1: the preview itself gets all the space this section is
        # given; the label/status/notice rows below keep their natural
        # (minimal) height rather than being squeezed or stretched.
        layout.addWidget(self._camera_preview_widget, stretch=1)

        self._camera_preview_label = QLabel("Camera: —")
        self._camera_preview_label.setProperty("role", "muted")
        layout.addWidget(self._camera_preview_label)

        status_row = QWidget()
        status_layout = QHBoxLayout(status_row)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.setSpacing(6)
        status_title = QLabel("Status:")
        status_title.setProperty("role", "muted")
        self._camera_preview_status_dot = StatusDot(StatusState.DISCONNECTED)
        self._camera_preview_status_text = QLabel("Disabled")
        self._camera_preview_status_text.setProperty("role", "mono")
        status_layout.addWidget(status_title)
        status_layout.addWidget(self._camera_preview_status_dot)
        status_layout.addWidget(self._camera_preview_status_text)
        status_layout.addStretch(1)
        layout.addWidget(status_row)

        # Purely informational -- never disables the camera, never touches
        # FPS/quality/streaming. Small and always visible rather than a
        # popup, matching how _camera_status_label/_recording_message_label
        # already surface asides in this app.
        performance_notice = QLabel(
            "ⓘ Camera preview may affect performance when used with screen casting."
        )
        performance_notice.setProperty("role", "muted")
        performance_notice.setWordWrap(True)
        layout.addWidget(performance_notice)

        return container

    def set_camera_preview_frame(self, frame) -> None:
        """frame: a real decoded RGB24 ndarray from camera/camera_session.py
        -- never a placeholder. Receiving one is itself the only honest
        basis for claiming Active (prompt.md: never show Active when the
        camera isn't actually providing frames)."""
        self._camera_preview_widget.set_frame(frame)
        self._camera_preview_status_dot.setState(StatusState.CONNECTED)
        self._camera_preview_status_text.setText("Active")

    def clear_camera_preview(self) -> None:
        self._camera_preview_widget.clear_frame()

    def set_camera_preview_label(self, camera_name: str) -> None:
        self._camera_preview_label.setText(f"Camera: {camera_name}")

    def set_camera_preview_status_connecting(self) -> None:
        self._camera_preview_status_dot.setState(StatusState.CONNECTING)
        self._camera_preview_status_text.setText("Connecting…")

    def set_camera_preview_status_disabled(self) -> None:
        self._camera_preview_status_dot.setState(StatusState.DISCONNECTED)
        self._camera_preview_status_text.setText("Disabled")
        self.clear_camera_preview()

    def set_camera_preview_status_disconnected(self) -> None:
        self._camera_preview_status_dot.setState(StatusState.DISCONNECTED)
        self._camera_preview_status_text.setText("Disconnected")
        self.clear_camera_preview()
        self.set_camera_preview_label("—")

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
