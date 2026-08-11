from PySide6.QtCore import Qt

from androidlink.input.keycodes import (
    AMETA_ALT_ON,
    AMETA_CTRL_ON,
    AMETA_META_ON,
    AMETA_SHIFT_ON,
    akeycode_for_qt_key,
    qt_modifiers_to_ameta,
)


def test_akeycode_for_known_special_keys():
    assert akeycode_for_qt_key(Qt.Key.Key_Backspace) == 67
    assert akeycode_for_qt_key(Qt.Key.Key_Return) == 66
    assert akeycode_for_qt_key(Qt.Key.Key_Enter) == 66
    assert akeycode_for_qt_key(Qt.Key.Key_Escape) == 111
    assert akeycode_for_qt_key(Qt.Key.Key_Up) == 19
    assert akeycode_for_qt_key(Qt.Key.Key_Down) == 20
    assert akeycode_for_qt_key(Qt.Key.Key_Left) == 21
    assert akeycode_for_qt_key(Qt.Key.Key_Right) == 22


def test_akeycode_for_unmapped_key_returns_none():
    assert akeycode_for_qt_key(Qt.Key.Key_A) is None


def test_qt_modifiers_to_ameta_none():
    assert qt_modifiers_to_ameta(Qt.KeyboardModifier.NoModifier) == 0


def test_qt_modifiers_to_ameta_shift():
    assert qt_modifiers_to_ameta(Qt.KeyboardModifier.ShiftModifier) == AMETA_SHIFT_ON


def test_qt_modifiers_to_ameta_combined():
    modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
    result = qt_modifiers_to_ameta(modifiers)
    assert result == (AMETA_CTRL_ON | AMETA_ALT_ON)


def test_qt_modifiers_to_ameta_meta():
    assert qt_modifiers_to_ameta(Qt.KeyboardModifier.MetaModifier) == AMETA_META_ON
