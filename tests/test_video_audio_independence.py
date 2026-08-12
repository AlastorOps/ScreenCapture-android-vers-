"""Regression coverage for item 12 of the FPS/frame-drop fix: minor audio
startup/timestamp issues (e.g. the Qt/WASAPI "Could not get initial audio
timestamp" warning seen in real logs -- a native Qt Multimedia diagnostic,
not something this codebase emits, so there's no message to "fix" on our
side) must never affect the video Automatic-FPS stability decision.

Verified directly: video's DiagnosticsSample fields (stream_fps,
dropped_frames, late_frames -- the only three FpsStabilityMonitor/
_on_stats_for_stability ever read, see streaming/controller.py and
fps_stability.py) are computed exclusively from _decoded_frame_count/
_frame_box/_late_frame_count, all written only inside the video half of
ScrcpyVideoClient._process_buffer(). Feeding a full real audio handshake
and packet stream through the same client alongside video proves this
isn't just true by code inspection -- audio processing genuinely never
touches those counters, even when driven through the exact same client
instance a real shared Cast+Audio session uses.
"""

import os
import struct
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import av

from androidlink.streaming.performance import resolve_streaming_profile
from androidlink.streaming.protocol import PACKET_FLAG_CONFIG, PACKET_FLAG_KEY_FRAME, PACKET_FLAG_SESSION
from androidlink.streaming.transport import ScrcpyVideoClient
from androidlink.utils.latest_value_box import LatestValueBox

VIDEO_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample.h264"
AUDIO_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample.opus.ogg"


def _video_access_units() -> list[bytes]:
    container = av.open(str(VIDEO_FIXTURE_PATH))
    try:
        stream = container.streams.video[0]
        return [bytes(p) for p in container.demux(stream) if bytes(p)]
    finally:
        container.close()


def _audio_extradata_and_packets() -> tuple[bytes, list[bytes]]:
    container = av.open(str(AUDIO_FIXTURE_PATH))
    try:
        stream = container.streams.audio[0]
        extradata = bytes(stream.codec_context.extradata)
        packets = [bytes(p) for p in container.demux(stream) if bytes(p)]
        return extradata, packets
    finally:
        container.close()


def _video_stream(width: int, height: int) -> bytes:
    stream = bytearray()
    stream += b"Test Device".ljust(64, b"\x00")
    stream += b"h264"
    stream += struct.pack(">III", PACKET_FLAG_SESSION >> 32, width, height)
    for i, access_unit in enumerate(_video_access_units()):
        pts_and_flags = i * 100_000
        if i == 0:
            pts_and_flags |= PACKET_FLAG_KEY_FRAME
        stream += struct.pack(">QI", pts_and_flags, len(access_unit))
        stream += access_unit
    return bytes(stream)


def _audio_stream() -> bytes:
    extradata, packets = _audio_extradata_and_packets()
    stream = bytearray()
    stream += b"opus"
    stream += struct.pack(">QI", PACKET_FLAG_CONFIG, len(extradata))
    stream += extradata
    for i, packet in enumerate(packets):
        pts_and_flags = i * 20_000
        if i == 0:
            pts_and_flags |= PACKET_FLAG_KEY_FRAME
        stream += struct.pack(">QI", pts_and_flags, len(packet))
        stream += packet
    return bytes(stream)


def test_audio_activity_does_not_change_video_diagnostics(qapp):
    profile = resolve_streaming_profile(50, max_fps_override=60)
    client = ScrcpyVideoClient(
        adb_path=Path("adb"),
        serial="TEST_SERIAL",
        server_jar_path=Path("unused.jar"),
        profile=profile,
        frame_box=LatestValueBox(),
        enable_audio=True,
    )

    # Video only, first -- establishes the baseline this test compares against.
    client._recv_buffer.extend(_video_stream(1080, 2400))
    client._process_buffer()

    baseline_samples = []
    client.stats_updated.connect(baseline_samples.append)
    client._emit_stats()
    baseline = baseline_samples[0]
    client.stats_updated.disconnect(baseline_samples.append)

    # Now drive a *second*, identical client the same way, but interleave a
    # full real audio handshake + packet stream alongside the video.
    client_with_audio = ScrcpyVideoClient(
        adb_path=Path("adb"),
        serial="TEST_SERIAL",
        server_jar_path=Path("unused.jar"),
        profile=profile,
        frame_box=LatestValueBox(),
        enable_audio=True,
    )
    client_with_audio._recv_buffer.extend(_video_stream(1080, 2400))
    client_with_audio._process_buffer()
    client_with_audio._audio_recv_buffer.extend(_audio_stream())
    client_with_audio._process_audio_buffer()

    assert client_with_audio._audio_decoder is not None  # audio really was processed

    samples = []
    client_with_audio.stats_updated.connect(samples.append)
    client_with_audio._emit_stats()
    sample = samples[0]

    assert sample.stream_fps == baseline.stream_fps
    assert sample.dropped_frames == baseline.dropped_frames
    assert sample.late_frames == baseline.late_frames


def test_fps_stability_monitor_never_reads_audio_fields():
    """FpsStabilityMonitor.record_sample()'s only two parameters are
    stream_fps and dropped_frames -- there is no audio-derived input it
    could even be given, by construction."""
    import inspect

    from androidlink.streaming.fps_stability import FpsStabilityMonitor

    signature = inspect.signature(FpsStabilityMonitor.record_sample)
    assert list(signature.parameters) == ["self", "stream_fps", "dropped_frames"]
