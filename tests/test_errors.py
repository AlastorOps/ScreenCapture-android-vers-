"""utils/errors.py's catalog (prompt.md section 21): every entry must
explain both what's wrong and what to do about it -- never a bare "Error: x
failed" -- and callers combine the two via `.text`.
"""

from androidlink.utils import errors
from androidlink.utils.errors import AppError

_CONSTANT_ERRORS = [
    value
    for value in vars(errors).values()
    if isinstance(value, AppError)
]

_FACTORY_ERRORS = [
    errors.unsupported_video_codec("vp8"),
    errors.unsupported_audio_codec("mp3"),
    errors.encoder_failure("disk full"),
    errors.virtual_camera_unavailable("no backend"),
    errors.virtual_microphone_unavailable("no driver"),
    errors.screenshot_save_failed("C:/tmp/shot.png"),
]


def test_catalog_has_entries_for_every_prompt_md_section_21_scenario():
    keys = {e.key for e in _CONSTANT_ERRORS}
    expected = {
        "adb_unavailable",
        "usb_debugging_disabled",
        "device_unauthorized",
        "device_offline",
        "unsupported_android_version",
        "usb_bandwidth_problem",
        "companion_app_unavailable",
    }
    assert expected <= keys


def test_every_error_has_a_non_empty_message_and_guidance():
    for error in _CONSTANT_ERRORS + _FACTORY_ERRORS:
        assert error.message.strip()
        assert error.guidance.strip()


def test_text_combines_message_and_guidance():
    error = errors.DEVICE_UNAUTHORIZED
    assert error.message in error.text
    assert error.guidance in error.text
    assert error.text != error.message
    assert error.text != error.guidance


def test_companion_app_unavailable_says_no_companion_app_exists():
    text = errors.COMPANION_APP_UNAVAILABLE.text.lower()
    assert "no companion" in text or "not applicable" in text.split(".")[0].lower()
    assert "scrcpy" in text


def test_factory_errors_include_the_dynamic_detail():
    assert "vp8" in errors.unsupported_video_codec("vp8").text
    assert "mp3" in errors.unsupported_audio_codec("mp3").text
    assert "disk full" in errors.encoder_failure("disk full").text


def test_keys_are_unique():
    keys = [e.key for e in _CONSTANT_ERRORS]
    assert len(keys) == len(set(keys))
