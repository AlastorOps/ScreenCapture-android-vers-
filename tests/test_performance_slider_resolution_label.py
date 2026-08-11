"""The Performance/Quality slider shows a live resolution readout (e.g.
"~1080p (1920px)") next to it, in both the main window's bottom toolbar and
the Settings dialog's Streaming tab, so the 0-100 slider isn't an opaque
number -- see streaming/performance.py's describe_resolution().
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.ui.themes.theme_manager import ThemeManager
from androidlink.ui.windows.main_window import MainWindow
from androidlink.ui.windows.settings_dialog import SettingsDialog

from tests.conftest import build_settings_dialog


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


def test_main_window_resolution_label_updates_live_as_slider_moves(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)

    window._performance_slider.setValue(0)
    assert window._resolution_label.text() == "~720p (1280px) @ 60 fps"

    window._performance_slider.setValue(100)
    assert window._resolution_label.text() == "~1440p (2560px) @ 60 fps"


def test_main_window_resolution_label_respects_persisted_override(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)
    window._settings_manager.settings.streaming.resolution_override = 2560

    window._update_resolution_label(window._performance_slider.value())

    assert "2560px" in window._resolution_label.text()


def test_opening_settings_refreshes_the_main_window_label_after_override_change(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)
    window._performance_slider.setValue(0)
    assert window._resolution_label.text() == "~720p (1280px) @ 60 fps"

    dialog = SettingsDialog(
        window._settings_manager,
        device_manager=window._device_manager,
        casting_controller=window._casting_controller,
        mic_controller=window._mic_controller,
        on_accent_changed=window._theme_manager.apply_theme,
        on_performance_default_changed=window._performance_slider.setValue,
        parent=window,
    )
    qtbot.addWidget(dialog)
    dialog._resolution_combo.setCurrentIndex(3)  # "Up to 2560×1440"
    dialog.close()

    window._update_resolution_label(window._performance_slider.value())
    assert "2560px" in window._resolution_label.text()


def test_settings_dialog_resolution_label_updates_with_slider_and_override(qtbot, tmp_path):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()

    dialog = build_settings_dialog(qtbot, settings_manager, device_manager)

    dialog._perf_slider.setValue(0)
    assert dialog._streaming_resolution_label.text() == "~720p (1280px) @ 60 fps"

    dialog._resolution_combo.setCurrentIndex(3)  # "Up to 2560×1440" override
    assert dialog._streaming_resolution_label.text() == "~1440p (2560px) @ 60 fps"
