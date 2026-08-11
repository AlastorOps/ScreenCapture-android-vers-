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
    # Otherwise MainWindow schedules a QTimer.singleShot(0, ...) to
    # auto-show the setup wizard (a real modal dialog.exec()) on the next
    # event-loop iteration -- harmless within this test alone, but the
    # QApplication is shared across the whole pytest session, so that
    # pending callback would fire and hang a LATER test the moment it next
    # pumps the event loop.
    settings.general.setup_wizard_completed = True

    theme_manager = ThemeManager(QApplication.instance())
    theme_manager.apply_theme(settings.general.accent_color)

    device_manager = DeviceManager()

    window = MainWindow(settings_manager, theme_manager, device_manager)
    qtbot.addWidget(window)

    assert window.windowTitle() == "AndroidLink"
