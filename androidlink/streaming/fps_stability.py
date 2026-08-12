"""Automatic-mode FPS instability fallback (FPS Limit Update spec, "Quality
Preservation": if 165 FPS is unstable, dynamically find the highest stable
configuration below it -- e.g. fall back to 144, not straight to 60).

Judges stability from genuinely measured DiagnosticsSample fields
(streaming/diagnostics.py) over a short rolling window, never a guess:

* stream_fps sustained well below the current target -- the encode/decode/
  transport pipeline isn't actually keeping up with the requested rate.
* a high proportion of arriving frames being dropped from the frame box
  (streaming/transport.py) before they could be rendered -- the consumer
  side can't keep pace either.

Only ever steps FPS *down*, at most one tier per unstable window, and never
back up automatically -- CastingController creates a fresh monitor at the
new (lower) target after each step-down, so a still-unstable result keeps
cascading down through SUPPORTED_TARGET_FPS_HZ until either a tier proves
stable or the lowest tier is reached. Applies only to Automatic FPS; an
explicit manual fps_override is a deliberate user choice this never
second-guesses.
"""

from dataclasses import dataclass, field

WINDOW_SAMPLES = 5  # ~5s at transport.py's STATS_INTERVAL_MS (1 DiagnosticsSample/s)
UNSTABLE_SAMPLE_RATIO = 0.6  # majority of the window must look unstable to act
DELIVERY_SHORTFALL_THRESHOLD = 0.15  # stream_fps > 15% below target counts as unstable
DROPPED_FRAME_RATIO_THRESHOLD = 0.15  # >15% of arriving frames dropped counts as unstable


@dataclass
class FpsStabilityMonitor:
    target_fps: int
    tiers: tuple[int, ...]
    _unstable_flags: list[bool] = field(default_factory=list, init=False, repr=False)

    def record_sample(self, stream_fps: float, dropped_frames: int) -> int | None:
        """Feed one DiagnosticsSample's worth of measured data in. Returns
        the next lower tier to step down to once a full window shows
        sustained instability, or None while stable / still filling the
        window / already at the lowest tier."""
        self._unstable_flags.append(self._is_unstable_sample(stream_fps, dropped_frames))
        if len(self._unstable_flags) < WINDOW_SAMPLES:
            return None

        unstable_count = sum(self._unstable_flags)
        self._unstable_flags.clear()
        if unstable_count < WINDOW_SAMPLES * UNSTABLE_SAMPLE_RATIO:
            return None

        lower_tiers = [tier for tier in self.tiers if tier < self.target_fps]
        return max(lower_tiers) if lower_tiers else None

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
