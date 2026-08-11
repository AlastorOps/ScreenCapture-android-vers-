from pathlib import Path

import av
import pytest

from androidlink.audio.decoder import AudioDecoder, UnsupportedAudioCodecError

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample.opus.ogg"


def _open_fixture():
    container = av.open(str(FIXTURE_PATH))
    stream = container.streams.audio[0]
    return container, stream


def test_decodes_real_opus_stream_to_expected_pcm_length():
    container, stream = _open_fixture()
    try:
        decoder = AudioDecoder("opus")
        decoder.set_extradata(stream.codec_context.extradata)

        total_pcm_bytes = 0
        packet_count = 0
        for packet in container.demux(stream):
            data = bytes(packet)
            if not data:
                continue
            packet_count += 1
            total_pcm_bytes += len(decoder.decode(data))
        decoder.close()
    finally:
        container.close()

    assert packet_count > 0
    # ~1 second at 48000 Hz, stereo, 16-bit = 192000 bytes; Opus priming
    # samples mean it's not exact, but should be very close.
    expected = 48000 * 2 * 2
    assert abs(total_pcm_bytes - expected) < 8000

    # Output must be interleaved 16-bit PCM: an even number of bytes, and a
    # whole number of stereo sample frames.
    assert total_pcm_bytes % 4 == 0


def test_decode_without_extradata_still_works():
    """Opus packets are self-contained enough that FFmpeg's decoder doesn't
    strictly require the OpusHead extradata to produce audio — verified
    against the real fixture rather than assumed."""
    container, stream = _open_fixture()
    try:
        decoder = AudioDecoder("opus")
        total_pcm_bytes = 0
        for packet in container.demux(stream):
            data = bytes(packet)
            if data:
                total_pcm_bytes += len(decoder.decode(data))
        decoder.close()
    finally:
        container.close()

    assert total_pcm_bytes > 0


def test_raw_codec_passes_bytes_through_unchanged():
    decoder = AudioDecoder("raw")
    pcm = b"\x01\x02\x03\x04"
    assert decoder.decode(pcm) == pcm
    decoder.close()  # must not raise


def test_unsupported_codec_raises():
    with pytest.raises(UnsupportedAudioCodecError):
        AudioDecoder("vorbis")
