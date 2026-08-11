import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.ui.themes.theme_manager import ThemeManager
from androidlink.ui.windows.main_window import MainWindow


def test_main_window_constructs(qtbot, tmp_path):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings = settings_manager.load()

    theme_manager = ThemeManager(QApplication.instance())
    theme_manager.apply_theme(settings.general.accent_color)

    device_manager = DeviceManager()

    window = MainWindow(settings_manager, theme_manager, device_manager)
    qtbot.addWidget(window)

    assert window.windowTitle() == "AndroidLink"
