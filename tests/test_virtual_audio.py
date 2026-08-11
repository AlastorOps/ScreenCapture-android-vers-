import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtMultimedia import QMediaDevices

from androidlink.audio.virtual_audio import (
    VirtualMicrophoneSink,
    VirtualMicrophoneUnavailableError,
    find_virtual_cable_output_device,
)


def _hide_real_cable_devices(monkeypatch) -> None:
    """Forces find_virtual_cable_output_device()'s real "not found" path
    (rather than relying on this machine happening to have no VB-Audio/
    VoiceMeeter driver installed, which stopped being true once one was
    installed to test the Mic feature for real) by filtering any genuinely
    cable-like devices out of the real enumeration -- everything else about
    the device list stays real, unmocked."""
    real_outputs = QMediaDevices.audioOutputs()
    non_cable_outputs = [
        d for d in real_outputs if "cable" not in d.description().lower()
        and "voicemeeter" not in d.description().lower()
    ]
    monkeypatch.setattr(QMediaDevices, "audioOutputs", staticmethod(lambda: non_cable_outputs))


def test_find_virtual_cable_output_device_returns_none_when_not_installed(qapp, monkeypatch):
    _hide_real_cable_devices(monkeypatch)
    assert find_virtual_cable_output_device() is None


def test_find_virtual_cable_output_device_finds_a_real_one_when_installed(qapp):
    """The inverse case, run unconditionally for real: if this machine has
    a virtual-audio-cable driver installed, it must actually be found --
    skipped (not failed) if this machine genuinely has none installed."""
    device = find_virtual_cable_output_device()
    if device is None:
        pytest.skip("No virtual-audio-cable driver installed on this machine")
    description = device.description().lower()
    assert "cable" in description or "voicemeeter" in description


def test_raises_clear_error_when_no_backend_available(qapp, monkeypatch):
    _hide_real_cable_devices(monkeypatch)

    with pytest.raises(VirtualMicrophoneUnavailableError) as exc_info:
        VirtualMicrophoneSink()

    message = str(exc_info.value).lower()
    assert "virtual audio cable" in message or "voicemeeter" in message
