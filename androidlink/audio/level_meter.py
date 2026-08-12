"""Computes a real-time microphone input level from actually-decoded PCM
samples -- never a fake/random animation. Called from audio/mic_session.py
right where it already decodes incoming Android microphone audio for the
virtual-cable sink, so this reads the exact same PCM rather than capturing
anything separately (avoids a duplicate audio capture path).
"""

import numpy as np

# A conventional "meter floor" for a mic/vocal level indicator -- quieter
# than this reads as zero. Well below typical room noise, well above true
# digital silence's -inf dB, so real-but-quiet sound (a soft voice) still
# registers visibly on a linear [0, 1] meter instead of looking identical to
# silence (a plain linear RMS/full-scale ratio compresses normal speech
# down near the bottom few percent of the range).
_SILENCE_FLOOR_DB = -60.0
_FULL_SCALE = 32768.0  # max magnitude of a 16-bit signed PCM sample


def compute_rms_level(pcm_bytes: bytes) -> float:
    """RMS level of interleaved 16-bit signed PCM audio, mapped from dBFS
    onto [0, 1] anchored at _SILENCE_FLOOR_DB. Returns exactly 0.0 for true
    digital silence (all-zero samples, or no samples at all) rather than a
    tiny non-zero number from log-of-near-zero -- silence must never read
    as activity."""
    if not pcm_bytes:
        return 0.0
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    if samples.size == 0:
        return 0.0

    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    if rms <= 0.0:
        return 0.0

    db = 20 * np.log10(rms / _FULL_SCALE)
    normalized = (db - _SILENCE_FLOOR_DB) / (0.0 - _SILENCE_FLOOR_DB)
    return max(0.0, min(1.0, normalized))
