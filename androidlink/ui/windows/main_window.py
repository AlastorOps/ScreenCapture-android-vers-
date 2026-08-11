from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QLabel, QMainWindow, QSplitter, QVBoxLayout, QWidget

from androidlink.audio.mic_controller import MicController
from androidlink.camera.camera_controller import CameraController
from androidlink.device.device_model import AndroidDevice
from androidlink.device.manager import DeviceManager
from androidlink.recording.recording_controller import RecordingController
from androidlink.settings.manager import SettingsManager
from androidlink.setup.wizard import SetupWizardDialog
from androidlink.streaming.controller import CastingController
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.panels.screen_panel import ScreenPanel
from androidlink.ui.panels.status_panel import StatusPanel
from androidlink.ui.themes.theme_manager import ThemeManager
from androidlink.ui.widgets.slider_labeled import LabeledSlider
from androidlink.ui.widgets.status_dot import StatusDot, StatusState
from androidlink.ui.windows.settings_dialog import SettingsDialog
from androidlink.utils.platform import get_logs_dir, open_path_in_explorer
from androidlink.utils.system_stats import SystemStatsSampler


class MainWindow(QMainWindow):
    def __init__(
        self,
        settings_manager: SettingsManager,
        theme_manager: ThemeManager,
        device_manager: DeviceManager,
    ) -> None:
        super().__init__()
        self._settings_manager = settings_manager
        self._theme_manager = theme_manager
        self._device_manager = device_manager

        self.setWindowTitle("AndroidLink")
        self.resize(1200, 760)

        self._build_menu()
        self._build_central_widget()
        self._build_status_bar()

        if not settings_manager.settings.general.setup_wizard_completed:
            QTimer.singleShot(0, self._show_setup_wizard)

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("&File")
        settings_action = file_menu.addAction("&Settings...")
        settings_action.triggered.connect(self._open_settings)
        file_menu.addSeparator()
        exit_action = file_menu.addAction("E&xit")
        exit_action.triggered.connect(self.close)

        help_menu = menu_bar.addMenu("&Help")
        setup_guide_action = help_menu.addAction("&Setup Guide...")
        setup_guide_action.triggered.connect(self._show_setup_wizard)
        open_logs_action = help_menu.addAction("Open &Logs")
        open_logs_action.triggered.connect(self._open_logs)

    def _build_central_widget(self) -> None:
        central = QWidget()
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)

        device_panel = DevicePanel(self._device_manager)
        screen_panel = ScreenPanel()
        status_panel = StatusPanel()

        splitter.addWidget(device_panel)
        splitter.addWidget(screen_panel)
        splitter.addWidget(status_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([260, 680, 260])

        outer_layout.addWidget(splitter, stretch=1)

        performance_slider = LabeledSlider("PERFORMANCE", "QUALITY", value=50)
        performance_slider.setToolTip(
            "Resolution/bitrate target used the next time casting starts"
        )
        outer_layout.addWidget(performance_slider)

        self.setCentralWidget(central)

        self._device_panel = device_panel
        self._status_panel = status_panel
        self._performance_slider = performance_slider
        self._screen_panel = screen_panel
        self._is_fullscreen = False
        self._pre_fullscreen_state = Qt.WindowState.WindowNoState

        screen_panel.fullscreen_toggled.connect(self._on_fullscreen_toggled)
        fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        fullscreen_shortcut.activated.connect(self._toggle_fullscreen_shortcut)
        escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        escape_shortcut.activated.connect(self._exit_fullscreen_shortcut)

        performance_slider.setValue(self._settings_manager.settings.streaming.performance_slider_value)
        self._casting_controller = CastingController(
            self._device_manager, device_panel, screen_panel, self._settings_manager
        )
        performance_slider.valueChanged.connect(self._casting_controller.set_slider_value)
        performance_slider.committed.connect(self._casting_controller.save_slider_value)
        self._camera_controller = CameraController(
            self._device_manager, device_panel, self._settings_manager
        )
        self._mic_controller = MicController(
            self._device_manager, device_panel, self._settings_manager
        )
        self._recording_controller = RecordingController(self._casting_controller, status_panel)

        self._casting_controller.stats_updated.connect(status_panel.set_stream_stats)
        self._casting_controller.cast_session_stopped.connect(status_panel.reset_stream_stats)
        screen_panel.render_fps_updated.connect(status_panel.set_render_fps)

        self._system_stats_sampler = SystemStatsSampler(parent=self)
        self._system_stats_sampler.sample_ready.connect(status_panel.set_system_stats)
        self._system_stats_sampler.start()

    def _build_status_bar(self) -> None:
        status_bar = self.statusBar()
        self._usb_dot = StatusDot(StatusState.DISCONNECTED)
        self._usb_label = QLabel("USB")
        self._usb_label.setProperty("role", "mono")

        status_bar.addPermanentWidget(self._usb_dot)
        status_bar.addPermanentWidget(self._usb_label)

        self._device_manager.adb_available_changed.connect(self._update_usb_status)
        self._device_manager.active_device_changed.connect(self._update_usb_status)
        self._update_usb_status()

    def _update_usb_status(self, *_args) -> None:
        active_device: AndroidDevice | None = self._device_manager.active_device

        if not self._device_manager.adb_available:
            self._usb_dot.setState(StatusState.ERROR)
            self._usb_label.setText("ADB missing")
        elif active_device is not None:
            self._usb_dot.setState(StatusState.CONNECTED)
            self._usb_label.setText(active_device.display_name)
        else:
            self._usb_dot.setState(StatusState.DISCONNECTED)
            self._usb_label.setText("USB")

    def _on_fullscreen_toggled(self, checked: bool) -> None:
        """Fullscreen mode (prompt.md section 8): hides everything but the
        Android screen mirror so it can use the whole window. Coordinate
        mapping for mouse/touch input already keys off the render widget's
        own size (see input/touch_mapper.py), not a fixed panel size, so it
        stays correct in fullscreen without any special-casing.

        Entering uses the high-level showFullScreen() -- switching that to a
        raw setWindowState() call (to symmetrically match the exit path
        below) turned out to visibly flicker through a minimized-looking
        frame before settling into fullscreen on Windows, so it's kept as
        the plain, well-behaved convenience method.

        Exiting deliberately does NOT use showNormal() -- on Windows,
        transitioning straight from WindowFullScreen back to WindowNoState
        is a known Qt/Windows quirk that can leave the window minimized to
        the taskbar instead of restored (reported: exiting this app's
        fullscreen minimized the whole window instead of returning to the
        normal view). Recording the exact pre-fullscreen state and
        restoring that precisely (and never a minimized one) avoids it.
        """
        self._is_fullscreen = checked
        self._device_panel.setVisible(not checked)
        self._status_panel.setVisible(not checked)
        self._performance_slider.setVisible(not checked)
        self._screen_panel.set_title_visible(not checked)
        self.menuBar().setVisible(not checked)
        self.statusBar().setVisible(not checked)

        if checked:
            self._pre_fullscreen_state = self.windowState()
            self.showFullScreen()
        else:
            restore_state = self._pre_fullscreen_state
            restore_state &= ~Qt.WindowState.WindowMinimized
            restore_state &= ~Qt.WindowState.WindowFullScreen
            self.setWindowState(restore_state)

        self._screen_panel.set_fullscreen_checked(checked)

    def _toggle_fullscreen_shortcut(self) -> None:
        self._on_fullscreen_toggled(not self._is_fullscreen)

    def _exit_fullscreen_shortcut(self) -> None:
        if self._is_fullscreen:
            self._on_fullscreen_toggled(False)

    def _show_setup_wizard(self) -> None:
        dialog = SetupWizardDialog(self._device_manager, self._settings_manager, parent=self)
        dialog.exec()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(
            self._settings_manager,
            on_accent_changed=self._theme_manager.apply_theme,
            parent=self,
        )
        dialog.exec()

    def _open_logs(self) -> None:
        open_path_in_explorer(get_logs_dir())

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._system_stats_sampler.stop()
        self._casting_controller.shutdown()
        self._camera_controller.shutdown()
        self._mic_controller.shutdown()
        self._recording_controller.shutdown()
        self._device_manager.stop()
        self._settings_manager.save()
        super().closeEvent(event)
