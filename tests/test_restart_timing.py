"""Regression tests for a real bug found via live hardware testing:
CastingController/CameraController/MicController's restart-on-settings-
change logic used to call stop() immediately followed by start() -- but
*Session.stop() posts a queued call to its worker thread (so the old
scrcpy-server process, and the device's hardware video encoder it's
holding, might still be alive when the new session tries to start).
Confirmed directly against a real device: changing the Resolution override
while casting would start a "new" session that silently kept using the old
resolution, because the old encoder session hadn't actually released the
hardware yet.

The fix waits for the old session's `stopped` signal (only emitted after
its worker thread has fully unwound) before starting the new one. These
tests verify that ordering using a fake session with a controllable
`stopped` signal, without needing real hardware for the timing assertion
itself (the actual resolution-change behavior is verified live -- see
test_settings_live_apply.py and this session's manual hardware runs).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal

from androidlink.audio.mic_controller import MicController
from androidlink.camera.camera_controller import CameraController
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.controller import CastingController
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.panels.screen_panel import ScreenPanel


class _FakeSession(QObject):
    stopped = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.stop_called = False

    def stop(self) -> None:
        self.stop_called = True  # deliberately does NOT emit stopped -- the test controls timing

    def send_control_message(self, _data: bytes) -> None:
        pass  # CastingController._disconnect_input_handlers() looks this up


def _make_casting_controller(qtbot, tmp_path) -> CastingController:
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    screen_panel = ScreenPanel()
    qtbot.addWidget(screen_panel)
    return CastingController(device_manager, device_panel, screen_panel, settings_manager)


def test_casting_restart_waits_for_old_session_to_report_stopped(qtbot, tmp_path):
    controller = _make_casting_controller(qtbot, tmp_path)
    fake_session = _FakeSession()
    controller._session = fake_session

    start_calls = []
    controller._start_casting = lambda: start_calls.append(1)

    controller._restart_if_casting()

    assert fake_session.stop_called is True
    assert start_calls == []  # must NOT have started yet -- old session hasn't confirmed teardown

    fake_session.stopped.emit()  # now the old session's worker thread has actually finished

    assert start_calls == [1]


def test_casting_restart_is_a_noop_when_not_casting(qtbot, tmp_path):
    controller = _make_casting_controller(qtbot, tmp_path)
    start_calls = []
    controller._start_casting = lambda: start_calls.append(1)

    controller._restart_if_casting()  # no session -- must not raise or start anything

    assert start_calls == []


def _make_camera_controller(qtbot, tmp_path) -> CameraController:
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    return CameraController(device_manager, device_panel, settings_manager)


def test_camera_restart_waits_for_old_session_to_report_stopped(qtbot, tmp_path):
    controller = _make_camera_controller(qtbot, tmp_path)
    fake_session = _FakeSession()
    controller._session = fake_session

    start_calls = []
    controller._start_camera = lambda: start_calls.append(1)

    controller._restart_camera_if_active()

    assert fake_session.stop_called is True
    assert start_calls == []

    fake_session.stopped.emit()

    assert start_calls == [1]


def _make_mic_controller(qtbot, tmp_path) -> MicController:
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    return MicController(device_manager, device_panel, settings_manager)


def test_mic_restart_waits_for_old_session_to_report_stopped(qtbot, tmp_path):
    controller = _make_mic_controller(qtbot, tmp_path)
    fake_session = _FakeSession()
    controller._session = fake_session

    start_calls = []
    controller._start_mic = lambda: start_calls.append(1)

    controller._restart_mic_if_active()

    assert fake_session.stop_called is True
    assert start_calls == []

    fake_session.stopped.emit()

    assert start_calls == [1]
