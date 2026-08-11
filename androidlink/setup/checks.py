"""Setup checks (prompt.md section 18): pure-ish functions over
DeviceManager's live state plus a couple of safe environment probes. Kept
separate from the dialog (setup/wizard.py) so the check logic is testable
without constructing any Qt widgets.

Camera/Microphone permission cannot be checked proactively without either a
companion Android app or actually starting a mirroring session (there's no
ADB command that reports a shell process's runtime capture permissions
ahead of time) -- surfaced honestly as CheckStatus.INFO rather than a
fabricated pass/fail (prompt.md section 33/34).
"""

from dataclasses import dataclass
from enum import Enum

from androidlink.audio.virtual_audio import find_virtual_cable_output_device
from androidlink.camera.virtual_camera import detect_backend_available
from androidlink.device.device_model import AndroidDevice, ConnectionState
from androidlink.device.manager import DeviceManager


class CheckStatus(Enum):
    OK = "ok"
    WARNING = "warning"
    ERROR = "error"
    INFO = "info"  # can't be determined ahead of time; not a failure


@dataclass(frozen=True)
class SetupCheck:
    key: str
    label: str
    status: CheckStatus
    detail: str
    guidance: str | None = None  # what to do about it; only shown when not OK


def run_setup_checks(device_manager: DeviceManager) -> list[SetupCheck]:
    return [
        _check_adb(device_manager),
        _check_usb_device(device_manager),
        _check_usb_debugging(device_manager),
        _check_android_version(device_manager),
        _check_companion_app(),
        _check_camera_permission(),
        _check_microphone_permission(),
        _check_virtual_camera(),
        _check_virtual_microphone(),
    ]


def _check_adb(device_manager: DeviceManager) -> SetupCheck:
    if device_manager.adb_available:
        return SetupCheck("adb", "ADB installed", CheckStatus.OK, str(device_manager.adb_path))
    return SetupCheck(
        "adb",
        "ADB installed",
        CheckStatus.ERROR,
        "Not found on PATH or in common SDK locations",
        guidance="Install Android Platform Tools (adb), add it to your PATH, then click Recheck.",
    )


def _check_usb_device(device_manager: DeviceManager) -> SetupCheck:
    devices = device_manager.devices
    if devices:
        return SetupCheck(
            "usb_device", "USB device detected", CheckStatus.OK, f"{len(devices)} device(s) found"
        )
    if not device_manager.adb_available:
        return SetupCheck(
            "usb_device", "USB device detected", CheckStatus.WARNING, "Can't check without ADB"
        )
    return SetupCheck(
        "usb_device",
        "USB device detected",
        CheckStatus.WARNING,
        "No device detected",
        guidance="Plug in an Android phone over USB Type-C.",
    )


def _check_usb_debugging(device_manager: DeviceManager) -> SetupCheck:
    devices = device_manager.devices
    if not devices:
        return SetupCheck(
            "usb_debugging", "USB debugging enabled", CheckStatus.WARNING, "No device to check"
        )
    if any(d.connection_state == ConnectionState.DEVICE for d in devices):
        return SetupCheck(
            "usb_debugging", "USB debugging enabled", CheckStatus.OK, "Device authorized"
        )
    if any(d.connection_state == ConnectionState.UNAUTHORIZED for d in devices):
        return SetupCheck(
            "usb_debugging",
            "USB debugging enabled",
            CheckStatus.WARNING,
            "Device connected but not authorized",
            guidance='Unlock your phone and accept "Allow USB debugging?" when prompted.',
        )
    return SetupCheck(
        "usb_debugging",
        "USB debugging enabled",
        CheckStatus.WARNING,
        "Device offline",
        guidance="Try reconnecting the USB cable, or re-enable USB debugging in Developer Options.",
    )


def _find_first_authorized(device_manager: DeviceManager) -> AndroidDevice | None:
    if device_manager.active_device is not None:
        return device_manager.active_device
    return next(
        (d for d in device_manager.devices if d.connection_state == ConnectionState.DEVICE), None
    )


def _check_android_version(device_manager: DeviceManager) -> SetupCheck:
    device = _find_first_authorized(device_manager)
    if device is None:
        return SetupCheck("android_version", "Android version", CheckStatus.INFO, "Not detected yet")
    if device.android_version:
        return SetupCheck(
            "android_version",
            "Android version",
            CheckStatus.OK,
            f"Android {device.android_version} (API {device.api_level or '?'})",
        )
    return SetupCheck("android_version", "Android version", CheckStatus.INFO, "Still detecting…")


def _check_companion_app() -> SetupCheck:
    return SetupCheck(
        "companion_app",
        "Companion app",
        CheckStatus.OK,
        "Not required — AndroidLink drives scrcpy directly over ADB",
    )


def _check_camera_permission() -> SetupCheck:
    return SetupCheck(
        "camera_permission",
        "Camera permission",
        CheckStatus.INFO,
        "Requested automatically the first time you enable Camera",
    )


def _check_microphone_permission() -> SetupCheck:
    return SetupCheck(
        "microphone_permission",
        "Microphone permission",
        CheckStatus.INFO,
        "Requested automatically the first time you enable Mic",
    )


def _check_virtual_camera() -> SetupCheck:
    if detect_backend_available():
        return SetupCheck("virtual_camera", "Virtual webcam backend", CheckStatus.OK, "Found")
    return SetupCheck(
        "virtual_camera",
        "Virtual webcam backend",
        CheckStatus.WARNING,
        "Not found",
        guidance="Install OBS Studio or Unity Capture if you want to use the Camera feature.",
    )


def _check_virtual_microphone() -> SetupCheck:
    if find_virtual_cable_output_device() is not None:
        return SetupCheck("virtual_microphone", "Virtual microphone driver", CheckStatus.OK, "Found")
    return SetupCheck(
        "virtual_microphone",
        "Virtual microphone driver",
        CheckStatus.WARNING,
        "Not found",
        guidance="Install VB-Audio Virtual Cable (or VoiceMeeter) if you want to use the Mic feature.",
    )
