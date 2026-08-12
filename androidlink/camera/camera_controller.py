import logging

from PySide6.QtCore import QObject, QTimer

from androidlink.camera.camera_manager import CameraManager
from androidlink.camera.camera_session import CameraSession
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.controller import SERVER_JAR_RELATIVE_PATH
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.panels.status_panel import StatusPanel
from androidlink.utils import crash_state
from androidlink.utils.platform import get_resource_path

logger = logging.getLogger(__name__)

DEFAULT_CAMERA_FPS = 30


class CameraController(QObject):
    """Owns camera capability detection and the CameraSession lifecycle —
    entirely independent of screen casting (prompt.md section 11), since
    camera mirroring is architecturally its own scrcpy-server session with
    no shared state with Cast/Control/Audio."""

    def __init__(
        self,
        device_manager: DeviceManager,
        device_panel: DevicePanel,
        status_panel: StatusPanel,
        settings_manager: SettingsManager,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._device_manager = device_manager
        self._device_panel = device_panel
        self._status_panel = status_panel  # owns the Camera Live Preview widget
        self._settings_manager = settings_manager
        self._camera_manager = CameraManager(parent=self)
        self._session: CameraSession | None = None

        settings = settings_manager.settings
        self._selected_camera_id: str | None = settings.camera.camera_id
        self._selected_fps = settings.camera.fps  # 0 = automatic
        self._cameras_by_id: dict[str, str] = {}  # camera_id -> display_name, for preview labeling

        device_manager.active_device_changed.connect(self._on_active_device_changed)
        self._camera_manager.cameras_listed.connect(self._on_cameras_listed)
        self._camera_manager.list_failed.connect(self._device_panel.set_camera_list_failed)

        device_panel.camera_toggled.connect(self._on_camera_toggled)
        device_panel.camera_selection_changed.connect(self._on_camera_selection_changed)
        device_panel.camera_fps_changed.connect(self._on_camera_fps_changed)

    def _on_cameras_listed(self, cameras) -> None:
        self._cameras_by_id = {camera.camera_id: camera.display_name for camera in cameras}
        default_camera = self._device_panel.set_camera_list(cameras)
        if self._selected_camera_id is not None:
            self._device_panel.select_camera_by_id(self._selected_camera_id, self._selected_fps)
        elif default_camera is not None:
            # No persisted preference -- track the combo's own default
            # (index 0) without treating it as a user choice worth saving.
            self._selected_camera_id = default_camera.camera_id

        display_name = self._cameras_by_id.get(self._selected_camera_id)
        if display_name is not None:
            self._status_panel.set_camera_preview_label(display_name)

    def shutdown(self) -> None:
        self._stop_camera()

    def _on_active_device_changed(self, device) -> None:
        if device is None:
            self._stop_camera()
            self._status_panel.set_camera_preview_status_disconnected()
            return

        adb_path = self._device_manager.adb_path
        if adb_path is None or self._camera_manager.is_busy():
            return

        server_jar_path = get_resource_path(SERVER_JAR_RELATIVE_PATH)
        self._camera_manager.list_cameras(adb_path, device.serial, server_jar_path)

    def _on_camera_toggled(self, enabled: bool) -> None:
        if enabled:
            self._start_camera()
        else:
            self._stop_camera()

    def _on_camera_selection_changed(self, camera_id: str) -> None:
        self._selected_camera_id = camera_id
        display_name = self._cameras_by_id.get(camera_id)
        if display_name is not None:
            self._status_panel.set_camera_preview_label(display_name)
        self._restart_camera_if_active()
        self._settings_manager.settings.camera.camera_id = camera_id
        self._settings_manager.save()

    def _on_camera_fps_changed(self, fps: int) -> None:
        self._selected_fps = fps
        self._restart_camera_if_active()
        self._settings_manager.settings.camera.fps = fps
        self._settings_manager.save()

    def _restart_camera_if_active(self) -> None:
        """Stops the current camera session and starts a fresh one once the
        old one has genuinely finished tearing down -- see
        streaming/controller.py's CastingController._restart_if_casting()
        docstring for why this can't just be stop() immediately followed by
        start(): CameraSession.stop() posts a queued call to its worker
        thread, so the old scrcpy-server process (and the device's hardware
        video encoder it's holding) may still be alive when a naive
        stop()-then-start() launches the new one, silently keeping the old
        camera/resolution/FPS active instead of applying the change."""
        if self._session is None:
            return
        session_to_stop = self._session
        session_to_stop.stopped.connect(self._start_camera)
        self._stop_camera()

    def _start_camera(self) -> None:
        if self._session is not None:
            # See streaming/controller.py's CastingController._start_casting()
            # for why this guard exists -- never let a second session run
            # alongside a live one.
            logger.warning("_start_camera() called while a session was already active; restarting instead")
            self._restart_camera_if_active()
            return

        device = self._device_manager.active_device
        adb_path = self._device_manager.adb_path
        if device is None or adb_path is None or self._selected_camera_id is None:
            logger.warning("Cannot start camera: no active device or no camera selected")
            self._device_panel.set_camera_list_failed("No device or camera selected")
            return

        server_jar_path = get_resource_path(SERVER_JAR_RELATIVE_PATH)
        session = CameraSession(
            adb_path,
            device.serial,
            server_jar_path,
            camera_id=self._selected_camera_id,
            camera_size=None,  # "Automatic" — per-resolution selection isn't implemented yet
            camera_facing=None,
            camera_fps=self._selected_fps or DEFAULT_CAMERA_FPS,
            parent=self,
        )
        session.connection_failed.connect(self._on_connection_failed)
        session.virtual_camera_unavailable.connect(self._on_virtual_camera_unavailable)
        session.frame_available.connect(self._on_frame_available)
        self._session = session
        self._status_panel.set_camera_preview_status_connecting()
        crash_state.update("camera", state="starting", camera_id=self._selected_camera_id)
        session.start()

    def _stop_camera(self) -> None:
        if self._session is not None:
            session = self._session
            self._session = None
            session.stop()
            self._defer_session_cleanup(session)
            crash_state.update("camera", state="stopped")
        self._status_panel.set_camera_preview_status_disabled()

    @staticmethod
    def _defer_session_cleanup(session: CameraSession) -> None:
        """Mirrors streaming/controller.py's CastingController._defer_
        session_cleanup(): once a session is being torn down, sever every
        signal connection it has into this controller so a callback still
        in flight from its worker thread (e.g. a trailing frame_available
        queued just before stop()) can never run against self._session
        after it's moved on to a different (or no) session -- deferred to
        the next event-loop tick (never synchronously), since the caller
        (_stop_camera(), _on_connection_failed()) can itself be running
        from inside one of `session`'s own signal handlers (e.g.
        connection_failed's handler tearing down the very session whose
        connection_failed.emit() is still on the call stack). Disconnecting
        a signal while that signal's own emission is still active is a
        reentrant pattern that can cause real, hard (non-Python-traceback)
        crashes across the PySide6/shiboken C++ boundary -- see
        streaming/controller.py's crash investigation note for the full
        story.

        deleteLater() is NOT scheduled on this same immediate timer --
        CameraSession owns an un-parented worker QThread (camera_session.py)
        that keeps running real teardown (killing the scrcpy-server process,
        closing the virtual camera) for a while after stop() merely queues
        the request to it. Destroying the CameraSession wrapper before that
        thread has actually finished is a hard native Qt crash ("QThread:
        Destroyed while thread is still running"), which is exactly what an
        immediate deleteLater() here risked -- see streaming/controller.py's
        crash investigation finding #2 for the full story. Instead,
        deleteLater() is wired to the session's own `stopped` signal (left
        connected below), which only fires once the worker thread's
        teardown has genuinely completed -- CameraSession's own teardown
        and _restart_camera_if_active()'s restart-chaining both still need
        `stopped` too.
        """
        def _cleanup() -> None:
            for signal in (session.connection_failed, session.virtual_camera_unavailable, session.frame_available):
                try:
                    signal.disconnect()
                except (TypeError, RuntimeError):
                    pass  # nothing was connected

        QTimer.singleShot(0, _cleanup)
        try:
            session.stopped.connect(session.deleteLater)
        except (TypeError, RuntimeError):
            pass  # session is already gone -- nothing to schedule

    def _on_frame_available(self) -> None:
        if self._session is None:
            return
        frame = self._session.take_latest_frame()
        if frame is not None:
            # A real decoded frame actually arrived -- only now is "Active"
            # honest (prompt.md: never show Active when no frames are
            # actually flowing). set_camera_preview_frame() sets it.
            self._status_panel.set_camera_preview_frame(frame)

    def _on_connection_failed(self, message: str) -> None:
        logger.warning("Camera session failed: %s", message)
        crash_state.update("camera", state="connection_failed", message=message)
        self._device_panel.set_camera_list_failed(message)
        if self._session is not None:
            session = self._session
            self._session = None
            session.stop()
            self._defer_session_cleanup(session)
        self._status_panel.set_camera_preview_status_disabled()

    def _on_virtual_camera_unavailable(self, message: str) -> None:
        self._device_panel.show_virtual_camera_unavailable(message)
        self._stop_camera()
