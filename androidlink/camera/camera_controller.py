import logging

from PySide6.QtCore import QObject

from androidlink.camera.camera_manager import CameraManager
from androidlink.camera.camera_session import CameraSession
from androidlink.device.manager import DeviceManager
from androidlink.streaming.controller import SERVER_JAR_RELATIVE_PATH
from androidlink.ui.panels.device_panel import DevicePanel
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
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._device_manager = device_manager
        self._device_panel = device_panel
        self._camera_manager = CameraManager(parent=self)
        self._session: CameraSession | None = None

        self._selected_camera_id: str | None = None
        self._selected_fps = 0  # 0 = automatic

        device_manager.active_device_changed.connect(self._on_active_device_changed)
        self._camera_manager.cameras_listed.connect(self._device_panel.set_camera_list)
        self._camera_manager.list_failed.connect(self._device_panel.set_camera_list_failed)

        device_panel.camera_toggled.connect(self._on_camera_toggled)
        device_panel.camera_selection_changed.connect(self._on_camera_selection_changed)
        device_panel.camera_fps_changed.connect(self._on_camera_fps_changed)

    def shutdown(self) -> None:
        self._stop_camera()

    def _on_active_device_changed(self, device) -> None:
        if device is None:
            self._stop_camera()
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
        if self._session is not None:
            self._stop_camera()
            self._start_camera()

    def _on_camera_fps_changed(self, fps: int) -> None:
        self._selected_fps = fps
        if self._session is not None:
            self._stop_camera()
            self._start_camera()

    def _start_camera(self) -> None:
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
        self._session = session
        session.start()

    def _stop_camera(self) -> None:
        if self._session is not None:
            self._session.stop()
            self._session = None

    def _on_connection_failed(self, message: str) -> None:
        logger.warning("Camera session failed: %s", message)
        self._device_panel.set_camera_list_failed(message)
        self._session = None

    def _on_virtual_camera_unavailable(self, message: str) -> None:
        self._device_panel.show_virtual_camera_unavailable(message)
        self._stop_camera()
