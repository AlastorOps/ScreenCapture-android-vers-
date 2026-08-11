import os
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

from androidlink.input.keyboard import KeyboardInputHandler
from androidlink.streaming.protocol import (
    CONTROL_MSG_TYPE_INJECT_KEYCODE,
    CONTROL_MSG_TYPE_INJECT_TEXT,
    KEY_EVENT_ACTION_DOWN,
    KEY_EVENT_ACTION_UP,
)


def _make_widget(qtbot):
    widget = QWidget()
    qtbot.addWidget(widget)
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    widget.show()
    widget.setFocus()
    return widget


def test_printable_key_sends_text_event(qtbot):
    widget = _make_widget(qtbot)
    handler = KeyboardInputHandler(widget)
    handler.set_enabled(True)

    messages = []
    handler.control_message.connect(messages.append)

    QTest.keyClick(widget, Qt.Key.Key_A)

    assert len(messages) == 1
    assert messages[0][0] == CONTROL_MSG_TYPE_INJECT_TEXT
    assert messages[0][5:] == b"a"


def test_special_key_sends_keycode_down_and_up(qtbot):
    widget = _make_widget(qtbot)
    handler = KeyboardInputHandler(widget)
    handler.set_enabled(True)

    messages = []
    handler.control_message.connect(messages.append)

    QTest.keyClick(widget, Qt.Key.Key_Backspace)

    assert len(messages) == 2
    down, up = messages
    assert down[0] == CONTROL_MSG_TYPE_INJECT_KEYCODE
    action, keycode = struct.unpack(">BI", down[1:6])
    assert action == KEY_EVENT_ACTION_DOWN
    assert keycode == 67  # AKEYCODE_DEL

    action_up = struct.unpack(">B", up[1:2])[0]
    assert action_up == KEY_EVENT_ACTION_UP


def test_ctrl_plus_letter_does_not_send_text(qtbot):
    widget = _make_widget(qtbot)
    handler = KeyboardInputHandler(widget)
    handler.set_enabled(True)

    messages = []
    handler.control_message.connect(messages.append)

    # QTest.keyClick with a modifier synthesizes real Ctrl-down/Ctrl-up key
    # events around the letter (verified by inspecting actual event.key()
    # values) -- those legitimately produce AKEYCODE_CTRL_LEFT messages.
    # What must NOT happen is 'c' itself leaking through as literal text.
    QTest.keyClick(widget, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier)

    text_events = [m for m in messages if m[0] == CONTROL_MSG_TYPE_INJECT_TEXT]
    assert text_events == []


def test_disabled_handler_emits_nothing(qtbot):
    widget = _make_widget(qtbot)
    handler = KeyboardInputHandler(widget)
    handler.set_enabled(False)

    messages = []
    handler.control_message.connect(messages.append)

    QTest.keyClick(widget, Qt.Key.Key_A)

    assert messages == []
