"""Full multi-section Settings page (prompt.md section 27): every control is
either wired to a real settings field and saves on change, or is visibly
disabled with a tooltip explaining why (the honesty pattern already used in
device_panel.py) -- never a fake button that does nothing silently.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager

from tests.conftest import build_settings_dialog


def _build_dialog(qtbot, tmp_path, *, accent_calls=None):
    if accent_calls is None:
        accent_calls = []

    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()

    dialog = build_settings_dialog(
        qtbot,
        settings_manager,
        device_manager,
        on_accent_changed=accent_calls.append,
    )
    return settings_manager, dialog


def test_codec_control_is_disabled_with_explanation(qtbot, tmp_path):
    _settings, dialog = _build_dialog(qtbot, tmp_path)
    assert dialog._settings_manager  # sanity: fixture wired

    # Codec combo lives in the Streaming tab; find it via the group box.
    combo = dialog.findChild(type(dialog._resolution_combo), None)
    assert dialog._resolution_combo.isEnabled()  # resolution IS real
    # The codec combo itself has no stored attribute name -- assert via the
    # advanced group's children instead.
    from PySide6.QtWidgets import QComboBox

    combos = dialog.findChildren(QComboBox)
    codec_combos = [c for c in combos if c.count() == 1 and "Automatic (device-selected)" in c.itemText(0)]
    assert len(codec_combos) == 1
    assert codec_combos[0].isEnabled() is False
    assert codec_combos[0].toolTip()


def test_camera_and_microphone_selection_are_disabled_with_explanation(qtbot, tmp_path):
    _settings, dialog = _build_dialog(qtbot, tmp_path)

    from PySide6.QtWidgets import QComboBox

    # Camera tab's Camera/Resolution/FPS combos and Microphone tab's Input
    # combo are all read-only summaries pointing at the Device panel.
    disabled_with_tooltip = [
        c for c in dialog.findChildren(QComboBox) if not c.isEnabled() and c.toolTip()
    ]
    assert len(disabled_with_tooltip) >= 4  # codec + camera + resolution + fps + mic input


def test_reconnect_checkbox_is_disabled_with_explanation(qtbot, tmp_path):
    _settings, dialog = _build_dialog(qtbot, tmp_path)

    from PySide6.QtWidgets import QCheckBox

    checkboxes = dialog.findChildren(QCheckBox)
    assert len(checkboxes) == 1
    assert checkboxes[0].isEnabled() is False
    assert "prompt.md" in checkboxes[0].toolTip() or "never auto-connect" in checkboxes[0].toolTip().lower()


def test_accent_color_change_invokes_callback_and_reverts_on_cancel(qtbot, tmp_path):
    accent_calls = []
    settings_manager, dialog = _build_dialog(qtbot, tmp_path, accent_calls=accent_calls)
    original = settings_manager.settings.general.accent_color

    dialog._pending_accent = "#ff0000"
    dialog._update_accent_button()
    dialog._on_accent_changed("#ff0000")  # simulate what _pick_accent_color does
    assert accent_calls == ["#ff0000"]

    dialog._cancel()
    assert accent_calls == ["#ff0000", original]
    assert settings_manager.settings.general.accent_color == original


def test_streaming_resolution_override_saves_immediately(qtbot, tmp_path):
    settings_manager, dialog = _build_dialog(qtbot, tmp_path)

    dialog._resolution_combo.setCurrentIndex(2)  # "Up to 1920×1080"
    assert settings_manager.settings.streaming.resolution_override == 1920

    reloaded = SettingsManager(settings_manager.config_path).load()
    assert reloaded.streaming.resolution_override == 1920


def test_streaming_tab_no_longer_has_its_own_performance_slider(qtbot, tmp_path):
    # There is exactly one Performance/Quality slider in the whole app now
    # (Device panel, under Microphone) -- the Settings dialog's old copy of
    # it was removed rather than left as a second, easy-to-desync control.
    _settings_manager, dialog = _build_dialog(qtbot, tmp_path)

    assert not hasattr(dialog, "_perf_slider")


def test_recording_quality_change_saves(qtbot, tmp_path):
    settings_manager, dialog = _build_dialog(qtbot, tmp_path)

    dialog._quality_combo.setCurrentIndex(1)  # "High"
    assert settings_manager.settings.recording.quality == "high"


def test_debug_mode_forces_and_disables_logging_level_combo(qtbot, tmp_path):
    settings_manager, dialog = _build_dialog(qtbot, tmp_path)

    dialog._debug_mode_toggle.setChecked(True)
    assert settings_manager.settings.general.debug_mode is True
    assert dialog._log_level_combo.isEnabled() is False

    dialog._debug_mode_toggle.setChecked(False)
    assert dialog._log_level_combo.isEnabled() is True


def test_audio_output_device_combo_defaults_to_system_default(qtbot, tmp_path):
    _settings, dialog = _build_dialog(qtbot, tmp_path)

    assert dialog._audio_output_combo.itemText(0) == "System Default"
    assert dialog._audio_output_combo.currentIndex() == 0
