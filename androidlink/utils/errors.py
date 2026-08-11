"""User-facing error catalog (prompt.md section 21): every runtime failure
this app can surface explains what's wrong and what to do about it, never a
bare "Error: subprocess failed".

Mirrors setup/checks.py's SetupCheck shape (a short technical detail plus
separate actionable guidance) but for *reactive* failures raised while a
feature is running, rather than setup/checks.py's *proactive* first-launch
checks -- the two are deliberately kept separate rather than unified, since
they answer different questions ("is the environment ready?" vs. "why did
this just fail?") for different UI surfaces (the setup wizard vs. inline
panel/status messages).

Modules that raise or emit these (device/manager.py, streaming/transport.py,
camera/*, audio/*, recording/*) reference the catalog below instead of
inline string literals, so wording stays consistent and each failure mode is
documented in exactly one place. This is a refactor of previously-scattered
ad-hoc strings, not new error handling behavior -- every AppError here
already had an equivalent inline string somewhere before this catalog
existed, with two exceptions noted inline where a genuinely unhandled crash
(an uncaught exception escaping a Qt slot) was closed using the same
try/except pattern already used nearby for other malformed-stream cases.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AppError:
    key: str
    message: str  # plain-language explanation of what's wrong
    guidance: str  # what to do about it

    @property
    def text(self) -> str:
        """message + guidance combined into one string, for UI surfaces
        (a QLabel, a Signal(str)) that show a single block of text rather
        than two separate fields."""
        return f"{self.message} {self.guidance}"


# ---------------------------------------------------------------------------
# Device / ADB / USB (prompt.md section 21: device disconnected, ADB
# unavailable, USB debugging disabled, device unauthorized, device offline)
# ---------------------------------------------------------------------------

ADB_UNAVAILABLE = AppError(
    key="adb_unavailable",
    message="ADB was not found.",
    guidance=(
        "Install Android Platform Tools (adb) and make sure it's on your PATH, "
        "then reopen AndroidLink."
    ),
)

USB_DEBUGGING_DISABLED = AppError(
    key="usb_debugging_disabled",
    message="USB debugging is not enabled on this device.",
    guidance=(
        "On the phone, enable Developer Options and turn on USB debugging, "
        "then reconnect the USB cable."
    ),
)

DEVICE_UNAUTHORIZED = AppError(
    key="device_unauthorized",
    message="USB debugging authorization is required.",
    guidance='Unlock your Android phone and accept "Allow USB debugging?" when prompted.',
)

DEVICE_OFFLINE = AppError(
    key="device_offline",
    message="The device is offline.",
    guidance="Try reconnecting the USB cable, or re-enable USB debugging in Developer Options.",
)

DEVICE_DISCONNECTED = AppError(
    key="device_disconnected",
    message="The connection to the device was lost.",
    guidance="Check the USB cable and connection, then reconnect from the Device panel.",
)

UNSUPPORTED_ANDROID_VERSION = AppError(
    key="unsupported_android_version",
    message="This device's Android version is not supported.",
    guidance="AndroidLink requires Android 10 (API 29) or newer.",
)

USB_BANDWIDTH_PROBLEM = AppError(
    key="usb_bandwidth_problem",
    message="The USB connection can't keep up with the current stream settings.",
    guidance=(
        "Try a shorter/higher-quality USB cable, a direct port instead of a hub, "
        "or lowering the Performance/Quality slider."
    ),
)

COMPANION_APP_UNAVAILABLE = AppError(
    key="companion_app_unavailable",
    message="Not applicable.",
    guidance=(
        "AndroidLink has no companion Android app in its architecture -- it drives "
        "the vendored scrcpy-server directly over ADB, so there is nothing to "
        "install or connect to on the device beyond USB debugging itself."
    ),
)

# scrcpy-server session lifecycle -- shared wording across screen casting,
# camera mirroring, and microphone capture (streaming/transport.py,
# camera/camera_session.py, camera/camera_manager.py, audio/mic_session.py),
# each of which drives its own independent scrcpy-server session.
SERVER_PUSH_FAILED = AppError(
    key="server_push_failed",
    message="Could not install the mirroring helper (scrcpy-server) on the device.",
    guidance="Reconnect the USB cable and make sure USB debugging is still authorized, then try again.",
)

REVERSE_TUNNEL_FAILED = AppError(
    key="reverse_tunnel_failed",
    message="Could not set up the ADB connection tunnel.",
    guidance=(
        "Reconnect the USB cable and try again; if it keeps failing, run "
        "`adb kill-server` and reopen AndroidLink."
    ),
)

SERVER_LAUNCH_FAILED = AppError(
    key="server_launch_failed",
    message="Could not start the mirroring helper on the device.",
    guidance="Try again, or check Open Logs for details if this keeps happening.",
)

CORRUPT_STREAM_DATA = AppError(
    key="corrupt_stream_data",
    message="Received corrupted data from the device.",
    guidance="This usually means an unstable USB connection; reconnect the cable and try again.",
)

QUERY_CAMERAS_FAILED = AppError(
    key="query_cameras_failed",
    message="Could not query the device's cameras.",
    guidance="Reconnect the USB cable and make sure USB debugging is still authorized, then try again.",
)

# ---------------------------------------------------------------------------
# Codecs / decoding (prompt.md section 21: unsupported codec, decoder
# failure, encoder failure)
# ---------------------------------------------------------------------------


def unsupported_video_codec(codec_name: str) -> AppError:
    return AppError(
        key="unsupported_video_codec",
        message=f'The device is using a video codec ("{codec_name}") this PC cannot decode.',
        guidance=(
            "This is a decoder limitation on this PC, not a device problem -- "
            "mirroring can't continue for this session."
        ),
    )


def unsupported_audio_codec(codec_name: str) -> AppError:
    return AppError(
        key="unsupported_audio_codec",
        message=f'The device is using an audio codec ("{codec_name}") this PC cannot decode.',
        guidance="This is a decoder limitation on this PC; audio will be unavailable for this session.",
    )


DECODER_UNAVAILABLE = AppError(
    key="decoder_unavailable",
    message="The video/audio decoder (PyAV/FFmpeg) is not installed.",
    guidance="Reinstall AndroidLink, or run `pip install av` in a development environment.",
)

ENCODER_UNAVAILABLE = AppError(
    key="encoder_unavailable",
    message="The recording encoder (PyAV/FFmpeg) is not installed.",
    guidance="Reinstall AndroidLink, or run `pip install av` in a development environment.",
)


def encoder_failure(detail: str) -> AppError:
    return AppError(
        key="encoder_failure",
        message="Could not start recording.",
        guidance=f"Check that the save location is writable and there's free disk space. ({detail})",
    )


# ---------------------------------------------------------------------------
# Camera / microphone permissions and virtual devices (prompt.md section 21:
# camera/microphone permission denied, virtual camera/microphone unavailable)
# ---------------------------------------------------------------------------

CAMERA_PERMISSION_DENIED = AppError(
    key="camera_permission_denied",
    message="Camera access was denied on the Android device.",
    guidance=(
        'On the phone, allow the camera permission when prompted (or enable it '
        "manually under Settings > Apps), then try again."
    ),
)

MICROPHONE_PERMISSION_DENIED = AppError(
    key="microphone_permission_denied",
    message="Microphone access was denied on the Android device.",
    guidance=(
        'On the phone, allow the microphone permission when prompted (or enable it '
        "manually under Settings > Apps), then try again."
    ),
)


def virtual_camera_unavailable(detail: str) -> AppError:
    return AppError(
        key="virtual_camera_unavailable",
        message="No Windows virtual camera backend was found.",
        guidance=f"Install OBS Studio or Unity Capture, then try again. ({detail})",
    )


def virtual_microphone_unavailable(detail: str) -> AppError:
    return AppError(
        key="virtual_microphone_unavailable",
        message="No virtual audio cable driver was found.",
        guidance=f"Install VB-Audio Virtual Cable (or VoiceMeeter), then try again. ({detail})",
    )


NO_AUDIO_OUTPUT_DEVICE = AppError(
    key="no_audio_output_device",
    message="No Windows audio output device is available.",
    guidance="Check Windows Sound settings for an enabled playback device, then try again.",
)

# ---------------------------------------------------------------------------
# PC-side recording (recording/recording_controller.py)
# ---------------------------------------------------------------------------

NO_ACTIVE_CAST_SESSION = AppError(
    key="no_active_cast_session",
    message="There's no active cast session to record.",
    guidance="Enable Screen Cast from the Device panel first, then start recording.",
)

NO_FRAME_TO_CAPTURE = AppError(
    key="no_frame_to_capture",
    message="No frame is available to screenshot yet.",
    guidance="Wait for the Android screen to appear, then try again.",
)


def screenshot_save_failed(path: str) -> AppError:
    return AppError(
        key="screenshot_save_failed",
        message=f"Could not save the screenshot to {path}.",
        guidance="Check that the save location is writable and there's free disk space.",
    )
