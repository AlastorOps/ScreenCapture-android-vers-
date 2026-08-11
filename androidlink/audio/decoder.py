"""Decodes the Opus/AAC/FLAC packets scrcpy-server sends into PCM samples.

Mirrors streaming/decoder.py's structure. "raw" is passed through directly
(the device already sends interleaved 16-bit PCM in that mode, no codec
involved) rather than through PyAV.

FFmpeg's decoders don't all share one native output format (Opus decodes to
planar float32 "fltp", other codecs may differ) — verified directly rather
than assumed by decoding a real Opus fixture during development. An
AudioResampler normalizes whatever the decoder produces to interleaved
16-bit PCM, matching what scrcpy captured on the Android side (AudioConfig.
ENCODING_PCM_16BIT) and what QAudioSink expects.
"""

import av

from androidlink.streaming.protocol import AUDIO_SAMPLE_RATE

_CODEC_NAME_TO_AV_NAME = {
    "opus": "opus",
    "aac": "aac",
    "flac": "flac",
}


class UnsupportedAudioCodecError(Exception):
    pass


class AudioDecoder:
    """One instance per scrcpy audio session. `codec_name` is whatever
    decode_audio_header() returned from the socket's first 4 bytes."""

    def __init__(self, codec_name: str) -> None:
        self._is_raw = codec_name == "raw"
        if self._is_raw:
            self._codec_context = None
            self._resampler = None
            return

        av_name = _CODEC_NAME_TO_AV_NAME.get(codec_name)
        if av_name is None:
            raise UnsupportedAudioCodecError(codec_name)

        self._codec_context = av.CodecContext.create(av_name, "r")
        self._codec_context.sample_rate = AUDIO_SAMPLE_RATE
        self._resampler = av.AudioResampler(
            format="s16", layout="stereo", rate=AUDIO_SAMPLE_RATE
        )

    def set_extradata(self, data: bytes) -> None:
        """Feed the config packet's payload (already unwrapped to the raw
        OpusHead/AAC-config bytes by the device, see Streamer.java's
        fixOpusConfigPacket) as the decoder's extradata."""
        if self._codec_context is not None:
            self._codec_context.extradata = data

    def decode(self, packet_bytes: bytes) -> bytes:
        """Returns interleaved 16-bit PCM bytes (possibly empty)."""
        if self._is_raw:
            return packet_bytes

        chunks = []
        for frame in self._codec_context.decode(av.Packet(packet_bytes)):
            for resampled in self._resampler.resample(frame):
                chunks.append(resampled.to_ndarray().tobytes())
        return b"".join(chunks)

    def close(self) -> None:
        if self._codec_context is not None:
            self._codec_context.flush_buffers()
