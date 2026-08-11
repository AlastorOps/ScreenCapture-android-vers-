from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from androidlink.camera.camera_list import CameraInfo
from androidlink.device.device_model import AndroidDevice, ConnectionState
from androidlink.device.manager import DeviceManager
from androidlink.streaming.protocol import (
    AUDIO_SOURCE_MIC,
    AUDIO_SOURCE_MIC_CAMCORDER,
    AUDIO_SOURCE_MIC_UNPROCESSED,
    AUDIO_SOURCE_MIC_VOICE_COMMUNICATION,
    AUDIO_SOURCE_MIC_VOICE_RECOGNITION,
)
from androidlink.ui.panels.base_panel import BasePanel
from androidlink.ui.widgets.status_dot import StatusDot, StatusState
from androidlink.ui.widgets.toggle_switch import ToggleSwitch

_FEATURES = ["Cast", "Control", "Audio", "Camera", "Mic"]
_CAST_DEPENDENT_FEATURES = ("Control", "Audio")
_AUTOMATIC = "Automatic"

_MIC_SOURCE_LABELS = {
    AUDIO_SOURCE_MIC: "Default Mic",
    AUDIO_SOURCE_MIC_UNPROCESSED: "Unprocessed (raw)",
    AUDIO_SOURCE_MIC_CAMCORDER: "Camcorder Mic",
    AUDIO_SOURCE_MIC_VOICE_RECOGNITION: "Voice Recognition",
    AUDIO_SOURCE_MIC_VOICE_COMMUNICATION: "Voice Communication",
}

_CONNECTION_STATUS_MAP = {
    ConnectionState.DEVICE: StatusState.CONNECTED,
    ConnectionState.UNAUTHORIZED: StatusState.ERROR,
    ConnectionState.OFFLINE: StatusState.DISCONNECTED,
    ConnectionState.UNKNOWN: StatusState.UNKNOWN,
}


def _device_detail_text(device: AndroidDevice) -> str:
    if device.connection_state == ConnectionState.DEVICE:
        return f"Android {device.android_version}" if device.android_version else "USB Connected"
    return device.connection_state.value.upper()


class DevicePanel(BasePanel):
    """Shows connected Android devices and feature toggles.

    Device data is live (DeviceManager polls `adb devices -l`). Cast,
    Control, Audio, Camera, and Mic (Phases 3-7) are all real. Camera and
    Mic are independent of Cast (enabled once a device connects), matching
    prompt.md section 13's "every major feature must work independently."

    Control and Audio both require Cast to be on: Control because touch
    coordinates are mapped against the live video frame size, and Audio
    because this implementation shares one scrcpy-server session across all
    three rather than opening a second independent session — a practical
    trade-off, not a hard protocol requirement (audio-only mirroring is
    technically possible in scrcpy itself).
    """

    cast_toggled = Signal(bool)
    control_toggled = Signal(bool)
    audio_toggled = Signal(bool)
    audio_volume_changed = Signal(int)  # 0-100
    audio_mute_toggled = Signal(bool)
    camera_toggled = Signal(bool)
    camera_selection_changed = Signal(str)  # camera_id
    camera_fps_changed = Signal(int)  # 0 = automatic
    mic_toggled = Signal(bool)
    mic_source_changed = Signal(str)  # AUDIO_SOURCE_* value
    mic_volume_changed = Signal(int)  # 0-100
    mic_mute_toggled = Signal(bool)

    def __init__(self, device_manager: DeviceManager, parent: QWidget | None = None) -> None:
        super().__init__("Device", parent)
        self._device_manager = device_manager

        self._adb_status_label = QLabel()
        self._adb_status_label.setProperty("role", "placeholder")
        self._adb_status_label.setWordWrap(True)
        self.content_layout.addWidget(self._adb_status_label)

        self._device_list_container = QWidget()
        self._device_list_layout = QVBoxLayout(self._device_list_container)
        self._device_list_layout.setContentsMargins(0, 0, 0, 0)
        self._device_list_layout.setSpacing(10)
        self.content_layout.addWidget(self._device_list_container)

        self._active_info_label = QLabel()
        self._active_info_label.setProperty("role", "mono")
        self._active_info_label.setWordWrap(True)
        self._active_info_label.hide()
        self.content_layout.addWidget(self._active_info_label)

        self._disconnect_button = QPushButton("Disconnect")
        self._disconnect_button.clicked.connect(self._device_manager.disconnect_device)
        self._disconnect_button.hide()
        self.content_layout.addWidget(self._disconnect_button)

        features_title = QLabel("FEATURES")
        features_title.setProperty("role", "muted")
        self.content_layout.addWidget(features_title)

        self._feature_toggles: dict[str, ToggleSwitch] = {}
        for feature in _FEATURES:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)

            label = QLabel(feature)
            toggle = ToggleSwitch(checked=False)

            if feature == "Cast":
                toggle.setEnabled(False)  # enabled once a device connects
                toggle.setToolTip("Mirror the Android screen into this window")
                toggle.toggled.connect(self._on_cast_toggle_changed)
            elif feature == "Control":
                toggle.setEnabled(False)  # requires Cast to be on (see below)
                toggle.setToolTip("Requires Screen Cast to be enabled first")
                toggle.toggled.connect(self.control_toggled)
            elif feature == "Audio":
                toggle.setEnabled(False)  # requires Cast to be on (see below)
                toggle.setToolTip("Requires Screen Cast to be enabled first")
                toggle.toggled.connect(self._on_audio_toggle_changed)
            elif feature == "Camera":
                toggle.setEnabled(False)  # enabled once a camera is detected
                toggle.setToolTip("Detecting cameras...")
                toggle.toggled.connect(self.camera_toggled)
            elif feature == "Mic":
                toggle.setEnabled(False)  # enabled once a device connects
                toggle.setToolTip("Expose the Android microphone as a Windows input device")
                toggle.toggled.connect(self._on_mic_toggle_changed)
            else:
                toggle.setEnabled(False)
                toggle.setToolTip("Not available until this feature's pipeline is implemented")

            self._feature_toggles[feature] = toggle
            row_layout.addWidget(label)
            row_layout.addStretch(1)
            row_layout.addWidget(toggle)
            self.content_layout.addWidget(row)

            if feature == "Audio":
                self.content_layout.addWidget(self._build_audio_controls())
            elif feature == "Camera":
                self.content_layout.addWidget(self._build_camera_controls())
            elif feature == "Mic":
                self.content_layout.addWidget(self._build_mic_controls())

        self.content_layout.addStretch(1)

        device_manager.adb_available_changed.connect(self._on_adb_available_changed)
        device_manager.devices_changed.connect(self._on_devices_changed)
        device_manager.active_device_changed.connect(self._on_active_device_changed)

        self._on_adb_available_changed(device_manager.adb_available)
        self._on_devices_changed(device_manager.devices)
        self._on_active_device_changed(device_manager.active_device)

    def _build_audio_controls(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(4)

        volume_row = QWidget()
        volume_layout = QHBoxLayout(volume_row)
        volume_layout.setContentsMargins(0, 0, 0, 0)

        volume_label = QLabel("Volume")
        volume_label.setProperty("role", "muted")
        self._volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._volume_slider.setRange(0, 100)
        self._volume_slider.setValue(100)
        self._volume_slider.setEnabled(False)
        self._volume_slider.valueChanged.connect(self.audio_volume_changed)

        volume_layout.addWidget(volume_label)
        volume_layout.addWidget(self._volume_slider, stretch=1)
        layout.addWidget(volume_row)

        mute_row = QWidget()
        mute_layout = QHBoxLayout(mute_row)
        mute_layout.setContentsMargins(0, 0, 0, 0)

        mute_label = QLabel("Mute")
        mute_label.setProperty("role", "muted")
        self._mute_toggle = ToggleSwitch(checked=False)
        self._mute_toggle.setEnabled(False)
        self._mute_toggle.toggled.connect(self.audio_mute_toggled)

        mute_layout.addWidget(mute_label)
        mute_layout.addStretch(1)
        mute_layout.addWidget(self._mute_toggle)
        layout.addWidget(mute_row)

        self._audio_status_label = QLabel()
        self._audio_status_label.setProperty("role", "muted")
        self._audio_status_label.setWordWrap(True)
        self._audio_status_label.hide()
        layout.addWidget(self._audio_status_label)

        return container

    def _build_camera_controls(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(4)

        camera_row = QWidget()
        camera_layout = QHBoxLayout(camera_row)
        camera_layout.setContentsMargins(0, 0, 0, 0)
        camera_label = QLabel("Camera")
        camera_label.setProperty("role", "muted")
        self._camera_combo = QComboBox()
        self._camera_combo.setEnabled(False)
        self._camera_combo.currentIndexChanged.connect(self._on_camera_selection_changed)
        camera_layout.addWidget(camera_label)
        camera_layout.addWidget(self._camera_combo, stretch=1)
        layout.addWidget(camera_row)

        resolution_row = QWidget()
        resolution_layout = QHBoxLayout(resolution_row)
        resolution_layout.setContentsMargins(0, 0, 0, 0)
        resolution_label = QLabel("Resolution")
        resolution_label.setProperty("role", "muted")
        self._camera_resolution_combo = QComboBox()
        self._camera_resolution_combo.addItem(_AUTOMATIC)
        self._camera_resolution_combo.setEnabled(False)
        self._camera_resolution_combo.setToolTip(
            "Per-resolution selection isn't implemented yet; the device's default is used"
        )
        resolution_layout.addWidget(resolution_label)
        resolution_layout.addWidget(self._camera_resolution_combo, stretch=1)
        layout.addWidget(resolution_row)

        fps_row = QWidget()
        fps_layout = QHBoxLayout(fps_row)
        fps_layout.setContentsMargins(0, 0, 0, 0)
        fps_label = QLabel("FPS")
        fps_label.setProperty("role", "muted")
        self._camera_fps_combo = QComboBox()
        self._camera_fps_combo.addItem(_AUTOMATIC)
        self._camera_fps_combo.setEnabled(False)
        self._camera_fps_combo.currentIndexChanged.connect(self._on_camera_fps_changed)
        fps_layout.addWidget(fps_label)
        fps_layout.addWidget(self._camera_fps_combo, stretch=1)
        layout.addWidget(fps_row)

        self._camera_status_label = QLabel("Detecting cameras...")
        self._camera_status_label.setProperty("role", "muted")
        self._camera_status_label.setWordWrap(True)
        layout.addWidget(self._camera_status_label)

        return container

    def _build_mic_controls(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(4)

        input_row = QWidget()
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_label = QLabel("Input")
        input_label.setProperty("role", "muted")
        self._mic_source_combo = QComboBox()
        for source, display_name in _MIC_SOURCE_LABELS.items():
            self._mic_source_combo.addItem(display_name, source)
        self._mic_source_combo.setEnabled(False)
        self._mic_source_combo.currentIndexChanged.connect(self._on_mic_source_index_changed)
        input_layout.addWidget(input_label)
        input_layout.addWidget(self._mic_source_combo, stretch=1)
        layout.addWidget(input_row)

        volume_row = QWidget()
        volume_layout = QHBoxLayout(volume_row)
        volume_layout.setContentsMargins(0, 0, 0, 0)
        volume_label = QLabel("Volume")
        volume_label.setProperty("role", "muted")
        self._mic_volume_slider = QSlider(Qt.Orientation.Horizontal)
        self._mic_volume_slider.setRange(0, 100)
        self._mic_volume_slider.setValue(100)
        self._mic_volume_slider.setEnabled(False)
        self._mic_volume_slider.valueChanged.connect(self.mic_volume_changed)
        volume_layout.addWidget(volume_label)
        volume_layout.addWidget(self._mic_volume_slider, stretch=1)
        layout.addWidget(volume_row)

        mute_row = QWidget()
        mute_layout = QHBoxLayout(mute_row)
        mute_layout.setContentsMargins(0, 0, 0, 0)
        mute_label = QLabel("Mute")
        mute_label.setProperty("role", "muted")
        self._mic_mute_toggle = ToggleSwitch(checked=False)
        self._mic_mute_toggle.setEnabled(False)
        self._mic_mute_toggle.toggled.connect(self.mic_mute_toggled)
        mute_layout.addWidget(mute_label)
        mute_layout.addStretch(1)
        mute_layout.addWidget(self._mic_mute_toggle)
        layout.addWidget(mute_row)

        self._mic_status_label = QLabel()
        self._mic_status_label.setProperty("role", "muted")
        self._mic_status_label.setWordWrap(True)
        self._mic_status_label.hide()
        layout.addWidget(self._mic_status_label)

        return container

    def _build_device_row(self, device: AndroidDevice) -> QWidget:
        row = QWidget()
        layout = QVBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        header_layout.addWidget(StatusDot(_CONNECTION_STATUS_MAP[device.connection_state]))
        header_layout.addWidget(QLabel(device.display_name))
        header_layout.addStretch(1)
        layout.addWidget(header)

        detail_label = QLabel(_device_detail_text(device))
        detail_label.setProperty("role", "muted")
        layout.addWidget(detail_label)

        if device.connection_state == ConnectionState.DEVICE:
            if device.is_active:
                active_label = QLabel("Connected")
                active_label.setProperty("role", "status-active")
                layout.addWidget(active_label)
            else:
                connect_button = QPushButton("Connect")
                connect_button.setProperty("role", "primary")
                connect_button.clicked.connect(
                    lambda _checked=False, serial=device.serial: self._device_manager.connect_device(
                        serial
                    )
                )
                layout.addWidget(connect_button)
        elif device.connection_state == ConnectionState.UNAUTHORIZED:
            msg = QLabel('Unlock your phone and accept "Allow USB debugging?"')
            msg.setProperty("role", "muted")
            msg.setWordWrap(True)
            layout.addWidget(msg)
        elif device.connection_state == ConnectionState.OFFLINE:
            msg = QLabel("Device offline — try reconnecting the USB cable")
            msg.setProperty("role", "muted")
            msg.setWordWrap(True)
            layout.addWidget(msg)

        return row

    def _clear_device_list(self) -> None:
        while self._device_list_layout.count():
            item = self._device_list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _on_adb_available_changed(self, available: bool) -> None:
        if available:
            self._adb_status_label.hide()
            self._device_list_container.show()
        else:
            self._adb_status_label.setText(
                "ADB not found. Install Android Platform Tools and ensure "
                "adb is on your PATH, then reopen AndroidLink."
            )
            self._adb_status_label.show()
            self._device_list_container.hide()

    def _on_devices_changed(self, devices: list[AndroidDevice]) -> None:
        self._clear_device_list()

        if not devices:
            empty_label = QLabel("No device connected")
            empty_label.setProperty("role", "placeholder")
            self._device_list_layout.addWidget(empty_label)

            hint_label = QLabel("Plug in an Android phone over USB Type-C.")
            hint_label.setProperty("role", "muted")
            hint_label.setWordWrap(True)
            self._device_list_layout.addWidget(hint_label)
            return

        for device in devices:
            self._device_list_layout.addWidget(self._build_device_row(device))

    def _on_active_device_changed(self, device: AndroidDevice | None) -> None:
        cast_toggle = self._feature_toggles["Cast"]

        if device is None:
            self._active_info_label.hide()
            self._disconnect_button.hide()
            cast_toggle.setEnabled(False)
            self.set_casting_active(False)
            self._reset_camera_controls()
            self._reset_mic_controls()
            return

        self._active_info_label.setText(
            f"{device.display_name}\n"
            f"{device.manufacturer or ''}\n"
            f"Android {device.android_version or '?'} (API {device.api_level or '?'})\n"
            f"{device.display_serial}"
        )
        self._active_info_label.show()
        self._disconnect_button.show()
        cast_toggle.setEnabled(True)
        self._feature_toggles["Mic"].setEnabled(True)

    def _on_cast_toggle_changed(self, checked: bool) -> None:
        self._set_cast_dependent_features_availability(checked)
        self.cast_toggled.emit(checked)

    def _on_audio_toggle_changed(self, checked: bool) -> None:
        self._volume_slider.setEnabled(checked)
        self._mute_toggle.setEnabled(checked)
        if not checked:
            self._audio_status_label.hide()
        self.audio_toggled.emit(checked)

    def _set_cast_dependent_features_availability(self, available: bool) -> None:
        for feature in _CAST_DEPENDENT_FEATURES:
            toggle = self._feature_toggles[feature]
            toggle.setEnabled(available)
            if not available:
                toggle.blockSignals(True)
                toggle.setChecked(False)
                toggle.blockSignals(False)
        if not available:
            self._volume_slider.setEnabled(False)
            self._mute_toggle.setEnabled(False)
            self._audio_status_label.hide()

    def _on_camera_selection_changed(self, _index: int) -> None:
        camera = self._camera_combo.currentData()
        if camera is not None:
            self.camera_selection_changed.emit(camera.camera_id)
            self._camera_fps_combo.clear()
            self._camera_fps_combo.addItem(_AUTOMATIC)
            for fps in camera.fps_options:
                self._camera_fps_combo.addItem(f"{fps} fps", fps)

    def _on_camera_fps_changed(self, _index: int) -> None:
        fps = self._camera_fps_combo.currentData()
        self.camera_fps_changed.emit(fps or 0)

    def _reset_camera_controls(self) -> None:
        camera_toggle = self._feature_toggles["Camera"]
        camera_toggle.setEnabled(False)
        camera_toggle.blockSignals(True)
        camera_toggle.setChecked(False)
        camera_toggle.blockSignals(False)
        self._camera_combo.clear()
        self._camera_combo.setEnabled(False)
        self._camera_resolution_combo.setEnabled(False)
        self._camera_fps_combo.setEnabled(False)
        self._camera_status_label.setText("Detecting cameras...")
        self._camera_status_label.show()

    def set_camera_list(self, cameras: list[CameraInfo]) -> None:
        """Populates the Camera dropdown once detection finishes (prompt.md
        section 11: "Detect all available cameras"; never silently fail)."""
        self._camera_combo.clear()

        if not cameras:
            self._camera_status_label.setText("No camera detected on this device.")
            self._camera_status_label.show()
            self._feature_toggles["Camera"].setEnabled(False)
            self._feature_toggles["Camera"].setToolTip("No camera detected on this device")
            return

        for camera in cameras:
            self._camera_combo.addItem(camera.display_name, camera)
        self._camera_combo.setEnabled(True)
        self._camera_resolution_combo.setEnabled(True)
        self._camera_fps_combo.setEnabled(True)
        self._camera_status_label.hide()
        self._feature_toggles["Camera"].setEnabled(True)
        self._feature_toggles["Camera"].setToolTip("Expose the Android camera as a Windows webcam")

    def set_camera_list_failed(self, message: str) -> None:
        self._camera_status_label.setText(message)
        self._camera_status_label.show()
        self._feature_toggles["Camera"].setEnabled(False)
        self._feature_toggles["Camera"].setToolTip(message)

    def show_virtual_camera_unavailable(self, message: str) -> None:
        """Reflects a missing OBS Virtual Camera/Unity Capture backend
        (prompt.md section 25: never silently install drivers) by forcing
        Camera off with an explanation."""
        camera_toggle = self._feature_toggles["Camera"]
        camera_toggle.blockSignals(True)
        camera_toggle.setChecked(False)
        camera_toggle.blockSignals(False)
        self._camera_status_label.setText(
            "No Windows virtual camera backend found. Install OBS Studio or "
            "Unity Capture, then try again.\n\n" + message
        )
        self._camera_status_label.show()

    def _on_mic_toggle_changed(self, checked: bool) -> None:
        self._mic_source_combo.setEnabled(checked)
        self._mic_volume_slider.setEnabled(checked)
        self._mic_mute_toggle.setEnabled(checked)
        if not checked:
            self._mic_status_label.hide()
        self.mic_toggled.emit(checked)

    def _on_mic_source_index_changed(self, _index: int) -> None:
        source = self._mic_source_combo.currentData()
        if source is not None:
            self.mic_source_changed.emit(source)

    def _reset_mic_controls(self) -> None:
        mic_toggle = self._feature_toggles["Mic"]
        mic_toggle.setEnabled(False)
        mic_toggle.blockSignals(True)
        mic_toggle.setChecked(False)
        mic_toggle.blockSignals(False)
        self._mic_source_combo.setEnabled(False)
        self._mic_volume_slider.setEnabled(False)
        self._mic_mute_toggle.setEnabled(False)
        self._mic_status_label.hide()

    def show_mic_connection_failed(self, message: str) -> None:
        mic_toggle = self._feature_toggles["Mic"]
        mic_toggle.blockSignals(True)
        mic_toggle.setChecked(False)
        mic_toggle.blockSignals(False)
        self._mic_source_combo.setEnabled(False)
        self._mic_volume_slider.setEnabled(False)
        self._mic_mute_toggle.setEnabled(False)
        self._mic_status_label.setText(message)
        self._mic_status_label.show()

    def show_mic_unavailable(self, is_error: bool) -> None:
        """Reflects a device-side microphone capture failure (mirrors
        show_audio_unavailable) by forcing Mic off."""
        mic_toggle = self._feature_toggles["Mic"]
        mic_toggle.blockSignals(True)
        mic_toggle.setChecked(False)
        mic_toggle.blockSignals(False)
        self._mic_source_combo.setEnabled(False)
        self._mic_volume_slider.setEnabled(False)
        self._mic_mute_toggle.setEnabled(False)

        text = (
            "This device reported a microphone configuration error."
            if is_error
            else "The selected microphone source isn't available on this device."
        )
        self._mic_status_label.setText(text)
        self._mic_status_label.show()

    def show_virtual_mic_unavailable(self, message: str) -> None:
        """Reflects a missing virtual-audio-cable driver (prompt.md section
        25: never silently install drivers) by forcing Mic off."""
        mic_toggle = self._feature_toggles["Mic"]
        mic_toggle.blockSignals(True)
        mic_toggle.setChecked(False)
        mic_toggle.blockSignals(False)
        self._mic_source_combo.setEnabled(False)
        self._mic_volume_slider.setEnabled(False)
        self._mic_mute_toggle.setEnabled(False)
        self._mic_status_label.setText(
            "No virtual audio cable driver found. Install VB-Audio Virtual "
            "Cable (or VoiceMeeter), then try again.\n\n" + message
        )
        self._mic_status_label.show()

    def show_audio_unavailable(self, is_error: bool) -> None:
        """Reflects a device-side audio capture failure (prompt.md section
        10: detect capability, never silently fail) by forcing Audio off."""
        audio_toggle = self._feature_toggles["Audio"]
        audio_toggle.blockSignals(True)
        audio_toggle.setChecked(False)
        audio_toggle.blockSignals(False)
        self._volume_slider.setEnabled(False)
        self._mute_toggle.setEnabled(False)

        text = (
            "This device reported an audio configuration error."
            if is_error
            else "Android audio isn't available on this device."
        )
        self._audio_status_label.setText(text)
        self._audio_status_label.show()

    def set_casting_active(self, active: bool) -> None:
        """Force the Cast toggle's visual state without re-emitting
        cast_toggled (used when the controller reflects actual session
        state back, e.g. after a connection failure)."""
        toggle = self._feature_toggles["Cast"]
        toggle.blockSignals(True)
        toggle.setChecked(active)
        toggle.blockSignals(False)
        self._set_cast_dependent_features_availability(active)
