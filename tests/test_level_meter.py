"""compute_rms_level() must derive the microphone level from real PCM
samples only -- never fake/random. Verified with synthetically constructed
(but real, deterministic) 16-bit PCM rather than a captured fixture, so the
expected value at each amplitude is exactly known.
"""

import numpy as np

from androidlink.audio.level_meter import compute_rms_level


def _square_wave(amplitude: int, count: int = 500) -> bytes:
    return np.array([amplitude, -amplitude] * count, dtype=np.int16).tobytes()


def test_empty_input_is_silent():
    assert compute_rms_level(b"") == 0.0


def test_true_digital_silence_is_exactly_zero():
    assert compute_rms_level(np.zeros(1000, dtype=np.int16).tobytes()) == 0.0


def test_full_scale_signal_is_near_the_top_of_the_range():
    assert compute_rms_level(_square_wave(32767)) > 0.95


def test_quiet_but_real_signal_is_still_clearly_visible():
    # A naive linear RMS/full-scale ratio would put this under 3% -- almost
    # invisible on a meter despite being real, audible signal.
    level = compute_rms_level(_square_wave(1000))
    assert 0.3 < level < 0.9


def test_level_increases_monotonically_and_strictly_with_amplitude():
    levels = [compute_rms_level(_square_wave(a)) for a in (500, 2000, 8000, 32000)]
    assert levels == sorted(levels)
    assert len(set(levels)) == len(levels)


def test_output_is_always_within_0_and_1():
    for amplitude in (1, 100, 10_000, 32767):
        level = compute_rms_level(_square_wave(amplitude))
        assert 0.0 <= level <= 1.0
