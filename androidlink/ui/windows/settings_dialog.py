"""Full multi-section Settings page (prompt.md section 27).

Follows the persistence pattern established elsewhere in the app (see
device_panel.py/camera_controller.py/mic_controller.py): load the current
value into each control on dialog open, save on change. Continuous controls
(sliders) save once on release, not per-tick, matching the main window's
Performance/Quality slider and the Device panel's volume sliders.

Only controls tied to a real, working settings field are enabled. Where a
field isn't wired to anything yet (camera/microphone selection require a
live connected device the dialog doesn't have; codec forcing and recording
format alternatives aren't implemented), the control is greyed out with a
tooltip explaining why -- the same honesty pattern already used throughout
(e.g. device_panel.py's camera Resolution combo).
"""

import logging
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from androidlink.audio.mic_controller import MicController
from androidlink.audio.virtual_audio import is_likely_virtual_cable
from androidlink.device.display_info import FALLBACK_HZ, MAX_STREAM_FPS
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.controller import CastingController
from androidlink.streaming.protocol import (
    AUDIO_SOURCE_MIC,
    AUDIO_SOURCE_MIC_CAMCORDER,
    AUDIO_SOURCE_MIC_UNPROCESSED,
    AUDIO_SOURCE_MIC_VOICE_COMMUNICATION,
    AUDIO_SOURCE_MIC_VOICE_RECOGNITION,
)
from androidlink.ui.themes import palette
from androidlink.ui.widgets.toggle_switch import ToggleSwitch
from androidlink.utils.logging import resolve_log_level, set_log_level
from androidlink.utils.platform import get_logs_dir, get_recordings_dir, open_path_in_explorer

logger = logging.getLogger(__name__)

_AUTOMATIC = "Automatic"

# Mirrors device_panel.py's mic source labels -- duplicated rather than
# imported since that dict is a panel-local display detail, not part of a
# shared module; keeping the two in sync is trivial (values come directly
# from streaming/protocol.py's AUDIO_SOURCE_* constants).
_MIC_SOURCE_LABELS = {
    AUDIO_SOURCE_MIC: "Default Mic",
    AUDIO_SOURCE_MIC_UNPROCESSED: "Unprocessed (raw)",
    AUDIO_SOURCE_MIC_CAMCORDER: "Camcorder Mic",
    AUDIO_SOURCE_MIC_VOICE_RECOGNITION: "Voice Recognition",
    AUDIO_SOURCE_MIC_VOICE_COMMUNICATION: "Voice Communication",
}

_RESOLUTION_OPTIONS = [
    (_AUTOMATIC, None),
    ("Up to 1280×720", 1280),
    ("Up to 1920×1080", 1920),
    ("Up to 2560×1440", 2560),
]
_QUALITY_OPTIONS = [
    ("Standard (encoder default)", "standard"),
    ("High (~12 Mbps)", "high"),
    ("Maximum (~24 Mbps)", "maximum"),
]


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings_manager: SettingsManager,
        *,
        device_manager: DeviceManager,
        casting_controller: CastingController,
        mic_controller: MicController,
        on_accent_changed: Callable[[str], None],
        on_theme_mode_changed: Callable[[str], None] = lambda _mode: None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Settings")
        self.setMinimumSize(520, 480)

        self._settings_manager = settings_manager
        self._device_manager = device_manager
        self._casting_controller = casting_controller
        self._mic_controller = mic_controller
        self._on_accent_changed = on_accent_changed
        self._on_theme_mode_changed = on_theme_mode_changed
        self._original_accent = settings_manager.settings.general.accent_color
        self._pending_accent = self._original_accent
        self._original_theme = settings_manager.settings.general.theme
        self._pending_theme = self._original_theme

        outer = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_streaming_tab(), "Streaming")
        tabs.addTab(self._build_audio_tab(), "Audio")
        tabs.addTab(self._build_camera_tab(), "Camera")
        tabs.addTab(self._build_microphone_tab(), "Microphone")
        tabs.addTab(self._build_recording_tab(), "Recording")
        tabs.addTab(self._build_device_tab(), "Device")
        tabs.addTab(self._build_diagnostics_tab(), "Diagnostics")
        outer.addWidget(tabs)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self._cancel)
        outer.addWidget(buttons)

    def _save(self) -> None:
        self._settings_manager.save()

    # -- General ------------------------------------------------------

    def _build_general_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)

        # Built from palette.py's PRESETS registry rather than a fixed list
        # here -- adding a new theme preset only means adding it there.
        self._theme_options = [(p.label, p.id) for p in palette.PRESETS.values()]
        self._theme_combo = QComboBox()
        for label, _theme_id in self._theme_options:
            self._theme_combo.addItem(label)
        self._theme_combo.setCurrentIndex(self._index_for_value(self._theme_options, self._pending_theme))
        self._theme_combo.setToolTip("Applies immediately; persists across restarts")
        self._theme_combo.currentIndexChanged.connect(self._on_theme_combo_changed)
        layout.addRow("Theme", self._theme_combo)

        self._accent_button = QPushButton()
        self._update_accent_button()
        self._accent_button.clicked.connect(self._pick_accent_color)
        layout.addRow("Accent Color", self._accent_button)

        return widget

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

    def _on_theme_combo_changed(self, index: int) -> None:
        self._pending_theme = self._theme_options[index][1]
        self._on_theme_mode_changed(self._pending_theme)

    # -- Streaming ------------------------------------------------------

    def _build_streaming_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        streaming = self._settings_manager.settings.streaming

        performance_slider_info = QLabel(
            "Performance ↔ Quality is set from the Device panel, directly under "
            "Microphone -- there's only one copy of that control. Changes there apply "
            "immediately to an active cast session."
        )
        performance_slider_info.setProperty("role", "muted")
        performance_slider_info.setWordWrap(True)
        layout.addRow("Performance ↔ Quality", performance_slider_info)

        advanced_group = QGroupBox("Advanced")
        advanced_group.setToolTip(
            "Changing Resolution/FPS/Bitrate restarts casting immediately if it's currently "
            "active -- scrcpy can't change these on an already-running session"
        )
        advanced_layout = QFormLayout(advanced_group)

        self._resolution_combo = QComboBox()
        for label, _value in _RESOLUTION_OPTIONS:
            self._resolution_combo.addItem(label)
        self._resolution_combo.setCurrentIndex(
            self._index_for_value(_RESOLUTION_OPTIONS, streaming.resolution_override)
        )
        self._resolution_combo.currentIndexChanged.connect(self._on_resolution_override_changed)
        advanced_layout.addRow("Resolution", self._resolution_combo)

        self._fps_options = self._build_fps_options()
        self._fps_combo = QComboBox()
        for label, _value in self._fps_options:
            self._fps_combo.addItem(label)
        self._fps_combo.setCurrentIndex(self._index_for_value(self._fps_options, streaming.fps_override))
        if len(self._fps_options) <= 1:
            self._fps_combo.setEnabled(False)
            self._fps_combo.setToolTip("Connect a device to detect the frame rates its screen actually supports")
        else:
            self._fps_combo.setToolTip(
                "Only rates this device's screen actually reports supporting are listed"
            )
        self._fps_combo.currentIndexChanged.connect(self._on_fps_override_changed)
        advanced_layout.addRow("FPS", self._fps_combo)

        self._bitrate_spin = QDoubleSpinBox()
        self._bitrate_spin.setRange(0, 50)
        self._bitrate_spin.setSingleStep(1)
        self._bitrate_spin.setSuffix(" Mbps")
        self._bitrate_spin.setSpecialValueText(_AUTOMATIC)
        self._bitrate_spin.setValue(streaming.bitrate_override_mbps or 0)
        self._bitrate_spin.setToolTip("0 = automatic (derived from the slider above)")
        self._bitrate_spin.editingFinished.connect(self._on_bitrate_override_committed)
        advanced_layout.addRow("Bitrate", self._bitrate_spin)

        codec_combo = QComboBox()
        codec_combo.addItem("Automatic (device-selected)")
        codec_combo.setEnabled(False)
        codec_combo.setToolTip(
            "scrcpy lets the Android device pick a codec its hardware encoder "
            "supports; forcing a specific codec isn't implemented"
        )
        advanced_layout.addRow("Codec", codec_combo)

        layout.addRow(advanced_group)
        return widget

    @staticmethod
    def _index_for_value(options: list[tuple[str, object]], value: object) -> int:
        for i, (_label, option_value) in enumerate(options):
            if option_value == value:
                return i
        return 0

    def _automatic_fps(self) -> int:
        device = self._device_manager.active_device
        hz = (device.refresh_rate_hz if device else None) or FALLBACK_HZ
        return min(hz, MAX_STREAM_FPS)

    def _build_fps_options(self) -> list[tuple[str, int | None]]:
        """Only offers rates the connected device's screen actually reports
        supporting (prompt.md: "only display/select modes that are
        realistically supported") -- device/display_info.py's detection,
        not a fixed 30/60 cap -- further filtered to MAX_STREAM_FPS (165):
        the app never requests above that, so a device panel capable of e.g.
        240Hz simply won't offer 240 as a manual choice. Automatic is always
        present and targets the device's own current refresh rate (also
        capped) rather than a hardcoded number."""
        device = self._device_manager.active_device
        if device is not None and device.supported_refresh_rates_hz:
            offerable_rates = [hz for hz in device.supported_refresh_rates_hz if hz <= MAX_STREAM_FPS]
            options: list[tuple[str, int | None]] = [
                (f"{_AUTOMATIC} ({self._automatic_fps()} Hz -- matches the device's screen)", None)
            ]
            options += [(f"{hz} Hz", hz) for hz in offerable_rates]
            return options
        return [(f"{_AUTOMATIC} ({FALLBACK_HZ} Hz -- no device connected to detect a real rate)", None)]

    def _on_resolution_override_changed(self, index: int) -> None:
        self._settings_manager.settings.streaming.resolution_override = _RESOLUTION_OPTIONS[index][1]
        self._save()
        self._casting_controller.restart_if_casting()

    def _on_fps_override_changed(self, index: int) -> None:
        self._settings_manager.settings.streaming.fps_override = self._fps_options[index][1]
        self._save()
        self._casting_controller.restart_if_casting()

    def _on_bitrate_override_committed(self) -> None:
        value = self._bitrate_spin.value()
        self._settings_manager.settings.streaming.bitrate_override_mbps = value or None
        self._save()
        self._casting_controller.restart_if_casting()

    # -- Audio ------------------------------------------------------

    def _build_audio_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        audio = self._settings_manager.settings.audio

        self._audio_enabled_toggle = ToggleSwitch(checked=audio.enabled)
        self._audio_enabled_toggle.setToolTip(
            "Default state the Device panel's Audio toggle starts at on next launch"
        )
        self._audio_enabled_toggle.toggled.connect(self._on_audio_enabled_changed)
        layout.addRow("Android Audio", self._audio_enabled_toggle)

        volume_row, self._audio_volume_slider = self._build_volume_row(audio.volume)
        self._audio_volume_slider.setToolTip("Applied immediately if Android audio is currently playing")
        self._audio_volume_slider.sliderReleased.connect(self._on_audio_volume_committed)
        layout.addRow("Volume", volume_row)

        self._audio_output_combo = QComboBox()
        self._populate_audio_output_combo()
        self._audio_output_combo.currentIndexChanged.connect(self._on_audio_output_changed)
        self._audio_output_combo.setToolTip(
            "Restarts casting immediately if Android Audio is currently active"
        )
        layout.addRow("Output Device", self._audio_output_combo)

        self._audio_output_warning_label = QLabel()
        self._audio_output_warning_label.setProperty("role", "muted")
        self._audio_output_warning_label.setWordWrap(True)
        self._audio_output_warning_label.hide()
        layout.addRow("", self._audio_output_warning_label)
        self._update_audio_output_warning()

        self._audio_secondary_output_combo = QComboBox()
        self._populate_audio_secondary_output_combo()
        self._audio_secondary_output_combo.currentIndexChanged.connect(
            self._on_audio_secondary_output_changed
        )
        self._audio_secondary_output_combo.setToolTip(
            "Play the same audio to a second device at once -- e.g. real speakers "
            "*and* a virtual-audio-cable so another app can pick it up too. Restarts "
            "casting immediately if Android Audio is currently active"
        )
        layout.addRow("Also Output To", self._audio_secondary_output_combo)

        return widget

    @staticmethod
    def _build_volume_row(value: int) -> tuple[QWidget, QSlider]:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(value)
        value_label = QLabel(str(value))
        value_label.setProperty("role", "mono")
        slider.valueChanged.connect(lambda v: value_label.setText(str(v)))
        row_layout.addWidget(slider, stretch=1)
        row_layout.addWidget(value_label)
        return row, slider

    def _populate_audio_output_combo(self) -> None:
        current_id_hex = self._settings_manager.settings.audio.output_device_id
        self._audio_output_combo.blockSignals(True)
        self._audio_output_combo.clear()
        self._audio_output_combo.addItem("System Default", None)
        selected_index = 0
        for i, device in enumerate(QMediaDevices.audioOutputs(), start=1):
            device_id_hex = bytes(device.id()).hex()
            self._audio_output_combo.addItem(device.description(), device_id_hex)
            if device_id_hex == current_id_hex:
                selected_index = i
        self._audio_output_combo.setCurrentIndex(selected_index)
        self._audio_output_combo.blockSignals(False)

    def _update_audio_output_warning(self) -> None:
        """Warns when Android Audio is about to silently play into a
        virtual-audio-cable instead of real speakers/headphones -- confirmed
        via real hardware (prompt.md section 21/33: never fail silently)
        that installing a virtual-cable driver (e.g. for the Mic feature)
        can set it as *Windows'* system-wide default playback device,
        making "System Default" here route Android's audio into a device
        nothing is listening to, even though decoding/playback succeeds
        with no error anywhere in the pipeline. Only warns for "System
        Default" -- if the user explicitly picked the cable themselves,
        that's an intentional choice (e.g. routing into OBS), not a trap.
        """
        if self._audio_output_combo.currentData() is not None:
            self._audio_output_warning_label.hide()
            return

        default_device = QMediaDevices.defaultAudioOutput()
        if default_device.isNull() or not is_likely_virtual_cable(default_device):
            self._audio_output_warning_label.hide()
            return

        self._audio_output_warning_label.setText(
            f'⚠ Your Windows default playback device is currently "{default_device.description()}" '
            "-- a virtual audio cable, not real speakers/headphones. Android Audio will decode and "
            "play successfully but be silent to you. Pick a real output device above, or change the "
            "Windows default in Settings > Sound."
        )
        self._audio_output_warning_label.show()

    def _on_audio_enabled_changed(self, checked: bool) -> None:
        self._settings_manager.settings.audio.enabled = checked
        self._save()

    def _on_audio_volume_committed(self) -> None:
        value = self._audio_volume_slider.value()
        self._settings_manager.settings.audio.volume = value
        self._save()
        self._casting_controller.apply_audio_volume(value)

    def _on_audio_output_changed(self, index: int) -> None:
        self._settings_manager.settings.audio.output_device_id = self._audio_output_combo.itemData(
            index
        )
        self._save()
        self._update_audio_output_warning()
        # A running QAudioSink can't be pointed at a different device --
        # restart so the newly-chosen device takes effect immediately
        # instead of only the next time Audio is toggled on.
        self._casting_controller.restart_if_casting()

    def _populate_audio_secondary_output_combo(self) -> None:
        current_id_hex = self._settings_manager.settings.audio.secondary_output_device_id
        self._audio_secondary_output_combo.blockSignals(True)
        self._audio_secondary_output_combo.clear()
        self._audio_secondary_output_combo.addItem("None (single output only)", None)
        selected_index = 0
        for i, device in enumerate(QMediaDevices.audioOutputs(), start=1):
            device_id_hex = bytes(device.id()).hex()
            self._audio_secondary_output_combo.addItem(device.description(), device_id_hex)
            if device_id_hex == current_id_hex:
                selected_index = i
        self._audio_secondary_output_combo.setCurrentIndex(selected_index)
        self._audio_secondary_output_combo.blockSignals(False)

    def _on_audio_secondary_output_changed(self, index: int) -> None:
        self._settings_manager.settings.audio.secondary_output_device_id = (
            self._audio_secondary_output_combo.itemData(index)
        )
        self._save()
        self._casting_controller.restart_if_casting()

    # -- Camera ------------------------------------------------------

    def _build_camera_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        camera = self._settings_manager.settings.camera

        camera_combo = QComboBox()
        camera_combo.addItem(camera.camera_id or "None selected")
        camera_combo.setEnabled(False)
        camera_combo.setToolTip(
            "Select a camera from the Device panel once a phone is connected "
            "-- the choice is saved automatically"
        )
        layout.addRow("Camera", camera_combo)

        resolution_combo = QComboBox()
        resolution_combo.addItem(_AUTOMATIC)
        resolution_combo.setEnabled(False)
        resolution_combo.setToolTip(
            "Per-resolution selection isn't implemented yet; the device's default is used"
        )
        layout.addRow("Resolution", resolution_combo)

        fps_combo = QComboBox()
        fps_combo.addItem(f"{camera.fps} fps" if camera.fps else _AUTOMATIC)
        fps_combo.setEnabled(False)
        fps_combo.setToolTip(
            "Select FPS from the Device panel once a phone is connected -- "
            "options depend on the connected camera's capabilities"
        )
        layout.addRow("FPS", fps_combo)

        return widget

    # -- Microphone ------------------------------------------------------

    def _build_microphone_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        microphone = self._settings_manager.settings.microphone

        input_combo = QComboBox()
        input_combo.addItem(_MIC_SOURCE_LABELS.get(microphone.audio_source, microphone.audio_source))
        input_combo.setEnabled(False)
        input_combo.setToolTip(
            "Select the input source from the Device panel once a phone is connected"
        )
        layout.addRow("Input", input_combo)

        volume_row, self._mic_volume_slider = self._build_volume_row(microphone.volume)
        self._mic_volume_slider.setToolTip("Applied immediately if the microphone is currently streaming")
        self._mic_volume_slider.sliderReleased.connect(self._on_mic_volume_committed)
        layout.addRow("Volume", volume_row)

        self._mic_mute_toggle = ToggleSwitch(checked=microphone.muted)
        self._mic_mute_toggle.toggled.connect(self._on_mic_mute_changed)
        layout.addRow("Mute", self._mic_mute_toggle)

        return widget

    def _on_mic_volume_committed(self) -> None:
        value = self._mic_volume_slider.value()
        self._settings_manager.settings.microphone.volume = value
        self._save()
        self._mic_controller.apply_volume(value)

    def _on_mic_mute_changed(self, checked: bool) -> None:
        self._settings_manager.settings.microphone.muted = checked
        self._save()
        self._mic_controller.apply_muted(checked)

    # -- Recording ------------------------------------------------------

    def _build_recording_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        recording = self._settings_manager.settings.recording

        location_row = QWidget()
        location_layout = QHBoxLayout(location_row)
        location_layout.setContentsMargins(0, 0, 0, 0)
        self._save_location_edit = QLineEdit(
            recording.save_directory or str(get_recordings_dir())
        )
        self._save_location_edit.setReadOnly(True)
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._on_browse_save_location)
        reset_button = QPushButton("Use Default")
        reset_button.clicked.connect(self._on_reset_save_location)
        location_layout.addWidget(self._save_location_edit, stretch=1)
        location_layout.addWidget(browse_button)
        location_layout.addWidget(reset_button)
        layout.addRow("Save Location", location_row)

        format_combo = QComboBox()
        format_combo.addItem("MP4 (H.264/HEVC + AAC)")
        format_combo.setEnabled(False)
        format_combo.setToolTip("Additional formats aren't implemented yet")
        layout.addRow("Format", format_combo)

        self._quality_combo = QComboBox()
        for label, _value in _QUALITY_OPTIONS:
            self._quality_combo.addItem(label)
        self._quality_combo.setCurrentIndex(
            self._index_for_value(_QUALITY_OPTIONS, recording.quality)
        )
        self._quality_combo.setToolTip(
            "Target video bitrate for new recordings (Standard leaves the encoder's own default)"
        )
        self._quality_combo.currentIndexChanged.connect(self._on_quality_changed)
        layout.addRow("Quality", self._quality_combo)

        return widget

    def _on_browse_save_location(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Choose Recording Save Location", self._save_location_edit.text()
        )
        if not directory:
            return
        self._save_location_edit.setText(directory)
        self._settings_manager.settings.recording.save_directory = directory
        self._save()

    def _on_reset_save_location(self) -> None:
        self._settings_manager.settings.recording.save_directory = None
        self._save()
        self._save_location_edit.setText(str(get_recordings_dir()))

    def _on_quality_changed(self, index: int) -> None:
        self._settings_manager.settings.recording.quality = _QUALITY_OPTIONS[index][1]
        self._save()

    # -- Device ------------------------------------------------------

    def _build_device_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)

        self._connected_device_label = QLabel()
        self._connected_device_label.setProperty("role", "mono")
        self._update_connected_device_label(self._device_manager.active_device)
        self._device_manager.active_device_changed.connect(self._update_connected_device_label)
        layout.addRow("Connected Device", self._connected_device_label)

        reconnect_row = self._build_reconnect_checkbox()
        layout.addRow("Reconnect Behavior", reconnect_row)

        companion_label = QLabel(
            "Not applicable — AndroidLink drives scrcpy directly over ADB; "
            "there is no companion app in this project's architecture."
        )
        companion_label.setProperty("role", "muted")
        companion_label.setWordWrap(True)
        layout.addRow("Companion App", companion_label)

        return widget

    def _build_reconnect_checkbox(self) -> QWidget:
        checkbox = QCheckBox("Automatically reconnect the last device on launch")
        checkbox.setEnabled(False)
        checkbox.setToolTip(
            "Not implemented -- AndroidLink never auto-connects to a device "
            "without an explicit Connect click, by design (prompt.md section 3)"
        )
        return checkbox

    def _update_connected_device_label(self, device=None) -> None:
        device = device if device is not None else self._device_manager.active_device
        self._connected_device_label.setText(device.display_name if device else "None connected")

    # -- Diagnostics ------------------------------------------------------

    def _build_diagnostics_tab(self) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        general = self._settings_manager.settings.general

        self._log_level_combo = QComboBox()
        self._log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self._log_level_combo.setCurrentText(general.logging_level)
        self._log_level_combo.setEnabled(not general.debug_mode)
        self._log_level_combo.currentTextChanged.connect(self._on_log_level_changed)
        layout.addRow("Logging Level", self._log_level_combo)

        self._debug_mode_toggle = ToggleSwitch(checked=general.debug_mode)
        self._debug_mode_toggle.setToolTip("Forces the Logging Level to DEBUG")
        self._debug_mode_toggle.toggled.connect(self._on_debug_mode_changed)
        layout.addRow("Debug Mode", self._debug_mode_toggle)

        metrics_label = QLabel(
            "Live performance metrics (FPS, latency, bitrate, CPU/RAM) are shown "
            "in the Status panel while casting is active."
        )
        metrics_label.setProperty("role", "muted")
        metrics_label.setWordWrap(True)
        layout.addRow("Performance Metrics", metrics_label)

        open_logs_button = QPushButton("Open Logs Folder")
        open_logs_button.clicked.connect(lambda: open_path_in_explorer(get_logs_dir()))
        layout.addRow(open_logs_button)

        return widget

    def _apply_log_level(self) -> None:
        general = self._settings_manager.settings.general
        set_log_level(resolve_log_level(general.logging_level, general.debug_mode))

    def _on_log_level_changed(self, level: str) -> None:
        self._settings_manager.settings.general.logging_level = level
        self._save()
        self._apply_log_level()

    def _on_debug_mode_changed(self, checked: bool) -> None:
        self._settings_manager.settings.general.debug_mode = checked
        self._log_level_combo.setEnabled(not checked)
        self._save()
        self._apply_log_level()

    # -- Dialog buttons ------------------------------------------------------

    def _accept(self) -> None:
        self._settings_manager.settings.general.accent_color = self._pending_accent
        self._settings_manager.settings.general.theme = self._pending_theme
        self._save()
        self.accept()

    def _cancel(self) -> None:
        if self._pending_accent != self._original_accent:
            self._on_accent_changed(self._original_accent)
        if self._pending_theme != self._original_theme:
            self._on_theme_mode_changed(self._original_theme)
        self.reject()
