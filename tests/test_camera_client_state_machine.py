"""Feeds synthetic camera-socket byte streams (built from the real H.264
fixture, using the same real-MediaCodec-shaped separate config packet as
test_video_client_state_machine.py) directly into CameraClient's parsing
state machine, bypassing sockets/ADB/hardware.

virtual_camera_unavailable firing on session start is forced via
monkeypatching pyvirtualcam.Camera (see
test_reports_virtual_cam_unavailable_when_no_backend_is_installed()) rather
than relying on this machine happening to have no OBS/Unity Capture
installed, which stopped being guaranteed once one was installed to test
the Camera feature for real.
"""

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import av
import numpy as np
import pyvirtualcam
import pytest

import androidlink.camera.camera_session as camera_session_module
from androidlink.camera.camera_orientation import CameraStaticInfo
from androidlink.camera.camera_session import CameraClient, _rotate_clockwise
from androidlink.streaming.protocol import (
    PACKET_FLAG_CONFIG,
    PACKET_FLAG_KEY_FRAME,
    PACKET_FLAG_SESSION,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample.h264"


def _access_units() -> list[bytes]:
    container = av.open(str(FIXTURE_PATH))
    try:
        stream = container.streams.video[0]
        return [bytes(p) for p in container.demux(stream) if bytes(p)]
    finally:
        container.close()


def _split_config_and_slice(access_unit: bytes) -> tuple[bytes, bytes]:
    return access_unit[:36], access_unit[36:]


def _raise_no_backend(*_args, **_kwargs):
    raise RuntimeError("Could not run virtual camera: try installing OBS Studio or Unity Capture")


@pytest.fixture
def client(qapp) -> CameraClient:
    return CameraClient(
        adb_path=Path("adb"),
        serial="TEST_SERIAL",
        server_jar_path=Path("unused.jar"),
        camera_id="0",
        camera_size="64x64",
        camera_facing="back",
        camera_fps=30,
    )


def test_separate_config_packet_decodes_and_reports_virtual_cam_unavailable(client, monkeypatch):
    """Forces pyvirtualcam's real "no backend" failure so session start
    genuinely fails to open a virtual camera -- verifying that real failure
    path is surfaced correctly rather than crashing or hanging, regardless
    of whether this machine happens to have a backend installed."""
    monkeypatch.setattr(pyvirtualcam, "Camera", _raise_no_backend)
    config_bytes, slice_bytes = _split_config_and_slice(_access_units()[0])

    stream = bytearray()
    stream += b"Test Device".ljust(64, b"\x00")
    stream += b"h264"
    stream += struct.pack(">III", PACKET_FLAG_SESSION >> 32, 64, 64)
    stream += struct.pack(">QI", PACKET_FLAG_CONFIG, len(config_bytes))
    stream += config_bytes
    stream += struct.pack(">QI", PACKET_FLAG_KEY_FRAME, len(slice_bytes))
    stream += slice_bytes

    unavailable_events = []
    client.virtual_camera_unavailable.connect(unavailable_events.append)
    started_events = []
    client.session_started.connect(lambda w, h: started_events.append((w, h)))
    failures = []
    client.connection_failed.connect(failures.append)

    client._recv_buffer.extend(stream)
    client._process_buffer()

    assert failures == []
    assert started_events == []  # session_started only fires once the sink opens
    assert len(unavailable_events) == 1
    assert "obs" in unavailable_events[0].lower() or "unitycapture" in unavailable_events[0].lower()

    # Decoding itself must still have succeeded despite no virtual camera --
    # the frame should be sitting in the frame box, just never consumed
    # since the output timer never starts without a sink.
    frame = client._frame_box.take()
    assert frame is not None
    assert frame.shape == (64, 64, 3)


def test_frame_available_fires_and_preview_box_is_independent_of_virtual_cam_box(client, monkeypatch):
    """The Device panel's Camera Live Preview reads client.take_latest_frame()
    (a second LatestValueBox, see camera_session.py) -- independent of
    _frame_box, which the virtual-camera output timer drains separately, so
    one consumer taking its frame must never remove the other's."""
    monkeypatch.setattr(pyvirtualcam, "Camera", _raise_no_backend)
    config_bytes, slice_bytes = _split_config_and_slice(_access_units()[0])

    stream = bytearray()
    stream += b"Test Device".ljust(64, b"\x00")
    stream += b"h264"
    stream += struct.pack(">III", PACKET_FLAG_SESSION >> 32, 64, 64)
    stream += struct.pack(">QI", PACKET_FLAG_CONFIG, len(config_bytes))
    stream += config_bytes
    stream += struct.pack(">QI", PACKET_FLAG_KEY_FRAME, len(slice_bytes))
    stream += slice_bytes

    frame_available_events = []
    client.frame_available.connect(lambda: frame_available_events.append(1))

    client._recv_buffer.extend(stream)
    client._process_buffer()

    assert frame_available_events == [1]

    preview_frame = client.take_latest_frame()
    assert preview_frame is not None
    assert preview_frame.shape == (64, 64, 3)

    # Still there -- take_latest_frame() above must not have drained it too.
    sink_frame = client._frame_box.take()
    assert sink_frame is not None
    assert sink_frame.shape == (64, 64, 3)


def test_rotate_clockwise_zero_degrees_is_a_noop():
    frame = np.arange(4 * 6 * 3, dtype=np.uint8).reshape(4, 6, 3)
    assert _rotate_clockwise(frame, 0) is frame


def test_rotate_clockwise_90_degrees_matches_a_real_clockwise_rotation():
    frame = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)  # 2 rows, 3 cols
    rotated = _rotate_clockwise(frame, 90)

    assert rotated.shape == (3, 2, 3)  # width/height swap, like a real 90-degree turn
    # A 90-degree clockwise turn puts the original's bottom-left pixel at the
    # new top-left.
    np.testing.assert_array_equal(rotated[0, 0], frame[-1, 0])


def test_rotate_clockwise_180_degrees():
    frame = np.arange(2 * 2 * 3, dtype=np.uint8).reshape(2, 2, 3)
    rotated = _rotate_clockwise(frame, 180)

    assert rotated.shape == frame.shape
    np.testing.assert_array_equal(rotated[0, 0], frame[-1, -1])


def test_rotate_clockwise_270_degrees():
    frame = np.arange(2 * 3 * 3, dtype=np.uint8).reshape(2, 3, 3)
    rotated = _rotate_clockwise(frame, 270)

    assert rotated.shape == (3, 2, 3)
    # A 270-degree clockwise turn (== 90 counter-clockwise) puts the
    # original's top-right pixel at the new top-left.
    np.testing.assert_array_equal(rotated[0, 0], frame[0, -1])


def test_poll_device_rotation_is_a_noop_without_static_info(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        camera_session_module, "get_device_rotation_degrees", lambda *a: calls.append(1) or 90
    )
    client._camera_static_info = None  # start() never found sensor orientation for this camera

    client._poll_device_rotation()

    assert calls == []  # never even queries live rotation -- nothing to combine it with
    assert client._preview_rotation_degrees == 0


def test_poll_device_rotation_updates_preview_rotation_on_a_real_change(client, monkeypatch):
    client._camera_static_info = CameraStaticInfo(sensor_orientation_degrees=90, facing="back")
    client._device_rotation_degrees = 0
    client._preview_rotation_degrees = 90  # matches device_rotation=0 baseline

    monkeypatch.setattr(camera_session_module, "get_device_rotation_degrees", lambda *a: 90)
    client._poll_device_rotation()

    # Phone physically turned 90 degrees -- back-camera formula: 90-90=0.
    assert client._device_rotation_degrees == 90
    assert client._preview_rotation_degrees == 0


def test_poll_device_rotation_ignores_an_unchanged_reading(client, monkeypatch):
    client._camera_static_info = CameraStaticInfo(sensor_orientation_degrees=90, facing="back")
    client._device_rotation_degrees = 90
    client._preview_rotation_degrees = 0

    calls = []
    monkeypatch.setattr(
        camera_session_module,
        "get_device_rotation_degrees",
        lambda *a: (calls.append(1), 90)[1],
    )
    client._poll_device_rotation()

    assert calls == [1]  # still polls...
    assert client._preview_rotation_degrees == 0  # ...but nothing changed, so no recompute needed


def test_poll_device_rotation_keeps_last_known_value_when_adb_query_fails(client, monkeypatch):
    """Never guess -- a failed/unparseable poll leaves the previously
    computed rotation in place rather than resetting to 0 (which would
    itself be a fabricated "upright" claim)."""
    client._camera_static_info = CameraStaticInfo(sensor_orientation_degrees=90, facing="back")
    client._device_rotation_degrees = 90
    client._preview_rotation_degrees = 0

    monkeypatch.setattr(camera_session_module, "get_device_rotation_degrees", lambda *a: None)
    client._poll_device_rotation()

    assert client._preview_rotation_degrees == 0
    assert client._device_rotation_degrees == 90


def test_preview_box_receives_rotated_frame_while_virtual_cam_box_stays_unrotated(
    client, monkeypatch
):
    """Item 3: rotation is scoped to the GUI preview only -- the virtual-
    camera/streaming pipeline (_frame_box) must never be touched by it."""
    monkeypatch.setattr(pyvirtualcam, "Camera", _raise_no_backend)
    client._preview_rotation_degrees = 90

    config_bytes, slice_bytes = _split_config_and_slice(_access_units()[0])
    stream = bytearray()
    stream += b"Test Device".ljust(64, b"\x00")
    stream += b"h264"
    stream += struct.pack(">III", PACKET_FLAG_SESSION >> 32, 64, 64)
    stream += struct.pack(">QI", PACKET_FLAG_CONFIG, len(config_bytes))
    stream += config_bytes
    stream += struct.pack(">QI", PACKET_FLAG_KEY_FRAME, len(slice_bytes))
    stream += slice_bytes

    client._recv_buffer.extend(stream)
    client._process_buffer()

    preview_frame = client.take_latest_frame()
    sink_frame = client._frame_box.take()

    assert preview_frame is not None
    assert sink_frame is not None
    np.testing.assert_array_equal(preview_frame, _rotate_clockwise(sink_frame, 90))
    # The real fixture frame is square (64x64), so this also confirms the
    # two boxes hold genuinely different arrays, not the same object twice.
    assert not np.array_equal(preview_frame, sink_frame)


def test_stop_is_idempotent(client):
    """See test_video_client_state_machine.py's equivalent -- a second
    stop() call must be a genuine no-op, not re-emit stopped (which could
    trigger an unwanted second _start_camera())."""
    stopped_events = []
    client.stopped.connect(lambda: stopped_events.append(1))

    client.stop()
    client.stop()
    client.stop()

    assert stopped_events == [1]


def test_unsupported_codec_reports_connection_failure_instead_of_crashing(client):
    """Same regression as test_video_client_state_machine.py's equivalent --
    CameraClient shares the same VideoDecoder(codec_name) construction, and
    previously had the same unguarded UnsupportedCodecError gap."""
    stream = bytearray()
    stream += b"Test Device".ljust(64, b"\x00")
    stream += struct.pack(">I", 0x00_76_70_38)  # "vp8" codec id
    stream += struct.pack(">III", PACKET_FLAG_SESSION >> 32, 64, 64)

    failures = []
    client.connection_failed.connect(failures.append)
    started_events = []
    client.session_started.connect(lambda w, h: started_events.append((w, h)))

    client._recv_buffer.extend(stream)
    client._process_buffer()  # must not raise

    assert started_events == []
    assert len(failures) == 1
    assert "codec" in failures[0].lower()


def test_rejects_implausible_session_meta(client):
    stream = bytearray()
    stream += b"Test Device".ljust(64, b"\x00")
    stream += b"h264"
    stream += struct.pack(">III", PACKET_FLAG_SESSION >> 32, 0xFFFFFFF0, 100)

    failures = []
    client.connection_failed.connect(failures.append)

    client._recv_buffer.extend(stream)
    client._process_buffer()

    assert len(failures) == 1
