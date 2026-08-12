"""MicController forwards real audio_level_updated values (never a fake/
random animation) from MicSession to the Device panel's level meter, keeps
the Microphone Active/No Signal/Disabled/Disconnected status honest -- via
a staleness timer, since "session running" and "audio actually arriving"
are genuinely different things -- and severs a finished session's callbacks
so a stale one can't affect whatever replaces it.

MicSession is replaced with a lightweight fake for the same reason other
controller tests do this: no real QThread/ADB/scrcpy I/O.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QObject, Signal

import androidlink.audio.mic_controller as mic_controller_module
from androidlink.audio.mic_controller import MicController
from androidlink.device.device_model import AndroidDevice, ConnectionState
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.widgets.status_dot import StatusState


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
        pass

    def set_volume(self, _volume: float) -> None:
        pass

    def set_muted(self, _muted: bool) -> None:
        pass


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
    controller = MicController(device_manager, device_panel, settings_manager)
    return controller, device_panel


def test_initial_status_is_disabled(qtbot, tmp_path):
    _controller, device_panel = _make_controller(qtbot, tmp_path)
    assert device_panel._mic_status_text.text() == "Disabled"
    assert device_panel._mic_status_dot.state() == StatusState.DISCONNECTED


def test_enabling_mic_shows_connecting_before_any_audio(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(mic_controller_module, "MicSession", _FakeMicSession)
    _FakeMicSession.instances = []
    controller, device_panel = _make_controller(qtbot, tmp_path)

    controller._start_mic()

    assert device_panel._mic_status_text.text() == "Connecting…"


def test_a_real_level_update_makes_status_active_and_reaches_the_meter(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(mic_controller_module, "MicSession", _FakeMicSession)
    _FakeMicSession.instances = []
    controller, device_panel = _make_controller(qtbot, tmp_path)
    controller._start_mic()
    session = _FakeMicSession.instances[-1]

    session.audio_level_updated.emit(0.6)

    assert device_panel._mic_status_text.text() == "Active"
    assert device_panel._mic_status_dot.state() == StatusState.CONNECTED
    assert abs(device_panel._mic_level_meter._displayed_level - 0.6 * 0.6) < 1e-9  # one attack step


def test_staleness_check_reports_no_signal_when_no_audio_has_arrived(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(mic_controller_module, "MicSession", _FakeMicSession)
    _FakeMicSession.instances = []
    controller, device_panel = _make_controller(qtbot, tmp_path)
    controller._start_mic()

    # Simulate the 2s no-signal window having elapsed without ever calling
    # time.sleep() -- the controller only compares timestamps.
    controller._last_level_time = 0.0
    controller._check_signal_staleness()

    assert device_panel._mic_status_text.text() == "No Signal"


def test_receiving_audio_after_a_stale_period_returns_to_active(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(mic_controller_module, "MicSession", _FakeMicSession)
    _FakeMicSession.instances = []
    controller, device_panel = _make_controller(qtbot, tmp_path)
    controller._start_mic()
    session = _FakeMicSession.instances[-1]

    controller._last_level_time = 0.0
    controller._check_signal_staleness()
    assert device_panel._mic_status_text.text() == "No Signal"

    session.audio_level_updated.emit(0.4)

    assert device_panel._mic_status_text.text() == "Active"


def test_disabling_mic_stops_the_meter_and_releases_resources(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(mic_controller_module, "MicSession", _FakeMicSession)
    _FakeMicSession.instances = []
    controller, device_panel = _make_controller(qtbot, tmp_path)
    controller._start_mic()
    session = _FakeMicSession.instances[-1]
    session.audio_level_updated.emit(0.9)
    assert device_panel._mic_level_meter._displayed_level > 0

    controller._on_mic_toggled(False)

    assert controller._session is None
    assert controller._status_timer.isActive() is False
    assert device_panel._mic_level_meter._displayed_level == 0.0
    assert device_panel._mic_status_text.text() == "Disabled"


def test_disconnect_releases_resources_and_shows_disconnected(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(mic_controller_module, "MicSession", _FakeMicSession)
    _FakeMicSession.instances = []
    controller, device_panel = _make_controller(qtbot, tmp_path)
    controller._start_mic()
    session = _FakeMicSession.instances[-1]
    session.audio_level_updated.emit(0.9)

    controller._on_active_device_changed(None)

    assert controller._session is None
    assert device_panel._mic_level_meter._displayed_level == 0.0
    assert device_panel._mic_status_text.text() == "Disconnected"


def test_reconnect_does_not_auto_enable_mic(qtbot, tmp_path, monkeypatch):
    """prompt.md section 10: hardware features stay off after a reconnect
    until the user explicitly re-enables them."""
    monkeypatch.setattr(mic_controller_module, "MicSession", _FakeMicSession)
    _FakeMicSession.instances = []
    controller, device_panel = _make_controller(qtbot, tmp_path)
    controller._start_mic()
    controller._on_active_device_changed(None)
    _FakeMicSession.instances = []

    device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE, is_active=True)
    controller._on_active_device_changed(device)

    assert controller._session is None
    assert _FakeMicSession.instances == []
    assert device_panel._mic_status_text.text() != "Active"


def test_stale_session_callbacks_are_disconnected_on_stop(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(mic_controller_module, "MicSession", _FakeMicSession)
    _FakeMicSession.instances = []
    controller, device_panel = _make_controller(qtbot, tmp_path)
    controller._start_mic()
    old_session = _FakeMicSession.instances[-1]

    controller._on_mic_toggled(False)  # stops (and should disconnect) old_session

    # A straggling emission from the now-stopped session's worker thread --
    # must be inert.
    old_session.audio_level_updated.emit(1.0)

    assert device_panel._mic_level_meter._displayed_level == 0.0
    assert device_panel._mic_status_text.text() == "Disabled"
