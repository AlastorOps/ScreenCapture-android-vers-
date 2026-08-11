"""Maps the Performance <-> Quality slider (prompt.md section 6) onto concrete
scrcpy encoder parameters, so the user never has to think in bitrate/codec
terms unless they open Advanced Settings.

All profiles request 60fps and instruct the client to always prefer fresh
frames over stale buffered ones (prompt.md section 34) — only resolution and
bitrate trade off along the slider.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StreamingProfile:
    max_size: int
    max_fps: int
    video_bit_rate: int
    prefer_fresh_frames: bool = True


_PERFORMANCE = StreamingProfile(max_size=1280, max_fps=60, video_bit_rate=4_000_000)
_BALANCED = StreamingProfile(max_size=1920, max_fps=60, video_bit_rate=12_000_000)
_QUALITY = StreamingProfile(max_size=2560, max_fps=60, video_bit_rate=24_000_000)


def _lerp(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def resolve_streaming_profile(slider_value: int) -> StreamingProfile:
    """slider_value: 0 = full Performance, 100 = full Quality, 50 = Balanced."""
    value = max(0, min(100, slider_value))

    if value <= 50:
        t = value / 50
        low, high = _PERFORMANCE, _BALANCED
    else:
        t = (value - 50) / 50
        low, high = _BALANCED, _QUALITY

    return StreamingProfile(
        max_size=_lerp(low.max_size, high.max_size, t),
        max_fps=60,
        video_bit_rate=_lerp(low.video_bit_rate, high.video_bit_rate, t),
    )
