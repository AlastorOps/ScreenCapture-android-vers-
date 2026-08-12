"""Maps the Performance <-> Quality slider (prompt.md section 6) onto concrete
scrcpy encoder parameters, so the user never has to think in bitrate/codec
terms unless they open Advanced Settings.

FPS is intentionally *not* one of the things this slider trades off: earlier
this always requested a hardcoded 60fps regardless of what the connected
device's screen could actually do, silently capping every device -- even a
120Hz/165Hz panel -- at 60. FPS now defaults to "Automatic", which targets
the device's own detected refresh rate (device/display_info.py) rather than
a fixed number, and is otherwise driven independently by
StreamingSettings.fps_override (a specific manual choice, e.g. "90"). What
the slider actually trades off is resolution and bitrate -- prioritizing
FPS/low-latency (small, cheap-to-encode/decode/transport frames) at the
Performance end vs. resolution/image quality (larger, heavier frames) at the
Quality end, per prompt.md section 12: a lighter total frame budget makes it
easier to sustain a high frame rate in practice than the number "60" ever
did on its own.

Whatever FPS is resolved to -- automatic or a manual override -- is always
clamped to MAX_STREAM_FPS (165, see device/display_info.py): removing the
old 60fps cap must never turn into requesting an arbitrarily high rate from
a 240Hz-class panel either. When 165 itself turns out to be more than the
real pipeline can sustain, streaming/fps_stability.py steps Automatic mode
down to the next lower standard tier at runtime rather than forcing it or
falling straight back to 60.

Every profile also instructs the client to always prefer fresh frames over
stale buffered ones (prompt.md section 34) — this is what actually keeps
latency bounded regardless of resolution/FPS, and also means the app never
needs to duplicate a frame just to pad out to the selected FPS; see
utils/latest_value_box.py.
"""

from dataclasses import dataclass

from androidlink.device.display_info import FALLBACK_HZ, MAX_STREAM_FPS


@dataclass(frozen=True)
class StreamingProfile:
    max_size: int
    max_fps: int
    video_bit_rate: int
    prefer_fresh_frames: bool = True


_PERFORMANCE = StreamingProfile(max_size=1280, max_fps=FALLBACK_HZ, video_bit_rate=4_000_000)
_BALANCED = StreamingProfile(max_size=1920, max_fps=FALLBACK_HZ, video_bit_rate=12_000_000)
_QUALITY = StreamingProfile(max_size=2560, max_fps=FALLBACK_HZ, video_bit_rate=24_000_000)

# Common shorthand names for the three preset anchor points, used only to
# label the slider for the user (prompt.md section 6) -- purely cosmetic,
# doesn't affect what's actually requested from the device.
_RESOLUTION_LABELS = [
    (_PERFORMANCE.max_size, "720p"),
    (_BALANCED.max_size, "1080p"),
    (_QUALITY.max_size, "1440p"),
]


def _lerp(a: int, b: int, t: float) -> int:
    return round(a + (b - a) * t)


def describe_resolution(max_size: int) -> str:
    """Human-readable label for a StreamingProfile's max_size (scrcpy's
    long-edge cap -- see build_server_launch_args()'s `max_size` in
    protocol.py). Deliberately approximate ("~1080p") rather than a fake
    exact WxH: scrcpy scales so neither dimension exceeds max_size while
    preserving the device's real aspect ratio, which isn't known until a
    device is actually connected, so an exact pixel pair would overstate
    the precision this setting actually has (prompt.md section 34: report
    real behavior, not fabricated precision). The literal px value is shown
    alongside it for users who want the exact number scrcpy will receive.
    """
    nearest_label = min(_RESOLUTION_LABELS, key=lambda pair: abs(pair[0] - max_size))[1]
    return f"~{nearest_label} ({max_size}px)"


def resolve_streaming_profile(
    slider_value: int,
    *,
    max_size_override: int | None = None,
    max_fps_override: int | None = None,
    bitrate_override_mbps: float | None = None,
    automatic_fps: int = FALLBACK_HZ,
) -> StreamingProfile:
    """slider_value: 0 = full Performance, 100 = full Quality, 50 = Balanced.

    The overrides (prompt.md section 27's Streaming "Advanced options") are
    layered on top of the slider-derived profile rather than replacing it
    entirely -- any left as None still falls back to the slider's value, so
    setting just e.g. a bitrate override doesn't also freeze resolution/FPS.

    automatic_fps: what "Automatic" FPS resolves to when max_fps_override is
    None -- callers should pass the connected device's real detected refresh
    rate (device/display_info.py) here; the FALLBACK_HZ default only applies
    when no device is connected yet or detection genuinely failed.

    The resolved FPS -- whichever of the two sources above wins -- is always
    clamped to MAX_STREAM_FPS (165). This is the one place that cap is
    actually enforced, so a device/monitor reporting a rate above it (e.g. a
    240Hz panel) or a stale/manual override above it can never reach the
    encoder uncapped.
    """
    value = max(0, min(100, slider_value))

    if value <= 50:
        t = value / 50
        low, high = _PERFORMANCE, _BALANCED
    else:
        t = (value - 50) / 50
        low, high = _BALANCED, _QUALITY

    return StreamingProfile(
        max_size=max_size_override or _lerp(low.max_size, high.max_size, t),
        max_fps=min(max_fps_override or automatic_fps, MAX_STREAM_FPS),
        video_bit_rate=(
            round(bitrate_override_mbps * 1_000_000)
            if bitrate_override_mbps
            else _lerp(low.video_bit_rate, high.video_bit_rate, t)
        ),
    )
