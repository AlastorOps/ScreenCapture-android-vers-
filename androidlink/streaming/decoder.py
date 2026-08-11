"""Decodes the Annex-B video packets scrcpy-server sends into RGB frames.

Uses PyAV (FFmpeg bindings). PyAV does NOT enable hardware-accelerated
decoding (D3D11VA/DXVA2/NVDEC) automatically just because FFmpeg supports it
-- confirmed directly against this project's PyAV 18 install: plain
`av.CodecContext.create("h264", "r")` decodes purely in software regardless
of what hwaccels are available, and `CodecContext.hwaccel` isn't even
settable after construction (raises "attribute ... is not writable"). A
hardware decoder must be requested explicitly via the `hwaccel=` kwarg on
`CodecContext.create()` itself. This class now does that, trying Windows'
two real hwaccel backends in order (D3D11VA, then the older DXVA2) and
falling back to software only if neither is available/working -- verified
end to end against this project's own real H.264 fixture
(tests/fixtures/sample.h264): both backends decode all 10 frames correctly
and `frame.to_ndarray(format="rgb24")` transparently downloads/converts the
GPU-resident frame, so nothing downstream needed to change.
`hardware_accelerated` reports which path is actually active for a given
session (surfaced in diagnostics), decided once at construction time from
whether hwaccel context creation actually succeeds -- not retried/demoted
per packet at decode time; see decode()'s docstring for why a mid-session
retry-on-failure was tried and reverted (it corrupted playback on real
corrupt-packet input, verified via test_video_client_state_machine.py).

Real Android encoders (MediaCodec) emit the SPS/PPS parameter sets as a
separate config buffer *before* the first keyframe buffer, with no parameter
sets repeated in-band in the keyframe itself. A decoder that hasn't been told
those parameter sets via set_extradata() before that point fails to decode
the keyframe with "Invalid data found when processing input" — verified by
reproducing it locally by splitting a real encoded stream's bundled SPS/PPS
away from its slice data.
"""

import logging

import numpy as np

try:
    import av
    from av.codec.hwaccel import HWAccel
except ImportError:  # pragma: no cover - exercised only when PyAV is missing
    av = None
    HWAccel = None

logger = logging.getLogger(__name__)

_CODEC_NAME_TO_AV_NAME = {
    "h264": "h264",
    "h265": "hevc",
    "av1": "av1",
}

# Tried in order; both are real Windows video-decode APIs (D3D11VA is the
# modern one, DXVA2 the older fallback still present on some GPU/driver
# combos where D3D11VA isn't). No vendor-specific backend (NVDEC/AMF/QSV) is
# tried explicitly -- D3D11VA already routes through whichever vendor's
# driver is installed, and guessing the wrong vendor-specific one first would
# just add failed-attempt latency on every session start.
_HWACCEL_DEVICE_TYPES = ("d3d11va", "dxva2")


def _create_hwaccel_context(av_name: str):
    """Returns (codec_context, device_type_used) for the first working
    hwaccel backend, or (None, None) if none are available/working on this
    machine -- callers fall back to software decode in that case."""
    if HWAccel is None:
        return None, None
    for device_type in _HWACCEL_DEVICE_TYPES:
        try:
            hwaccel = HWAccel(device_type=device_type, allow_software_fallback=False)
            context = av.CodecContext.create(av_name, "r", hwaccel=hwaccel)
        except Exception as exc:  # noqa: BLE001 - any backend/driver failure just means "try the next one"
            logger.debug("hwaccel %s unavailable for %s: %s", device_type, av_name, exc)
            continue
        return context, device_type
    return None, None


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

        self._codec_context, hwaccel_device = _create_hwaccel_context(av_name)
        if self._codec_context is None:
            self._codec_context = av.CodecContext.create(av_name, "r")
            self.hardware_accelerated = False
        else:
            self.hardware_accelerated = True
            logger.info("Video decode: using hardware acceleration (%s)", hwaccel_device)

    def set_extradata(self, data: bytes) -> None:
        """Feed the config packet's payload (SPS/PPS in Annex-B form) as the
        decoder's extradata. Must be called before the first decode() call
        that depends on it — i.e. as soon as a config packet arrives."""
        self._codec_context.extradata = data

    def decode(self, packet_bytes: bytes) -> list[np.ndarray]:
        """Feed one Annex-B access unit; returns zero or more decoded RGB24
        frames (a config/SPS-PPS-only packet yields zero frames).

        Deliberately does NOT catch decode errors here and retry on a fresh
        software context: a first attempt at that (mid-session hwaccel ->
        software fallback) turned out to actively corrupt playback on a real
        corrupt/garbage packet -- rebuilding the codec context to retry
        discarded its decoded reference-frame state, so the *next legitimate*
        frame after the bad one silently failed to decode too (verified via
        tests/test_video_client_state_machine.py's corrupt-packet-recovery
        test, which is exactly the scenario this would have broken). Callers
        (streaming/transport.py's _process_buffer) already catch decode
        exceptions per-packet and drop just that packet without desyncing the
        parser or tearing down the session -- the right layer for this, since
        it doesn't need to guess whether a given failure was hwaccel-specific
        or just bad data.
        """
        packet = av.Packet(packet_bytes)
        frames = self._codec_context.decode(packet)
        return [frame.to_ndarray(format="rgb24") for frame in frames]

    def close(self) -> None:
        # PyAV's CodecContext has no explicit close/dispose method; it frees
        # its underlying FFmpeg resources when garbage collected. Flushing
        # releases any reference frames the decoder is still holding.
        self._codec_context.flush_buffers()
