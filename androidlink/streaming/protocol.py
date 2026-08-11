"""scrcpy v4.1 device-side wire protocol (video, audio, control).

Derived from reading Genymobile/scrcpy v4.1 source directly (not from memory/
guesswork) to ensure byte-for-byte compatibility with the vendored server jar:
  - server/src/main/java/com/genymobile/scrcpy/device/DesktopConnection.java
  - server/src/main/java/com/genymobile/scrcpy/device/Streamer.java
  - server/src/main/java/com/genymobile/scrcpy/video/VideoCodec.java
  - server/src/main/java/com/genymobile/scrcpy/audio/AudioCodec.java, AudioConfig.java
  - app/src/server.c (host-side launch argument construction)
  - app/src/control_msg.c / control_msg.h (control message wire format)
  - app/src/util/binary.h (big-endian writes, u16/i16 fixed-point encoding)
  - app/src/android/input.h, app/src/android/keycodes.h (AOSP action/keycode
    constants, vendored verbatim by scrcpy)

Reverse tunnel mode (`adb reverse`) is used, matching scrcpy's USB default:
the device connects out to us, so no "dummy byte" handshake is needed (that
only applies to the `adb forward` fallback path).
"""

from __future__ import annotations

import secrets
import struct
from dataclasses import dataclass

SCRCPY_SERVER_VERSION = "4.1"
DEVICE_SERVER_PATH = "/data/local/tmp/scrcpy-server.jar"
SOCKET_NAME_PREFIX = "scrcpy"

DEVICE_NAME_FIELD_LENGTH = 64
PACKET_HEADER_LENGTH = 12

# Top 3 bits of the 64-bit ptsAndFlags header field (Streamer.java).
PACKET_FLAG_SESSION = 1 << 63
PACKET_FLAG_CONFIG = 1 << 62
PACKET_FLAG_KEY_FRAME = 1 << 61
_PTS_MASK = ~(PACKET_FLAG_SESSION | PACKET_FLAG_CONFIG | PACKET_FLAG_KEY_FRAME) & (
    (1 << 64) - 1
)

# 4-byte ASCII codec identifiers, big-endian (VideoCodec.java).
_CODEC_ID_TO_NAME = {
    0x68_32_36_34: "h264",
    0x68_32_36_35: "h265",
    0x00_61_76_31: "av1",
    0x00_76_70_38: "vp8",
    0x00_76_70_39: "vp9",
}


def generate_scid() -> int:
    """A random 31-bit id identifying this client session (avoids colliding
    with another concurrently running scrcpy/AndroidLink instance)."""
    return secrets.randbelow(0x7FFFFFFF) + 1


def format_scid(scid: int) -> str:
    return f"{scid:08x}"


def device_socket_name(scid: int) -> str:
    return f"{SOCKET_NAME_PREFIX}_{format_scid(scid)}"


def build_server_launch_args(
    scid: int,
    *,
    video_bit_rate: int | None = None,
    max_size: int | None = None,
    max_fps: int | None = None,
    control: bool = False,
    audio: bool = False,
    log_level: str = "info",
) -> list[str]:
    """Build the `key=value` argument list for launching scrcpy-server.

    Matches app/src/server.c's execute_server(), restricted to the options
    AndroidLink uses: video always on, audio/control optional. Both default
    to matching server.c's own defaults (true) unless explicitly disabled —
    server.c only ever writes "control=false"/"audio=false" when off.
    """
    args = [
        f"scid={format_scid(scid)}",
        f"log_level={log_level}",
    ]
    if not control:
        args.append("control=false")
    if not audio:
        args.append("audio=false")
    if video_bit_rate:
        args.append(f"video_bit_rate={video_bit_rate}")
    if max_size:
        args.append(f"max_size={max_size}")
    if max_fps:
        args.append(f"max_fps={max_fps}")
    return args


def build_camera_server_launch_args(
    scid: int,
    *,
    camera_id: str | None = None,
    camera_size: str | None = None,
    camera_facing: str | None = None,
    camera_fps: int | None = None,
    video_bit_rate: int | None = None,
    log_level: str = "info",
) -> list[str]:
    """Launch args for a camera-mirroring session (prompt.md section 11) —
    a separate scrcpy-server session from screen casting: video_source=camera
    instead of the default "display", no audio/control at all.
    """
    args = [
        f"scid={format_scid(scid)}",
        f"log_level={log_level}",
        "video_source=camera",
        "audio=false",
        "control=false",
    ]
    if camera_id:
        args.append(f"camera_id={camera_id}")
    if camera_size:
        args.append(f"camera_size={camera_size}")
    if camera_facing:
        args.append(f"camera_facing={camera_facing}")
    if camera_fps:
        args.append(f"camera_fps={camera_fps}")
    if video_bit_rate:
        args.append(f"video_bit_rate={video_bit_rate}")
    return args


def build_list_cameras_args(scid: int, *, log_level: str = "info") -> list[str]:
    """Launch args that make scrcpy-server print camera capabilities to
    stdout and exit immediately, without opening any socket connection at
    all (Options.java: getList() is true whenever list_cameras is true)."""
    return [
        f"scid={format_scid(scid)}",
        f"log_level={log_level}",
        "list_cameras=true",
    ]


# audio_source command-line names (device/AudioSource.java's findByName()),
# confirmed against scrcpy v4.1 source directly. Restricted here to the
# device-microphone-capture sources relevant to prompt.md section 12 --
# excludes OUTPUT/PLAYBACK (device audio output, Phase 5's audio_source
# default) and the VOICE_CALL* sources (require an active phone call).
AUDIO_SOURCE_MIC = "mic"
AUDIO_SOURCE_MIC_UNPROCESSED = "mic-unprocessed"
AUDIO_SOURCE_MIC_CAMCORDER = "mic-camcorder"
AUDIO_SOURCE_MIC_VOICE_RECOGNITION = "mic-voice-recognition"
AUDIO_SOURCE_MIC_VOICE_COMMUNICATION = "mic-voice-communication"

# Not per-device "detected" sources -- scrcpy has no query for this and no
# companion app exists (yet) to ask Android's AudioManager directly. This is
# the protocol-level list scrcpy itself accepts, offered honestly as that
# rather than faking per-device capability detection (prompt.md section 37).
MIC_AUDIO_SOURCES = [
    AUDIO_SOURCE_MIC,
    AUDIO_SOURCE_MIC_UNPROCESSED,
    AUDIO_SOURCE_MIC_CAMCORDER,
    AUDIO_SOURCE_MIC_VOICE_RECOGNITION,
    AUDIO_SOURCE_MIC_VOICE_COMMUNICATION,
]


def build_mic_server_launch_args(
    scid: int,
    *,
    audio_source: str = AUDIO_SOURCE_MIC,
    log_level: str = "info",
) -> list[str]:
    """Launch args for a microphone-mirroring session (prompt.md section
    12): a separate scrcpy-server session from screen casting/camera, video
    disabled entirely (Options.java's "video" defaults true, so it must be
    explicitly turned off) with audio_source set to a MIC_AUDIO_SOURCES
    value instead of the default "output" device-audio source.

    Per DesktopConnection.java's getFirstSocket(), when video is disabled
    the audio socket becomes the *first* socket opened and therefore
    receives the 64-byte device-name field that normally goes to the video
    socket -- unlike Phase 5's shared session, where video claims that role.
    """
    return [
        f"scid={format_scid(scid)}",
        f"log_level={log_level}",
        "video=false",
        "audio=true",
        "control=false",
        f"audio_source={audio_source}",
    ]


def decode_device_name(raw: bytes) -> str:
    if len(raw) != DEVICE_NAME_FIELD_LENGTH:
        raise ValueError(f"expected {DEVICE_NAME_FIELD_LENGTH} bytes, got {len(raw)}")
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def decode_codec_id(raw: bytes) -> str:
    if len(raw) != 4:
        raise ValueError(f"expected 4 bytes, got {len(raw)}")
    (codec_id,) = struct.unpack(">I", raw)
    name = _CODEC_ID_TO_NAME.get(codec_id)
    if name is None:
        raise ValueError(f"unknown codec id 0x{codec_id:08x}")
    return name


# 4-byte ASCII audio codec identifiers, big-endian (AudioCodec.java).
_AUDIO_CODEC_ID_TO_NAME = {
    0x6F_70_75_73: "opus",
    0x00_61_61_63: "aac",
    0x66_6C_61_63: "flac",
    0x00_72_61_77: "raw",
}

AUDIO_SAMPLE_RATE = 48000
AUDIO_CHANNELS = 2

# Streamer.java writeDisableStream(): in place of a real codec id header, the
# device may send one of these two sentinel values if audio capture failed.
_AUDIO_DISABLE_CODE = 0x00000000  # capture failed; continue mirroring video-only
_AUDIO_CONFIG_ERROR_CODE = 0x00000001  # configuration error; mirroring should stop


@dataclass(frozen=True)
class AudioStreamUnavailable:
    is_error: bool  # True: device-side config error. False: capture just isn't available.


def decode_audio_header(raw: bytes) -> str | AudioStreamUnavailable:
    """Parse the audio socket's first 4 bytes: either a real codec id, or one
    of the disable sentinels Streamer.writeDisableStream() sends when the
    device couldn't start audio capture at all (see prompt.md section 10:
    detect capability, never silently fail)."""
    if len(raw) != 4:
        raise ValueError(f"expected 4 bytes, got {len(raw)}")
    (value,) = struct.unpack(">I", raw)

    if value == _AUDIO_DISABLE_CODE:
        return AudioStreamUnavailable(is_error=False)
    if value == _AUDIO_CONFIG_ERROR_CODE:
        return AudioStreamUnavailable(is_error=True)

    name = _AUDIO_CODEC_ID_TO_NAME.get(value)
    if name is None:
        raise ValueError(f"unknown audio codec id 0x{value:08x}")
    return name


@dataclass(frozen=True)
class SessionMeta:
    width: int
    height: int
    is_client_resize: bool


@dataclass(frozen=True)
class FrameMeta:
    packet_size: int
    pts_us: int | None  # None for config packets (SPS/PPS), which have no PTS
    is_config: bool
    is_key_frame: bool


def parse_packet_header(raw: bytes) -> SessionMeta | FrameMeta:
    """Parse a 12-byte packet header from the video socket.

    Both session-meta and frame-meta packets are 12 bytes but laid out
    differently (Streamer.java writeSessionMeta / writeFrameMeta share one
    ByteBuffer). They're disambiguated by the top bit of the first 8 bytes
    interpreted as a big-endian uint64: if PACKET_FLAG_SESSION is set, the
    header is actually [flags:4][width:4][height:4] with no packet payload
    following; otherwise it's [ptsAndFlags:8][packet_size:4] followed by
    that many bytes of Annex-B video payload.
    """
    if len(raw) != PACKET_HEADER_LENGTH:
        raise ValueError(f"expected {PACKET_HEADER_LENGTH} bytes, got {len(raw)}")

    (pts_and_flags,) = struct.unpack(">Q", raw[:8])

    if pts_and_flags & PACKET_FLAG_SESSION:
        flags, width, height = struct.unpack(">III", raw)
        return SessionMeta(width=width, height=height, is_client_resize=bool(flags & 1))

    (packet_size,) = struct.unpack(">I", raw[8:12])
    is_config = bool(pts_and_flags & PACKET_FLAG_CONFIG)
    is_key_frame = bool(pts_and_flags & PACKET_FLAG_KEY_FRAME)
    pts_us = None if is_config else (pts_and_flags & _PTS_MASK)

    return FrameMeta(
        packet_size=packet_size,
        pts_us=pts_us,
        is_config=is_config,
        is_key_frame=is_key_frame,
    )


# ---------------------------------------------------------------------------
# Control messages (client -> device, control_msg.c's sc_control_msg_serialize)
# ---------------------------------------------------------------------------

CONTROL_MSG_TYPE_INJECT_KEYCODE = 0
CONTROL_MSG_TYPE_INJECT_TEXT = 1
CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT = 2
CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT = 3
CONTROL_MSG_TYPE_BACK_OR_SCREEN_ON = 4

INJECT_TEXT_MAX_LENGTH = 300

# android/input.h
MOTION_EVENT_ACTION_DOWN = 0
MOTION_EVENT_ACTION_UP = 1
MOTION_EVENT_ACTION_MOVE = 2
MOTION_EVENT_ACTION_CANCEL = 3

KEY_EVENT_ACTION_DOWN = 0
KEY_EVENT_ACTION_UP = 1

MOTION_EVENT_BUTTON_PRIMARY = 1 << 0
MOTION_EVENT_BUTTON_SECONDARY = 1 << 1
MOTION_EVENT_BUTTON_TERTIARY = 1 << 2

# control_msg.h: SC_POINTER_ID_MOUSE = UINT64_C(-1)
POINTER_ID_MOUSE = (1 << 64) - 1


def _float_to_u16fp(value: float) -> int:
    """0.0-1.0 -> unsigned 16-bit fixed point (util/binary.h sc_float_to_u16fp)."""
    value = max(0.0, min(1.0, value))
    fixed = int(value * 0x10000)
    return min(fixed, 0xFFFF)


def _float_to_i16fp(value: float) -> int:
    """-1.0-1.0 -> signed 16-bit fixed point (util/binary.h sc_float_to_i16fp)."""
    value = max(-1.0, min(1.0, value))
    fixed = int(value * 0x8000)
    return min(fixed, 0x7FFF)


def _pack_position(x: int, y: int, screen_width: int, screen_height: int) -> bytes:
    return struct.pack(">iiHH", x, y, screen_width, screen_height)


def encode_touch_event(
    action: int,
    x: int,
    y: int,
    screen_width: int,
    screen_height: int,
    *,
    pointer_id: int = POINTER_ID_MOUSE,
    pressure: float = 1.0,
    action_button: int = 0,
    buttons: int = 0,
) -> bytes:
    """SC_CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT, 32 bytes total.

    screen_width/screen_height must be the video frame size reported by the
    most recent SessionMeta (not the physical device resolution) — the
    device scales from that size to its real screen internally.
    """
    buf = bytearray()
    buf.append(CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT)
    buf.append(action)
    buf += struct.pack(">Q", pointer_id)
    buf += _pack_position(x, y, screen_width, screen_height)
    buf += struct.pack(">H", _float_to_u16fp(pressure))
    buf += struct.pack(">I", action_button)
    buf += struct.pack(">I", buttons)
    assert len(buf) == 32
    return bytes(buf)


def encode_scroll_event(
    x: int,
    y: int,
    screen_width: int,
    screen_height: int,
    hscroll: float,
    vscroll: float,
    *,
    buttons: int = 0,
) -> bytes:
    """SC_CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT, 21 bytes total.

    hscroll/vscroll are accepted in [-16, 16] "wheel notches" (matching
    scrcpy's own client range) and normalized to [-1, 1] before encoding.
    """
    buf = bytearray()
    buf.append(CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT)
    buf += _pack_position(x, y, screen_width, screen_height)
    buf += struct.pack(">h", _float_to_i16fp(hscroll / 16))
    buf += struct.pack(">h", _float_to_i16fp(vscroll / 16))
    buf += struct.pack(">I", buttons)
    assert len(buf) == 21
    return bytes(buf)


def encode_key_event(action: int, keycode: int, *, repeat: int = 0, metastate: int = 0) -> bytes:
    """SC_CONTROL_MSG_TYPE_INJECT_KEYCODE, 14 bytes total."""
    buf = bytearray()
    buf.append(CONTROL_MSG_TYPE_INJECT_KEYCODE)
    buf.append(action)
    buf += struct.pack(">I", keycode)
    buf += struct.pack(">I", repeat)
    buf += struct.pack(">I", metastate)
    assert len(buf) == 14
    return bytes(buf)


def _utf8_truncation_index(data: bytes, max_len: int) -> int:
    """Port of scrcpy's util/str.c sc_str_utf8_truncation_index: the largest
    cut point <= max_len that doesn't split a multi-byte UTF-8 sequence."""
    if len(data) <= max_len:
        return len(data)
    length = max_len
    while length > 0 and (data[length] & 0x80) != 0 and (data[length] & 0xC0) != 0xC0:
        # data[length] is a continuation byte: cutting here would split a
        # codepoint, so back off until we land on a boundary.
        length -= 1
    return length


def encode_text_event(text: str) -> bytes:
    """SC_CONTROL_MSG_TYPE_INJECT_TEXT: type(1) + length(4 BE) + utf-8 bytes.

    Truncates to INJECT_TEXT_MAX_LENGTH *bytes* (not characters) without
    splitting a multi-byte UTF-8 sequence.
    """
    encoded = text.encode("utf-8")
    truncation_index = _utf8_truncation_index(encoded, INJECT_TEXT_MAX_LENGTH)
    encoded = encoded[:truncation_index]

    buf = bytearray()
    buf.append(CONTROL_MSG_TYPE_INJECT_TEXT)
    buf += struct.pack(">I", len(encoded))
    buf += encoded
    return bytes(buf)
