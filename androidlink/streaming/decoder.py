"""Decodes the Annex-B video packets scrcpy-server sends into RGB frames.

Uses PyAV (FFmpeg bindings). FFmpeg picks a hardware-accelerated decoder
(D3D11VA/DXVA2/NVDEC) automatically when available; this class does not
special-case the backend, it just asks for an "h264"/"hevc"/"av1" decoder and
lets FFmpeg's own hwaccel fallback chain decide.

Real Android encoders (MediaCodec) emit the SPS/PPS parameter sets as a
separate config buffer *before* the first keyframe buffer, with no parameter
sets repeated in-band in the keyframe itself. A decoder that hasn't been told
those parameter sets via set_extradata() before that point fails to decode
the keyframe with "Invalid data found when processing input" — verified by
reproducing it locally by splitting a real encoded stream's bundled SPS/PPS
away from its slice data.
"""

import numpy as np

try:
    import av
except ImportError:  # pragma: no cover - exercised only when PyAV is missing
    av = None

_CODEC_NAME_TO_AV_NAME = {
    "h264": "h264",
    "h265": "hevc",
    "av1": "av1",
}


class UnsupportedCodecError(Exception):
    pass


class VideoDecoder:
    """Wraps a single av.CodecContext for one scrcpy video session.

    A new instance must be created whenever the device sends a new
    SessionMeta (e.g. after a rotation or resize), since scrcpy always
    restarts the encoder — and therefore the SPS/PPS parameter sets — at
    that point.
    """

    def __init__(self, codec_name: str) -> None:
        if av is None:
            raise RuntimeError("PyAV (the 'av' package) is not installed")

        av_name = _CODEC_NAME_TO_AV_NAME.get(codec_name)
        if av_name is None:
            raise UnsupportedCodecError(codec_name)

        self._codec_context = av.CodecContext.create(av_name, "r")

    def set_extradata(self, data: bytes) -> None:
        """Feed the config packet's payload (SPS/PPS in Annex-B form) as the
        decoder's extradata. Must be called before the first decode() call
        that depends on it — i.e. as soon as a config packet arrives."""
        self._codec_context.extradata = data

    def decode(self, packet_bytes: bytes) -> list[np.ndarray]:
        """Feed one Annex-B access unit; returns zero or more decoded RGB24
        frames (a config/SPS-PPS-only packet yields zero frames)."""
        packet = av.Packet(packet_bytes)
        frames = self._codec_context.decode(packet)
        return [frame.to_ndarray(format="rgb24") for frame in frames]

    def close(self) -> None:
        # PyAV's CodecContext has no explicit close/dispose method; it frees
        # its underlying FFmpeg resources when garbage collected. Flushing
        # releases any reference frames the decoder is still holding.
        self._codec_context.flush_buffers()
