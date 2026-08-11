"""Owns PC-side recording (prompt.md section 14) and screenshot capture.
Both require Cast to be active -- there's nothing to record or screenshot
otherwise -- so availability tracks CastingController's
cast_session_started/cast_session_stopped signals, and frames are supplied
via its frame_ready signal: the same already-decoded frames being rendered,
no separate capture path. When Android audio is enabled, its decoded PCM
(via audio_pcm_ready) is muxed into the recording too -- the same audio
already being played back, no separate capture path there either.
"""

import datetime
import logging
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject

from androidlink.recording.recorder import VideoRecorder
from androidlink.recording.screenshots import save_screenshot
from androidlink.streaming.controller import CastingController
from androidlink.ui.panels.status_panel import StatusPanel
from androidlink.utils.platform import get_recordings_dir, get_screenshots_dir

logger = logging.getLogger(__name__)


def _timestamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


class RecordingController(QObject):
    def __init__(
        self,
        casting_controller: CastingController,
        status_panel: StatusPanel,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._status_panel = status_panel
        self._recorder = VideoRecorder(parent=self)

        self._frame_width = 0
        self._frame_height = 0
        self._fps = 30
        self._audio_enabled = False
        self._latest_frame: np.ndarray | None = None

        casting_controller.cast_session_started.connect(self._on_cast_session_started)
        casting_controller.cast_session_stopped.connect(self._on_cast_session_stopped)
        casting_controller.frame_ready.connect(self._on_frame_ready)
        casting_controller.audio_pcm_ready.connect(self._on_audio_pcm_ready)

        status_panel.record_toggled.connect(self._on_record_toggled)
        status_panel.pause_toggled.connect(self._recorder.set_paused)
        status_panel.screenshot_requested.connect(self._on_screenshot_requested)

        self._recorder.started.connect(self._on_recorder_started)
        self._recorder.error.connect(self._on_recorder_error)
        self._recorder.stopped.connect(self._on_recorder_stopped)

    def shutdown(self) -> None:
        if self._recorder.is_recording:
            self._recorder.stop()

    def _on_cast_session_started(self, width: int, height: int, fps: int, audio_enabled: bool) -> None:
        self._frame_width = width
        self._frame_height = height
        self._fps = fps
        self._audio_enabled = audio_enabled
        self._status_panel.set_recording_available(True)

    def _on_cast_session_stopped(self) -> None:
        self._frame_width = 0
        self._frame_height = 0
        self._audio_enabled = False
        self._latest_frame = None
        self._status_panel.set_recording_available(False)
        if self._recorder.is_recording:
            self._recorder.stop()

    def _on_frame_ready(self, frame: np.ndarray) -> None:
        self._latest_frame = frame
        if self._recorder.is_recording:
            self._recorder.submit_frame(frame)

    def _on_audio_pcm_ready(self, pcm_bytes: bytes) -> None:
        if self._recorder.is_recording:
            self._recorder.submit_audio(pcm_bytes)

    def _on_record_toggled(self, enabled: bool) -> None:
        if enabled:
            self._start_recording()
        else:
            self._recorder.stop()

    def _start_recording(self) -> None:
        if self._frame_width == 0 or self._frame_height == 0:
            self._status_panel.show_recording_error("No active cast session")
            return

        path = get_recordings_dir() / f"AndroidLink_{_timestamp()}.mp4"
        self._recorder.start(
            path, self._frame_width, self._frame_height, self._fps, has_audio=self._audio_enabled
        )

    def _on_recorder_started(self) -> None:
        self._status_panel.set_recording_state("recording")

    def _on_recorder_error(self, message: str) -> None:
        logger.warning("Recording error: %s", message)
        self._status_panel.show_recording_error(message)

    def _on_recorder_stopped(self, path: str) -> None:
        logger.info("Recording saved: %s", path)
        self._status_panel.show_recording_saved(path)

    def _on_screenshot_requested(self) -> None:
        if self._latest_frame is None:
            self._status_panel.show_recording_error("No frame to capture yet")
            return

        path = get_screenshots_dir() / f"AndroidLink_{_timestamp()}.png"
        if save_screenshot(self._latest_frame, path):
            logger.info("Screenshot saved: %s", path)
            self._status_panel.show_screenshot_saved(str(path))
        else:
            logger.warning("Could not save screenshot to %s", path)
            self._status_panel.show_recording_error("Could not save screenshot")
