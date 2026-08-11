"""Theme presets (ui/themes/palette.py) are an open registry, not a fixed
Dark/Light pair -- palette.PRESETS is the single source of truth for what
Settings > General's Theme dropdown offers, and adding a new preset there
needs no other code changes. These tests cover the registry contract and its
wiring through ThemeManager/SettingsDialog, not exact color values (those
are a design choice, not a behavior to pin in a test).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.ui.themes import palette
from androidlink.ui.themes.theme_manager import ThemeManager

from tests.conftest import build_settings_dialog


def test_registry_contains_the_expected_presets():
    expected_ids = {"dark", "light", "midnight", "nord", "solarized_dark", "solarized_light"}
    assert expected_ids <= set(palette.PRESETS)


def test_every_preset_id_matches_its_own_dict_key():
    for key, preset in palette.PRESETS.items():
        assert preset.id == key


def test_set_theme_switches_the_active_palette():
    palette.set_theme("nord")
    assert palette.current() is palette.NORD
    palette.set_theme("dark")
    assert palette.current() is palette.DARK


def test_set_theme_falls_back_to_dark_for_an_unknown_id():
    palette.set_theme("some_removed_or_future_preset")
    assert palette.current() is palette.DARK


def test_theme_manager_apply_theme_switches_preset_and_reports_it(qapp):
    tm = ThemeManager(QApplication.instance())
    tm.apply_theme("#7aa2f7", "nord")
    assert tm.current_theme == "nord"
    assert palette.current() is palette.NORD

    tm.apply_theme("#ff5533")  # theme_id=None -- must keep the current preset
    assert tm.current_theme == "nord"


def test_theme_manager_set_theme_keeps_the_current_accent(qapp):
    tm = ThemeManager(QApplication.instance())
    tm.apply_theme("#ff5533", "dark")
    tm.set_theme("solarized_light")
    assert tm.current_theme == "solarized_light"
    assert tm.current_accent == "#ff5533"


def test_general_settings_accepts_any_preset_id_string(tmp_path):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings = settings_manager.load()
    settings.general.theme = "solarized_dark"
    settings_manager.save()

    reloaded = SettingsManager(tmp_path / "config.json").load()
    assert reloaded.general.theme == "solarized_dark"


def test_settings_dialog_theme_combo_lists_every_preset(qtbot, tmp_path):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()

    dialog = build_settings_dialog(qtbot, settings_manager, device_manager)

    combo_labels = {dialog._theme_combo.itemText(i) for i in range(dialog._theme_combo.count())}
    assert combo_labels == {p.label for p in palette.PRESETS.values()}


def test_settings_dialog_picking_a_preset_calls_the_live_preview_callback(qtbot, tmp_path):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()

    calls = []
    dialog = build_settings_dialog(
        qtbot, settings_manager, device_manager, on_theme_mode_changed=calls.append
    )

    nord_index = next(i for i, (_label, theme_id) in enumerate(dialog._theme_options) if theme_id == "nord")
    dialog._theme_combo.setCurrentIndex(nord_index)

    assert calls == ["nord"]
    assert dialog._pending_theme == "nord"
