import logging
import time

from PySide6.QtCore import QObject, QTimer

from androidlink.audio.mic_session import MicSession
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.controller import SERVER_JAR_RELATIVE_PATH
from androidlink.streaming.protocol import AUDIO_SOURCE_MIC
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.utils import crash_state
from androidlink.utils.platform import get_resource_path

logger = logging.getLogger(__name__)

# How long a session can go without a real decoded PCM packet before the
# meter honestly reports "No Signal" instead of a stale "Active" -- must be
# comfortably longer than normal packet spacing (Opus/AAC frames arrive
# every ~20-40ms) so ordinary jitter never trips it, but short enough that a
# genuinely stalled pipeline is caught quickly.
_NO_SIGNAL_TIMEOUT_S = 2.0
_STATUS_CHECK_INTERVAL_MS = 1000


class MicController(QObject):
    """Owns the MicSession lifecycle -- entirely independent of screen
    casting/camera (prompt.md section 13), since microphone mirroring is
    architecturally its own scrcpy-server session (video disabled,
    audio_source=mic) with no shared state with Cast/Control/Audio/Camera.
    """

    def __init__(
        self,
        device_manager: DeviceManager,
        device_panel: DevicePanel,
        settings_manager: SettingsManager,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._device_manager = device_manager
        self._device_panel = device_panel
        self._settings_manager = settings_manager
        self._session: MicSession | None = None
        self._mic_active_session = False  # True between _start_mic() and _stop_mic()
        self._last_level_time: float | None = None

        # Polls whether real audio_level_updated emissions have actually
        # kept arriving (see _on_audio_level_updated()/_check_signal_
        # staleness()) -- the honest way to tell "No Signal" (session
        # running, nothing decoded in a while) apart from "Active" (session
        # running, genuinely receiving audio), matching how status_panel.py/
        # renderer.py already use a QTimer for periodic real-measurement
        # checks rather than trusting a one-shot "started" signal forever.
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(_STATUS_CHECK_INTERVAL_MS)
        self._status_timer.timeout.connect(self._check_signal_staleness)

        settings = settings_manager.settings
        self._audio_source = settings.microphone.audio_source
        self._volume = settings.microphone.volume
        self._muted = settings.microphone.muted
        device_panel.set_initial_mic_state(self._audio_source, self._volume, self._muted)

        device_manager.active_device_changed.connect(self._on_active_device_changed)
        device_panel.mic_toggled.connect(self._on_mic_toggled)
        device_panel.mic_source_changed.connect(self._on_mic_source_changed)
        device_panel.mic_volume_changed.connect(self._on_mic_volume_changed)
        device_panel.mic_volume_committed.connect(self._save_mic_volume)
        device_panel.mic_mute_toggled.connect(self._on_mic_mute_toggled)

    def shutdown(self) -> None:
        self._stop_mic()

    def apply_volume(self, value: int) -> None:
        """Applies a volume change live to whatever mic session is
        currently active (a no-op otherwise), without touching settings
        persistence. Mirrors the Device panel's own mic volume slider."""
        self._on_mic_volume_changed(value)

    def apply_muted(self, muted: bool) -> None:
        """Applies a mute change live to whatever mic session is currently
        active (a no-op otherwise), and persists it. Mirrors the Device
        panel's own mic mute toggle."""
        self._on_mic_mute_toggled(muted)

    def _on_active_device_changed(self, device) -> None:
        if device is None:
            self._stop_mic()
            self._device_panel.set_mic_status_disconnected()

    def _on_mic_toggled(self, enabled: bool) -> None:
        if enabled:
            self._start_mic()
        else:
            self._stop_mic()

    def _on_mic_source_changed(self, source: str) -> None:
        self._audio_source = source
        self._restart_mic_if_active()
        self._settings_manager.settings.microphone.audio_source = source
        self._settings_manager.save()

    def _restart_mic_if_active(self) -> None:
        """Stops the current mic session and starts a fresh one once the
        old one has genuinely finished tearing down -- see
        streaming/controller.py's CastingController._restart_if_casting()
        docstring for why a naive stop()-then-start() can silently keep the
        old audio source active instead of applying the change (MicSession
        .stop() also posts a queued call to its worker thread)."""
        if self._session is None:
            return
        session_to_stop = self._session
        session_to_stop.stopped.connect(self._start_mic)
        self._stop_mic()

    def _on_mic_volume_changed(self, value: int) -> None:
        self._volume = value
        if self._session is not None:
            self._session.set_volume(value / 100)

    def _save_mic_volume(self, value: int) -> None:
        self._settings_manager.settings.microphone.volume = value
        self._settings_manager.save()

    def _on_mic_mute_toggled(self, muted: bool) -> None:
        self._muted = muted
        if self._session is not None:
            self._session.set_muted(muted)
        self._settings_manager.settings.microphone.muted = muted
        self._settings_manager.save()

    def _start_mic(self) -> None:
        if self._session is not None:
            # See streaming/controller.py's CastingController._start_casting()
            # for why this guard exists -- never let a second session run
            # alongside a live one.
            logger.warning("_start_mic() called while a session was already active; restarting instead")
            self._restart_mic_if_active()
            return

        device = self._device_manager.active_device
        adb_path = self._device_manager.adb_path
        if device is None or adb_path is None:
            logger.warning("Cannot start microphone: no active device")
            self._device_panel.show_mic_connection_failed("No device connected")
            return

        server_jar_path = get_resource_path(SERVER_JAR_RELATIVE_PATH)
        session = MicSession(
            adb_path,
            device.serial,
            server_jar_path,
            audio_source=self._audio_source,
            parent=self,
        )
        session.connection_failed.connect(self._on_connection_failed)
        session.audio_unavailable.connect(self._on_audio_unavailable)
        session.virtual_mic_unavailable.connect(self._on_virtual_mic_unavailable)
        session.audio_level_updated.connect(self._on_audio_level_updated)
        self._session = session
        self._mic_active_session = True
        self._last_level_time = None
        self._status_timer.start()
        self._device_panel.set_mic_status_connecting()
        crash_state.update("mic", state="starting", audio_source=self._audio_source)
        session.start()
        session.set_volume(self._volume / 100)
        session.set_muted(self._muted)

    def _stop_mic(self) -> None:
        if self._session is not None:
            session = self._session
            self._session = None
            session.stop()
            self._defer_session_cleanup(session)
            crash_state.update("mic", state="stopped")
        self._mic_active_session = False
        self._status_timer.stop()
        self._device_panel.set_mic_status_disabled()

    @staticmethod
    def _defer_session_cleanup(session: MicSession) -> None:
        """Mirrors streaming/controller.py's CastingController._defer_
        session_cleanup() -- severs every signal connection this specific
        session has into the controller the moment it's being torn down, so
        a callback still in flight from its worker thread can never run
        against a since-replaced (or since-cleared) self._session -- deferred
        to the next event-loop tick (never synchronously), since the caller
        (_stop_mic(), _on_connection_failed()) can itself be running from
        inside one of `session`'s own signal handlers. Disconnecting a
        signal while that signal's own emission is still active is a
        reentrant pattern that can cause real, hard (non-Python-traceback)
        crashes across the PySide6/shiboken C++ boundary -- see
        streaming/controller.py's crash investigation note for the full
        story.

        deleteLater() is NOT scheduled on this same immediate timer --
        MicSession owns an un-parented worker QThread (mic_session.py) that
        keeps running real teardown (killing the scrcpy-server process,
        closing the virtual mic sink) for a while after stop() merely
        queues the request to it. Destroying the MicSession wrapper before
        that thread has actually finished is a hard native Qt crash
        ("QThread: Destroyed while thread is still running"), which is
        exactly what an immediate deleteLater() here risked -- see
        streaming/controller.py's crash investigation finding #2 for the
        full story. Instead, deleteLater() is wired to the session's own
        `stopped` signal (left connected below), which only fires once the
        worker thread's teardown has genuinely completed -- MicSession's
        own teardown and _restart_mic_if_active()'s restart-chaining both
        still need `stopped` too."""
        def _cleanup() -> None:
            for signal in (
                session.connection_failed,
                session.audio_unavailable,
                session.virtual_mic_unavailable,
                session.audio_level_updated,
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

    def _on_audio_level_updated(self, level: float) -> None:
        if self._session is None:
            return  # a straggling emission from a session that's already been stopped
        self._last_level_time = time.monotonic()
        self._device_panel.set_mic_level(level)
        self._device_panel.set_mic_status_active()

    def _check_signal_staleness(self) -> None:
        if not self._mic_active_session:
            return
        stale = self._last_level_time is None or (
            time.monotonic() - self._last_level_time > _NO_SIGNAL_TIMEOUT_S
        )
        if stale:
            self._device_panel.set_mic_status_no_signal()
            self._device_panel.set_mic_level(0.0)

    def _on_connection_failed(self, message: str) -> None:
        logger.warning("Microphone session failed: %s", message)
        crash_state.update("mic", state="connection_failed", message=message)
        self._device_panel.show_mic_connection_failed(message)
        if self._session is not None:
            session = self._session
            self._session = None
            session.stop()
            self._defer_session_cleanup(session)
        self._mic_active_session = False
        self._status_timer.stop()
        self._device_panel.set_mic_status_disabled()

    def _on_audio_unavailable(self, is_error: bool) -> None:
        logger.warning("Android microphone unavailable (error=%s)", is_error)
        self._device_panel.show_mic_unavailable(is_error)
        self._stop_mic()

    def _on_virtual_mic_unavailable(self, message: str) -> None:
        self._device_panel.show_virtual_mic_unavailable(message)
        self._stop_mic()
