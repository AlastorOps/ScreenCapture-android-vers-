import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.setup.wizard import SetupWizardDialog


def _build(qtbot, tmp_path):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()
    dialog = SetupWizardDialog(device_manager, settings_manager)
    qtbot.addWidget(dialog)
    return dialog, settings_manager


def test_wizard_renders_a_row_per_check(qtbot, tmp_path):
    dialog, _settings_manager = _build(qtbot, tmp_path)
    # 9 checks defined in setup/checks.py's run_setup_checks()
    assert dialog._rows_layout.count() == 9


def test_wizard_shows_guidance_when_things_are_missing(qtbot, tmp_path):
    dialog, _settings_manager = _build(qtbot, tmp_path)
    # Fresh DeviceManager: ADB missing, no virtual backends on this machine.
    assert "ADB installed" in dialog._guidance_label.text()
    assert dialog._guidance_label.text() != "Everything looks good."


def test_recheck_button_rerenders(qtbot, tmp_path):
    dialog, _settings_manager = _build(qtbot, tmp_path)
    count_before = dialog._rows_layout.count()
    dialog._run_checks()
    assert dialog._rows_layout.count() == count_before


def test_closing_without_checkbox_does_not_persist(qtbot, tmp_path):
    dialog, settings_manager = _build(qtbot, tmp_path)
    dialog._dont_show_checkbox.setChecked(False)
    dialog._on_close()
    assert settings_manager.settings.general.setup_wizard_completed is False


def test_closing_with_checkbox_persists(qtbot, tmp_path):
    dialog, settings_manager = _build(qtbot, tmp_path)
    dialog._dont_show_checkbox.setChecked(True)
    dialog._on_close()

    assert settings_manager.settings.general.setup_wizard_completed is True
    reloaded = SettingsManager(tmp_path / "config.json").load()
    assert reloaded.general.setup_wizard_completed is True
