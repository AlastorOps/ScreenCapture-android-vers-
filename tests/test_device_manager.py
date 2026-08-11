"""Regression tests for a real bug found via extended live testing against
real hardware: `_on_devices_result`/`_on_device_info_result` could crash with
a shiboken "Internal C++ object already deleted" RuntimeError (a known
PySide6/Qt race on Windows when adb has to bootstrap its background daemon
mid-poll), and -- worse -- `_fetch_device_info` had no guard against
re-spawning an `adb shell getprop` call for the same device on every single
1.5s poll tick when the previous one never set device.model. Under sustained
real usage this measurably destabilized the local adb server (observed:
adb devices going empty despite the device staying physically connected),
which drops any `adb reverse` tunnels active scrcpy-server sessions depend
on -- surfacing as unexplained video/audio/camera socket disconnects.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path

import shiboken6
from PySide6.QtCore import QProcess

from androidlink.device.device_model import AndroidDevice, ConnectionState
from androidlink.device.manager import DeviceManager


def _deleted_process(qapp) -> QProcess:
    """A QProcess whose underlying C++ object has already been destroyed --
    reproduces the exact race real adb invocations hit intermittently,
    without depending on actual process/timing flakiness."""
    process = QProcess()
    shiboken6.delete(process)
    return process


def test_on_devices_result_survives_an_already_deleted_process(qapp):
    manager = DeviceManager()
    manager._devices_refresh_in_flight = True

    manager._on_devices_result(_deleted_process(qapp))  # must not raise

    assert manager._devices_refresh_in_flight is False


def test_on_device_info_result_survives_an_already_deleted_process(qapp):
    manager = DeviceManager()
    manager._devices = {"SERIAL1": AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE)}
    manager._info_fetch_in_flight = {"SERIAL1"}

    manager._on_device_info_result("SERIAL1", _deleted_process(qapp))  # must not raise

    assert "SERIAL1" not in manager._info_fetch_in_flight


def test_fetch_device_info_does_not_duplicate_an_in_flight_request(qapp, monkeypatch):
    manager = DeviceManager()
    manager._adb_path = Path("adb")

    start_calls = []
    monkeypatch.setattr(QProcess, "start", lambda self, *a, **k: start_calls.append(a))

    manager._fetch_device_info("SERIAL1")
    manager._fetch_device_info("SERIAL1")  # same serial, still in flight -- must be a no-op

    assert len(start_calls) == 1
    assert manager._info_fetch_in_flight == {"SERIAL1"}


def test_fetch_device_info_can_be_retried_after_the_first_attempt_completes(qapp, monkeypatch):
    manager = DeviceManager()
    manager._adb_path = Path("adb")

    start_calls = []
    monkeypatch.setattr(QProcess, "start", lambda self, *a, **k: start_calls.append(a))

    manager._fetch_device_info("SERIAL1")
    manager._on_device_info_result("SERIAL1", _deleted_process(qapp))  # clears the in-flight marker
    manager._fetch_device_info("SERIAL1")

    assert len(start_calls) == 2


def test_on_display_info_result_survives_an_already_deleted_process(qapp):
    manager = DeviceManager()
    manager._devices = {"SERIAL1": AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE)}
    manager._display_fetch_in_flight = {"SERIAL1"}

    manager._on_display_info_result("SERIAL1", _deleted_process(qapp))  # must not raise

    assert "SERIAL1" not in manager._display_fetch_in_flight
    assert "SERIAL1" in manager._display_fetch_attempted


def test_fetch_display_info_does_not_duplicate_an_in_flight_request(qapp, monkeypatch):
    manager = DeviceManager()
    manager._adb_path = Path("adb")

    start_calls = []
    monkeypatch.setattr(QProcess, "start", lambda self, *a, **k: start_calls.append(a))

    manager._fetch_display_info("SERIAL1")
    manager._fetch_display_info("SERIAL1")

    assert len(start_calls) == 1


def test_on_devices_result_does_not_retry_display_info_after_a_failed_parse(qapp, monkeypatch):
    """A dumpsys display format this app's parser doesn't recognize (e.g. an
    unfamiliar OEM layout) must not be re-fetched on every 1.5s poll forever
    -- see manager.py's _display_fetch_attempted docstring for why that
    class of bug previously destabilized the local adb server."""
    import androidlink.device.manager as manager_module
    from androidlink.device.adb import RawDeviceEntry

    manager = DeviceManager()
    manager._devices = {"SERIAL1": AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE)}
    manager._display_fetch_attempted = {"SERIAL1"}
    monkeypatch.setattr(
        manager_module, "parse_devices_output", lambda _output: [RawDeviceEntry("SERIAL1", "device")]
    )

    fetch_calls = []
    monkeypatch.setattr(manager, "_fetch_display_info", lambda serial: fetch_calls.append(serial))

    manager._on_devices_result(QProcess())

    assert fetch_calls == []


def test_on_devices_result_does_not_refetch_info_for_a_serial_already_in_flight(qapp, monkeypatch):
    import androidlink.device.manager as manager_module
    from androidlink.device.adb import RawDeviceEntry

    manager = DeviceManager()
    manager._devices = {"SERIAL1": AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE)}
    manager._info_fetch_in_flight = {"SERIAL1"}
    monkeypatch.setattr(
        manager_module, "parse_devices_output", lambda _output: [RawDeviceEntry("SERIAL1", "device")]
    )

    fetch_calls = []
    monkeypatch.setattr(manager, "_fetch_device_info", lambda serial: fetch_calls.append(serial))

    manager._on_devices_result(QProcess())  # never started -- readAllStandardOutput() returns b""

    assert fetch_calls == []
