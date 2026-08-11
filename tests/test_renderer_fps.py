"""VideoRenderWidget's render-FPS counter is a real measured value (prompt.md
section 20/34: never fabricate a performance number) -- these tests force
genuine synchronous paintEvent() calls via widget.grab() rather than mocking
the paint pipeline.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from androidlink.streaming.renderer import VideoRenderWidget


def test_render_fps_counts_real_paint_events(qtbot):
    widget = VideoRenderWidget()
    qtbot.addWidget(widget)
    widget.resize(64, 64)

    widget.set_frame(np.zeros((64, 64, 3), dtype=np.uint8))
    for _ in range(3):
        widget.grab()  # forces a genuine synchronous paintEvent

    fps_events = []
    widget.render_fps_updated.connect(fps_events.append)
    widget._emit_render_fps()

    assert fps_events == [3.0]


def test_render_fps_is_zero_when_nothing_was_painted(qtbot):
    widget = VideoRenderWidget()
    qtbot.addWidget(widget)

    fps_events = []
    widget.render_fps_updated.connect(fps_events.append)
    widget._emit_render_fps()

    assert fps_events == [0.0]


def test_render_fps_counter_resets_between_windows(qtbot):
    widget = VideoRenderWidget()
    qtbot.addWidget(widget)
    widget.resize(64, 64)

    widget.set_frame(np.zeros((64, 64, 3), dtype=np.uint8))
    widget.grab()
    widget._emit_render_fps()  # drains the counter

    fps_events = []
    widget.render_fps_updated.connect(fps_events.append)
    widget._emit_render_fps()  # nothing painted since the previous drain

    assert fps_events == [0.0]
