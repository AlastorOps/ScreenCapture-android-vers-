import base64
import logging

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QDockWidget, QLabel, QMainWindow, QPushButton, QToolBar, QWidget

from androidlink.audio.mic_controller import MicController
from androidlink.camera.camera_controller import CameraController
from androidlink.device.device_model import AndroidDevice
from androidlink.device.display_info import FALLBACK_HZ
from androidlink.device.manager import DeviceManager
from androidlink.recording.recording_controller import RecordingController
from androidlink.settings.manager import SettingsManager
from androidlink.setup.wizard import SetupWizardDialog
from androidlink.streaming.controller import CastingController
from androidlink.streaming.performance import describe_resolution, resolve_streaming_profile
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.panels.screen_panel import ScreenPanel
from androidlink.ui.panels.status_panel import StatusPanel
from androidlink.ui.themes.theme_manager import ThemeManager
from androidlink.ui.widgets.slider_labeled import LabeledSlider
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
        self._build_performance_toolbar()
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
            self._device_manager, device_panel, self._settings_manager
        )
        self._mic_controller = MicController(
            self._device_manager, device_panel, self._settings_manager
        )
        self._recording_controller = RecordingController(
            self._casting_controller, status_panel, self._settings_manager
        )

        self._casting_controller.stats_updated.connect(status_panel.set_stream_stats)
        self._casting_controller.cast_session_stopped.connect(status_panel.reset_stream_stats)
        screen_panel.render_fps_updated.connect(status_panel.set_render_fps)

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

    def _build_performance_toolbar(self) -> None:
        performance_slider = LabeledSlider("PERFORMANCE", "QUALITY", value=50, snap_interval=10)
        performance_slider.setToolTip(
            "Resolution/bitrate target for the next cast -- drag, then click"
            " ↻ Refresh to apply immediately to an already-active session"
        )
        performance_slider.setValue(self._settings_manager.settings.streaming.performance_slider_value)
        performance_slider.valueChanged.connect(self._casting_controller.set_slider_value)
        performance_slider.committed.connect(self._casting_controller.save_slider_value)
        self._performance_slider = performance_slider

        # Live resolution readout (prompt.md section 6/17) so the slider
        # isn't an opaque 0-100 number -- reflects the real profile
        # resolve_streaming_profile() would use for the *next* cast start,
        # including any Settings > Streaming > Advanced overrides.
        self._resolution_label = QLabel()
        self._resolution_label.setProperty("role", "mono")
        self._resolution_label.setContentsMargins(12, 0, 12, 0)
        self._resolution_label.setToolTip(
            "Approximate resolution cap for the next time casting starts -- "
            "the exact output depends on the connected device's real aspect ratio"
        )
        self._update_resolution_label(performance_slider.value())
        performance_slider.valueChanged.connect(self._update_resolution_label)
        # Refresh-rate detection (device/display_info.py) completes
        # asynchronously after connect -- without this the "@ N fps" readout
        # would keep showing the FALLBACK_HZ guess until the user happened
        # to touch the slider again after detection finished.
        self._device_manager.devices_changed.connect(
            lambda _devices: self._update_resolution_label(self._performance_slider.value())
        )

        # Dragging the slider alone never restarts an active session (that
        # would restart on every drag tick, which would be far more
        # disruptive than useful) -- this button lets the user apply the
        # new position on demand instead of having to toggle Cast off and
        # back on. Only meaningful while actually casting.
        self._refresh_resolution_button = QPushButton("↻ Refresh")
        self._refresh_resolution_button.setToolTip(
            "Apply the current Performance/Quality position to the active cast "
            "session now, instead of waiting for the next time Cast is turned on"
        )
        self._refresh_resolution_button.setEnabled(self._casting_controller.is_casting)
        self._refresh_resolution_button.clicked.connect(self._casting_controller.restart_if_casting)
        self._casting_controller.cast_session_started.connect(
            lambda *_args: self._refresh_resolution_button.setEnabled(True)
        )
        self._casting_controller.cast_session_stopped.connect(
            lambda: self._refresh_resolution_button.setEnabled(False)
        )

        # A plain QToolBar pinned to the bottom -- not a QDockWidget -- so it
        # stays fixed and full-width regardless of how the panels above it
        # are rearranged (prompt.md section 16/17: the slider bar is not one
        # of the customizable panels).
        toolbar = QToolBar("Performance", self)
        toolbar.setObjectName("performance_toolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.addWidget(performance_slider)
        toolbar.addWidget(self._resolution_label)
        toolbar.addWidget(self._refresh_resolution_button)
        self.addToolBar(Qt.ToolBarArea.BottomToolBarArea, toolbar)
        self._performance_toolbar = toolbar

    def _update_resolution_label(self, slider_value: int) -> None:
        streaming = self._settings_manager.settings.streaming
        device = self._device_manager.active_device
        profile = resolve_streaming_profile(
            slider_value,
            max_size_override=streaming.resolution_override,
            max_fps_override=streaming.fps_override,
            bitrate_override_mbps=streaming.bitrate_override_mbps,
            automatic_fps=(device.refresh_rate_hz if device else None) or FALLBACK_HZ,
        )
        self._resolution_label.setText(f"{describe_resolution(profile.max_size)} @ {profile.max_fps} fps")

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

        self._performance_toolbar.setVisible(not checked)
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
            on_performance_default_changed=self._performance_slider.setValue,
            on_theme_mode_changed=self._theme_manager.set_theme,
            parent=self,
        )
        dialog.exec()
        # Streaming > Advanced overrides (resolution/FPS/bitrate) may have
        # changed while the dialog was open even without moving the slider
        # itself -- refresh the readout so it never shows a stale value.
        self._update_resolution_label(self._performance_slider.value())

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
