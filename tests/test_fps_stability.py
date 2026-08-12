from androidlink.streaming.fps_stability import WINDOW_SAMPLES, FpsStabilityMonitor

_TIERS = (30, 60, 90, 120, 144, 165)


def test_stable_delivery_never_recommends_stepping_down():
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)
    result = None
    for _ in range(WINDOW_SAMPLES * 2):
        result = monitor.record_sample(stream_fps=164.7, dropped_frames=0)
    assert result is None


def test_sustained_delivery_shortfall_steps_down_to_next_lower_tier():
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)
    result = None
    for _ in range(WINDOW_SAMPLES):
        # Only delivering ~110fps of the requested 165 -- a genuine shortfall.
        result = monitor.record_sample(stream_fps=110.0, dropped_frames=0)
    assert result == 144


def test_sustained_frame_drops_step_down_even_with_fps_nominally_on_target():
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)
    result = None
    for _ in range(WINDOW_SAMPLES):
        result = monitor.record_sample(stream_fps=165.0, dropped_frames=60)
    assert result == 144


def test_does_not_step_down_to_60_directly_from_165():
    # prompt.md/FPS Limit Update: "Do not immediately fall back to 60 FPS."
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)
    result = None
    for _ in range(WINDOW_SAMPLES):
        result = monitor.record_sample(stream_fps=100.0, dropped_frames=0)
    assert result == 144
    assert result != 60


def test_a_single_bad_sample_in_an_otherwise_stable_window_does_not_trigger():
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)
    result = None
    for i in range(WINDOW_SAMPLES):
        stream_fps = 50.0 if i == 0 else 164.5  # one transient blip, then stable
        result = monitor.record_sample(stream_fps=stream_fps, dropped_frames=0)
    assert result is None


def test_lowest_tier_has_nowhere_lower_to_step_down_to():
    monitor = FpsStabilityMonitor(target_fps=30, tiers=_TIERS)
    result = None
    for _ in range(WINDOW_SAMPLES):
        result = monitor.record_sample(stream_fps=5.0, dropped_frames=0)
    assert result is None


def test_window_resets_after_a_decision_is_made():
    monitor = FpsStabilityMonitor(target_fps=165, tiers=_TIERS)
    for _ in range(WINDOW_SAMPLES):
        monitor.record_sample(stream_fps=100.0, dropped_frames=0)  # triggers a step-down

    # A fresh window of stable samples afterwards should not immediately
    # trigger again just because of leftover state.
    result = None
    for _ in range(WINDOW_SAMPLES - 1):
        result = monitor.record_sample(stream_fps=164.0, dropped_frames=0)
    assert result is None
