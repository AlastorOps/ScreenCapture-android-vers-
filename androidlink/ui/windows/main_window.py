import base64
import logging

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow, QWidget

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
from androidlink.ui.widgets.status_dot import StatusDot, StatusState
from androidlink.ui.windows.settings_dialog import SettingsDialog
from androidlink.utils.platform import get_logs_dir, open_path_in_explorer
from androidlink.utils.system_stats import SystemStatsSampler

logger = logging.getLogger(__name__)

# Default dock widths in pixels, matching Phase 1's fixed splitter sizes
# ([260, 680, 260]) so "Restore Default Layout" reproduces the original look.
_DEFAULT_DOCK_WIDTHS = [260, 680, 260]


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
        self.setDockNestingEnabled(True)

        self._build_docks()
        self._build_menu()
        self._build_status_bar()
        self._restore_saved_layout_or_default()

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

        view_menu = menu_bar.addMenu("&View")
        for dock in (self._device_dock, self._screen_dock, self._status_dock):
            view_menu.addAction(dock.toggleViewAction())
        view_menu.addSeparator()
        restore_layout_action = view_menu.addAction("&Restore Default Layout")
        restore_layout_action.triggered.connect(self._on_restore_default_layout)

        help_menu = menu_bar.addMenu("&Help")
        setup_guide_action = help_menu.addAction("&Setup Guide...")
        setup_guide_action.triggered.connect(self._show_setup_wizard)
        open_logs_action = help_menu.addAction("Open &Logs")
        open_logs_action.triggered.connect(self._open_logs)

    def _make_dock(self, object_name: str, title: str, widget: QWidget) -> QDockWidget:
        """Wraps a panel in a QDockWidget so show/hide/float/rearrange/resize
        (prompt.md section 16) come from Qt's native dock machinery instead
        of a fixed QSplitter. The panel's own BasePanel title label is
        redundant once the dock provides its own titlebar, so it's hidden
        here rather than shown twice.
        """
        widget.set_title_visible(False)
        dock = QDockWidget(title, self)
        dock.setObjectName(object_name)  # required for QMainWindow.saveState()/restoreState()
        dock.setWidget(widget)
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        return dock

    def _build_docks(self) -> None:
        device_panel = DevicePanel(self._device_manager)
        screen_panel = ScreenPanel()
        status_panel = StatusPanel()

        self._device_panel = device_panel
        self._screen_panel = screen_panel
        self._status_panel = status_panel

        self._device_dock = self._make_dock("device_dock", "Device", device_panel)
        self._screen_dock = self._make_dock("screen_dock", "Screen", screen_panel)
        self._status_dock = self._make_dock("status_dock", "Status", status_panel)

        self._is_fullscreen = False
        self._pre_fullscreen_state = Qt.WindowState.WindowNoState
        self._device_dock_was_visible = True
        self._status_dock_was_visible = True

        screen_panel.fullscreen_toggled.connect(self._on_fullscreen_toggled)
        fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        fullscreen_shortcut.activated.connect(self._toggle_fullscreen_shortcut)
        escape_shortcut = QShortcut(QKeySequence("Escape"), self)
        escape_shortcut.activated.connect(self._exit_fullscreen_shortcut)

        self._casting_controller = CastingController(
            self._device_manager, device_panel, screen_panel, self._settings_manager
        )
        self._camera_controller = CameraController(
            self._device_manager, device_panel, status_panel, self._settings_manager
        )
        self._mic_controller = MicController(
            self._device_manager, device_panel, self._settings_manager
        )
        self._recording_controller = RecordingController(
            self._casting_controller, status_panel, self._settings_manager
        )

        self._casting_controller.stats_updated.connect(status_panel.set_stream_stats)
        self._casting_controller.cast_session_stopped.connect(status_panel.reset_stream_stats)
        self._casting_controller.cast_session_started.connect(self._on_cast_session_started_diagnostics)
        screen_panel.render_fps_updated.connect(status_panel.set_render_fps)

        # Performance/Quality slider (Device panel, under Microphone -- the
        # only copy of this control in the app). Drag ticks only update
        # CastingController's in-memory position and the Diagnostics
        # readout; commit (slider release) is what actually applies it,
        # restarting an already-active cast session if there is one -- see
        # CastingController.commit_slider_value()'s docstring for the full
        # trace from this signal down to the scrcpy-server launch args.
        initial_slider_value = self._settings_manager.settings.streaming.performance_slider_value
        device_panel.set_initial_performance_slider_value(initial_slider_value)
        device_panel.performance_slider_changed.connect(self._on_performance_slider_changed)
        device_panel.performance_slider_committed.connect(self._casting_controller.commit_slider_value)
        status_panel.set_performance_quality(initial_slider_value)

        self._system_stats_sampler = SystemStatsSampler(parent=self)
        self._system_stats_sampler.sample_ready.connect(status_panel.set_system_stats)
        self._system_stats_sampler.start()

    def _apply_default_dock_layout(self) -> None:
        """Device | Screen | Status side by side, matching Phase 1's fixed
        splitter arrangement -- the baseline "Restore Default Layout" resets
        to (prompt.md section 16)."""
        for dock in (self._device_dock, self._screen_dock, self._status_dock):
            dock.setFloating(False)
            dock.setVisible(True)

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self._device_dock)
        self.splitDockWidget(self._device_dock, self._screen_dock, Qt.Orientation.Horizontal)
        self.splitDockWidget(self._screen_dock, self._status_dock, Qt.Orientation.Horizontal)
        self.resizeDocks(
            [self._device_dock, self._screen_dock, self._status_dock],
            _DEFAULT_DOCK_WIDTHS,
            Qt.Orientation.Horizontal,
        )

    def _restore_saved_layout_or_default(self) -> None:
        self._apply_default_dock_layout()

        state_b64 = self._settings_manager.settings.general.layout_state
        if not state_b64:
            return
        try:
            raw = base64.b64decode(state_b64.encode("ascii"))
        except (ValueError, UnicodeDecodeError):
            logger.warning("Saved layout state was corrupt; using the default layout")
            return
        if not self.restoreState(QByteArray(raw)):
            logger.warning("Saved layout could not be restored; using the default layout")

    def _on_restore_default_layout(self) -> None:
        self._apply_default_dock_layout()
        self._settings_manager.settings.general.layout_state = None
        self._settings_manager.save()

    def _save_layout_state(self) -> None:
        state = bytes(self.saveState())
        self._settings_manager.settings.general.layout_state = base64.b64encode(state).decode(
            "ascii"
        )

    def _on_performance_slider_changed(self, value: int) -> None:
        """Every drag tick (Device panel's Performance/Quality slider):
        updates CastingController's in-memory position (used the next time
        a session starts or is restarted, see _start_casting() in
        streaming/controller.py) and the Diagnostics readout. Never
        restarts an active session by itself -- that would fire on every
        tick; see device_panel.performance_slider_committed /
        CastingController.commit_slider_value() for the actual apply-on-
        release path."""
        self._casting_controller.set_slider_value(value)
        self._status_panel.set_performance_quality(value)

    def _on_cast_session_started_diagnostics(
        self, _width: int, _height: int, fps: int, _audio_enabled: bool
    ) -> None:
        """Feeds the Status panel's Display Refresh / Target FPS rows
        (prompt.md section 20/diagnostics) once a cast session actually
        starts -- fps here is CastingController's resolved, already-capped
        target; display refresh is the device's own real detected rate,
        read directly off the active device rather than threaded through
        the signal (avoids widening cast_session_started's signature, which
        recording_controller.py and tests also depend on)."""
        device = self._device_manager.active_device
        self._status_panel.set_target_fps(fps)
        self._status_panel.set_display_refresh(device.refresh_rate_hz if device else None)
        self._status_panel.set_max_supported_refresh(device.supported_refresh_rates_hz if device else None)

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

        Device/Status are QDockWidgets now (see _build_docks()): entering
        fullscreen remembers each one's actual visibility rather than
        blindly forcing it on again when exiting, so a panel the user had
        already hidden via the View menu / dock close button stays hidden
        afterwards instead of silently reappearing.

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

        if checked:
            self._device_dock_was_visible = self._device_dock.isVisible()
            self._status_dock_was_visible = self._status_dock.isVisible()
            self._device_dock.setVisible(False)
            self._status_dock.setVisible(False)
            self._screen_dock.setTitleBarWidget(QWidget())
        else:
            self._device_dock.setVisible(self._device_dock_was_visible)
            self._status_dock.setVisible(self._status_dock_was_visible)
            self._screen_dock.setTitleBarWidget(None)

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
            device_manager=self._device_manager,
            casting_controller=self._casting_controller,
            mic_controller=self._mic_controller,
            on_accent_changed=self._theme_manager.apply_theme,
            on_theme_mode_changed=self._theme_manager.set_theme,
            parent=self,
        )
        dialog.exec()

    def _open_logs(self) -> None:
        open_path_in_explorer(get_logs_dir())

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self._save_layout_state()
        self._system_stats_sampler.stop()
        self._casting_controller.shutdown()
        self._camera_controller.shutdown()
        self._mic_controller.shutdown()
        self._recording_controller.shutdown()
        self._device_manager.stop()
        self._settings_manager.save()
        super().closeEvent(event)
