from pathlib import Path

import av
import pytest

from androidlink.streaming.decoder import UnsupportedCodecError, VideoDecoder

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample.h264"


def _access_units() -> list[bytes]:
    """Split the fixture into per-frame Annex-B access units the same way
    scrcpy-server frames them (one packet per encoded frame)."""
    container = av.open(str(FIXTURE_PATH))
    try:
        stream = container.streams.video[0]
        return [bytes(packet) for packet in container.demux(stream) if bytes(packet)]
    finally:
        container.close()


def test_decodes_real_h264_annexb_stream_into_rgb_frames():
    decoder = VideoDecoder("h264")
    try:
        total_frames = 0
        for access_unit in _access_units():
            frames = decoder.decode(access_unit)
            total_frames += len(frames)
            for frame in frames:
                assert frame.ndim == 3
                assert frame.shape[2] == 3  # RGB24
                assert frame.dtype.name == "uint8"
    finally:
        decoder.close()

    assert total_frames == 10  # matches the fixture: 10 frames at 10fps


def test_unsupported_codec_raises():
    with pytest.raises(UnsupportedCodecError):
        VideoDecoder("vp8")


def _split_config_and_slice(access_unit: bytes) -> tuple[bytes, bytes]:
    """Real Android encoders (MediaCodec) deliver SPS/PPS as a separate
    config buffer from the keyframe slice; ffmpeg's own muxer bundles them
    into one access unit instead. Split our fixture's first access unit the
    same way MediaCodec would, to test against the real-world shape rather
    than the muxer's convenient-but-unrepresentative one. Byte 36 is where
    the SEI+slice NAL units start in this specific fixture (verified by
    inspecting its NAL unit boundaries directly)."""
    return access_unit[:36], access_unit[36:]


def test_decode_fails_without_extradata_when_config_is_separate_from_slice():
    """Reproduces the real bug found via a live device: a parameter-sets-only
    packet (SPS/PPS with no slice data, as real MediaCodec sends it) is not
    itself decodable via decode() -- it must go through set_extradata()."""
    config_only, _slice_only = _split_config_and_slice(_access_units()[0])

    decoder = VideoDecoder("h264")
    try:
        with pytest.raises(av.error.InvalidDataError):
            decoder.decode(config_only)  # decode()-ing it, NOT set_extradata()
    finally:
        decoder.close()


def test_set_extradata_fixes_separate_config_packet_decode():
    config_only, slice_only = _split_config_and_slice(_access_units()[0])

    decoder = VideoDecoder("h264")
    try:
        decoder.set_extradata(config_only)
        frames = decoder.decode(slice_only)
    finally:
        decoder.close()

    assert len(frames) == 1
    assert frames[0].shape == (64, 64, 3)
