"""Windows monitor refresh-rate detection (FPS Limit Update spec, Automatic
Mode: "Detect the Windows monitor refresh rate where possible").

Informational only -- deliberately does not clamp the streaming FPS target.
Every profile already prefers fresh frames over stale buffered ones
(streaming/performance.py, utils/latest_value_box.py), so requesting more
frames than the monitor can actually display costs a little extra encode/
decode/transport work but never duplicates or corrupts anything; clamping
the target to it would trade that small cost for strictly worse input
latency, which prompt.md section 5 prioritizes over image quality. Logged at
cast-session start purely as a diagnostic data point.
"""

from PySide6.QtGui import QGuiApplication


def get_primary_monitor_refresh_hz() -> int | None:
    """Real measured value from Qt's screen API, or None if unavailable
    (e.g. no QGuiApplication yet, or the platform doesn't report it) --
    never a guessed/fabricated number."""
    app = QGuiApplication.instance()
    if app is None:
        return None
    screen = app.primaryScreen()
    if screen is None:
        return None
    rate = screen.refreshRate()
    return round(rate) if rate > 0 else None
