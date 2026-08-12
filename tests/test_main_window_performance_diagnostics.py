"""MainWindow wires the Device panel's Performance/Quality slider to the
Status panel's diagnostics readout (prompt.md section 20) so the actual
current setting can always be verified, not just guessed from the slider's
visual position.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.ui.themes.theme_manager import ThemeManager
from androidlink.ui.windows.main_window import MainWindow


def _make_main_window(qtbot, tmp_path, *, initial_slider_value=50) -> MainWindow:
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    settings_manager.settings.general.setup_wizard_completed = True
    settings_manager.settings.streaming.performance_slider_value = initial_slider_value
    theme_manager = ThemeManager(QApplication.instance())
    theme_manager.apply_theme(settings_manager.settings.general.accent_color)
    device_manager = DeviceManager()
    window = MainWindow(settings_manager, theme_manager, device_manager)
    qtbot.addWidget(window)
    return window


def test_persisted_slider_value_seeds_the_device_panel_and_diagnostics_on_launch(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path, initial_slider_value=70)

    assert window._device_panel.performance_slider.value() == 70
    assert window._status_panel._value_labels["performance_quality"].text() == "70%"


def test_dragging_the_slider_updates_the_diagnostics_readout_live(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)

    window._device_panel.performance_slider.setValue(30)

    assert window._status_panel._value_labels["performance_quality"].text() == "30%"


def test_dragging_the_slider_updates_the_casting_controller_slider_value(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)

    window._device_panel.performance_slider.setValue(20)

    assert window._casting_controller._slider_value == 20
