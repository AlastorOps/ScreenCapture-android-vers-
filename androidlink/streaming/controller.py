import logging

from PySide6.QtCore import QObject, QTimer, Signal

from androidlink.device.display_info import FALLBACK_HZ, SUPPORTED_TARGET_FPS_HZ
from androidlink.device.manager import DeviceManager
from androidlink.input.keyboard import KeyboardInputHandler
from androidlink.input.mouse import MouseInputHandler
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.fps_stability import CONSECUTIVE_UNSTABLE_WINDOWS_REQUIRED, FpsStabilityMonitor
from androidlink.streaming.performance import resolve_streaming_profile
from androidlink.streaming.transport import CastingSession
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.panels.screen_panel import ScreenPanel
from androidlink.utils import crash_state
from androidlink.utils.monitor_info import get_primary_monitor_refresh_hz
from androidlink.utils.platform import get_resource_path

logger = logging.getLogger(__name__)

SERVER_JAR_RELATIVE_PATH = "androidlink/vendor/scrcpy/scrcpy-server-v4.1.jar"

# Crash investigation (real report: AndroidLink terminating during casting,
# reproduced around FPS evaluation / connection-failure / reconnect):
# _on_stats_for_stability()'s auto-restart, when it fires, called
# _restart_if_casting() -> _stop_casting() synchronously from *within* the
# session's own stats_updated signal handler -- disconnecting that signal
# (and every other one, plus scheduling the session for deletion) while its
# own emission was still on the call stack. That reentrant pattern is a
# known source of hard, native (non-Python-traceback) crashes across the
# PySide6/shiboken C++ boundary, not just here but for connection_failed and
# audio/virtual-device-unavailable too, all of which react to one of a
# session's own signals by tearing that same session down.
#
# Fixed structurally: session cleanup (_defer_session_cleanup) is now always
# deferred by one event-loop tick, so disconnecting/deleting a session never
# happens while one of its own signals is still mid-emission, regardless of
# which handler triggered it. On top of that fix, AUTO_FPS_RESTART_ENABLED
# keeps Automatic FPS itself conservative for now -- it still measures and
# logs every window's evaluation, it just never acts on an unstable one --
# so the *feature* most directly implicated stays inert while this is
# verified against real hardware. Flip back to True once confirmed safe.
AUTO_FPS_RESTART_ENABLED = False


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
        # Learned by _on_stats_for_stability() when Automatic FPS proves
        # unstable at the device's real detected rate -- an extra ceiling on
        # top of MAX_STREAM_FPS, cleared whenever the user explicitly turns
        # Cast on again so a fresh session always gets to re-probe from the
        # top (see fps_stability.py's module docstring).
        self._auto_fps_ceiling: int | None = None
        self._fps_stability_monitor: FpsStabilityMonitor | None = None
        # The multi-second ADB push/reverse-tunnel/server-launch/socket-
        # handshake sequence _start_casting() kicks off reports stream_fps=0
        # for as long as it takes -- indistinguishable from "the pipeline
        # can't sustain the target" if fed to the stability monitor. Gated
        # on the video session having actually started (SessionMeta
        # received, see _on_session_started()) so that startup noise is
        # never mistaken for a real capacity problem (see
        # fps_stability.py's module docstring for the bug this fixes).
        self._video_session_started = False

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

    def commit_slider_value(self) -> None:
        """Called once when the user releases the Performance/Quality
        slider (Device panel): persists the new position and, if a cast
        session is already running, applies it immediately by restarting
        the session.

        This is the fix for the slider "moving visually but not affecting
        the stream": resolve_streaming_profile() (streaming/performance.py)
        always resolved the position into a real resolution/bitrate/FPS
        profile correctly, but previously nothing told an *already-running*
        session to pick that profile up -- set_slider_value() (connected to
        every drag tick) only ever updated CastingController's in-memory
        _slider_value, so the new position only took effect the next time
        Cast was turned on. scrcpy can't change resolution/bitrate on an
        already-running session (same constraint restart_if_casting()
        already handles for the Advanced Resolution/FPS/Bitrate overrides),
        so "apply immediately" here means a fresh scrcpy-server session --
        the Android device itself stays connected throughout, only the
        streaming session restarts. Only fires on release (not every drag
        tick), so dragging alone stays cheap and local.
        """
        self.save_slider_value()
        self.restart_if_casting()

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
            self._auto_fps_ceiling = None
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
        """Fires only on a genuine connect/disconnect transition -- never on
        a routine devices_changed poll tick for the same still-connected
        device (DeviceManager only emits this signal when active_device
        itself actually changes), so this is safe from accidentally tearing
        down a live session just because a background device scan ran.

        On disconnect (device is None): _control_enabled is the single
        source of truth _start_casting() reads for whether the *next*
        CastingSession should launch with control wired up -- resetting it
        here, unconditionally, is what makes Control actually turn off
        rather than just *look* off. Without this, the Device panel's
        Control toggle silently resets itself back to unchecked on
        disconnect (see device_panel.py's _set_cast_dependent_features_
        availability(), which uses blockSignals() so a programmatic reset
        never fires control_toggled -- deliberately, so it isn't logged/
        treated as a user action) while this class's own _control_enabled
        flag was never told about it, staying True. The next time the user
        turned Cast back on for a reconnected device, _start_casting() would
        then launch the new session with enable_control=True from that
        stale flag -- mouse/keyboard genuinely wired up and working -- while
        the UI still showed Control: OFF. That's the exact bug this reset
        closes: one authoritative boolean, reset in the one place a session
        (and whatever it was doing) actually goes away.
        """
        if device is None:
            self._control_enabled = False
            if self._session is not None:
                self._stop_casting()
                self._device_panel.set_casting_active(False)

    @staticmethod
    def _resolve_automatic_fps(device) -> int:
        """Automatic FPS starts optimistic: the highest refresh rate the
        device's screen reports *supporting* (device.supported_refresh_
        rates_hz, from dumpsys display), not just whatever it happens to be
        actively running right now (device.refresh_rate_hz). Many Android
        panels sit at a lower active rate by default (battery saving, an
        idle home screen, ...) but switch higher under load, and scrcpy's
        max_fps is only a ceiling on the encoder -- requesting a higher one
        doesn't force anything, it just stops artificially capping a device
        that could do more. If that optimistic target genuinely can't be
        sustained, the FpsStabilityMonitor below (streaming/fps_stability.py)
        steps it down with real, sustained, multi-window evidence rather
        than this method ever guessing conservatively up front -- that
        monitor is what makes starting optimistic safe.

        Falls back to the active rate (or FALLBACK_HZ) only when no
        supported-rates list was ever detected at all.
        """
        if device.supported_refresh_rates_hz:
            return max(device.supported_refresh_rates_hz)
        return device.refresh_rate_hz or FALLBACK_HZ

    def _start_casting(self) -> None:
        if self._session is not None:
            # Never let a second session exist alongside a live one -- both
            # would try to drive the same device's ADB connection/hardware
            # encoder at once (item 6: no duplicate streaming sessions).
            # Every intentional caller already routes through
            # _restart_if_casting() (which clears self._session before
            # calling back into this method), so reaching this branch means
            # something tried to start casting directly while a session was
            # already up -- stop it safely first, the same way a real
            # restart would, rather than silently overwriting the reference
            # and orphaning the old scrcpy-server process/thread.
            logger.warning("_start_casting() called while a session was already active; restarting instead")
            self._restart_if_casting()
            return

        device = self._device_manager.active_device
        adb_path = self._device_manager.adb_path

        if device is None or adb_path is None:
            logger.warning("Cannot start casting: no active device or adb path")
            self._device_panel.set_casting_active(False)
            return

        server_jar_path = get_resource_path(SERVER_JAR_RELATIVE_PATH)
        streaming_settings = self._settings_manager.settings.streaming
        automatic_fps = self._resolve_automatic_fps(device)
        if self._auto_fps_ceiling is not None:
            automatic_fps = min(automatic_fps, self._auto_fps_ceiling)
        profile = resolve_streaming_profile(
            self._slider_value,
            max_size_override=streaming_settings.resolution_override,
            max_fps_override=streaming_settings.fps_override,
            bitrate_override_mbps=streaming_settings.bitrate_override_mbps,
            automatic_fps=automatic_fps,
        )
        self._current_fps = profile.max_fps
        self._video_session_started = False

        monitor_hz = get_primary_monitor_refresh_hz()
        if device.supported_refresh_rates_hz:
            supported_text = "/".join(str(hz) for hz in device.supported_refresh_rates_hz)
        else:
            supported_text = "unknown"
        logger.info(
            "Display refresh: active=%sHz supported=%sHz PC monitor=%sHz",
            device.refresh_rate_hz, supported_text, monitor_hz,
        )
        logger.info("Starting cast: target=%dfps", profile.max_fps)
        crash_state.update(
            "casting",
            state="starting",
            device=device.display_serial,
            target_fps=profile.max_fps,
            resolution=profile.max_size,
            bitrate=profile.video_bit_rate,
            control_enabled=self._control_enabled,
            audio_enabled=self._audio_enabled,
            fps_override=streaming_settings.fps_override,
            auto_fps_ceiling=self._auto_fps_ceiling,
        )

        # Only probe for instability in Automatic mode -- a manual
        # fps_override is a deliberate user choice this never second-guesses
        # (see fps_stability.py's module docstring).
        self._fps_stability_monitor = (
            FpsStabilityMonitor(profile.max_fps, SUPPORTED_TARGET_FPS_HZ)
            if streaming_settings.fps_override is None
            else None
        )

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
        session.stats_updated.connect(self._on_stats_for_stability)

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
            session = self._session
            self._session = None
            self._disconnect_input_handlers(session)
            session.stop()
            self._defer_session_cleanup(session)

        self._screen_panel.show_placeholder("Waiting for device")
        if was_running:
            crash_state.update("casting", state="stopped")
            self.cast_session_stopped.emit()

    def _disconnect_input_handlers(self, session: CastingSession) -> None:
        for handler in (self._mouse_handler, self._keyboard_handler):
            try:
                handler.control_message.disconnect(session.send_control_message)
            except (TypeError, RuntimeError):
                pass  # was never connected (control was off for this session)

    @staticmethod
    def _defer_session_cleanup(session: CastingSession) -> None:
        """Severs every session->controller signal connection _start_casting()
        made for this specific session, deferred to the *next* event-loop
        tick (QTimer.singleShot(0, ...)) rather than synchronously.

        Crash investigation finding #1: every caller of this method
        (_stop_casting(), _on_connection_failed()) can itself be running
        *from inside* one of `session`'s own signal handlers -- e.g.
        connection_failed's handler tearing down the very session whose
        connection_failed.emit() is still on the call stack, or (before
        AUTO_FPS_RESTART_ENABLED existed) an unstable stats_updated sample
        triggering a restart mid-emission. Disconnecting a Qt signal while
        that signal's own emission is still active is a reentrant pattern
        that has caused real, hard (non-Python-traceback) crashes across
        the PySide6/shiboken C++ boundary. Deferring by one tick guarantees
        the original emission has always fully returned to the event loop
        first, so this is now safe regardless of which signal handler
        triggered it.

        Crash investigation finding #2 (the actual "toggling Control
        crashes the app" bug -- every Control toggle restarts casting, so
        this path runs on every single one): session.deleteLater() must
        NOT be scheduled here. CastingSession owns an un-parented QThread
        (streaming/transport.py) that keeps running real teardown work
        (killing the scrcpy-server process, closing sockets/decoder --
        ScrcpyVideoClient.stop() can legitimately take up to 2 real
        seconds) for a while *after* session.stop() merely requests it via
        a queued cross-thread call. Scheduling deleteLater() on a bare
        immediate timer -- as this used to do -- could destroy the
        CastingSession wrapper while its QThread was still genuinely
        running, which is a hard native Qt crash ("QThread: Destroyed
        while thread is still running"), not a Python exception. Deletion
        is instead wired to the session's own `stopped` signal below,
        which -- unlike this method's own disconnect timer -- only fires
        once ScrcpyVideoClient.stop() has actually finished (`stopped` is
        the very last thing it does), so by the time deleteLater() runs,
        there is nothing left running to destroy out from under.

        `stopped` is deliberately left connected here (not disconnected
        above) for exactly that reason, on top of CastingSession's own
        teardown and _restart_if_casting()'s restart-chaining both still
        needing it to fire exactly once more after this call.
        """
        def _cleanup() -> None:
            for signal in (
                session.session_started,
                session.frame_available,
                session.connection_failed,
                session.audio_unavailable,
                session.audio_pcm_available,
                session.stats_updated,
            ):
                try:
                    signal.disconnect()
                except (TypeError, RuntimeError):
                    pass  # nothing was connected

        QTimer.singleShot(0, _cleanup)
        try:
            session.stopped.connect(session.deleteLater)
        except (TypeError, RuntimeError):
            pass  # session is already gone -- nothing to schedule

    def _on_session_started(self, width: int, height: int) -> None:
        logger.info("Casting session started: %dx%d", width, height)
        # Only from this point on is stream_fps/dropped_frames genuinely
        # measuring the decode/render pipeline rather than "hasn't finished
        # connecting yet" -- see _video_session_started's docstring in
        # __init__ and fps_stability.py's module docstring.
        self._video_session_started = True
        crash_state.update("casting", state="running", width=width, height=height)
        self._screen_panel.show_video()
        self.cast_session_started.emit(width, height, self._current_fps, self._audio_enabled)

    def _on_stats_for_stability(self, sample) -> None:
        """Feeds measured delivery stats into the Automatic-mode instability
        monitor (fps_stability.py) once the video session has actually
        started, and logs every completed window's evaluation -- not just
        the rare step-down -- so "is Automatic FPS behaving" is answerable
        straight from the logs (prompt.md: log the reason, not just the
        decision). A confirmed-unstable *streak* (not a single bad window)
        lowers _auto_fps_ceiling and restarts casting at the next lower
        standard tier. A no-op in manual-FPS mode (monitor is None, see
        _start_casting()) or before the session has started.
        """
        if self._fps_stability_monitor is None or not self._video_session_started:
            return
        evaluation = self._fps_stability_monitor.record_sample(sample.stream_fps, sample.dropped_frames)
        if evaluation is None:
            return  # window still filling

        crash_state.update(
            "casting_fps",
            target_fps=evaluation.target_fps,
            avg_decode_fps=evaluation.avg_stream_fps,
            avg_dropped_frames=evaluation.avg_dropped_frames,
            stable=evaluation.stable,
            consecutive_unstable_windows=evaluation.consecutive_unstable_windows,
        )

        if evaluation.stable:
            logger.info(
                "Automatic FPS evaluation: target=%dfps window=%ds avg_decode=%.1ffps "
                "avg_dropped=%.1f unstable_samples=%d/%d stability=STABLE decision=keep %dfps",
                evaluation.target_fps, evaluation.window_seconds, evaluation.avg_stream_fps,
                evaluation.avg_dropped_frames, evaluation.unstable_samples, evaluation.total_samples,
                evaluation.target_fps,
            )
            return

        if evaluation.decision_tier is None:
            logger.info(
                "Automatic FPS evaluation: target=%dfps window=%ds avg_decode=%.1ffps "
                "avg_dropped=%.1f unstable_samples=%d/%d stability=UNSTABLE "
                "(%d/%d consecutive unstable windows) decision=keep monitoring",
                evaluation.target_fps, evaluation.window_seconds, evaluation.avg_stream_fps,
                evaluation.avg_dropped_frames, evaluation.unstable_samples, evaluation.total_samples,
                evaluation.consecutive_unstable_windows, CONSECUTIVE_UNSTABLE_WINDOWS_REQUIRED,
            )
            return

        if not AUTO_FPS_RESTART_ENABLED:
            logger.info(
                "Automatic FPS evaluation: target=%dfps window=%ds avg_decode=%.1ffps "
                "avg_dropped=%.1f unstable_samples=%d/%d stability=UNSTABLE "
                "reason=sustained shortfall over %d consecutive %ds windows "
                "decision=WOULD reduce to %dfps (auto-restart temporarily disabled -- "
                "see AUTO_FPS_RESTART_ENABLED)",
                evaluation.target_fps, evaluation.window_seconds, evaluation.avg_stream_fps,
                evaluation.avg_dropped_frames, evaluation.unstable_samples, evaluation.total_samples,
                evaluation.consecutive_unstable_windows, evaluation.window_seconds, evaluation.decision_tier,
            )
            # Still record the streak reset so re-enabling later doesn't
            # inherit a stale decision, but never touch the session itself.
            return

        logger.info(
            "Automatic FPS evaluation: target=%dfps window=%ds avg_decode=%.1ffps "
            "avg_dropped=%.1f unstable_samples=%d/%d stability=UNSTABLE "
            "reason=sustained shortfall over %d consecutive %ds windows decision=reduce to %dfps",
            evaluation.target_fps, evaluation.window_seconds, evaluation.avg_stream_fps,
            evaluation.avg_dropped_frames, evaluation.unstable_samples, evaluation.total_samples,
            evaluation.consecutive_unstable_windows, evaluation.window_seconds, evaluation.decision_tier,
        )
        self._auto_fps_ceiling = evaluation.decision_tier
        self._fps_stability_monitor = None
        # Deferred even though _restart_if_casting()/_stop_casting() are now
        # internally safe to call reentrantly (see _defer_session_cleanup) --
        # belt and suspenders: this call site is, by construction, always
        # inside the stats_updated signal's own emission, so there is never
        # a reason to risk it.
        QTimer.singleShot(0, self._restart_if_casting)

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
        crash_state.update("casting", state="connection_failed", message=message)
        was_running = self._session is not None
        if self._session is not None:
            session = self._session
            self._session = None
            self._disconnect_input_handlers(session)
            session.stop()
            self._defer_session_cleanup(session)
        self._mouse_handler.set_enabled(False)
        self._keyboard_handler.set_enabled(False)
        self._device_panel.set_casting_active(False)
        self._screen_panel.show_placeholder(f"Could not start casting: {message}")
        if was_running:
            self.cast_session_stopped.emit()
