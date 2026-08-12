"""Fullscreen mode (prompt.md section 8): toggling it must hide the side
panels/chrome and leave only the Android screen mirror, and must not lose
track of its own state across the button/F11/Escape entry points.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.ui.panels.screen_panel import ScreenPanel
from androidlink.ui.themes.theme_manager import ThemeManager
from androidlink.ui.windows.main_window import MainWindow


def test_fullscreen_button_emits_signal(qtbot):
    panel = ScreenPanel()
    qtbot.addWidget(panel)

    events = []
    panel.fullscreen_toggled.connect(events.append)

    panel._fullscreen_button.setChecked(True)
    assert events == [True]

    panel._fullscreen_button.setChecked(False)
    assert events == [True, False]


def test_set_fullscreen_checked_does_not_reemit(qtbot):
    panel = ScreenPanel()
    qtbot.addWidget(panel)

    events = []
    panel.fullscreen_toggled.connect(events.append)

    panel.set_fullscreen_checked(True)
    assert panel._fullscreen_button.isChecked() is True
    assert events == []  # programmatic sync, not a user action


def _make_main_window(qtbot, tmp_path) -> MainWindow:
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    # Otherwise MainWindow schedules a QTimer.singleShot(0, ...) that opens
    # a real modal setup-wizard dialog.exec() on the next event-loop tick --
    # since the QApplication is shared across the whole pytest session,
    # that pending callback can fire during a LATER test and hang it.
    settings_manager.settings.general.setup_wizard_completed = True
    theme_manager = ThemeManager(QApplication.instance())
    theme_manager.apply_theme(settings_manager.settings.general.accent_color)
    device_manager = DeviceManager()
    window = MainWindow(settings_manager, theme_manager, device_manager)
    qtbot.addWidget(window)
    window.show()
    return window


def test_entering_fullscreen_hides_side_panels_and_chrome(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)

    window._on_fullscreen_toggled(True)

    assert window._is_fullscreen is True
    assert window._device_panel.isVisible() is False
    assert window._status_panel.isVisible() is False
    assert window._device_panel.performance_slider.isVisible() is False
    assert window.menuBar().isVisible() is False
    assert window.statusBar().isVisible() is False


def test_exiting_fullscreen_restores_everything(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)

    window._on_fullscreen_toggled(True)
    window._on_fullscreen_toggled(False)

    assert window._is_fullscreen is False
    assert window._device_panel.isVisible() is True
    assert window._status_panel.isVisible() is True
    assert window._device_panel.performance_slider.isVisible() is True
    assert window.menuBar().isVisible() is True
    assert window.statusBar().isVisible() is True


def test_escape_only_exits_fullscreen_never_enters_it(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)
    assert window._is_fullscreen is False

    window._exit_fullscreen_shortcut()
    assert window._is_fullscreen is False  # no-op: wasn't fullscreen

    window._on_fullscreen_toggled(True)
    window._exit_fullscreen_shortcut()
    assert window._is_fullscreen is False


def test_f11_shortcut_toggles_both_directions(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)

    window._toggle_fullscreen_shortcut()
    assert window._is_fullscreen is True

    window._toggle_fullscreen_shortcut()
    assert window._is_fullscreen is False


def test_exiting_fullscreen_never_leaves_window_minimized(qtbot, tmp_path):
    """Regression test: on Windows, going straight from WindowFullScreen to
    WindowNoState via showNormal() is a known Qt quirk that can leave the
    window minimized to the taskbar instead of restored -- reported by a
    real user. Exiting fullscreen must never result in a minimized window."""
    window = _make_main_window(qtbot, tmp_path)

    window._on_fullscreen_toggled(True)
    assert bool(window.windowState() & Qt.WindowState.WindowFullScreen) is True

    window._on_fullscreen_toggled(False)
    state = window.windowState()
    assert not (state & Qt.WindowState.WindowMinimized)
    assert not (state & Qt.WindowState.WindowFullScreen)


def test_exiting_fullscreen_restores_prior_maximized_state(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)
    window.setWindowState(Qt.WindowState.WindowMaximized)

    window._on_fullscreen_toggled(True)
    window._on_fullscreen_toggled(False)

    assert bool(window.windowState() & Qt.WindowState.WindowMaximized) is True
    assert not (window.windowState() & Qt.WindowState.WindowFullScreen)
