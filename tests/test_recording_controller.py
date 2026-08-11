"""RecordingController's audio wiring: has_audio must reflect the cast
session's actual audio_enabled state, and decoded PCM must only reach the
recorder while a recording is in progress.

Uses a lightweight fake in place of VideoRecorder (whose real encode/mux
behavior already has its own thorough tests in test_recorder.py) so these
tests focus purely on RecordingController's own wiring logic: is_recording
is a read-only property on the real class, and a real recorder would spin
up a background encode thread that isn't relevant here.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.device.manager import DeviceManager
from androidlink.recording.recording_controller import RecordingController
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.controller import CastingController
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.panels.screen_panel import ScreenPanel
from androidlink.ui.panels.status_panel import StatusPanel


class _FakeRecorder:
    def __init__(self) -> None:
        self.is_recording = False
        self.start_calls = []
        self.submitted_audio = []

    def start(self, path, width, height, fps, has_audio=False, video_bit_rate=None):
        self.start_calls.append(has_audio)

    def submit_audio(self, pcm_bytes):
        self.submitted_audio.append(pcm_bytes)

    def submit_frame(self, frame):
        pass

    def stop(self):
        pass

    def set_paused(self, paused):
        pass


def _build(qtbot, tmp_path):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()

    device_manager = DeviceManager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    screen_panel = ScreenPanel()
    qtbot.addWidget(screen_panel)
    status_panel = StatusPanel()
    qtbot.addWidget(status_panel)

    casting_controller = CastingController(device_manager, device_panel, screen_panel, settings_manager)
    recording_controller = RecordingController(casting_controller, status_panel, settings_manager)
    recording_controller._recorder = _FakeRecorder()
    return casting_controller, recording_controller, status_panel


def test_has_audio_flows_from_cast_session_started(qtbot, tmp_path):
    _casting, recording, status_panel = _build(qtbot, tmp_path)

    recording._on_cast_session_started(1280, 720, 30, True)
    status_panel.record_toggled.emit(True)

    assert recording._recorder.start_calls == [True]


def test_has_audio_false_when_cast_session_has_no_audio(qtbot, tmp_path):
    _casting, recording, status_panel = _build(qtbot, tmp_path)

    recording._on_cast_session_started(1280, 720, 30, False)
    status_panel.record_toggled.emit(True)

    assert recording._recorder.start_calls == [False]


def test_audio_pcm_forwarded_only_while_recording(qtbot, tmp_path):
    _casting, recording, _status_panel = _build(qtbot, tmp_path)

    # Not recording yet -- must be ignored.
    recording._on_audio_pcm_ready(b"\x00\x01")
    assert recording._recorder.submitted_audio == []

    # Recording -- must be forwarded.
    recording._recorder.is_recording = True
    recording._on_audio_pcm_ready(b"\x02\x03")
    assert recording._recorder.submitted_audio == [b"\x02\x03"]
