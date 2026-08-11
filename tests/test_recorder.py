"""Exercises VideoRecorder's real encode path (writes a genuine mp4 via
PyAV/libx264 and reads it back) plus the pure queue-overflow logic in
submit_frame(), using a stand-in stalled background thread rather than
mocking anything.
"""

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import av
import numpy as np
import pytest

from androidlink.recording.recorder import (
    _QUEUE_MAXSIZE,
    _SOFTWARE_ENCODER,
    VideoRecorder,
    select_video_encoder,
)


def test_select_video_encoder_falls_back_to_libx264():
    """This machine has no NVENC/QSV/AMF hardware encoder available, so
    this genuinely exercises the real fallback path rather than a mock."""
    assert select_video_encoder(64, 64, 30) == _SOFTWARE_ENCODER


def test_record_and_playback_roundtrip(qtbot, tmp_path):
    recorder = VideoRecorder()
    path = tmp_path / "out.mp4"

    with qtbot.waitSignal(recorder.started, timeout=5000):
        recorder.start(path, 64, 64, 30)

    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    for i in range(5):
        recorder.submit_frame(np.full((64, 64, 3), i * 10, dtype=np.uint8))

    with qtbot.waitSignal(recorder.stopped, timeout=5000):
        recorder.stop()

    assert path.exists()
    container = av.open(str(path))
    try:
        stream = container.streams.video[0]
        decoded = list(container.decode(stream))
        assert len(decoded) == 5
    finally:
        container.close()


def test_start_with_unwritable_path_emits_error(qtbot, tmp_path):
    """A directory (no file extension for PyAV to infer a container format
    from) is a genuinely invalid recording path -- exercises the real
    av.open() failure path rather than a contrived one."""
    recorder = VideoRecorder()

    with qtbot.waitSignal(recorder.error, timeout=5000):
        recorder.start(tmp_path, 64, 64, 30)

    assert not recorder.is_recording


def test_submit_frame_noop_when_not_recording(qapp):
    recorder = VideoRecorder()
    recorder.submit_frame(np.zeros((4, 4, 3), dtype=np.uint8))
    assert recorder._queue.qsize() == 0


def test_submit_frame_noop_when_paused(qapp):
    recorder = VideoRecorder()
    stall = threading.Event()
    recorder._thread = threading.Thread(target=stall.wait, daemon=True)
    recorder._thread.start()
    recorder.set_paused(True)

    recorder.submit_frame(np.zeros((4, 4, 3), dtype=np.uint8))
    assert recorder._queue.qsize() == 0

    stall.set()
    recorder._thread.join(timeout=2)


def test_submit_frame_drops_oldest_when_queue_full(qapp):
    recorder = VideoRecorder()
    stall = threading.Event()
    recorder._thread = threading.Thread(target=stall.wait, daemon=True)
    recorder._thread.start()  # alive but not draining the queue

    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    for _ in range(_QUEUE_MAXSIZE + 10):
        recorder.submit_frame(frame)

    assert recorder._queue.qsize() == _QUEUE_MAXSIZE
    assert recorder._dropped_frames == 10

    stall.set()
    recorder._thread.join(timeout=2)
