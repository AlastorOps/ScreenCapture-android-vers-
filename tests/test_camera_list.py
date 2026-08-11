from androidlink.camera.camera_list import CameraInfo, parse_camera_list


def test_parses_multiple_cameras():
    output = (
        "List of cameras:\n"
        "    --camera-id=0    (back, 1920x1080, fps={30, 60}, zoom-range=1.0-8.0)\n"
        "    --camera-id=1    (front, 1280x960, fps={30})\n"
    )

    cameras = parse_camera_list(output)

    assert cameras == [
        CameraInfo(camera_id="0", facing="back", width=1920, height=1080, fps_options=(30, 60)),
        CameraInfo(camera_id="1", facing="front", width=1280, height=960, fps_options=(30,)),
    ]


def test_parses_camera_without_fps_info():
    output = "List of cameras:\n    --camera-id=2    (external, 640x480)\n"

    cameras = parse_camera_list(output)

    assert cameras == [
        CameraInfo(camera_id="2", facing="external", width=640, height=480, fps_options=())
    ]


def test_no_cameras_returns_empty_list():
    output = "List of cameras:\n    (none)\n"
    assert parse_camera_list(output) == []


def test_access_denied_returns_empty_list():
    output = "List of cameras:\n    (access denied)\n"
    assert parse_camera_list(output) == []


def test_ignores_scrcpy_server_log_prefixes():
    """Real captured output is piped through our logger, which may prefix
    each line with scrcpy-server's own log framing -- parsing must not
    depend on lines starting exactly with the camera entry pattern."""
    output = (
        "[server] INFO: List of cameras:\n"
        "[server] INFO:     --camera-id=0    (back, 1920x1080, fps={60})\n"
    )

    cameras = parse_camera_list(output)

    assert cameras == [
        CameraInfo(camera_id="0", facing="back", width=1920, height=1080, fps_options=(60,))
    ]


def test_display_name_property():
    camera = CameraInfo(camera_id="0", facing="back", width=1920, height=1080, fps_options=(30,))
    assert camera.display_name == "Back camera (1920x1080)"
