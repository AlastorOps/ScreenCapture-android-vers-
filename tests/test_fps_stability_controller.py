"""Integration test: CastingController._on_stats_for_stability() actually
drives an automatic restart at a lower FPS tier when Automatic mode proves
unstable, end to end through _restart_if_casting() -- not just
fps_stability.py's own unit tests in isolation.

CastingSession is replaced with a lightweight fake for the same reason
test_casting_fps_detection.py and test_restart_timing.py do: no real QThread
or ADB I/O, and stop() must defer its `stopped` signal to the next event
loop turn (via QTimer.singleShot) rather than emitting synchronously, since
_restart_if_casting() relies on that queued ordering to avoid starting the
new session before the old one has released `self._session` (see
CastingController._restart_if_casting()'s docstring).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

import androidlink.streaming.controller as controller_module
from androidlink.device.device_model import AndroidDevice, ConnectionState
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.controller import CastingController
from androidlink.streaming.diagnostics import DiagnosticsSample
from androidlink.streaming.fps_stability import WINDOW_SAMPLES
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

    instances: list["_FakeCastingSession"] = []  # every session created, in order

    def __init__(self, adb_path, serial, server_jar_path, profile, **kwargs) -> None:
        super().__init__()
        self.profile = profile
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


def _make_controller_with_connected_device(qtbot, tmp_path) -> CastingController:
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()
    device_manager._adb_path = Path("adb")
    device = AndroidDevice(
        serial="SERIAL1",
        connection_state=ConnectionState.DEVICE,
        refresh_rate_hz=165,
        supported_refresh_rates_hz=(30, 60, 90, 120, 144, 165),
    )
    device_manager._devices = {"SERIAL1": device}
    device_manager._active_serial = "SERIAL1"

    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    screen_panel = ScreenPanel()
    qtbot.addWidget(screen_panel)
    return CastingController(device_manager, device_panel, screen_panel, settings_manager)


def _feed_unstable_samples(session: _FakeCastingSession) -> None:
    for _ in range(WINDOW_SAMPLES):
        session.stats_updated.emit(
            DiagnosticsSample(
                stream_fps=100.0,  # well short of the 165 target -> unstable
                dropped_frames=0,
                decode_latency_ms=5.0,
                bitrate_bps=1_000_000,
                resolution=(1920, 1080),
                codec="h264",
            )
        )


def test_sustained_instability_at_165_restarts_casting_at_144(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    _FakeCastingSession.instances = []
    controller = _make_controller_with_connected_device(qtbot, tmp_path)

    controller._start_casting()
    assert _FakeCastingSession.instances[0].profile.max_fps == 165

    _feed_unstable_samples(_FakeCastingSession.instances[0])
    qtbot.wait(50)  # let the queued stop()->stopped->_start_casting chain settle

    assert len(_FakeCastingSession.instances) == 2
    assert _FakeCastingSession.instances[1].profile.max_fps == 144


def test_manual_fps_override_is_never_auto_downgraded(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    _FakeCastingSession.instances = []
    controller = _make_controller_with_connected_device(qtbot, tmp_path)
    controller._settings_manager.settings.streaming.fps_override = 165

    controller._start_casting()
    _feed_unstable_samples(_FakeCastingSession.instances[0])
    qtbot.wait(50)

    assert len(_FakeCastingSession.instances) == 1  # never restarted -- manual choice is untouched


def test_fresh_cast_toggle_clears_a_previously_learned_downgrade(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    _FakeCastingSession.instances = []
    controller = _make_controller_with_connected_device(qtbot, tmp_path)

    controller._start_casting()
    _feed_unstable_samples(_FakeCastingSession.instances[0])
    qtbot.wait(50)
    assert _FakeCastingSession.instances[-1].profile.max_fps == 144

    controller._on_cast_toggled(False)
    qtbot.wait(10)
    controller._on_cast_toggled(True)

    assert _FakeCastingSession.instances[-1].profile.max_fps == 165
