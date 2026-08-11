import logging

from androidlink.app.application import AndroidLinkApplication
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.ui.themes.theme_manager import ThemeManager
from androidlink.ui.windows.main_window import MainWindow
from androidlink.utils.logging import resolve_log_level, setup_logging

logger = logging.getLogger(__name__)


def startup() -> tuple[AndroidLinkApplication, MainWindow]:
    """Ordered startup sequence. Later phases insert streaming-pipeline /
    audio/camera/mic manager start here, after the window is constructed."""
    settings_manager = SettingsManager()
    settings = settings_manager.load()

    setup_logging(resolve_log_level(settings.general.logging_level, settings.general.debug_mode))
    logger.info("Starting AndroidLink")

    app = AndroidLinkApplication()

    theme_manager = ThemeManager(app)
    theme_manager.apply_theme(settings.general.accent_color, settings.general.theme)

    device_manager = DeviceManager()
    device_manager.start()

    window = MainWindow(settings_manager, theme_manager, device_manager)
    window.show()

    return app, window
