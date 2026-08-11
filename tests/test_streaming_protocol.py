import struct

import pytest

from androidlink.streaming.protocol import (
    CONTROL_MSG_TYPE_INJECT_KEYCODE,
    CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT,
    CONTROL_MSG_TYPE_INJECT_TEXT,
    CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT,
    MOTION_EVENT_ACTION_DOWN,
    MOTION_EVENT_BUTTON_PRIMARY,
    PACKET_FLAG_KEY_FRAME,
    PACKET_FLAG_SESSION,
    POINTER_ID_MOUSE,
    AudioStreamUnavailable,
    FrameMeta,
    SessionMeta,
    AUDIO_SOURCE_MIC,
    MIC_AUDIO_SOURCES,
    build_camera_server_launch_args,
    build_list_cameras_args,
    build_mic_server_launch_args,
    build_server_launch_args,
    decode_audio_header,
    decode_codec_id,
    decode_device_name,
    device_socket_name,
    encode_key_event,
    encode_scroll_event,
    encode_text_event,
    encode_touch_event,
    format_scid,
    generate_scid,
    parse_packet_header,
)


def test_format_scid_is_8_lowercase_hex_digits():
    assert format_scid(0x1A) == "0000001a"
    assert format_scid(0xFFFFFFFF) == "ffffffff"


def test_device_socket_name():
    assert device_socket_name(0x1A) == "scrcpy_0000001a"


def test_generate_scid_is_nonzero_and_in_range():
    for _ in range(50):
        scid = generate_scid()
        assert 0 < scid <= 0x7FFFFFFF


def test_decode_device_name_strips_null_padding():
    raw = b"Galaxy S24" + b"\x00" * (64 - len(b"Galaxy S24"))
    assert decode_device_name(raw) == "Galaxy S24"


def test_decode_device_name_wrong_length_raises():
    with pytest.raises(ValueError):
        decode_device_name(b"too short")


def test_decode_codec_id_h264():
    assert decode_codec_id(b"h264") == "h264"


def test_decode_codec_id_unknown_raises():
    with pytest.raises(ValueError):
        decode_codec_id(b"xxxx")


def test_parse_packet_header_session_meta():
    flags = PACKET_FLAG_SESSION >> 32  # top bit set, as a 32-bit int
    header = struct.pack(">III", flags, 1080, 2400)

    meta = parse_packet_header(header)

    assert meta == SessionMeta(width=1080, height=2400, is_client_resize=False)


def test_parse_packet_header_session_meta_with_client_resize_flag():
    flags = (PACKET_FLAG_SESSION >> 32) | 1
    header = struct.pack(">III", flags, 720, 1600)

    meta = parse_packet_header(header)

    assert meta.is_client_resize is True


def test_parse_packet_header_key_frame():
    pts_and_flags = 123_456 | PACKET_FLAG_KEY_FRAME
    header = struct.pack(">QI", pts_and_flags, 4096)

    meta = parse_packet_header(header)

    assert meta == FrameMeta(packet_size=4096, pts_us=123_456, is_config=False, is_key_frame=True)


def test_parse_packet_header_non_key_frame():
    header = struct.pack(">QI", 999, 512)

    meta = parse_packet_header(header)

    assert meta == FrameMeta(packet_size=512, pts_us=999, is_config=False, is_key_frame=False)


def test_parse_packet_header_config_packet_has_no_pts():
    from androidlink.streaming.protocol import PACKET_FLAG_CONFIG

    header = struct.pack(">QI", PACKET_FLAG_CONFIG, 32)

    meta = parse_packet_header(header)

    assert meta == FrameMeta(packet_size=32, pts_us=None, is_config=True, is_key_frame=False)


def test_parse_packet_header_wrong_length_raises():
    with pytest.raises(ValueError):
        parse_packet_header(b"short")


def test_build_server_launch_args_control_disabled_by_default():
    args = build_server_launch_args(0x1A)
    assert "control=false" in args


def test_build_server_launch_args_control_enabled_omits_control_false():
    args = build_server_launch_args(0x1A, control=True)
    assert "control=false" not in args
    assert not any(a.startswith("control=") for a in args)


def test_encode_touch_event_byte_layout():
    data = encode_touch_event(
        MOTION_EVENT_ACTION_DOWN,
        100,
        200,
        1080,
        2400,
        pointer_id=POINTER_ID_MOUSE,
        pressure=1.0,
        action_button=MOTION_EVENT_BUTTON_PRIMARY,
        buttons=MOTION_EVENT_BUTTON_PRIMARY,
    )

    assert len(data) == 32
    assert data[0] == CONTROL_MSG_TYPE_INJECT_TOUCH_EVENT
    assert data[1] == MOTION_EVENT_ACTION_DOWN
    pointer_id, x, y, w, h, pressure_fp, action_button, buttons = struct.unpack(
        ">QiiHHHII", data[2:]
    )
    assert pointer_id == POINTER_ID_MOUSE
    assert (x, y, w, h) == (100, 200, 1080, 2400)
    assert pressure_fp == 0xFFFF  # 1.0 clamped, per sc_float_to_u16fp
    assert action_button == MOTION_EVENT_BUTTON_PRIMARY
    assert buttons == MOTION_EVENT_BUTTON_PRIMARY


def test_encode_touch_event_pressure_zero():
    data = encode_touch_event(MOTION_EVENT_ACTION_DOWN, 0, 0, 100, 100, pressure=0.0)
    pressure_fp = struct.unpack(">H", data[22:24])[0]
    assert pressure_fp == 0


def test_encode_scroll_event_byte_layout():
    data = encode_scroll_event(50, 60, 1080, 2400, hscroll=0.0, vscroll=16.0)

    assert len(data) == 21
    assert data[0] == CONTROL_MSG_TYPE_INJECT_SCROLL_EVENT
    x, y, w, h, hscroll_fp, vscroll_fp, buttons = struct.unpack(">iiHHhhI", data[1:])
    assert (x, y, w, h) == (50, 60, 1080, 2400)
    assert hscroll_fp == 0
    assert vscroll_fp == 0x7FFF  # vscroll=16 normalizes to 1.0 -> max positive fixed point
    assert buttons == 0


def test_encode_scroll_event_negative_direction():
    data = encode_scroll_event(0, 0, 100, 100, hscroll=-16.0, vscroll=0.0)
    hscroll_fp = struct.unpack(">h", data[13:15])[0]
    assert hscroll_fp < 0


def test_encode_key_event_byte_layout():
    data = encode_key_event(1, 66, repeat=0, metastate=0x02)  # AKEYCODE_ENTER, UP

    assert len(data) == 14
    assert data[0] == CONTROL_MSG_TYPE_INJECT_KEYCODE
    action, keycode, repeat, metastate = struct.unpack(">BIII", data[1:])
    assert action == 1
    assert keycode == 66
    assert repeat == 0
    assert metastate == 0x02


def test_encode_text_event_byte_layout():
    data = encode_text_event("hi")

    assert data[0] == CONTROL_MSG_TYPE_INJECT_TEXT
    (length,) = struct.unpack(">I", data[1:5])
    assert length == 2
    assert data[5:] == b"hi"


def test_encode_text_event_truncates_without_splitting_utf8():
    text = "é" * 200  # each 'é' is 2 UTF-8 bytes -> 400 bytes, over the 300 limit
    data = encode_text_event(text)

    (length,) = struct.unpack(">I", data[1:5])
    payload = data[5:]
    assert length == len(payload)
    assert length <= 300
    # Must decode cleanly (no truncated multi-byte sequence at the end)
    payload.decode("utf-8")


def test_encode_text_event_does_not_over_truncate_when_boundary_already_clean():
    # 150 'é' characters = exactly 300 bytes, with byte 299 (the last byte of
    # the slice) being a *complete* character's continuation byte, not a
    # truncated one -> nothing should be trimmed away.
    text = "é" * 150
    data = encode_text_event(text)

    (length,) = struct.unpack(">I", data[1:5])
    assert length == 300
    assert data[5:] == text.encode("utf-8")


def test_build_server_launch_args_audio_disabled_by_default():
    args = build_server_launch_args(0x1A)
    assert "audio=false" in args


def test_build_server_launch_args_audio_enabled_omits_audio_false():
    args = build_server_launch_args(0x1A, audio=True)
    assert not any(a.startswith("audio=") for a in args)


def test_decode_audio_header_opus():
    assert decode_audio_header(b"opus") == "opus"


def test_decode_audio_header_aac():
    assert decode_audio_header(b"\x00aac") == "aac"


def test_decode_audio_header_disabled_sentinel():
    result = decode_audio_header(b"\x00\x00\x00\x00")
    assert result == AudioStreamUnavailable(is_error=False)


def test_decode_audio_header_config_error_sentinel():
    result = decode_audio_header(b"\x00\x00\x00\x01")
    assert result == AudioStreamUnavailable(is_error=True)


def test_decode_audio_header_unknown_raises():
    with pytest.raises(ValueError):
        decode_audio_header(b"xxxx")


def test_decode_audio_header_wrong_length_raises():
    with pytest.raises(ValueError):
        decode_audio_header(b"abc")


def test_build_camera_server_launch_args_sets_video_source_camera():
    args = build_camera_server_launch_args(0x1A)
    assert "video_source=camera" in args
    assert "audio=false" in args
    assert "control=false" in args


def test_build_camera_server_launch_args_includes_optional_params():
    args = build_camera_server_launch_args(
        0x1A, camera_id="1", camera_size="1920x1080", camera_facing="front", camera_fps=30
    )
    assert "camera_id=1" in args
    assert "camera_size=1920x1080" in args
    assert "camera_facing=front" in args
    assert "camera_fps=30" in args


def test_build_camera_server_launch_args_omits_unset_optional_params():
    args = build_camera_server_launch_args(0x1A)
    assert not any(a.startswith("camera_") for a in args)


def test_build_list_cameras_args():
    args = build_list_cameras_args(0x1A)
    assert "list_cameras=true" in args


def test_build_mic_server_launch_args_disables_video_and_control():
    args = build_mic_server_launch_args(0x1A)
    assert "video=false" in args
    assert "audio=true" in args
    assert "control=false" in args
    assert f"audio_source={AUDIO_SOURCE_MIC}" in args


def test_build_mic_server_launch_args_uses_given_source():
    args = build_mic_server_launch_args(0x1A, audio_source="mic-unprocessed")
    assert "audio_source=mic-unprocessed" in args


def test_mic_audio_sources_are_all_distinct_mic_prefixed_values():
    assert len(MIC_AUDIO_SOURCES) == len(set(MIC_AUDIO_SOURCES))
    assert all(source.startswith("mic") for source in MIC_AUDIO_SOURCES)
