"""Exposes decoded Android camera frames as a real Windows virtual camera
device via pyvirtualcam (prompt.md section 11: "It should function as an
actual Windows camera device", not just an in-app preview).

pyvirtualcam drives an existing OBS Virtual Camera or Unity Capture
DirectShow filter — it does not install one itself. If neither is present on
the system, opening the camera raises RuntimeError with a message naming
both backends it tried; we surface that as a clear, actionable UI state
(prompt.md section 25: never silently install drivers) rather than crash.
"""

import numpy as np
import pyvirtualcam


class VirtualCameraUnavailableError(Exception):
    """No virtual camera backend (OBS Virtual Camera / Unity Capture) found."""


class VirtualCameraSink:
    def __init__(self, width: int, height: int, fps: int) -> None:
        try:
            self._camera = pyvirtualcam.Camera(width=width, height=height, fps=fps)
        except RuntimeError as exc:
            raise VirtualCameraUnavailableError(str(exc)) from exc

        self.width = width
        self.height = height
        self.fps = fps

    @property
    def backend_device_name(self) -> str:
        return self._camera.device

    def send(self, frame_rgb: np.ndarray) -> None:
        self._camera.send(frame_rgb)

    def sleep_until_next_frame(self) -> None:
        self._camera.sleep_until_next_frame()

    def close(self) -> None:
        self._camera.close()
