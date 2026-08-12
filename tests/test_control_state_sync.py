"""Regression tests for a real Control-state desync bug: the Device panel's
Control toggle correctly reset itself to unchecked on disconnect (see
device_panel.py's _set_cast_dependent_features_availability(), which uses
blockSignals() so a programmatic reset is never treated as a user action --
deliberately, so it isn't logged/persisted like a real toggle click), but
CastingController._control_enabled -- the flag _start_casting() actually
reads to decide whether the next scrcpy-server session gets control wired up
-- was never told about it, so it stayed True. The next time Cast was turned
on for a reconnected device, the new session launched with control genuinely
enabled (mouse/keyboard wired up and working) while the UI still showed
Control: OFF.

CastingSession is replaced with a lightweight fake for the same reason
test_casting_fps_detection.py and test_restart_timing.py do: no real
QThread/ADB I/O, just inspecting what _start_casting() actually requested.
Tests avoid exercising the queued stop-then-restart chain (_restart_if_
casting(), covered by test_restart_timing.py) by driving _control_enabled
and _start_casting() directly where that chain isn't the thing under test.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QObject, Signal

import androidlink.streaming.controller as controller_module
from androidlink.device.device_model import AndroidDevice, ConnectionState
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.controller import CastingController
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.panels.screen_panel import ScreenPanel


class _FakeCastingSession(QObject):
    session_started = Signal(int, int)
    frame_available = Signal()
    connection_failed = Signal(str)
    audio_unavailable = Signal(bool)
    audio_pcm_available = Signal(bytes)
    stats_updated = Signal(object)
    stopped = Signal()

    instances: list["_FakeCastingSession"] = []

    def __init__(self, adb_path, serial, server_jar_path, profile, *, enable_control=False, **kwargs) -> None:
        super().__init__()
        self.enable_control = enable_control
        self.stop_called = False
        _FakeCastingSession.instances.append(self)

    def start(self) -> None:
        pass

    def stop(self) -> None:
        self.stop_called = True

    def send_control_message(self, _data: bytes) -> None:
        pass

    def set_audio_volume(self, _volume: float) -> None:
        pass

    def set_audio_muted(self, _muted: bool) -> None:
        pass


def _make_controller(qtbot, tmp_path):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()
    device_manager._adb_path = Path("adb")
    device = AndroidDevice(
        serial="SERIAL1", connection_state=ConnectionState.DEVICE, refresh_rate_hz=60, is_active=True
    )
    device_manager._devices = {"SERIAL1": device}
    device_manager._active_serial = "SERIAL1"

    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    screen_panel = ScreenPanel()
    qtbot.addWidget(screen_panel)
    controller = CastingController(device_manager, device_panel, screen_panel, settings_manager)
    return controller, device_manager


def test_control_toggle_sets_the_flag(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    controller, _device_manager = _make_controller(qtbot, tmp_path)

    controller._on_control_toggled(True)  # no session yet -- _restart_if_casting() is a no-op

    assert controller._control_enabled is True


def test_disconnect_resets_control_enabled_flag(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    _FakeCastingSession.instances = []
    controller, device_manager = _make_controller(qtbot, tmp_path)

    controller._control_enabled = True  # Control was already on for this session
    controller._start_casting()
    assert _FakeCastingSession.instances[-1].enable_control is True

    device_manager.disconnect_device()  # emits active_device_changed(None)

    assert controller._control_enabled is False


def test_disconnect_terminates_the_active_control_session(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    _FakeCastingSession.instances = []
    controller, device_manager = _make_controller(qtbot, tmp_path)

    controller._control_enabled = True
    controller._start_casting()
    controller._mouse_handler.set_enabled(True)
    controller._keyboard_handler.set_enabled(True)
    session = _FakeCastingSession.instances[-1]

    device_manager.disconnect_device()

    assert session.stop_called is True
    assert controller._session is None
    assert controller._mouse_handler._enabled is False
    assert controller._keyboard_handler._enabled is False


def test_reconnect_does_not_restore_control_even_if_cast_restarts(qtbot, tmp_path, monkeypatch):
    """The actual reported bug, end to end: Control on, disconnect,
    reconnect, Cast on again (the one thing the user is allowed/expected to
    do without touching Control) -- the new session must launch with control
    OFF, matching what the UI already (correctly) shows."""
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    _FakeCastingSession.instances = []
    controller, device_manager = _make_controller(qtbot, tmp_path)

    controller._control_enabled = True
    controller._start_casting()
    assert _FakeCastingSession.instances[-1].enable_control is True

    device_manager.disconnect_device()

    # Reconnect: a fresh device object, as a real unplug-replug produces
    # (DeviceManager never auto-reconnects -- see manager.py's docstring).
    device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE, refresh_rate_hz=60)
    device_manager._devices = {"SERIAL1": device}
    device_manager.connect_device("SERIAL1")

    controller._start_casting()  # user clicks Cast again -- Control was never touched

    assert controller._control_enabled is False
    assert _FakeCastingSession.instances[-1].enable_control is False
    assert controller._mouse_handler._enabled is False
    assert controller._keyboard_handler._enabled is False


def test_control_can_be_re_enabled_after_reconnect(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    _FakeCastingSession.instances = []
    controller, device_manager = _make_controller(qtbot, tmp_path)

    controller._control_enabled = True
    controller._start_casting()
    device_manager.disconnect_device()

    device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE, refresh_rate_hz=60)
    device_manager._devices = {"SERIAL1": device}
    device_manager.connect_device("SERIAL1")
    controller._on_control_toggled(True)  # user explicitly re-enables it, no session yet -- no-op restart
    controller._start_casting()  # user clicks Cast

    assert controller._control_enabled is True
    assert controller._mouse_handler._enabled is True
    assert _FakeCastingSession.instances[-1].enable_control is True


def test_repeated_disconnect_reconnect_cycles_never_leave_control_on(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    _FakeCastingSession.instances = []
    controller, device_manager = _make_controller(qtbot, tmp_path)

    for _ in range(4):
        controller._control_enabled = True
        controller._start_casting()
        controller._mouse_handler.set_enabled(True)
        device_manager.disconnect_device()
        assert controller._control_enabled is False
        assert controller._mouse_handler._enabled is False

        device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE, refresh_rate_hz=60)
        device_manager._devices = {"SERIAL1": device}
        device_manager.connect_device("SERIAL1")

    controller._start_casting()
    assert controller._control_enabled is False
    assert _FakeCastingSession.instances[-1].enable_control is False


def test_devices_changed_alone_does_not_touch_control_state(qtbot, tmp_path, monkeypatch):
    """CastingController only listens to active_device_changed, never
    devices_changed -- a routine background poll tick for the same
    still-connected device must never reset Control (or restart casting)."""
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    _FakeCastingSession.instances = []
    controller, device_manager = _make_controller(qtbot, tmp_path)

    controller._control_enabled = True
    controller._start_casting()
    session_before = controller._session

    device_manager.devices_changed.emit(device_manager.devices)  # e.g. getprop metadata landing

    assert controller._control_enabled is True
    assert controller._session is session_before
    assert len(_FakeCastingSession.instances) == 1  # no restart happened


def test_stale_session_callbacks_are_disconnected_on_stop(qtbot, tmp_path, monkeypatch):
    """Item 3: a signal still in flight from a session that's already being
    torn down must not be able to reach the controller and affect whatever
    session (if any) replaced it -- session_started/frame_available/etc. are
    fully disconnected from a session the moment _stop_casting() runs it.

    Proven via an observable side effect (screen_panel.show_placeholder(),
    which _on_connection_failed() calls) rather than re-checking
    controller._session: _on_connection_failed() sets that to None too, so
    it would stay None either way and wouldn't actually catch a regression
    where the stale callback still fired.
    """
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    _FakeCastingSession.instances = []
    controller, device_manager = _make_controller(qtbot, tmp_path)

    controller._start_casting()
    old_session = _FakeCastingSession.instances[-1]

    device_manager.disconnect_device()  # stops (and should disconnect) old_session

    placeholder_calls = []
    monkeypatch.setattr(controller._screen_panel, "show_placeholder", placeholder_calls.append)

    # Straggling emissions from the now-stopped session's worker thread --
    # must be inert: no handler left connected to react to any of them.
    old_session.session_started.emit(1920, 1080)
    old_session.frame_available.emit()
    old_session.connection_failed.emit("late failure from the old session")

    assert placeholder_calls == []  # _on_connection_failed() never ran
