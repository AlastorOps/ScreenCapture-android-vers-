import logging
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QTimer, Signal

from androidlink.device.adb import find_adb_executable, parse_devices_output, parse_getprop_output
from androidlink.device.device_model import AndroidDevice, ConnectionState, parse_connection_state

logger = logging.getLogger(__name__)

POLL_INTERVAL_MS = 1500

_GETPROP_KEYS = {
    "ro.product.model": "model",
    "ro.product.manufacturer": "manufacturer",
    "ro.build.version.release": "android_version",
    "ro.build.version.sdk": "api_level",
}


class DeviceManager(QObject):
    """Polls `adb devices -l` for connected Android devices.

    Never takes control of a device automatically — connect_device() must be
    called explicitly (e.g. from a user's Connect click) per prompt.md section 3.
    """

    devices_changed = Signal(list)
    active_device_changed = Signal(object)
    adb_available_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._adb_path: Path | None = None
        self._adb_available = False
        self._adb_checked = False
        self._devices: dict[str, AndroidDevice] = {}
        self._active_serial: str | None = None
        self._devices_refresh_in_flight = False

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)

    @property
    def adb_available(self) -> bool:
        return self._adb_available

    @property
    def adb_path(self) -> Path | None:
        return self._adb_path

    @property
    def devices(self) -> list[AndroidDevice]:
        return list(self._devices.values())

    @property
    def active_device(self) -> AndroidDevice | None:
        if self._active_serial:
            return self._devices.get(self._active_serial)
        return None

    def start(self) -> None:
        self._locate_adb()
        self._poll()
        self._poll_timer.start()

    def stop(self) -> None:
        self._poll_timer.stop()

    def refresh_now(self) -> None:
        self._locate_adb()
        self._poll()

    def connect_device(self, serial: str) -> None:
        device = self._devices.get(serial)
        if device is None or device.connection_state != ConnectionState.DEVICE:
            return
        if self._active_serial is not None:
            self.disconnect_device()

        self._active_serial = serial
        device.is_active = True
        logger.info("Connected to device %s", device.display_serial)
        self.active_device_changed.emit(device)
        self.devices_changed.emit(self.devices)

    def disconnect_device(self) -> None:
        if self._active_serial is None:
            return
        device = self._devices.get(self._active_serial)
        if device is not None:
            device.is_active = False
            logger.info("Disconnected from device %s", device.display_serial)
        self._active_serial = None
        self.active_device_changed.emit(None)
        self.devices_changed.emit(self.devices)

    def _locate_adb(self) -> None:
        path = find_adb_executable()
        available = path is not None
        changed = not self._adb_checked or available != self._adb_available or path != self._adb_path
        self._adb_checked = True

        if changed:
            self._adb_path = path
            self._adb_available = available
            if available:
                logger.info("ADB found at %s", path)
            else:
                logger.warning("ADB not found on PATH or in common SDK locations")
            self.adb_available_changed.emit(available)

    def _poll(self) -> None:
        if not self._adb_available or self._devices_refresh_in_flight or self._adb_path is None:
            return
        self._devices_refresh_in_flight = True

        process = QProcess(self)
        process.finished.connect(lambda *_: self._on_devices_result(process))
        process.errorOccurred.connect(lambda err: self._on_process_error("devices -l", err))
        process.start(str(self._adb_path), ["devices", "-l"])

    def _on_devices_result(self, process: QProcess) -> None:
        self._devices_refresh_in_flight = False
        output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        process.deleteLater()

        raw_entries = parse_devices_output(output)
        seen_serials = {entry.serial for entry in raw_entries}
        changed = False

        for entry in raw_entries:
            state = parse_connection_state(entry.state)
            device = self._devices.get(entry.serial)

            if device is None:
                device = AndroidDevice(serial=entry.serial, connection_state=state)
                self._devices[entry.serial] = device
                changed = True
            elif device.connection_state != state:
                device.connection_state = state
                changed = True

            if state == ConnectionState.DEVICE and device.model is None:
                self._fetch_device_info(entry.serial)

        for serial in set(self._devices) - seen_serials:
            if serial == self._active_serial:
                self._active_serial = None
                self.active_device_changed.emit(None)
            del self._devices[serial]
            changed = True

        if changed:
            self.devices_changed.emit(self.devices)

    def _fetch_device_info(self, serial: str) -> None:
        if self._adb_path is None:
            return
        process = QProcess(self)
        process.finished.connect(lambda *_: self._on_device_info_result(serial, process))
        process.errorOccurred.connect(lambda err: self._on_process_error("getprop", err))
        process.start(str(self._adb_path), ["-s", serial, "shell", "getprop"])

    def _on_device_info_result(self, serial: str, process: QProcess) -> None:
        output = bytes(process.readAllStandardOutput()).decode("utf-8", errors="replace")
        process.deleteLater()

        device = self._devices.get(serial)
        if device is None:
            return

        props = parse_getprop_output(output)
        updated = False
        for prop_key, attr in _GETPROP_KEYS.items():
            raw_value = props.get(prop_key)
            if raw_value is None:
                continue

            value: str | int = raw_value
            if attr == "api_level":
                try:
                    value = int(raw_value)
                except ValueError:
                    continue

            if getattr(device, attr) != value:
                setattr(device, attr, value)
                updated = True

        if updated:
            self.devices_changed.emit(self.devices)

    @staticmethod
    def _on_process_error(command: str, error: QProcess.ProcessError) -> None:
        logger.warning("adb %s failed: %s", command, error)
