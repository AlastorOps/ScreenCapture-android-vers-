from androidlink.streaming.fps_stability import (
    CONSECUTIVE_UNSTABLE_WINDOWS_REQUIRED,
    WINDOW_SAMPLES,
    FpsStabilityMonitor,
)

_TIERS = (30, 60, 90, 120, 144, 165)


def _feed_stable_window(monitor, stream_fps, dropped_frames=0):
    result = None
    for _ in range(WINDOW_SAMPLES):
        result = monitor.record_sample(stream_fps=stream_fps, dropped_frames=dropped_frames)
    return result


def test_stable_delivery_never_recommends_stepping_down():
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)
    evaluation = None
    for _ in range(WINDOW_SAMPLES * 3):
        evaluation = monitor.record_sample(stream_fps=164.7, dropped_frames=0)
    assert evaluation is not None
    assert evaluation.stable is True
    assert evaluation.decision_tier is None


def test_a_single_unstable_window_does_not_step_down_yet():
    """The core hysteresis requirement: one bad window on its own is not
    enough evidence -- CONSECUTIVE_UNSTABLE_WINDOWS_REQUIRED separate
    windows must each independently look unstable before anything changes."""
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)

    evaluation = _feed_stable_window(monitor, stream_fps=110.0)  # ~67% delivery -- genuinely bad

    assert evaluation.stable is False
    assert evaluation.consecutive_unstable_windows == 1
    assert evaluation.decision_tier is None  # not enough evidence yet


def test_sustained_delivery_shortfall_across_consecutive_windows_steps_down():
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)
    evaluation = None
    for _ in range(CONSECUTIVE_UNSTABLE_WINDOWS_REQUIRED):
        evaluation = _feed_stable_window(monitor, stream_fps=110.0)

    assert evaluation.stable is False
    assert evaluation.decision_tier == 144


def test_sustained_frame_drops_step_down_even_with_fps_nominally_on_target():
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)
    evaluation = None
    for _ in range(CONSECUTIVE_UNSTABLE_WINDOWS_REQUIRED):
        evaluation = _feed_stable_window(monitor, stream_fps=165.0, dropped_frames=60)

    assert evaluation.decision_tier == 144


def test_does_not_step_down_to_60_directly_from_165():
    # prompt.md/FPS Limit Update: "Do not immediately fall back to 60 FPS."
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)
    evaluation = None
    for _ in range(CONSECUTIVE_UNSTABLE_WINDOWS_REQUIRED):
        evaluation = _feed_stable_window(monitor, stream_fps=100.0)

    assert evaluation.decision_tier == 144
    assert evaluation.decision_tier != 60


def test_a_single_bad_sample_in_an_otherwise_stable_window_does_not_trigger():
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)
    evaluation = None
    for i in range(WINDOW_SAMPLES):
        stream_fps = 50.0 if i == 0 else 164.5  # one transient blip, then stable
        evaluation = monitor.record_sample(stream_fps=stream_fps, dropped_frames=0)

    assert evaluation.stable is True
    assert evaluation.decision_tier is None


def test_one_good_window_in_the_middle_resets_the_unstable_streak():
    """Item 3's hysteresis: a stable window anywhere in the streak resets
    progress toward a step-down back to zero -- it doesn't just pause."""
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)

    first = _feed_stable_window(monitor, stream_fps=100.0)  # unstable
    assert first.consecutive_unstable_windows == 1

    recovered = _feed_stable_window(monitor, stream_fps=164.0)  # stable
    assert recovered.stable is True
    assert recovered.consecutive_unstable_windows == 0

    # Only one more bad window since the reset -- must not be enough on its
    # own to trigger a step-down even though two *total* unstable windows
    # have now occurred across the monitor's lifetime.
    third = _feed_stable_window(monitor, stream_fps=100.0)
    assert third.consecutive_unstable_windows == 1
    assert third.decision_tier is None


def test_lowest_tier_has_nowhere_lower_to_step_down_to():
    monitor = FpsStabilityMonitor(target_fps=30, tiers=_TIERS)
    evaluation = None
    for _ in range(CONSECUTIVE_UNSTABLE_WINDOWS_REQUIRED):
        evaluation = _feed_stable_window(monitor, stream_fps=5.0)

    assert evaluation.stable is False
    assert evaluation.decision_tier is None  # nowhere lower to go


def test_window_resets_after_a_window_completes():
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)
    for _ in range(CONSECUTIVE_UNSTABLE_WINDOWS_REQUIRED):
        _feed_stable_window(monitor, stream_fps=100.0)  # triggers a step-down

    # A fresh window of stable samples afterwards should not immediately
    # trigger again just because of leftover state.
    evaluation = None
    for _ in range(WINDOW_SAMPLES - 1):
        evaluation = monitor.record_sample(stream_fps=164.0, dropped_frames=0)
    assert evaluation is None  # window not full yet


def test_evaluation_reports_real_averages_not_just_a_verdict():
    monitor = FpsStabilityMonitor(target_fps=60, tiers=_TIERS)
    stream_values = [55.0, 60.0, 58.0, 60.0, 57.0, 60.0, 59.0, 60.0]
    assert len(stream_values) == WINDOW_SAMPLES
    evaluation = None
    for value in stream_values:
        evaluation = monitor.record_sample(stream_fps=value, dropped_frames=1)

    assert evaluation.target_fps == 60
    assert evaluation.total_samples == WINDOW_SAMPLES
    assert abs(evaluation.avg_stream_fps - sum(stream_values) / len(stream_values)) < 1e-9
    assert evaluation.avg_dropped_frames == 1.0
    assert evaluation.stable is True
