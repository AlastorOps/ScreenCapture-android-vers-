"""The main window's Performance/Quality slider bar has a "Refresh" button
(prompt.md sections 6/17) so a user can apply a new slider position to an
already-active cast session on demand -- dragging the slider alone never
auto-restarts (that would restart on every drag tick), and the Settings
dialog's equivalent is a separate control (see
test_settings_live_apply.py). Enabled only while actually casting.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.ui.themes.theme_manager import ThemeManager
from androidlink.ui.windows.main_window import MainWindow


def _make_main_window(qtbot, tmp_path) -> MainWindow:
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    settings_manager.settings.general.setup_wizard_completed = True
    theme_manager = ThemeManager(QApplication.instance())
    theme_manager.apply_theme(settings_manager.settings.general.accent_color)
    device_manager = DeviceManager()
    window = MainWindow(settings_manager, theme_manager, device_manager)
    qtbot.addWidget(window)
    return window


def test_refresh_button_disabled_when_not_casting(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)
    assert window._refresh_resolution_button.isEnabled() is False


def test_refresh_button_enables_on_cast_session_started(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)

    window._casting_controller.cast_session_started.emit(1920, 1080, 60, True)

    assert window._refresh_resolution_button.isEnabled() is True


def test_refresh_button_disables_on_cast_session_stopped(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)
    window._casting_controller.cast_session_started.emit(1920, 1080, 60, True)
    assert window._refresh_resolution_button.isEnabled() is True

    window._casting_controller.cast_session_stopped.emit()

    assert window._refresh_resolution_button.isEnabled() is False


def test_refresh_button_click_calls_restart_if_casting(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)
    window._casting_controller.cast_session_started.emit(1920, 1080, 60, True)  # enables the button
    calls = []
    window._casting_controller.restart_if_casting = lambda: calls.append(1)

    window._refresh_resolution_button.click()

    assert calls == [1]


def test_dragging_slider_alone_does_not_restart(qtbot, tmp_path):
    """Only clicking Refresh should trigger a restart -- dragging the
    slider by itself must stay purely local (updates the readout/internal
    value only), or every drag tick would restart the session."""
    window = _make_main_window(qtbot, tmp_path)
    calls = []
    window._casting_controller.restart_if_casting = lambda: calls.append(1)

    window._performance_slider.setValue(0)
    window._performance_slider.setValue(100)

    assert calls == []
