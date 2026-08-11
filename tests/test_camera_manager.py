import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.camera.camera_list import CameraInfo
from androidlink.camera.camera_manager import CameraManager


def test_on_list_finished_parses_output_and_emits_cameras(qapp):
    manager = CameraManager()
    manager._output = bytearray(
        b"List of cameras:\n"
        b"    --camera-id=0    (back, 1920x1080, fps={30, 60})\n"
        b"    --camera-id=1    (front, 1280x960, fps={30})\n"
    )

    results = []
    manager.cameras_listed.connect(results.append)

    manager._on_list_finished(0, None)

    assert manager._process is None  # busy flag cleared
    assert len(results) == 1
    assert results[0] == [
        CameraInfo(camera_id="0", facing="back", width=1920, height=1080, fps_options=(30, 60)),
        CameraInfo(camera_id="1", facing="front", width=1280, height=960, fps_options=(30,)),
    ]


def test_on_list_finished_with_no_cameras_emits_empty_list(qapp):
    manager = CameraManager()
    manager._output = bytearray(b"List of cameras:\n    (none)\n")

    results = []
    manager.cameras_listed.connect(results.append)

    manager._on_list_finished(0, None)

    assert results == [[]]


def test_is_busy_reflects_in_flight_process(qapp):
    manager = CameraManager()
    assert manager.is_busy() is False
