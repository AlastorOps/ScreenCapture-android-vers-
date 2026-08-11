from dataclasses import dataclass
from enum import Enum


class ConnectionState(Enum):
    DEVICE = "device"
    UNAUTHORIZED = "unauthorized"
    OFFLINE = "offline"
    UNKNOWN = "unknown"


_STATE_MAP = {
    "device": ConnectionState.DEVICE,
    "unauthorized": ConnectionState.UNAUTHORIZED,
    "offline": ConnectionState.OFFLINE,
}


def parse_connection_state(raw_state: str) -> ConnectionState:
    return _STATE_MAP.get(raw_state, ConnectionState.UNKNOWN)


def mask_serial(serial: str) -> str:
    """Show a safe, user-facing form of a device serial (prompt.md section 3)."""
    if len(serial) <= 8:
        return serial
    return f"{serial[:4]}···{serial[-4:]}"


@dataclass
class AndroidDevice:
    serial: str
    connection_state: ConnectionState
    model: str | None = None
    manufacturer: str | None = None
    android_version: str | None = None
    api_level: int | None = None
    is_active: bool = False
    #: Real display capability from `adb shell dumpsys display` (see
    #: device/display_info.py) -- None until fetched or if detection failed
    #: on this device/OEM, never a guessed/fabricated value.
    refresh_rate_hz: int | None = None
    supported_refresh_rates_hz: tuple[int, ...] | None = None

    @property
    def display_serial(self) -> str:
        return mask_serial(self.serial)

    @property
    def display_name(self) -> str:
        return self.model or self.display_serial
