"""Feeds synthetic camera-socket byte streams (built from the real H.264
fixture, using the same real-MediaCodec-shaped separate config packet as
test_video_client_state_machine.py) directly into CameraClient's parsing
state machine, bypassing sockets/ADB/hardware.

This machine has no virtual camera backend (OBS/Unity Capture) installed,
so virtual_camera_unavailable firing on session start is the real, accurate
behavior here -- not a simulated failure.
"""

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import av
import pytest

from androidlink.camera.camera_session import CameraClient
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


def test_separate_config_packet_decodes_and_reports_virtual_cam_unavailable(client):
    """This machine has no OBS/Unity Capture installed, so session start
    should genuinely fail to open a virtual camera -- verifying that real
    failure path is surfaced correctly rather than crashing or hanging."""
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
