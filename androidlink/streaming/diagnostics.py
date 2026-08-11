"""Runtime performance stats for the Diagnostics readouts (prompt.md
section 20 and the "Critical Engineering Rule" in section 33/34: measure
actual performance, never claim fabricated numbers like "0 dropped
frames"). Every field here is a genuinely measured value -- see
streaming/transport.py's _emit_stats() for how each is computed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class DiagnosticsSample:
    stream_fps: float  # decoded frames in the last sampling window
    dropped_frames: int  # frames overwritten in the frame box before being rendered
    decode_latency_ms: float  # average time spent inside decoder.decode() this window
    bitrate_bps: float  # bytes actually received on the video socket this window, x8
    resolution: tuple[int, int] | None
    codec: str | None
