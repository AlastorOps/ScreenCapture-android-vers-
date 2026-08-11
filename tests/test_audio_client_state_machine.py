"""Feeds synthetic audio-socket byte streams (built from a real ffmpeg-
encoded Opus fixture) directly into ScrcpyVideoClient's audio parsing state
machine, bypassing sockets/ADB/hardware — same approach as
test_video_client_state_machine.py.
"""

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import av
import pytest

from androidlink.streaming.performance import resolve_streaming_profile
from androidlink.streaming.protocol import PACKET_FLAG_CONFIG, PACKET_FLAG_KEY_FRAME
from androidlink.streaming.transport import ScrcpyVideoClient
from androidlink.utils.latest_value_box import LatestValueBox

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample.opus.ogg"


def _real_opus_packets_and_extradata() -> tuple[bytes, list[bytes]]:
    container = av.open(str(FIXTURE_PATH))
    try:
        stream = container.streams.audio[0]
        extradata = bytes(stream.codec_context.extradata)
        packets = [bytes(p) for p in container.demux(stream) if bytes(p)]
        return extradata, packets
    finally:
        container.close()


def _build_synthetic_audio_stream(codec_header: bytes, extradata: bytes, packets: list[bytes]) -> bytes:
    stream = bytearray()
    stream += codec_header

    stream += struct.pack(">QI", PACKET_FLAG_CONFIG, len(extradata))
    stream += extradata

    for i, packet in enumerate(packets):
        pts_and_flags = i * 20_000
        if i == 0:
            pts_and_flags |= PACKET_FLAG_KEY_FRAME
        stream += struct.pack(">QI", pts_and_flags, len(packet))
        stream += packet

    return bytes(stream)


@pytest.fixture
def client(qapp) -> ScrcpyVideoClient:
    profile = resolve_streaming_profile(50)
    return ScrcpyVideoClient(
        adb_path=Path("adb"),
        serial="TEST_SERIAL",
        server_jar_path=Path("unused.jar"),
        profile=profile,
        frame_box=LatestValueBox(),
        enable_audio=True,
    )


def test_full_audio_handshake_and_packets_processed_without_error(client):
    extradata, packets = _real_opus_packets_and_extradata()
    stream = _build_synthetic_audio_stream(b"opus", extradata, packets)

    client._audio_recv_buffer.extend(stream)
    client._process_audio_buffer()

    assert client._audio_decoder is not None
    assert client._audio_playback is not None
    assert client._audio_stage == "audio_packet_header"  # fully drained, ready for more
    assert len(client._audio_recv_buffer) == 0

    client._audio_playback.stop()


def test_handles_arbitrary_tcp_chunk_boundaries(client):
    extradata, packets = _real_opus_packets_and_extradata()
    stream = _build_synthetic_audio_stream(b"opus", extradata, packets)

    chunk_size = 11
    for i in range(0, len(stream), chunk_size):
        client._audio_recv_buffer.extend(stream[i : i + chunk_size])
        client._process_audio_buffer()

    assert client._audio_stage == "audio_packet_header"
    assert len(client._audio_recv_buffer) == 0

    client._audio_playback.stop()


def test_disable_sentinel_emits_audio_unavailable_and_stops_gracefully(client):
    events = []
    client.audio_unavailable.connect(events.append)

    client._audio_recv_buffer.extend(b"\x00\x00\x00\x00")
    client._process_audio_buffer()

    assert events == [False]  # is_error=False (capture just unavailable)
    assert client._audio_stage == "disabled"
    assert client._audio_decoder is None
    assert client._audio_playback is None


def test_config_error_sentinel_reports_is_error_true(client):
    events = []
    client.audio_unavailable.connect(events.append)

    client._audio_recv_buffer.extend(b"\x00\x00\x00\x01")
    client._process_audio_buffer()

    assert events == [True]
