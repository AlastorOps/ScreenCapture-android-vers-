"""Translates PC mouse events on the video widget into Android touch events
over scrcpy's control socket (prompt.md section 9).

Implemented as a QObject event filter installed on the render widget rather
than a VideoRenderWidget subclass override, so the rendering widget itself
stays free of input/protocol concerns (single responsibility) and this
handler could be pointed at a different widget later without changes.
"""

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QMouseEvent, QWheelEvent

from androidlink.streaming.protocol import (
    MOTION_EVENT_ACTION_DOWN,
    MOTION_EVENT_ACTION_MOVE,
    MOTION_EVENT_ACTION_UP,
    MOTION_EVENT_BUTTON_PRIMARY,
    MOTION_EVENT_BUTTON_SECONDARY,
    MOTION_EVENT_BUTTON_TERTIARY,
    encode_scroll_event,
    encode_touch_event,
)
from androidlink.streaming.renderer import VideoRenderWidget

_BUTTON_MAP = {
    Qt.MouseButton.LeftButton: MOTION_EVENT_BUTTON_PRIMARY,
    Qt.MouseButton.RightButton: MOTION_EVENT_BUTTON_SECONDARY,
    Qt.MouseButton.MiddleButton: MOTION_EVENT_BUTTON_TERTIARY,
}


def _qt_buttons_to_android(buttons: Qt.MouseButton) -> int:
    result = 0
    for qt_button, android_button in _BUTTON_MAP.items():
        if buttons & qt_button:
            result |= android_button
    return result


class MouseInputHandler(QObject):
    control_message = Signal(bytes)

    def __init__(self, render_widget: VideoRenderWidget, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._widget = render_widget
        self._enabled = False
        render_widget.installEventFilter(self)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if obj is not self._widget or not self._enabled:
            return False

        event_type = event.type()
        if event_type in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick):
            self._handle_press(event)
        elif event_type == QEvent.Type.MouseMove:
            self._handle_move(event)
        elif event_type == QEvent.Type.MouseButtonRelease:
            self._handle_release(event)
        elif event_type == QEvent.Type.Wheel:
            self._handle_wheel(event)

        return False  # never consume: let Qt still process focus, etc.

    def _handle_press(self, event: QMouseEvent) -> None:
        pos = self._widget.map_to_frame(event.position())
        if pos is None:
            return
        frame_size = self._widget.frame_size()
        data = encode_touch_event(
            MOTION_EVENT_ACTION_DOWN,
            int(pos.x()),
            int(pos.y()),
            frame_size.width(),
            frame_size.height(),
            action_button=_BUTTON_MAP.get(event.button(), 0),
            buttons=_qt_buttons_to_android(event.buttons()),
        )
        self.control_message.emit(data)

    def _handle_move(self, event: QMouseEvent) -> None:
        if event.buttons() == Qt.MouseButton.NoButton:
            return  # only forward drags; hover-move isn't meaningful for touch
        pos = self._widget.clamp_to_frame(event.position())
        if pos is None:
            return
        frame_size = self._widget.frame_size()
        data = encode_touch_event(
            MOTION_EVENT_ACTION_MOVE,
            int(pos.x()),
            int(pos.y()),
            frame_size.width(),
            frame_size.height(),
            action_button=0,
            buttons=_qt_buttons_to_android(event.buttons()),
        )
        self.control_message.emit(data)

    def _handle_release(self, event: QMouseEvent) -> None:
        pos = self._widget.clamp_to_frame(event.position())
        if pos is None:
            return
        frame_size = self._widget.frame_size()
        data = encode_touch_event(
            MOTION_EVENT_ACTION_UP,
            int(pos.x()),
            int(pos.y()),
            frame_size.width(),
            frame_size.height(),
            action_button=_BUTTON_MAP.get(event.button(), 0),
            buttons=_qt_buttons_to_android(event.buttons()),
        )
        self.control_message.emit(data)

    def _handle_wheel(self, event: QWheelEvent) -> None:
        pos = self._widget.map_to_frame(event.position())
        if pos is None:
            return
        frame_size = self._widget.frame_size()
        delta = event.angleDelta()
        data = encode_scroll_event(
            int(pos.x()),
            int(pos.y()),
            frame_size.width(),
            frame_size.height(),
            hscroll=delta.x() / 120,  # eighths-of-a-degree -> "notches"
            vscroll=delta.y() / 120,
        )
        self.control_message.emit(data)
