"""PC-side recording of the live cast (prompt.md section 14: recording is
handled by the PC, never the Android device). RecordingController (in
recording_controller.py) hands VideoRecorder already-decoded RGB24 frames
-- the same frames already being rendered, no separate capture path -- and
a dedicated background thread encodes/muxes them, so recording never adds
latency to live casting or the GUI (prompt.md section 22).

Deliberately a plain threading.Thread rather than a QThread: there's no Qt
event-loop work to do here, just a blocking frame queue, and mixing a
blocking queue.get() with a Qt event loop would stall delivery of any
queued Qt signals to this object. Frame handoff uses a bounded queue.Queue
with drop-oldest-on-overflow, so a slow encoder degrades recording quality
(a dropped frame) rather than ever blocking the GUI thread's submit_frame()
call (prompt.md section 34: prioritize a responsive app over perfect
frame-accuracy in the recording).

Video-only for this pass -- audio muxing isn't wired up yet. Android audio
lives entirely inside streaming/transport.py's own worker thread with no
tap point exposed to the recorder; documented here and in README rather
than silently dropped.

Frames are muxed in arrival order at a constant declared frame rate (the
cast's target max-fps) rather than stamped with wall-clock PTS -- verified
directly that explicit sub-frame-accurate PTS gets silently quantized to
the codec's 1/fps granularity, so it bought nothing. If the device's actual
delivered frame rate drifts from the declared target, playback speed will
drift correspondingly -- a known limitation, not silently hidden (prompt.md
section 34: report real behavior, not fabricated precision).

Hardware encoding (NVENC/QSV/AMF) is tried first, matching whichever the
FFmpeg build + local GPU actually support, falling back to libx264.
select_video_encoder() genuinely probes each candidate by opening it --
av.CodecContext.create() alone succeeds even for encoders the machine can't
actually run; only .open() surfaces that failure. Verified directly on this
dev machine: no hardware encoder is available here, so it always falls
back to libx264, which does open successfully.
"""

import logging
import queue
import threading
from fractions import Fraction
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

try:
    import av
except ImportError:  # pragma: no cover - exercised only when PyAV is missing
    av = None

logger = logging.getLogger(__name__)

_HARDWARE_ENCODER_CANDIDATES = ("h264_nvenc", "h264_qsv", "h264_amf")
_SOFTWARE_ENCODER = "libx264"
_QUEUE_MAXSIZE = 60  # ~2s of buffering at 30fps before frames start dropping
_STOP_SENTINEL = object()


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

    def start(self, path: Path, width: int, height: int, fps: int) -> None:
        if self.is_recording:
            return
        if av is None:
            self.error.emit("PyAV (the 'av' package) is not installed")
            return

        self._dropped_frames = 0
        self._paused.clear()
        self._queue = queue.Queue(maxsize=_QUEUE_MAXSIZE)
        self._thread = threading.Thread(
            target=self._run, args=(path, width, height, fps), daemon=True
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
        if not self.is_recording or self._paused.is_set():
            return
        try:
            self._queue.put_nowait(frame)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            self._dropped_frames += 1
            try:
                self._queue.put_nowait(frame)
            except queue.Full:
                pass

    def _run(self, path: Path, width: int, height: int, fps: int) -> None:
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            encoder_name = select_video_encoder(width, height, fps)
            container = av.open(str(path), mode="w")
            stream = container.add_stream(encoder_name, rate=fps)
            stream.width = width
            stream.height = height
            stream.pix_fmt = "yuv420p"
        except Exception as exc:
            logger.exception("Could not start recording")
            self.error.emit(f"Could not start recording: {exc}")
            self._thread = None
            return

        logger.info(
            "Recording started: %s (%dx%d @ %dfps, encoder=%s)",
            path,
            width,
            height,
            fps,
            encoder_name,
        )
        self.started.emit()

        try:
            while True:
                item = self._queue.get()
                if item is _STOP_SENTINEL:
                    break
                try:
                    vframe = av.VideoFrame.from_ndarray(item, format="rgb24")
                    vframe = vframe.reformat(format=stream.pix_fmt)
                    for packet in stream.encode(vframe):
                        container.mux(packet)
                except Exception:
                    logger.exception("Error encoding a recorded frame; dropping it")

            for packet in stream.encode():  # flush
                container.mux(packet)
        finally:
            container.close()
            if self._dropped_frames:
                logger.warning(
                    "Recording finished with %d frames dropped (encoder fell behind)",
                    self._dropped_frames,
                )
            self.stopped.emit(str(path))
