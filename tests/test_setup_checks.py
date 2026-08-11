"""run_setup_checks() against a real DeviceManager instance (white-box:
directly setting its private device/adb state, the same way other tests in
this suite drive transport/session state machines) plus the two
environment probes, which genuinely run for real on this machine (no
virtual-cable/virtual-cam backend installed here, confirmed elsewhere in
this suite).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

from androidlink.device.device_model import AndroidDevice, ConnectionState
from androidlink.device.manager import DeviceManager
from androidlink.setup.checks import CheckStatus, run_setup_checks


def _checks_by_key(device_manager: DeviceManager) -> dict:
    return {check.key: check for check in run_setup_checks(device_manager)}


def test_adb_missing_reports_error(qapp):
    device_manager = DeviceManager()
    checks = _checks_by_key(device_manager)
    assert checks["adb"].status == CheckStatus.ERROR
    assert checks["adb"].guidance is not None


def test_adb_available_but_no_device_reports_warning(qapp):
    device_manager = DeviceManager()
    device_manager._adb_available = True
    device_manager._adb_path = Path("adb")

    checks = _checks_by_key(device_manager)
    assert checks["adb"].status == CheckStatus.OK
    assert checks["usb_device"].status == CheckStatus.WARNING
    assert checks["usb_debugging"].status == CheckStatus.WARNING


def test_unauthorized_device_reports_specific_guidance(qapp):
    device_manager = DeviceManager()
    device_manager._adb_available = True
    device_manager._adb_path = Path("adb")
    device_manager._devices = {
        "SERIAL1": AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.UNAUTHORIZED)
    }

    checks = _checks_by_key(device_manager)
    assert checks["usb_device"].status == CheckStatus.OK
    assert checks["usb_debugging"].status == CheckStatus.WARNING
    assert "authorized" in checks["usb_debugging"].detail.lower()
    assert "allow usb debugging" in checks["usb_debugging"].guidance.lower()


def test_authorized_device_with_version_reports_ok(qapp):
    device_manager = DeviceManager()
    device_manager._adb_available = True
    device_manager._adb_path = Path("adb")
    device_manager._devices = {
        "SERIAL1": AndroidDevice(
            serial="SERIAL1",
            connection_state=ConnectionState.DEVICE,
            android_version="14",
            api_level=34,
        )
    }

    checks = _checks_by_key(device_manager)
    assert checks["usb_debugging"].status == CheckStatus.OK
    assert checks["android_version"].status == CheckStatus.OK
    assert "14" in checks["android_version"].detail


def test_android_version_unknown_is_info_not_a_failure(qapp):
    device_manager = DeviceManager()
    device_manager._adb_available = True
    device_manager._adb_path = Path("adb")
    device_manager._devices = {
        "SERIAL1": AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE)
    }

    checks = _checks_by_key(device_manager)
    assert checks["android_version"].status == CheckStatus.INFO


def test_permission_checks_are_always_info_never_fabricated_pass_or_fail(qapp):
    device_manager = DeviceManager()
    checks = _checks_by_key(device_manager)
    assert checks["camera_permission"].status == CheckStatus.INFO
    assert checks["microphone_permission"].status == CheckStatus.INFO


def test_companion_app_check_reflects_actual_architecture(qapp):
    """This project doesn't build/require a companion Android app (it
    drives scrcpy directly) -- the check must say so honestly rather than
    reporting a fabricated pass for something that doesn't exist."""
    device_manager = DeviceManager()
    checks = _checks_by_key(device_manager)
    assert checks["companion_app"].status == CheckStatus.OK


def test_virtual_backend_checks_reflect_real_machine_state(qapp):
    """This dev machine has neither a virtual camera backend nor a virtual
    audio cable installed (verified directly elsewhere in this suite), so
    these should genuinely report WARNING, not a mocked value."""
    device_manager = DeviceManager()
    checks = _checks_by_key(device_manager)
    assert checks["virtual_camera"].status == CheckStatus.WARNING
    assert checks["virtual_microphone"].status == CheckStatus.WARNING
    assert checks["virtual_camera"].guidance is not None
    assert checks["virtual_microphone"].guidance is not None
