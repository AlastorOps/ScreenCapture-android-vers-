"""Item 6 of the crash investigation: only one active streaming session may
exist per feature at a time. _start_casting()/_start_camera()/_start_mic()
now guard against being invoked while a session is already active (instead
of silently overwriting self._session and orphaning the old scrcpy-server
process/thread) by routing through the same safe stop-then-start restart
path a normal settings change already uses.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

import androidlink.audio.mic_controller as mic_controller_module
import androidlink.camera.camera_controller as camera_controller_module
import androidlink.streaming.controller as controller_module
from androidlink.audio.mic_controller import MicController
from androidlink.camera.camera_controller import CameraController
from androidlink.device.device_model import AndroidDevice, ConnectionState
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.controller import CastingController
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.panels.screen_panel import ScreenPanel
from androidlink.ui.panels.status_panel import StatusPanel


def _make_device_manager() -> DeviceManager:
    device_manager = DeviceManager()
    device_manager._adb_path = Path("adb")
    device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE, is_active=True)
    device_manager._devices = {"SERIAL1": device}
    device_manager._active_serial = "SERIAL1"
    return device_manager


class _FakeCastingSession(QObject):
    session_started = Signal(int, int)
    frame_available = Signal()
    connection_failed = Signal(str)
    audio_unavailable = Signal(bool)
    audio_pcm_available = Signal(bytes)
    stats_updated = Signal(object)
    stopped = Signal()

    instances: list["_FakeCastingSession"] = []

    def __init__(self, adb_path, serial, server_jar_path, profile, **kwargs) -> None:
        super().__init__()
        _FakeCastingSession.instances.append(self)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        QTimer.singleShot(0, self.stopped.emit)

    def send_control_message(self, _data: bytes) -> None:
        pass

    def set_audio_volume(self, _volume: float) -> None:
        pass

    def set_audio_muted(self, _muted: bool) -> None:
        pass


def test_start_casting_twice_never_creates_two_live_sessions(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    _FakeCastingSession.instances = []
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = _make_device_manager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    screen_panel = ScreenPanel()
    qtbot.addWidget(screen_panel)
    controller = CastingController(device_manager, device_panel, screen_panel, settings_manager)

    controller._start_casting()
    first_session = _FakeCastingSession.instances[0]
    assert controller._session is first_session

    controller._start_casting()  # called again while already active
    qtbot.wait(20)  # let the safe stop -> stopped -> restart chain settle

    # The first session was told to stop (not silently abandoned)...
    assert first_session is not controller._session
    # ...and exactly one session is active at the end, not two.
    assert controller._session is _FakeCastingSession.instances[-1]
    assert len(_FakeCastingSession.instances) == 2


class _FakeCameraSession(QObject):
    session_started = Signal(int, int)
    connection_failed = Signal(str)
    virtual_camera_unavailable = Signal(str)
    frame_available = Signal()
    stopped = Signal()

    instances: list["_FakeCameraSession"] = []

    def __init__(self, adb_path, serial, server_jar_path, camera_id, camera_size, camera_facing, camera_fps, parent=None) -> None:
        super().__init__(parent)
        _FakeCameraSession.instances.append(self)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        QTimer.singleShot(0, self.stopped.emit)

    def take_latest_frame(self):
        return None


def test_start_camera_twice_never_creates_two_live_sessions(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(camera_controller_module, "CameraSession", _FakeCameraSession)
    _FakeCameraSession.instances = []
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = _make_device_manager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    status_panel = StatusPanel()
    qtbot.addWidget(status_panel)
    controller = CameraController(device_manager, device_panel, status_panel, settings_manager)
    controller._selected_camera_id = "0"

    controller._start_camera()
    first_session = _FakeCameraSession.instances[0]
    assert controller._session is first_session

    controller._start_camera()  # called again while already active
    qtbot.wait(20)

    assert first_session is not controller._session
    assert controller._session is _FakeCameraSession.instances[-1]
    assert len(_FakeCameraSession.instances) == 2


class _FakeMicSession(QObject):
    session_started = Signal()
    connection_failed = Signal(str)
    audio_unavailable = Signal(bool)
    virtual_mic_unavailable = Signal(str)
    audio_level_updated = Signal(float)
    stopped = Signal()

    instances: list["_FakeMicSession"] = []

    def __init__(self, adb_path, serial, server_jar_path, *, audio_source="mic", parent=None) -> None:
        super().__init__(parent)
        _FakeMicSession.instances.append(self)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        QTimer.singleShot(0, self.stopped.emit)

    def set_volume(self, _volume: float) -> None:
        pass

    def set_muted(self, _muted: bool) -> None:
        pass


def test_start_mic_twice_never_creates_two_live_sessions(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(mic_controller_module, "MicSession", _FakeMicSession)
    _FakeMicSession.instances = []
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = _make_device_manager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    controller = MicController(device_manager, device_panel, settings_manager)

    controller._start_mic()
    first_session = _FakeMicSession.instances[0]
    assert controller._session is first_session

    controller._start_mic()  # called again while already active
    qtbot.wait(20)

    assert first_session is not controller._session
    assert controller._session is _FakeMicSession.instances[-1]
    assert len(_FakeMicSession.instances) == 2
