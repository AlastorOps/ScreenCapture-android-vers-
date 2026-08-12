"""Automatic-mode FPS instability fallback (FPS Limit Update spec, "Quality
Preservation": if a target FPS is unstable, dynamically find the highest
stable configuration below it -- e.g. fall back to 144 from 165, not
straight to 30/60).

Judges stability from genuinely measured DiagnosticsSample fields
(streaming/diagnostics.py) over a multi-second rolling window, never a
guess:

* stream_fps (decoded FPS) sustained well below the current target -- the
  encode/decode/transport pipeline isn't actually keeping up.
* a high proportion of arriving frames being dropped from the frame box
  (streaming/transport.py) before they could be rendered -- the consumer
  side can't keep pace either.

Two layers of protection against reacting to noise rather than genuine
sustained problems (root-caused against a real bug report: 60fps on a
60Hz-active/144Hz-monitor device was being marked "unstable" and dropped to
30fps within the first several seconds of a session -- turned out to be
session-startup noise, not a real capacity problem):

1. CastingController only starts feeding this monitor samples *after* the
   video session has actually started (SessionMeta received) -- the
   multi-second ADB push / reverse-tunnel / server-launch / socket-handshake
   sequence that precedes it reports stream_fps=0 for as long as it takes,
   which would otherwise look identical to "the pipeline can't sustain the
   target" on the very first window.
2. A single bad window is not enough to act on: CONSECUTIVE_UNSTABLE_
   WINDOWS_REQUIRED separate windows must *each* independently look
   unstable, back to back, before a step-down happens. One good window
   anywhere in between resets the streak to zero. This is the literal
   hysteresis the spec asks for -- a handful of dropped frames during a
   brief hiccup can no longer cascade into a visible FPS drop and a stream
   restart.

Only ever steps FPS *down*, at most one tier per confirmed-unstable streak,
and never back up automatically -- CastingController creates a fresh
monitor at the new (lower) target after each step-down, so a still-unstable
result keeps cascading down through SUPPORTED_TARGET_FPS_HZ until either a
tier proves stable or the lowest tier is reached. Applies only to Automatic
FPS; an explicit manual fps_override is a deliberate user choice this never
second-guesses.
"""

from dataclasses import dataclass, field

WINDOW_SAMPLES = 8  # ~8s per evaluation window at transport.py's 1 DiagnosticsSample/s cadence
UNSTABLE_SAMPLE_RATIO = 0.6  # this fraction of a window's samples must look bad for the window itself to count as unstable
DELIVERY_SHORTFALL_THRESHOLD = 0.15  # stream_fps > 15% below target counts a sample as unstable
DROPPED_FRAME_RATIO_THRESHOLD = 0.15  # >15% of arriving frames dropped counts a sample as unstable
CONSECUTIVE_UNSTABLE_WINDOWS_REQUIRED = 2  # ~2x WINDOW_SAMPLES seconds of back-to-back trouble before acting


@dataclass(frozen=True)
class FpsWindowEvaluation:
    """One full window's worth of measured evidence -- returned every time a
    window completes, whether or not it changes anything, so the caller can
    log a genuinely useful "kept N fps" line for the common case and not
    just the rare step-down (see streaming/controller.py's
    _on_stats_for_stability())."""

    target_fps: int
    window_seconds: int
    total_samples: int
    unstable_samples: int
    avg_stream_fps: float
    avg_dropped_frames: float
    stable: bool
    consecutive_unstable_windows: int
    decision_tier: int | None  # set only when this evaluation actually triggers a step-down


@dataclass
class FpsStabilityMonitor:
    target_fps: int
    tiers: tuple[int, ...]
    _unstable_flags: list[bool] = field(default_factory=list, init=False, repr=False)
    _stream_fps_samples: list[float] = field(default_factory=list, init=False, repr=False)
    _dropped_samples: list[int] = field(default_factory=list, init=False, repr=False)
    _consecutive_unstable_windows: int = field(default=0, init=False, repr=False)

    def record_sample(self, stream_fps: float, dropped_frames: int) -> FpsWindowEvaluation | None:
        """Feed one DiagnosticsSample's worth of measured data in. Returns
        None while the window is still filling; once full, always returns
        an evaluation -- check .decision_tier for whether it's actually
        time to step down."""
        self._unstable_flags.append(self._is_unstable_sample(stream_fps, dropped_frames))
        self._stream_fps_samples.append(stream_fps)
        self._dropped_samples.append(dropped_frames)
        if len(self._unstable_flags) < WINDOW_SAMPLES:
            return None

        total_samples = len(self._unstable_flags)
        unstable_count = sum(self._unstable_flags)
        window_stable = unstable_count < WINDOW_SAMPLES * UNSTABLE_SAMPLE_RATIO
        avg_stream_fps = sum(self._stream_fps_samples) / total_samples
        avg_dropped = sum(self._dropped_samples) / total_samples

        self._consecutive_unstable_windows = 0 if window_stable else self._consecutive_unstable_windows + 1

        decision_tier = None
        if not window_stable and self._consecutive_unstable_windows >= CONSECUTIVE_UNSTABLE_WINDOWS_REQUIRED:
            lower_tiers = [tier for tier in self.tiers if tier < self.target_fps]
            decision_tier = max(lower_tiers) if lower_tiers else None

        evaluation = FpsWindowEvaluation(
            target_fps=self.target_fps,
            window_seconds=WINDOW_SAMPLES,
            total_samples=total_samples,
            unstable_samples=unstable_count,
            avg_stream_fps=avg_stream_fps,
            avg_dropped_frames=avg_dropped,
            stable=window_stable,
            consecutive_unstable_windows=self._consecutive_unstable_windows,
            decision_tier=decision_tier,
        )

        self._unstable_flags.clear()
        self._stream_fps_samples.clear()
        self._dropped_samples.clear()
        return evaluation

    def _is_unstable_sample(self, stream_fps: float, dropped_frames: int) -> bool:
        if self.target_fps <= 0:
            return False

        delivery_ratio = stream_fps / self.target_fps
        if delivery_ratio < (1 - DELIVERY_SHORTFALL_THRESHOLD):
            return True

        total_frames = stream_fps + dropped_frames
        if total_frames <= 0:
            return False
        drop_ratio = dropped_frames / total_frames
        return drop_ratio > DROPPED_FRAME_RATIO_THRESHOLD
