from androidlink.streaming.performance import resolve_streaming_profile


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


def test_all_profiles_request_60fps_and_prefer_fresh_frames():
    for value in (0, 25, 50, 75, 100):
        profile = resolve_streaming_profile(value)
        assert profile.max_fps == 60
        assert profile.prefer_fresh_frames is True
