import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


def find_adb_executable() -> Path | None:
    """Locate an adb executable: PATH first, then common SDK install locations."""
    which_result = shutil.which("adb")
    if which_result:
        return Path(which_result)

    candidates: list[Path] = []

    sdk_root = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk_root:
        candidates.append(Path(sdk_root) / "platform-tools" / "adb.exe")

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Android" / "Sdk" / "platform-tools" / "adb.exe")

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    return None


@dataclass(frozen=True)
class RawDeviceEntry:
    serial: str
    state: str
    extra: dict[str, str] = field(default_factory=dict)


def parse_devices_output(output: str) -> list[RawDeviceEntry]:
    """Parse `adb devices -l` output into raw entries.

    Example line: "R58N123ABCD    device usb:1-1 product:d2q model:SM_S921U
    device:d2q transport_id:3"
    """
    entries: list[RawDeviceEntry] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("List of devices attached") or line.startswith("*"):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        serial, state, *rest = parts
        extra: dict[str, str] = {}
        for token in rest:
            if ":" in token:
                key, _, value = token.partition(":")
                extra[key] = value

        entries.append(RawDeviceEntry(serial=serial, state=state, extra=extra))

    return entries


def parse_getprop_output(output: str) -> dict[str, str]:
    """Parse the output of `adb shell getprop`, which is lines like:
    [ro.product.model]: [SM-S921U]
    """
    props: dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("["):
            continue
        try:
            key_part, value_part = line.split("]:", 1)
        except ValueError:
            continue
        key = key_part.strip("[]").strip()
        value = value_part.strip().strip("[]")
        props[key] = value
    return props
