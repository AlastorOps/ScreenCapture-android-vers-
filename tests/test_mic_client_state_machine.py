"""Feeds a synthetic mic-socket byte stream (built from the real ffmpeg-
encoded Opus fixture, same approach as test_audio_client_state_machine.py)
directly into MicClient's parsing state machine, bypassing sockets/ADB/
hardware.

Unlike the shared Cast+Audio session, MicClient's socket receives the
64-byte device-name field itself first (video is disabled, so audio becomes
scrcpy-server's first socket -- see protocol.build_mic_server_launch_args's
docstring), so the synthetic stream here includes that field too.

virtual_mic_unavailable firing on session start is forced via monkeypatching
QMediaDevices.audioOutputs() (see
test_full_handshake_decodes_and_reports_virtual_mic_unavailable()) rather
than relying on this machine happening to have no VB-Audio/VoiceMeeter
driver installed, which stopped being guaranteed once one was installed to
test the Mic feature for real.
"""

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import av
import pytest
from PySide6.QtMultimedia import QMediaDevices

from androidlink.audio.mic_session import MicClient
from androidlink.streaming.protocol import PACKET_FLAG_CONFIG, PACKET_FLAG_KEY_FRAME

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


def _build_synthetic_mic_stream(codec_header: bytes, extradata: bytes, packets: list[bytes]) -> bytes:
    stream = bytearray()
    stream += b"Test Device".ljust(64, b"\x00")
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
def client(qapp) -> MicClient:
    return MicClient(
        adb_path=Path("adb"),
        serial="TEST_SERIAL",
        server_jar_path=Path("unused.jar"),
        audio_source="mic",
    )


def test_full_handshake_decodes_and_reports_virtual_mic_unavailable(client, monkeypatch):
    real_outputs = QMediaDevices.audioOutputs()
    non_cable_outputs = [
        d for d in real_outputs
        if "cable" not in d.description().lower() and "voicemeeter" not in d.description().lower()
    ]
    monkeypatch.setattr(QMediaDevices, "audioOutputs", staticmethod(lambda: non_cable_outputs))

    extradata, packets = _real_opus_packets_and_extradata()
    stream = _build_synthetic_mic_stream(b"opus", extradata, packets)

    unavailable_events = []
    client.virtual_mic_unavailable.connect(unavailable_events.append)
    started_events = []
    client.session_started.connect(lambda: started_events.append(True))
    failures = []
    client.connection_failed.connect(failures.append)

    client._recv_buffer.extend(stream)
    client._process_buffer()

    assert failures == []
    assert started_events == []  # session_started only fires once the sink opens
    assert len(unavailable_events) == 1
    assert client._decoder is not None
    assert client._stage == "packet_header"  # fully drained, ready for more
    assert len(client._recv_buffer) == 0


def test_unrecognized_codec_id_degrades_to_audio_unavailable_instead_of_crashing(client):
    """Same regression as test_audio_client_state_machine.py's equivalent --
    MicClient shares the same decode_audio_header() call, previously
    unguarded against its ValueError for an unrecognized codec id."""
    stream = bytearray()
    stream += b"Test Device".ljust(64, b"\x00")
    stream += b"\x01\x02\x03\x04"

    events = []
    client.audio_unavailable.connect(events.append)

    client._recv_buffer.extend(stream)
    client._process_buffer()  # must not raise

    assert events == [True]
    assert client._stage == "disabled"


def test_handles_arbitrary_tcp_chunk_boundaries(client):
    extradata, packets = _real_opus_packets_and_extradata()
    stream = _build_synthetic_mic_stream(b"opus", extradata, packets)

    chunk_size = 13
    for i in range(0, len(stream), chunk_size):
        client._recv_buffer.extend(stream[i : i + chunk_size])
        client._process_buffer()

    assert client._stage == "packet_header"
    assert len(client._recv_buffer) == 0


def test_disable_sentinel_emits_audio_unavailable_and_stops_gracefully(client):
    events = []
    client.audio_unavailable.connect(events.append)

    stream = b"Test Device".ljust(64, b"\x00") + b"\x00\x00\x00\x00"
    client._recv_buffer.extend(stream)
    client._process_buffer()

    assert events == [False]  # is_error=False (capture just unavailable)
    assert client._stage == "disabled"
    assert client._decoder is None
    assert client._sink is None


def test_config_error_sentinel_reports_is_error_true(client):
    events = []
    client.audio_unavailable.connect(events.append)

    stream = b"Test Device".ljust(64, b"\x00") + b"\x00\x00\x00\x01"
    client._recv_buffer.extend(stream)
    client._process_buffer()

    assert events == [True]
