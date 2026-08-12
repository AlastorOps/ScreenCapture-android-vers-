"""parse_camera_static_info()/parse_device_rotation_degrees()/
compute_preview_rotation_degrees() are pure text parsing and arithmetic --
exercised directly here without any real ADB/device I/O (get_camera_static_
info()/get_device_rotation_degrees() just wrap the parsing with the QProcess
call, mirroring device/display_info.py's dumpsys-parsing tests)."""

from androidlink.camera.camera_orientation import (
    CameraStaticInfo,
    compute_preview_rotation_degrees,
    parse_camera_static_info,
    parse_device_rotation_degrees,
)

_SAMPLE_CAMERA_DUMP = """
Camera module HAL: Interface version: 0x100
Number of camera devices: 2

== Camera HAL device 0 static information ==
Camera 0 static information:
  Facing: back
  Orientation: 90
  Resource cost: 100
  Conflicting devices:

Camera 1 static information:
  Facing: front
  Orientation: 270
  Resource cost: 100
"""


def test_parses_static_info_for_matching_camera_id():
    assert parse_camera_static_info(_SAMPLE_CAMERA_DUMP, "0") == CameraStaticInfo(
        sensor_orientation_degrees=90, facing="back"
    )
    assert parse_camera_static_info(_SAMPLE_CAMERA_DUMP, "1") == CameraStaticInfo(
        sensor_orientation_degrees=270, facing="front"
    )


def test_returns_none_for_unknown_camera_id():
    assert parse_camera_static_info(_SAMPLE_CAMERA_DUMP, "5") is None


def test_returns_none_when_orientation_line_is_missing():
    output = "Camera 0 static information:\n  Facing: back\n"
    assert parse_camera_static_info(output, "0") is None


def test_returns_none_for_implausible_orientation_value():
    # Never fabricate/guess -- an unrecognized value (not a multiple of 90)
    # is treated the same as "not found" rather than applying a nonsense
    # rotation.
    output = "Camera 0 static information:\n  Orientation: 45\n"
    assert parse_camera_static_info(output, "0") is None


def test_returns_none_for_empty_output():
    assert parse_camera_static_info("", "0") is None


def test_handles_zero_degrees():
    output = "Camera 0 static information:\n  Facing: back\n  Orientation: 0\n"
    assert parse_camera_static_info(output, "0") == CameraStaticInfo(
        sensor_orientation_degrees=0, facing="back"
    )


def test_defaults_facing_to_back_when_facing_line_is_missing():
    # Facing isn't strictly required to determine "some rotation is needed"
    # -- only the sign of the correction, and back-facing is the more
    # common case -- so a dump missing that line still isn't fatal.
    output = "Camera 0 static information:\n  Orientation: 180\n"
    assert parse_camera_static_info(output, "0") == CameraStaticInfo(
        sensor_orientation_degrees=180, facing="back"
    )


def test_parse_device_rotation_prefers_surface_orientation_source():
    dumpsys_input = "SurfaceOrientation: 2\nOther: stuff\n"
    dumpsys_window = "mRotation=1\n"
    assert parse_device_rotation_degrees(dumpsys_input, dumpsys_window) == 180


def test_parse_device_rotation_falls_back_to_window_source():
    assert parse_device_rotation_degrees(None, "mRotation=3\n") == 270
    assert parse_device_rotation_degrees("no match here", "mRotation=3\n") == 270


def test_parse_device_rotation_returns_none_when_neither_source_matches():
    assert parse_device_rotation_degrees("nothing", "nothing either") is None
    assert parse_device_rotation_degrees(None, None) is None


def test_compute_preview_rotation_back_camera_matches_old_fixed_baseline():
    # device_rotation=0 (phone held in natural orientation) must reduce to
    # exactly the fixed sensor orientation, matching this module's
    # pre-live-tracking behavior for a back camera.
    info = CameraStaticInfo(sensor_orientation_degrees=90, facing="back")
    assert compute_preview_rotation_degrees(info, 0) == 90


def test_compute_preview_rotation_back_camera_tracks_device_rotation():
    info = CameraStaticInfo(sensor_orientation_degrees=90, facing="back")
    assert compute_preview_rotation_degrees(info, 90) == 0
    assert compute_preview_rotation_degrees(info, 270) == 180


def test_compute_preview_rotation_front_camera_adds_instead_of_subtracts():
    info = CameraStaticInfo(sensor_orientation_degrees=270, facing="front")
    assert compute_preview_rotation_degrees(info, 0) == 270
    assert compute_preview_rotation_degrees(info, 90) == 0
