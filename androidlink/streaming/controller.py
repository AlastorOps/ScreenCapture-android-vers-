import logging

from PySide6.QtCore import QObject, Signal

from androidlink.device.display_info import FALLBACK_HZ
from androidlink.device.manager import DeviceManager
from androidlink.input.keyboard import KeyboardInputHandler
from androidlink.input.mouse import MouseInputHandler
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.performance import resolve_streaming_profile
from androidlink.streaming.transport import CastingSession
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.panels.screen_panel import ScreenPanel
from androidlink.utils.platform import get_resource_path

logger = logging.getLogger(__name__)

SERVER_JAR_RELATIVE_PATH = "androidlink/vendor/scrcpy/scrcpy-server-v4.1.jar"


class CastingController(QObject):
    """Owns the CastingSession lifecycle: starts/stops it in response to the
    Cast/Control/Audio toggles and device connect/disconnect, routes decoded
    frames into the ScreenPanel's render widget, wires mouse/keyboard input
    to the control socket when Control is enabled, and routes volume/mute
    to the audio socket when Audio is enabled.

    Control and audio are fixed at scrcpy-server launch time (the protocol
    has no way to enable either on an already-running session), so toggling
    them while already casting restarts the session with the new flags.
    """

    cast_session_started = Signal(int, int, int, bool)  # width, height, target_fps, audio_enabled
    cast_session_stopped = Signal()
    frame_ready = Signal(object)  # decoded RGB24 ndarray, e.g. for recording/screenshots
    audio_pcm_ready = Signal(bytes)  # decoded PCM (48kHz stereo s16), e.g. for recording
    stats_updated = Signal(object)  # DiagnosticsSample, see streaming/diagnostics.py

    def __init__(
        self,
        device_manager: DeviceManager,
        device_panel: DevicePanel,
        screen_panel: ScreenPanel,
        settings_manager: SettingsManager,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._device_manager = device_manager
        self._device_panel = device_panel
        self._screen_panel = screen_panel
        self._settings_manager = settings_manager
        self._session: CastingSession | None = None
        self._control_enabled = False
        self._current_fps = 30

        settings = settings_manager.settings
        self._slider_value = settings.streaming.performance_slider_value
        self._audio_enabled = settings.audio.enabled
        self._audio_volume = settings.audio.volume
        self._audio_muted = settings.audio.muted
        device_panel.set_initial_audio_state(self._audio_enabled, self._audio_volume, self._audio_muted)

        self._mouse_handler = MouseInputHandler(screen_panel.render_widget, parent=self)
        self._keyboard_handler = KeyboardInputHandler(screen_panel.render_widget, parent=self)

        device_panel.cast_toggled.connect(self._on_cast_toggled)
        device_panel.control_toggled.connect(self._on_control_toggled)
        device_panel.audio_toggled.connect(self._on_audio_toggled)
        device_panel.audio_volume_changed.connect(self._on_audio_volume_changed)
        device_panel.audio_volume_committed.connect(self._save_audio_volume)
        device_panel.audio_mute_toggled.connect(self._on_audio_mute_toggled)
        device_manager.active_device_changed.connect(self._on_active_device_changed)

    @property
    def is_casting(self) -> bool:
        return self._session is not None

    def set_slider_value(self, value: int) -> None:
        self._slider_value = value

    def save_slider_value(self) -> None:
        self._settings_manager.settings.streaming.performance_slider_value = self._slider_value
        self._settings_manager.save()

    def restart_if_casting(self) -> None:
        """Public entry point for settings changes that require a fresh
        session to take effect -- resolution/FPS/bitrate overrides and
        audio output device selection can't be changed on an
        already-running scrcpy-server session any more than Control/Audio
        can (see this class's docstring), so the Settings dialog calls this
        after saving one of those instead of leaving the user to manually
        toggle Cast off and back on. A no-op while casting is off."""
        self._restart_if_casting()

    def apply_audio_volume(self, value: int) -> None:
        """Applies a volume change live to whatever cast session is
        currently active (a no-op otherwise) without touching settings
        persistence -- callers own persisting the value themselves. Mirrors
        the Device panel's own volume slider (_on_audio_volume_changed)."""
        self._on_audio_volume_changed(value)

    def apply_audio_muted(self, muted: bool) -> None:
        """Applies a mute change live to whatever cast session is currently
        active (a no-op otherwise), and persists it -- mirrors the Device
        panel's own mute toggle (_on_audio_mute_toggled)."""
        self._on_audio_mute_toggled(muted)

    def _save_audio_volume(self, value: int) -> None:
        self._settings_manager.settings.audio.volume = value
        self._settings_manager.save()

    def shutdown(self) -> None:
        self._stop_casting()

    def _on_cast_toggled(self, enabled: bool) -> None:
        if enabled:
            self._start_casting()
        else:
            self._stop_casting()

    def _on_control_toggled(self, enabled: bool) -> None:
        self._control_enabled = enabled
        self._restart_if_casting()

    def _on_audio_toggled(self, enabled: bool) -> None:
        self._audio_enabled = enabled
        self._restart_if_casting()
        self._settings_manager.settings.audio.enabled = enabled
        self._settings_manager.save()

    def _on_audio_volume_changed(self, value: int) -> None:
        self._audio_volume = value
        if self._session is not None:
            self._session.set_audio_volume(value / 100)

    def _on_audio_mute_toggled(self, muted: bool) -> None:
        self._audio_muted = muted
        if self._session is not None:
            self._session.set_audio_muted(muted)
        self._settings_manager.settings.audio.muted = muted
        self._settings_manager.save()

    def _restart_if_casting(self) -> None:
        """Stops the current session and starts a fresh one once the old
        one has genuinely finished tearing down.

        CastingSession.stop() posts a *queued* call to the worker thread
        (QMetaObject.invokeMethod(..., QueuedConnection)) so it returns
        immediately, well before the old scrcpy-server process is killed
        and its `adb reverse` tunnel is removed on-device. Calling
        _start_casting() right after used to launch a brand new
        scrcpy-server session while the old one was still mid-teardown --
        on real hardware this let the old session keep holding the
        device's hardware video encoder, so a resolution/FPS/bitrate change
        could silently fail to take effect (confirmed: the new session
        would start, but the device kept serving the old encoder
        configuration) even though a "new" session had technically begun.
        Waiting for the old session's `stopped` signal (only emitted after
        its worker thread has fully unwound) closes that race.
        """
        if self._session is None:
            return
        session_to_stop = self._session
        session_to_stop.stopped.connect(self._start_casting)
        self._stop_casting()

    def _on_active_device_changed(self, device) -> None:
        if device is None and self._session is not None:
            self._stop_casting()
            self._device_panel.set_casting_active(False)

    def _start_casting(self) -> None:
        device = self._device_manager.active_device
        adb_path = self._device_manager.adb_path

        if device is None or adb_path is None:
            logger.warning("Cannot start casting: no active device or adb path")
            self._device_panel.set_casting_active(False)
            return

        server_jar_path = get_resource_path(SERVER_JAR_RELATIVE_PATH)
        streaming_settings = self._settings_manager.settings.streaming
        profile = resolve_streaming_profile(
            self._slider_value,
            max_size_override=streaming_settings.resolution_override,
            max_fps_override=streaming_settings.fps_override,
            bitrate_override_mbps=streaming_settings.bitrate_override_mbps,
            automatic_fps=device.refresh_rate_hz or FALLBACK_HZ,
        )
        self._current_fps = profile.max_fps

        self._screen_panel.show_placeholder("Connecting...")

        audio_settings = self._settings_manager.settings.audio
        audio_output_device_id = (
            bytes.fromhex(audio_settings.output_device_id) if audio_settings.output_device_id else None
        )
        audio_secondary_output_device_id = (
            bytes.fromhex(audio_settings.secondary_output_device_id)
            if audio_settings.secondary_output_device_id
            else None
        )

        session = CastingSession(
            adb_path,
            device.serial,
            server_jar_path,
            profile,
            enable_control=self._control_enabled,
            enable_audio=self._audio_enabled,
            audio_output_device_id=audio_output_device_id,
            audio_secondary_output_device_id=audio_secondary_output_device_id,
            parent=self,
        )
        session.session_started.connect(self._on_session_started)
        session.frame_available.connect(self._on_frame_available)
        session.connection_failed.connect(self._on_connection_failed)
        session.audio_unavailable.connect(self._on_audio_unavailable)
        session.audio_pcm_available.connect(self.audio_pcm_ready)
        session.stats_updated.connect(self.stats_updated)

        if self._control_enabled:
            self._mouse_handler.control_message.connect(session.send_control_message)
            self._keyboard_handler.control_message.connect(session.send_control_message)
        self._mouse_handler.set_enabled(self._control_enabled)
        self._keyboard_handler.set_enabled(self._control_enabled)

        if self._audio_enabled:
            session.set_audio_volume(self._audio_volume / 100)
            session.set_audio_muted(self._audio_muted)

        self._session = session
        session.start()

    def _stop_casting(self) -> None:
        self._mouse_handler.set_enabled(False)
        self._keyboard_handler.set_enabled(False)

        was_running = self._session is not None
        if self._session is not None:
            self._disconnect_input_handlers(self._session)
            self._session.stop()
            self._session = None

        self._screen_panel.show_placeholder("Waiting for device")
        if was_running:
            self.cast_session_stopped.emit()

    def _disconnect_input_handlers(self, session: CastingSession) -> None:
        for handler in (self._mouse_handler, self._keyboard_handler):
            try:
                handler.control_message.disconnect(session.send_control_message)
            except (TypeError, RuntimeError):
                pass  # was never connected (control was off for this session)

    def _on_session_started(self, width: int, height: int) -> None:
        logger.info("Casting session started: %dx%d", width, height)
        self._screen_panel.show_video()
        self.cast_session_started.emit(width, height, self._current_fps, self._audio_enabled)

    def _on_frame_available(self) -> None:
        if self._session is None:
            return
        frame = self._session.take_latest_frame()
        if frame is not None:
            self._screen_panel.render_widget.set_frame(frame)
            self.frame_ready.emit(frame)

    def _on_audio_unavailable(self, is_error: bool) -> None:
        logger.warning("Android audio unavailable (error=%s)", is_error)
        self._device_panel.show_audio_unavailable(is_error)
        self._audio_enabled = False

    def _on_connection_failed(self, message: str) -> None:
        logger.warning("Casting failed: %s", message)
        was_running = self._session is not None
        if self._session is not None:
            self._disconnect_input_handlers(self._session)
        self._mouse_handler.set_enabled(False)
        self._keyboard_handler.set_enabled(False)
        self._device_panel.set_casting_active(False)
        self._screen_panel.show_placeholder(f"Could not start casting: {message}")
        self._session = None
        if was_running:
            self.cast_session_stopped.emit()
