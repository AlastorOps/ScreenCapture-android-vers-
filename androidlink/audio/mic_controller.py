import logging

from PySide6.QtCore import QObject

from androidlink.audio.mic_session import MicSession
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.controller import SERVER_JAR_RELATIVE_PATH
from androidlink.streaming.protocol import AUDIO_SOURCE_MIC
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.utils.platform import get_resource_path

logger = logging.getLogger(__name__)


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
        self._session = session
        session.start()
        session.set_volume(self._volume / 100)
        session.set_muted(self._muted)

    def _stop_mic(self) -> None:
        if self._session is not None:
            self._session.stop()
            self._session = None

    def _on_connection_failed(self, message: str) -> None:
        logger.warning("Microphone session failed: %s", message)
        self._device_panel.show_mic_connection_failed(message)
        self._session = None

    def _on_audio_unavailable(self, is_error: bool) -> None:
        logger.warning("Android microphone unavailable (error=%s)", is_error)
        self._device_panel.show_mic_unavailable(is_error)
        self._stop_mic()

    def _on_virtual_mic_unavailable(self, message: str) -> None:
        self._device_panel.show_virtual_mic_unavailable(message)
        self._stop_mic()
