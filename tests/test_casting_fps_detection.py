"""Verifies CastingController._start_casting() actually passes the connected
device's detected refresh rate (device/display_info.py, populated by
DeviceManager's dumpsys display fetch) through to resolve_streaming_profile()
as automatic_fps -- this is what removes the old hardcoded 60fps cap end to
end, not just inside performance.py's own unit tests.

CastingSession itself is replaced with a lightweight fake (it would otherwise
spin up a real QThread and try real ADB I/O, which test_restart_timing.py
avoids for the same reason) so this stays a fast, hermetic unit test; the
actual on-device behavior (a real cast session running above 60fps) is
verified separately against real hardware.
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

    last_profile = None  # class-level: simplest way for the test to inspect it

    def __init__(self, adb_path, serial, server_jar_path, profile, **kwargs) -> None:
        super().__init__()
        _FakeCastingSession.last_profile = profile

    def start(self) -> None:
        pass

    def send_control_message(self, _data: bytes) -> None:
        pass

    def set_audio_volume(self, _volume: float) -> None:
        pass

    def set_audio_muted(self, _muted: bool) -> None:
        pass


def _make_controller_with_connected_device(qtbot, tmp_path, *, refresh_rate_hz):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()
    device_manager._adb_path = Path("adb")
    device = AndroidDevice(
        serial="SERIAL1",
        connection_state=ConnectionState.DEVICE,
        refresh_rate_hz=refresh_rate_hz,
        supported_refresh_rates_hz=(30, 60, 90, 120, 144, 165) if refresh_rate_hz else None,
    )
    device_manager._devices = {"SERIAL1": device}
    device_manager._active_serial = "SERIAL1"

    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    screen_panel = ScreenPanel()
    qtbot.addWidget(screen_panel)
    return CastingController(device_manager, device_panel, screen_panel, settings_manager)


def test_start_casting_targets_the_detected_device_refresh_rate(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    controller = _make_controller_with_connected_device(qtbot, tmp_path, refresh_rate_hz=120)

    controller._start_casting()

    assert _FakeCastingSession.last_profile.max_fps == 120


def test_start_casting_falls_back_to_60fps_when_refresh_rate_undetected(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    controller = _make_controller_with_connected_device(qtbot, tmp_path, refresh_rate_hz=None)

    controller._start_casting()

    assert _FakeCastingSession.last_profile.max_fps == 60


def test_start_casting_respects_manual_fps_override_over_detected_rate(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(controller_module, "CastingSession", _FakeCastingSession)
    controller = _make_controller_with_connected_device(qtbot, tmp_path, refresh_rate_hz=120)
    controller._settings_manager.settings.streaming.fps_override = 90

    controller._start_casting()

    assert _FakeCastingSession.last_profile.max_fps == 90
