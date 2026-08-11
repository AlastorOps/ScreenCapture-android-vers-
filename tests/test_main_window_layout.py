"""Customizable panel layout (prompt.md section 16): panels are QDockWidgets
so show/hide/float/rearrange/resize come from Qt natively, and the resulting
arrangement round-trips through settings.general.layout_state.
"""

import base64
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
    # See test_app_boot.py: otherwise a pending setup-wizard QTimer.singleShot
    # can fire during a later test and hang it.
    settings_manager.settings.general.setup_wizard_completed = True
    theme_manager = ThemeManager(QApplication.instance())
    theme_manager.apply_theme(settings_manager.settings.general.accent_color)
    device_manager = DeviceManager()
    window = MainWindow(settings_manager, theme_manager, device_manager)
    qtbot.addWidget(window)
    window.show()
    return window


def test_panels_are_dock_widgets_with_stable_object_names(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)

    assert window._device_dock.objectName() == "device_dock"
    assert window._screen_dock.objectName() == "screen_dock"
    assert window._status_dock.objectName() == "status_dock"
    assert window._device_dock.widget() is window._device_panel
    assert window._screen_dock.widget() is window._screen_panel
    assert window._status_dock.widget() is window._status_panel


def test_docks_can_be_hidden_and_shown_like_any_qdockwidget(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)

    window._device_dock.setVisible(False)
    assert window._device_dock.isVisible() is False
    assert window._device_panel.isVisible() is False  # cascades from the dock

    window._device_dock.setVisible(True)
    assert window._device_panel.isVisible() is True


def test_view_menu_has_a_toggle_action_per_panel_and_a_restore_action(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)

    menu_bar = window.menuBar()
    view_menu_action = next(a for a in menu_bar.actions() if a.text() == "&View")
    action_texts = [a.text() for a in view_menu_action.menu().actions()]

    assert "Device" in action_texts
    assert "Screen" in action_texts
    assert "Status" in action_texts
    assert any("Restore Default Layout" in t for t in action_texts)


def test_closing_the_window_persists_layout_state(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)
    window._device_dock.setVisible(False)

    window._save_layout_state()

    saved = window._settings_manager.settings.general.layout_state
    assert saved
    # Must be valid base64 of a real QMainWindow.saveState() QByteArray.
    raw = base64.b64decode(saved.encode("ascii"))
    assert len(raw) > 0


def test_saved_layout_is_restored_on_next_launch(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)
    window._device_dock.setVisible(False)
    window._save_layout_state()
    window._settings_manager.save()

    # Fresh MainWindow reading the same settings file (simulating a restart).
    settings_manager2 = SettingsManager(window._settings_manager.config_path)
    settings_manager2.load()
    theme_manager = ThemeManager(QApplication.instance())
    device_manager = DeviceManager()
    window2 = MainWindow(settings_manager2, theme_manager, device_manager)
    qtbot.addWidget(window2)
    window2.show()

    assert window2._device_dock.isVisible() is False


def test_restore_default_layout_clears_saved_state_and_reshows_all_docks(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)
    window._device_dock.setVisible(False)
    window._save_layout_state()
    assert window._settings_manager.settings.general.layout_state is not None

    window._on_restore_default_layout()

    assert window._settings_manager.settings.general.layout_state is None
    assert window._device_dock.isVisible() is True
    assert window._screen_dock.isVisible() is True
    assert window._status_dock.isVisible() is True


def test_corrupt_saved_layout_state_falls_back_to_default_without_crashing(qtbot, tmp_path):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    settings_manager.settings.general.setup_wizard_completed = True
    settings_manager.settings.general.layout_state = "not valid base64!!!"
    theme_manager = ThemeManager(QApplication.instance())
    device_manager = DeviceManager()

    window = MainWindow(settings_manager, theme_manager, device_manager)  # must not raise
    qtbot.addWidget(window)
    window.show()

    assert window._device_dock.isVisible() is True
