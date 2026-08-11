import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from androidlink.input.mouse import MouseInputHandler
from androidlink.streaming.protocol import (
    CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT,
    CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT,
    MOTION_EVENT_ACTION_DOWN,
    MOTION_EVENT_ACTION_MOVE,
    MOTION_EVENT_ACTION_UP,
    MOTION_EVENT_BUTTON_PRIMARY,
)
from androidlink.streaming.renderer import VideoRenderWidget


def _make_widget_with_frame(qtbot, widget_size=(200, 100), frame_size=(100, 50)):
    """A widget sized at exactly 2x the frame -> no letterboxing, so widget
    pixel (x, y) maps to frame pixel (x/2, y/2) exactly."""
    widget = VideoRenderWidget()
    qtbot.addWidget(widget)
    widget.resize(*widget_size)
    widget.show()

    frame = np.zeros((frame_size[1], frame_size[0], 3), dtype=np.uint8)
    widget.set_frame(frame)
    return widget


def test_click_emits_touch_down_and_up_at_mapped_coordinates(qtbot):
    widget = _make_widget_with_frame(qtbot)
    handler = MouseInputHandler(widget)
    handler.set_enabled(True)

    messages = []
    handler.control_message.connect(messages.append)

    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=QPoint(40, 20))
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=QPoint(40, 20))

    assert len(messages) == 2
    down, up = messages

    assert down[0] == CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT
    assert down[1] == MOTION_EVENT_ACTION_DOWN
    x, y, w, h = struct.unpack(">iiHH", down[10:22])
    assert (x, y, w, h) == (20, 10, 100, 50)  # (40,20) widget -> (20,10) frame at 2x scale
    action_button = struct.unpack(">I", down[24:28])[0]
    assert action_button == MOTION_EVENT_BUTTON_PRIMARY

    assert up[1] == MOTION_EVENT_ACTION_UP


def test_disabled_handler_emits_nothing(qtbot):
    widget = _make_widget_with_frame(qtbot)
    handler = MouseInputHandler(widget)
    handler.set_enabled(False)

    messages = []
    handler.control_message.connect(messages.append)

    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=QPoint(40, 20))
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=QPoint(40, 20))

    assert messages == []


def test_drag_emits_move_events(qtbot):
    widget = _make_widget_with_frame(qtbot)
    handler = MouseInputHandler(widget)
    handler.set_enabled(True)

    messages = []
    handler.control_message.connect(messages.append)

    QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseMove(widget, pos=QPoint(50, 50))
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=QPoint(50, 50))

    actions = [m[1] for m in messages]
    assert actions[0] == MOTION_EVENT_ACTION_DOWN
    assert actions[-1] == MOTION_EVENT_ACTION_UP
    assert MOTION_EVENT_ACTION_MOVE in actions


def test_wheel_emits_scroll_event(qtbot):
    widget = _make_widget_with_frame(qtbot)
    handler = MouseInputHandler(widget)
    handler.set_enabled(True)

    messages = []
    handler.control_message.connect(messages.append)

    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent

    event = QWheelEvent(
        QPointF(40, 20),
        QPointF(40, 20),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    handler.eventFilter(widget, event)

    assert len(messages) == 1
    assert messages[0][0] == CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT
