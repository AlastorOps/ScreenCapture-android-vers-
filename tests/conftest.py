"""Shared pytest fixtures.

The `qtbot`/`qapp` fixtures used in tests are provided automatically by the
pytest-qt plugin (see requirements.txt) once a QApplication-based widget is
instantiated in a test.
"""

from androidlink.audio.mic_controller import MicController
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.controller import CastingController
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.panels.screen_panel import ScreenPanel
from androidlink.ui.windows.settings_dialog import SettingsDialog


def build_settings_dialog(
    qtbot,
    settings_manager: SettingsManager,
    device_manager: DeviceManager,
    *,
    on_accent_changed=lambda _c: None,
    on_theme_mode_changed=lambda _m: None,
    parent=None,
) -> SettingsDialog:
    """Constructs a real SettingsDialog with real (not mocked)
    CastingController/MicController -- SettingsDialog needs both to restart
    an active cast/mic session live when the Settings dialog changes a
    setting a running session already picked at start time (resolution/FPS/
    bitrate overrides, audio output device, volume/mute)."""
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    screen_panel = ScreenPanel()
    qtbot.addWidget(screen_panel)

    casting_controller = CastingController(device_manager, device_panel, screen_panel, settings_manager)
    mic_controller = MicController(device_manager, device_panel, settings_manager)

    dialog = SettingsDialog(
        settings_manager,
        device_manager=device_manager,
        casting_controller=casting_controller,
        mic_controller=mic_controller,
        on_accent_changed=on_accent_changed,
        on_theme_mode_changed=on_theme_mode_changed,
        parent=parent,
    )
    qtbot.addWidget(dialog)
    return dialog
