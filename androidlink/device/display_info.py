"""Detects the Android device's real display refresh rate via `adb shell
dumpsys display`, so the app can offer/target FPS values the device's own
panel actually supports instead of an arbitrary hardcoded cap (see
streaming/performance.py).

There is no dedicated scrcpy/ADB API for "what refresh rates does this
screen support" -- dumpsys display is the same source scrcpy's own Android-
side code and every other screen-mirroring tool ultimately reads from.
Verified directly against a real device (Lenovo TB321FU, a 165Hz-capable
panel) rather than guessing at the output format from documentation:

    mActiveSfDisplayMode=DisplayMode{id=0, width=1600, height=2560,
        xDpi=344.406, yDpi=342.231, peakRefreshRate=120.00001, ...}
    mSupportedRefreshRates=[120.00001, 165.0, 144.00002, 90.0,
        60.000004, 30.000002]

Real devices report refresh rates as slightly-off floats (e.g. 59.998,
120.00001) rather than clean integers -- rounded to the nearest "marketed"
rate below so the UI shows "120Hz" rather than a confusing "120.00001Hz".
OEM `dumpsys display` output isn't guaranteed identical across Android
versions/vendors; if these fields aren't found, parse_dumpsys_display()
returns None rather than fabricating a number (prompt.md: never invent a
performance/capability value that wasn't actually measured) -- callers must
treat that as "unknown" and fall back to a conservative default.
"""

import re
from dataclasses import dataclass

_ACTIVE_MODE_RE = re.compile(r"mActiveSfDisplayMode=DisplayMode\{[^}]*?peakRefreshRate=([\d.]+)")
_SUPPORTED_RATES_RE = re.compile(r"mSupportedRefreshRates=\[([^\]]*)\]")

# "Marketed" rates real panels are rounded to for display purposes -- an
# OEM-reported 119.98 or 60.0003 is shown as "120Hz"/"60Hz", not a raw float.
STANDARD_RATES_HZ = (24, 25, 30, 48, 50, 60, 90, 120, 144, 165, 240)

FALLBACK_HZ = 60  # used only when detection genuinely fails -- see performance.py


def _round_to_standard(value: float) -> int:
    return min(STANDARD_RATES_HZ, key=lambda rate: abs(rate - value))


@dataclass(frozen=True)
class DisplayRefreshInfo:
    active_hz: int
    supported_hz: tuple[int, ...]  # sorted ascending, deduped, always includes active_hz


def parse_dumpsys_display(output: str) -> DisplayRefreshInfo | None:
    active_match = _ACTIVE_MODE_RE.search(output)
    supported_match = _SUPPORTED_RATES_RE.search(output)
    if active_match is None or supported_match is None:
        return None

    active_hz = _round_to_standard(float(active_match.group(1)))

    supported = {
        _round_to_standard(float(token))
        for token in supported_match.group(1).split(",")
        if token.strip()
    }
    supported.add(active_hz)

    return DisplayRefreshInfo(active_hz=active_hz, supported_hz=tuple(sorted(supported)))
