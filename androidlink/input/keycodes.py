"""Qt key -> Android AKEYCODE/AMETA mapping (prompt.md section 9: keyboard).

AKEYCODE/AMETA values are AOSP constants, vendored by scrcpy verbatim in
app/src/android/keycodes.h and app/src/android/input.h — this only maps the
"special" keys (navigation, editing, function keys, modifiers) that need
SC_CONTROL_MSG_TYPE_INJECT_KEYCODE. Plain printable characters are sent via
SC_CONTROL_MSG_TYPE_INJECT_TEXT instead (see input/keyboard.py), which is
simpler and layout-independent — Android handles the text directly rather
than us needing a full keyboard-layout-to-keycode table.
"""

from PySide6.QtCore import Qt

AMETA_SHIFT_ON = 0x01
AMETA_ALT_ON = 0x02
AMETA_CTRL_ON = 0x1000
AMETA_META_ON = 0x10000

# Keys that must go through INJECT_KEYCODE rather than INJECT_TEXT: they
# either have no printable representation, or (Enter/Tab/Backspace) behave
# as editing commands rather than literal text on Android.
QT_KEY_TO_AKEYCODE: dict[Qt.Key, int] = {
    Qt.Key.Key_Backspace: 67,  # AKEYCODE_DEL
    Qt.Key.Key_Delete: 112,  # AKEYCODE_FORWARD_DEL
    Qt.Key.Key_Return: 66,  # AKEYCODE_ENTER
    Qt.Key.Key_Enter: 66,
    Qt.Key.Key_Tab: 61,  # AKEYCODE_TAB
    Qt.Key.Key_Escape: 111,  # AKEYCODE_ESCAPE
    Qt.Key.Key_Space: 62,  # AKEYCODE_SPACE
    Qt.Key.Key_Up: 19,  # AKEYCODE_DPAD_UP
    Qt.Key.Key_Down: 20,  # AKEYCODE_DPAD_DOWN
    Qt.Key.Key_Left: 21,  # AKEYCODE_DPAD_LEFT
    Qt.Key.Key_Right: 22,  # AKEYCODE_DPAD_RIGHT
    Qt.Key.Key_Home: 122,  # AKEYCODE_MOVE_HOME
    Qt.Key.Key_End: 123,  # AKEYCODE_MOVE_END
    Qt.Key.Key_PageUp: 92,  # AKEYCODE_PAGE_UP
    Qt.Key.Key_PageDown: 93,  # AKEYCODE_PAGE_DOWN
    Qt.Key.Key_Insert: 124,  # AKEYCODE_INSERT
    Qt.Key.Key_CapsLock: 115,  # AKEYCODE_CAPS_LOCK
    Qt.Key.Key_Shift: 59,  # AKEYCODE_SHIFT_LEFT
    Qt.Key.Key_Control: 113,  # AKEYCODE_CTRL_LEFT
    Qt.Key.Key_Alt: 57,  # AKEYCODE_ALT_LEFT
    Qt.Key.Key_Meta: 117,  # AKEYCODE_META_LEFT
    Qt.Key.Key_F1: 131,
    Qt.Key.Key_F2: 132,
    Qt.Key.Key_F3: 133,
    Qt.Key.Key_F4: 134,
    Qt.Key.Key_F5: 135,
    Qt.Key.Key_F6: 136,
    Qt.Key.Key_F7: 137,
    Qt.Key.Key_F8: 138,
    Qt.Key.Key_F9: 139,
    Qt.Key.Key_F10: 140,
    Qt.Key.Key_F11: 141,
    Qt.Key.Key_F12: 142,
}


def qt_modifiers_to_ameta(modifiers: Qt.KeyboardModifier) -> int:
    metastate = 0
    if modifiers & Qt.KeyboardModifier.ShiftModifier:
        metastate |= AMETA_SHIFT_ON
    if modifiers & Qt.KeyboardModifier.ControlModifier:
        metastate |= AMETA_CTRL_ON
    if modifiers & Qt.KeyboardModifier.AltModifier:
        metastate |= AMETA_ALT_ON
    if modifiers & Qt.KeyboardModifier.MetaModifier:
        metastate |= AMETA_META_ON
    return metastate


def akeycode_for_qt_key(key: int) -> int | None:
    return QT_KEY_TO_AKEYCODE.get(Qt.Key(key))
