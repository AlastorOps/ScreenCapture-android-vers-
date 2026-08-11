"""Forwards keyboard input to Android, only while the video widget has focus
(prompt.md section 9: "Mouse for control, keyboard when typing" — and never
leak keystrokes into the desktop app's own controls).

Qt only delivers key events to whichever widget currently has focus, so
installing this filter on the render widget (which is focusable via click,
see streaming/renderer.py) is sufficient to scope input correctly — no extra
"is the Android view focused" bookkeeping needed.
"""

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent

from androidlink.input.keycodes import akeycode_for_qt_key, qt_modifiers_to_ameta
from androidlink.streaming.protocol import (
    KEY_EVENT_ACTION_DOWN,
    KEY_EVENT_ACTION_UP,
    encode_key_event,
    encode_text_event,
)


class KeyboardInputHandler(QObject):
    control_message = Signal(bytes)

    def __init__(self, target_widget, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._widget = target_widget
        self._enabled = False
        target_widget.installEventFilter(self)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj is not self._widget or not self._enabled:
            return False

        if event.type() == QEvent.Type.KeyPress:
            self._handle_key(event, KEY_EVENT_ACTION_DOWN)
            return True
        if event.type() == QEvent.Type.KeyRelease:
            self._handle_key(event, KEY_EVENT_ACTION_UP)
            return True

        return False

    def _handle_key(self, event: QKeyEvent, action: int) -> None:
        if event.isAutoRepeat():
            # Android repeats the key itself once ACTION_DOWN is received;
            # forwarding the OS's own autorepeat would double it up.
            return

        akeycode = akeycode_for_qt_key(event.key())
        if akeycode is not None:
            metastate = qt_modifiers_to_ameta(event.modifiers())
            data = encode_key_event(action, akeycode, metastate=metastate)
            self.control_message.emit(data)
            return

        if action != KEY_EVENT_ACTION_DOWN:
            return  # unmapped keys only send text on down, nothing on up

        text = event.text()
        if not text or not text.isprintable():
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            return  # a Ctrl+letter shortcut, not literal text (avoid \x01 etc.)

        self.control_message.emit(encode_text_event(text))
