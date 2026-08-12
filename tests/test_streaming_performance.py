from androidlink.streaming.performance import describe_resolution, resolve_streaming_profile


def test_slider_zero_matches_performance_anchor():
    profile = resolve_streaming_profile(0)
    assert profile.max_size == 1280
    assert profile.video_bit_rate == 4_000_000


def test_slider_fifty_matches_balanced_anchor():
    profile = resolve_streaming_profile(50)
    assert profile.max_size == 1920
    assert profile.video_bit_rate == 12_000_000


def test_slider_hundred_matches_quality_anchor():
    profile = resolve_streaming_profile(100)
    assert profile.max_size == 2560
    assert profile.video_bit_rate == 24_000_000


def test_slider_is_monotonic_in_bitrate():
    values = [resolve_streaming_profile(v).video_bit_rate for v in range(0, 101, 10)]
    assert values == sorted(values)


def test_slider_clamps_out_of_range_values():
    assert resolve_streaming_profile(-10) == resolve_streaming_profile(0)
    assert resolve_streaming_profile(200) == resolve_streaming_profile(100)


def test_all_profiles_default_to_60fps_fallback_and_prefer_fresh_frames():
    # No automatic_fps passed -> falls back to FALLBACK_HZ (60), the
    # honest "detection unavailable" default -- not a hardcoded cap. See
    # test_automatic_fps_targets_the_detected_device_refresh_rate below for
    # the actual uncapped behavior once a device's real rate is known.
    for value in (0, 25, 50, 75, 100):
        profile = resolve_streaming_profile(value)
        assert profile.max_fps == 60
        assert profile.prefer_fresh_frames is True


def test_automatic_fps_targets_the_detected_device_refresh_rate():
    """The 60fps cap this used to have unconditionally is gone -- FPS now
    tracks whatever the connected device's screen actually supports
    (device/display_info.py), verified here up to a real 165Hz panel."""
    for hz in (90, 120, 144, 165):
        profile = resolve_streaming_profile(50, automatic_fps=hz)
        assert profile.max_fps == hz


def test_fps_override_takes_priority_over_automatic_fps():
    profile = resolve_streaming_profile(50, max_fps_override=90, automatic_fps=120)
    assert profile.max_fps == 90


def test_automatic_fps_is_capped_at_165_even_for_a_240hz_panel():
    # FPS Limit Update: removing the old blanket 60fps cap must never turn
    # into requesting an arbitrarily high rate from a 240Hz-class panel --
    # 165 is the new hard ceiling regardless of source.
    profile = resolve_streaming_profile(50, automatic_fps=240)
    assert profile.max_fps == 165


def test_manual_fps_override_is_also_capped_at_165():
    profile = resolve_streaming_profile(50, max_fps_override=240, automatic_fps=60)
    assert profile.max_fps == 165


def test_165_fps_itself_passes_through_uncapped():
    profile = resolve_streaming_profile(50, automatic_fps=165)
    assert profile.max_fps == 165


def test_fps_is_independent_of_resolution_and_bitrate_slider_position():
    # FPS isn't traded off along the slider the way resolution/bitrate are --
    # Automatic targets the same detected device rate at every slider
    # position (prompt.md section 12: only resolution/bitrate trade off).
    fps_values = {resolve_streaming_profile(v, automatic_fps=120).max_fps for v in range(0, 101, 10)}
    assert fps_values == {120}


def test_resolution_override_takes_priority_over_the_slider():
    profile = resolve_streaming_profile(0, max_size_override=2560)
    assert profile.max_size == 2560
    # Bitrate/FPS still follow the slider -- the override is scoped to
    # resolution only, not a blanket "freeze everything" switch.
    assert profile.video_bit_rate == resolve_streaming_profile(0).video_bit_rate


def test_describe_resolution_labels_the_three_anchor_points():
    assert describe_resolution(1280) == "~720p (1280px)"
    assert describe_resolution(1920) == "~1080p (1920px)"
    assert describe_resolution(2560) == "~1440p (2560px)"


def test_describe_resolution_picks_nearest_label_for_interpolated_sizes():
    assert describe_resolution(1600).startswith("~720p")  # closer to 1280 than 1920
    assert describe_resolution(1700).startswith("~1080p")  # closer to 1920 than 1280
    assert "1600px" in describe_resolution(1600)


def test_describe_resolution_reflects_the_actual_resolved_profile():
    for slider_value in (0, 25, 50, 75, 100):
        profile = resolve_streaming_profile(slider_value)
        label = describe_resolution(profile.max_size)
        assert str(profile.max_size) in label
