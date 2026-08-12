"""The Performance/Quality slider (Device panel, under Microphone) actually
controls the streaming pipeline: releasing it after a drag applies the new
position to an already-active cast session by restarting it, instead of
requiring the user to notice a separate "Refresh" button (removed -- see
CastingController.commit_slider_value()) or wait for the next time Cast is
turned on. Dragging alone (before release) stays purely local -- every drag
tick would otherwise restart the session.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.controller import CastingController
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.panels.screen_panel import ScreenPanel
from androidlink.ui.themes.theme_manager import ThemeManager
from androidlink.ui.windows.main_window import MainWindow


def _make_controller(qtbot, tmp_path) -> CastingController:
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    screen_panel = ScreenPanel()
    qtbot.addWidget(screen_panel)
    return CastingController(device_manager, device_panel, screen_panel, settings_manager)


def test_commit_slider_value_restarts_an_active_cast_session(qtbot, tmp_path):
    controller = _make_controller(qtbot, tmp_path)
    calls = []
    controller.restart_if_casting = lambda: calls.append(1)

    controller.set_slider_value(80)
    controller.commit_slider_value()

    assert calls == [1]
    assert controller._settings_manager.settings.streaming.performance_slider_value == 80


def test_commit_slider_value_still_persists_when_not_casting(qtbot, tmp_path):
    # restart_if_casting() is already a no-op while not casting (see
    # test_restart_timing.py) -- this just confirms commit_slider_value()
    # still saves the setting even though nothing restarts.
    controller = _make_controller(qtbot, tmp_path)

    controller.set_slider_value(30)
    controller.commit_slider_value()

    assert controller._settings_manager.settings.streaming.performance_slider_value == 30
    assert controller.is_casting is False


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


def test_dragging_the_slider_alone_does_not_restart(qtbot, tmp_path):
    """Every intermediate drag tick (valueChanged) must stay purely local --
    dragging across the whole slider must not restart the session dozens
    of times."""
    window = _make_main_window(qtbot, tmp_path)
    calls = []
    window._casting_controller.restart_if_casting = lambda: calls.append(1)

    window._device_panel.performance_slider.setValue(0)
    window._device_panel.performance_slider.setValue(100)

    assert calls == []


def test_releasing_the_slider_applies_it_end_to_end(qtbot, tmp_path):
    """Full path: LabeledSlider.committed -> DevicePanel's
    performance_slider_committed -> CastingController.commit_slider_value()
    -> restart_if_casting(). This is the fix for the slider "moving visually
    but not affecting the stream": previously only a since-removed manual
    Refresh button ever reached restart_if_casting() for this control, so
    releasing the slider on its own did nothing to an active session.
    """
    window = _make_main_window(qtbot, tmp_path)
    calls = []
    window._casting_controller.restart_if_casting = lambda: calls.append(1)

    window._device_panel.performance_slider.setValue(70)
    window._device_panel.performance_slider.committed.emit()

    assert calls == [1]
    assert window._settings_manager.settings.streaming.performance_slider_value == 70


def test_releasing_the_slider_when_not_casting_does_not_raise(qtbot, tmp_path):
    window = _make_main_window(qtbot, tmp_path)

    window._device_panel.performance_slider.setValue(40)
    window._device_panel.performance_slider.committed.emit()  # must not raise

    assert window._settings_manager.settings.streaming.performance_slider_value == 40
