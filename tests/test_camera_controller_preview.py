"""CameraController forwards real decoded frames (never a placeholder) from
CameraSession to the Status panel's live preview (Camera Live Preview lives
in the Status panel's right-side bar, under Screenshot -- see
status_panel.py), keeps the preview's Active/Connecting/Disabled/
Disconnected status honest, and severs a finished session's callbacks so a
stale one can't affect whatever replaces it (mirrors streaming/controller.py's
CastingController fix -- see test_control_state_sync.py).

CameraSession is replaced with a lightweight fake for the same reason other
controller tests do this: no real QThread/ADB/scrcpy I/O, just inspecting
what the controller actually does with what the session reports.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

import androidlink.camera.camera_controller as camera_controller_module
from androidlink.camera.camera_controller import CameraController
from androidlink.camera.camera_list import CameraInfo
from androidlink.device.device_model import AndroidDevice, ConnectionState
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.panels.status_panel import StatusPanel
from androidlink.ui.widgets.status_dot import StatusState


class _FakeCameraSession(QObject):
    session_started = Signal(int, int)
    connection_failed = Signal(str)
    virtual_camera_unavailable = Signal(str)
    frame_available = Signal()
    stopped = Signal()

    instances: list["_FakeCameraSession"] = []

    def __init__(
        self, adb_path, serial, server_jar_path, camera_id, camera_size, camera_facing, camera_fps, parent=None
    ) -> None:
        super().__init__(parent)
        self.camera_id = camera_id
        self._pending_frame = None
        _FakeCameraSession.instances.append(self)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def take_latest_frame(self):
        frame, self._pending_frame = self._pending_frame, None
        return frame

    def push_frame(self, frame: np.ndarray) -> None:
        self._pending_frame = frame
        self.frame_available.emit()


def _fake_camera(camera_id: str = "0") -> CameraInfo:
    return CameraInfo(camera_id=camera_id, facing="back", width=1920, height=1080, fps_options=(30,))


def _make_controller(qtbot, tmp_path):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()
    device_manager._adb_path = Path("adb")
    device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE, is_active=True)
    device_manager._devices = {"SERIAL1": device}
    device_manager._active_serial = "SERIAL1"

    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    status_panel = StatusPanel()
    qtbot.addWidget(status_panel)
    controller = CameraController(device_manager, device_panel, status_panel, settings_manager)
    return controller, status_panel


def test_initial_status_is_disabled(qtbot, tmp_path):
    _controller, status_panel = _make_controller(qtbot, tmp_path)
    assert status_panel._camera_preview_status_text.text() == "Disabled"
    assert status_panel._camera_preview_status_dot.state() == StatusState.DISCONNECTED


def test_enabling_camera_shows_connecting_before_any_frame(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(camera_controller_module, "CameraSession", _FakeCameraSession)
    _FakeCameraSession.instances = []
    controller, status_panel = _make_controller(qtbot, tmp_path)
    controller._selected_camera_id = "0"

    controller._start_camera()

    assert status_panel._camera_preview_status_text.text() == "Connecting…"
    assert not status_panel._camera_preview_widget.has_frame()


def test_a_real_decoded_frame_makes_status_active_and_reaches_the_widget(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(camera_controller_module, "CameraSession", _FakeCameraSession)
    _FakeCameraSession.instances = []
    controller, status_panel = _make_controller(qtbot, tmp_path)
    controller._selected_camera_id = "0"
    controller._start_camera()
    session = _FakeCameraSession.instances[-1]

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    session.push_frame(frame)

    assert status_panel._camera_preview_widget.has_frame() is True
    assert status_panel._camera_preview_status_text.text() == "Active"
    assert status_panel._camera_preview_status_dot.state() == StatusState.CONNECTED


def test_disabling_camera_stops_the_preview_and_releases_resources(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(camera_controller_module, "CameraSession", _FakeCameraSession)
    _FakeCameraSession.instances = []
    controller, status_panel = _make_controller(qtbot, tmp_path)
    controller._selected_camera_id = "0"
    controller._start_camera()
    session = _FakeCameraSession.instances[-1]
    session.push_frame(np.zeros((64, 64, 3), dtype=np.uint8))
    assert status_panel._camera_preview_widget.has_frame() is True

    controller._on_camera_toggled(False)

    assert controller._session is None
    assert status_panel._camera_preview_widget.has_frame() is False
    assert status_panel._camera_preview_status_text.text() == "Disabled"


def test_disconnect_releases_resources_and_shows_disconnected(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(camera_controller_module, "CameraSession", _FakeCameraSession)
    _FakeCameraSession.instances = []
    controller, status_panel = _make_controller(qtbot, tmp_path)
    controller._selected_camera_id = "0"
    controller._start_camera()
    session = _FakeCameraSession.instances[-1]
    session.push_frame(np.zeros((64, 64, 3), dtype=np.uint8))

    controller._on_active_device_changed(None)

    assert controller._session is None
    assert status_panel._camera_preview_widget.has_frame() is False
    assert status_panel._camera_preview_status_text.text() == "Disconnected"


def test_reconnect_does_not_auto_enable_camera(qtbot, tmp_path, monkeypatch):
    """prompt.md section 10: hardware features stay off after a reconnect
    until the user explicitly re-enables them."""
    monkeypatch.setattr(camera_controller_module, "CameraSession", _FakeCameraSession)
    # Reconnect triggers a real camera-list scan (_on_active_device_changed()
    # -> CameraManager.list_cameras()) unrelated to what this test checks --
    # stub it out so it doesn't spawn a real `adb` QProcess in the background.
    monkeypatch.setattr(camera_controller_module.CameraManager, "list_cameras", lambda self, *a: None)
    _FakeCameraSession.instances = []
    controller, status_panel = _make_controller(qtbot, tmp_path)
    controller._selected_camera_id = "0"
    controller._start_camera()
    controller._on_active_device_changed(None)
    _FakeCameraSession.instances = []

    device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE, is_active=True)
    controller._on_active_device_changed(device)

    assert controller._session is None
    assert _FakeCameraSession.instances == []
    assert status_panel._camera_preview_status_text.text() != "Active"


def test_stale_session_callbacks_are_disconnected_on_stop(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(camera_controller_module, "CameraSession", _FakeCameraSession)
    _FakeCameraSession.instances = []
    controller, status_panel = _make_controller(qtbot, tmp_path)
    controller._selected_camera_id = "0"
    controller._start_camera()
    old_session = _FakeCameraSession.instances[-1]

    controller._on_camera_toggled(False)  # stops (and should disconnect) old_session

    # A straggling emission from the now-stopped session's worker thread --
    # must be inert. If it weren't, this would resurrect a frame/status the
    # user just turned off.
    old_session.push_frame(np.ones((64, 64, 3), dtype=np.uint8))

    assert status_panel._camera_preview_widget.has_frame() is False
    assert status_panel._camera_preview_status_text.text() == "Disabled"
