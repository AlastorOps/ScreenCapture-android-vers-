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
    hardware_decode: bool | None = None  # None until a decoder exists for this session
    #: Frames whose wire PTS gap from the previous frame was well beyond
    #: what the current target FPS would predict -- a genuine encoder/
    #: transport-side delivery gap, derived from real frame timestamps
    #: (streaming/protocol.py's FrameMeta.pts_us), not from PC-side receive
    #: jitter. Distinct from dropped_frames (a *consumer*-side measurement:
    #: frames that arrived fine but were overwritten before the renderer
    #: took them) -- see transport.py's _record_frame_timing().
    late_frames: int = 0
