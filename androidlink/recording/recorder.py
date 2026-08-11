"""PC-side recording of the live cast (prompt.md section 14: recording is
handled by the PC, never the Android device). RecordingController (in
recording_controller.py) hands VideoRecorder already-decoded RGB24 frames
-- the same frames already being rendered, no separate capture path -- and,
when Android audio is enabled, the same decoded PCM already being played
back. A dedicated background thread encodes/muxes both, so recording never
adds latency to live casting or the GUI (prompt.md section 22).

Deliberately a plain threading.Thread rather than a QThread: there's no Qt
event-loop work to do here, just a blocking queue, and mixing a blocking
queue.get() with a Qt event loop would stall delivery of any queued Qt
signals to this object. Video and audio share one bounded queue.Queue,
tagged by kind, so items are encoded/muxed in the order they actually
arrived; drop-oldest-on-overflow means a slow encoder degrades recording
quality (a dropped frame/audio chunk) rather than ever blocking the GUI
thread's submit_frame()/submit_audio() calls (prompt.md section 34:
prioritize a responsive app over perfect frame-accuracy in the recording).

Video frames are muxed in arrival order at a constant declared frame rate
(the cast's target max-fps) rather than stamped with wall-clock PTS --
verified directly that explicit sub-frame-accurate PTS gets silently
quantized to the codec's 1/fps granularity, so it bought nothing. If the
device's actual delivered frame rate drifts from the declared target,
playback speed will drift correspondingly -- a known limitation, not
silently hidden (prompt.md section 34: report real behavior, not
fabricated precision). Audio is encoded via PyAV's high-level stream.encode
the same way -- verified end-to-end (write, close, decode back) that this
produces a valid interleaved audio+video file.

Hardware video encoding (NVENC/QSV/AMF) is tried first, matching whichever
the FFmpeg build + local GPU actually support, falling back to libx264.
select_video_encoder() genuinely probes each candidate by opening it --
av.CodecContext.create() alone succeeds even for encoders the machine can't
actually run; only .open() surfaces that failure. Verified directly on this
dev machine: no hardware encoder is available here, so it always falls
back to libx264, which does open successfully. Audio always uses AAC (a
standard software encoder built into every FFmpeg build, no hardware
variants to probe).
"""

import logging
import queue
import threading
from fractions import Fraction
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from androidlink.streaming.protocol import AUDIO_SAMPLE_RATE

try:
    import av
except ImportError:  # pragma: no cover - exercised only when PyAV is missing
    av = None

logger = logging.getLogger(__name__)

_HARDWARE_ENCODER_CANDIDATES = ("h264_nvenc", "h264_qsv", "h264_amf")
_SOFTWARE_ENCODER = "libx264"
_AUDIO_ENCODER = "aac"
_QUEUE_MAXSIZE = 240  # a few seconds of mixed video+audio buffering
_STOP_SENTINEL = object()
_KIND_VIDEO = "video"
_KIND_AUDIO = "audio"


def _encoder_opens(name: str, width: int, height: int, fps: int) -> bool:
    try:
        context = av.CodecContext.create(name, "w")
        context.width = width
        context.height = height
        context.pix_fmt = "yuv420p"
        context.time_base = Fraction(1, fps)
        context.framerate = Fraction(fps, 1)
        context.open()
        return True
    except Exception:
        return False


def select_video_encoder(width: int, height: int, fps: int) -> str:
    """Returns the first hardware encoder that actually opens on this
    machine, falling back to libx264 (always available in the bundled
    FFmpeg build)."""
    for name in _HARDWARE_ENCODER_CANDIDATES:
        if _encoder_opens(name, width, height, fps):
            return name
    return _SOFTWARE_ENCODER


class VideoRecorder(QObject):
    """GUI-thread-facing handle. Owns a background encode thread and
    re-exposes its state as Qt signals -- emitting a signal from a plain
    Python thread is safe; Qt queues delivery to whatever thread the
    receiving object lives on."""

    started = Signal()
    error = Signal(str)
    stopped = Signal(str)  # final file path

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._queue: queue.Queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._paused = threading.Event()
        self._dropped_frames = 0

    @property
    def is_recording(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, path: Path, width: int, height: int, fps: int, *, has_audio: bool = False) -> None:
        if self.is_recording:
            return
        if av is None:
            self.error.emit("PyAV (the 'av' package) is not installed")
            return

        self._dropped_frames = 0
        self._paused.clear()
        self._queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._thread = threading.Thread(
            target=self._run, args=(path, width, height, fps, has_audio), daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if not self.is_recording:
            return
        self._queue.put(_STOP_SENTINEL)

    def set_paused(self, paused: bool) -> None:
        if paused:
            self._paused.set()
        else:
            self._paused.clear()

    def submit_frame(self, frame: np.ndarray) -> None:
        """Called from the GUI thread with each newly rendered frame while
        recording is active. Never blocks."""
        self._submit((_KIND_VIDEO, frame))

    def submit_audio(self, pcm_bytes: bytes) -> None:
        """Called with each newly decoded Android-audio PCM chunk (48kHz
        stereo s16 interleaved, matching audio/decoder.py's output) while
        recording is active. A no-op if this recording was started without
        audio (has_audio=False) -- the chunk is simply dropped, not
        buffered forever. Never blocks."""
        self._submit((_KIND_AUDIO, pcm_bytes))

    def _submit(self, item: tuple) -> None:
        if not self.is_recording or self._paused.is_set():
            return
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._dropped_frames += 1
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                pass

    def _run(self, path: Path, width: int, height: int, fps: int, has_audio: bool) -> None:
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            encoder_name = select_video_encoder(width, height, fps)
            container = av.open(str(path), mode="w")
            video_stream = container.add_stream(encoder_name, rate=fps)
            video_stream.width = width
            video_stream.height = height
            video_stream.pix_fmt = "yuv420p"

            audio_stream = None
            audio_resampler = None
            if has_audio:
                audio_stream = container.add_stream(_AUDIO_ENCODER, rate=AUDIO_SAMPLE_RATE)
                audio_resampler = av.AudioResampler(
                    format=audio_stream.format, layout=audio_stream.layout, rate=AUDIO_SAMPLE_RATE
                )
        except Exception as exc:
            logger.exception("Could not start recording")
            self.error.emit(f"Could not start recording: {exc}")
            self._thread = None
            return

        logger.info(
            "Recording started: %s (%dx%d @ %dfps, encoder=%s, audio=%s)",
            path,
            width,
            height,
            fps,
            encoder_name,
            has_audio,
        )
        self.started.emit()

        try:
            while True:
                item = self._queue.get()
                if item is _STOP_SENTINEL:
                    break
                kind, payload = item
                try:
                    if kind == _KIND_VIDEO:
                        vframe = av.VideoFrame.from_ndarray(payload, format="rgb24")
                        vframe = vframe.reformat(format=video_stream.pix_fmt)
                        for packet in video_stream.encode(vframe):
                            container.mux(packet)
                    elif kind == _KIND_AUDIO and audio_stream is not None:
                        # 16-bit stereo interleaved -> 4 bytes per sample-pair.
                        aframe = av.AudioFrame(
                            format="s16", layout="stereo", samples=len(payload) // 4
                        )
                        aframe.planes[0].update(payload)
                        aframe.sample_rate = AUDIO_SAMPLE_RATE
                        for resampled in audio_resampler.resample(aframe):
                            for packet in audio_stream.encode(resampled):
                                container.mux(packet)
                except Exception:
                    logger.exception("Error encoding a recorded %s chunk; dropping it", kind)

            for packet in video_stream.encode():  # flush
                container.mux(packet)
            if audio_stream is not None:
                for packet in audio_stream.encode():
                    container.mux(packet)
        finally:
            container.close()
            if self._dropped_frames:
                logger.warning(
                    "Recording finished with %d frames/chunks dropped (encoder fell behind)",
                    self._dropped_frames,
                )
            self.stopped.emit(str(path))
