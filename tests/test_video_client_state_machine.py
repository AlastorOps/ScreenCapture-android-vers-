"""Feeds a synthetic byte stream that matches exactly what a real
scrcpy-server would send (device name header, codec header, session meta,
then frame-meta+payload per access unit, built from a real ffmpeg-encoded
H.264 fixture) directly into ScrcpyVideoClient's parsing state machine —
bypassing actual sockets/ADB/hardware, which aren't available in this
environment, while still exercising the real protocol parsing and real
decode path end-to-end.
"""

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import av
import pytest

from androidlink.streaming.performance import resolve_streaming_profile
from androidlink.streaming.protocol import (
    PACKET_FLAG_CONFIG,
    PACKET_FLAG_KEY_FRAME,
    PACKET_FLAG_SESSION,
)
from androidlink.streaming.transport import ScrcpyVideoClient
from androidlink.utils.latest_value_box import LatestValueBox

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample.h264"


def _access_units() -> list[bytes]:
    container = av.open(str(FIXTURE_PATH))
    try:
        stream = container.streams.video[0]
        return [bytes(packet) for packet in container.demux(stream) if bytes(packet)]
    finally:
        container.close()


def _split_config_and_slice(access_unit: bytes) -> tuple[bytes, bytes]:
    """See tests/test_decoder.py: real MediaCodec sends SPS/PPS as a
    separate config buffer, unlike ffmpeg's muxer which bundles them into
    one access unit. Byte 36 is this fixture's SEI+slice boundary."""
    return access_unit[:36], access_unit[36:]


def _build_synthetic_stream(device_name: str, width: int, height: int) -> bytes:
    stream = bytearray()

    name_bytes = device_name.encode("utf-8")
    stream += name_bytes + b"\x00" * (64 - len(name_bytes))

    stream += b"h264"

    session_flags = PACKET_FLAG_SESSION >> 32
    stream += struct.pack(">III", session_flags, width, height)

    for i, access_unit in enumerate(_access_units()):
        pts_and_flags = i * 100_000
        if i == 0:
            pts_and_flags |= PACKET_FLAG_KEY_FRAME
        stream += struct.pack(">QI", pts_and_flags, len(access_unit))
        stream += access_unit

    return bytes(stream)


@pytest.fixture
def client() -> ScrcpyVideoClient:
    profile = resolve_streaming_profile(50)
    return ScrcpyVideoClient(
        adb_path=Path("adb"),
        serial="TEST_SERIAL",
        server_jar_path=Path("unused.jar"),
        profile=profile,
        frame_box=LatestValueBox(),
    )


def test_full_handshake_and_frames_parsed_in_one_chunk(client):
    stream = _build_synthetic_stream("Test Device", 1080, 2400)

    sessions = []
    client.session_started.connect(lambda w, h: sessions.append((w, h)))
    frame_events = []
    client.frame_available.connect(lambda: frame_events.append(client.take_latest_frame()))

    client._recv_buffer.extend(stream)
    client._process_buffer()

    assert sessions == [(1080, 2400)]
    assert len(frame_events) == 10
    for frame in frame_events:
        assert frame is not None
        assert frame.shape == (64, 64, 3)


def test_handles_arbitrary_tcp_chunk_boundaries(client):
    """The real protocol data arrives in arbitrary TCP-sized chunks, not
    conveniently aligned to header/payload boundaries — feed it 7 bytes at a
    time to prove the state machine handles partial reads correctly."""
    stream = _build_synthetic_stream("Test Device", 640, 480)

    frame_events = []
    client.frame_available.connect(lambda: frame_events.append(client.take_latest_frame()))

    chunk_size = 7
    for i in range(0, len(stream), chunk_size):
        client._recv_buffer.extend(stream[i : i + chunk_size])
        client._process_buffer()

    assert len(frame_events) == 10


def test_separate_config_packet_like_real_mediacodec(client):
    """Regression test for the real bug found via a live device: unlike the
    other tests here (which feed bundled access units the way ffmpeg's own
    muxer produces them), this builds packets the way real Android
    MediaCodec/scrcpy actually does -- a dedicated config (SPS/PPS-only)
    packet, separate from the keyframe's slice-only packet."""
    config_bytes, slice_bytes = _split_config_and_slice(_access_units()[0])

    stream = bytearray()
    stream += b"Test Device".ljust(64, b"\x00")
    stream += b"h264"
    stream += struct.pack(">III", PACKET_FLAG_SESSION >> 32, 1080, 2400)
    stream += struct.pack(">QI", PACKET_FLAG_CONFIG, len(config_bytes))
    stream += config_bytes
    stream += struct.pack(">QI", PACKET_FLAG_KEY_FRAME, len(slice_bytes))
    stream += slice_bytes

    frame_events = []
    client.frame_available.connect(lambda: frame_events.append(client.take_latest_frame()))
    failures = []
    client.connection_failed.connect(failures.append)

    client._recv_buffer.extend(stream)
    client._process_buffer()

    assert failures == []
    assert len(frame_events) == 1
    assert frame_events[0].shape == (64, 64, 3)


def test_recovers_from_a_corrupt_packet_without_desyncing(client):
    """Regression test: previously, a decode error left the parser stuck
    mid-payload, so the NEXT packet's header bytes were misread as more
    payload data -- cascading into garbage for the rest of the connection
    (this is what actually produced the blank/green screen: no frame ever
    successfully rendered again after the first decode error). A corrupt
    packet must be dropped without breaking packets that come after it.

    The decoder needs valid state (extradata + an established keyframe)
    before a corrupt packet can meaningfully be "recovered from" -- so this
    sends a real keyframe first, then a corrupt packet, then another real
    access unit, and checks the corrupt one is the only one that produces
    no frame.
    """
    access_units = _access_units()

    stream = bytearray()
    stream += b"Test Device".ljust(64, b"\x00")
    stream += b"h264"
    stream += struct.pack(">III", PACKET_FLAG_SESSION >> 32, 64, 64)

    good_unit_0 = access_units[0]
    stream += struct.pack(">QI", PACKET_FLAG_KEY_FRAME, len(good_unit_0))
    stream += good_unit_0

    corrupt_payload = b"\xff" * 50  # not valid H.264 data
    stream += struct.pack(">QI", 100_000, len(corrupt_payload))
    stream += corrupt_payload

    good_unit_1 = access_units[1]
    stream += struct.pack(">QI", 200_000, len(good_unit_1))
    stream += good_unit_1

    frame_events = []
    client.frame_available.connect(lambda: frame_events.append(client.take_latest_frame()))
    failures = []
    client.connection_failed.connect(failures.append)

    client._recv_buffer.extend(stream)
    client._process_buffer()

    assert failures == []  # a single bad packet must not tear down the session
    assert client._stage == "header"  # parser stayed in sync
    assert len(client._recv_buffer) == 0  # all three packets fully consumed
    # Both good access units decode; the corrupt one in between contributes
    # nothing but must not break the ones after it.
    assert len(frame_events) == 2
    for frame in frame_events:
        assert frame.shape == (64, 64, 3)


def test_emit_stats_reports_measured_values(client):
    stream = _build_synthetic_stream("Test Device", 1080, 2400)
    # _bytes_received is normally incremented in _on_video_ready_read() as
    # real socket bytes arrive; feeding _recv_buffer directly (this test
    # suite's usual bypass-the-socket approach) skips that, so account for
    # it explicitly to exercise the bitrate calculation too.
    client._bytes_received += len(stream)
    client._recv_buffer.extend(stream)
    client._process_buffer()  # decodes 10 frames, none taken out of the frame box

    samples = []
    client.stats_updated.connect(samples.append)
    client._emit_stats()

    assert len(samples) == 1
    sample = samples[0]
    assert sample.stream_fps == 10.0  # 10 frames decoded within one 1000ms window
    assert sample.dropped_frames == 9  # 10 puts into the frame box, only the last unread
    assert sample.decode_latency_ms >= 0
    assert sample.bitrate_bps > 0  # real bytes were received
    assert sample.resolution == (1080, 2400)
    assert sample.codec == "h264"


def test_emit_stats_resets_counters_after_emitting(client):
    stream = _build_synthetic_stream("Test Device", 640, 480)
    client._recv_buffer.extend(stream)
    client._process_buffer()
    client._emit_stats()  # drains counters from the first window

    samples = []
    client.stats_updated.connect(samples.append)
    client._emit_stats()  # nothing new happened since the previous emit

    assert samples[0].stream_fps == 0.0
    assert samples[0].bitrate_bps == 0.0
    assert samples[0].dropped_frames == 0


def test_rejects_implausible_session_meta_as_connection_failure(client):
    """A prior version of this parser could, after desyncing, interpret
    random bytes as a SessionMeta with nonsense (even negative-looking,
    once marshaled through a Qt int signal) width/height -- guard against
    ever acting on implausible dimensions."""
    stream = bytearray()
    stream += b"Test Device".ljust(64, b"\x00")
    stream += b"h264"
    # A width far beyond any real display, built the same way a corrupted
    # parse would produce it.
    stream += struct.pack(">III", PACKET_FLAG_SESSION >> 32, 0xFFFFFFF0, 100)

    sessions = []
    client.session_started.connect(lambda w, h: sessions.append((w, h)))
    failures = []
    client.connection_failed.connect(failures.append)

    client._recv_buffer.extend(stream)
    client._process_buffer()

    assert sessions == []
    assert len(failures) == 1
