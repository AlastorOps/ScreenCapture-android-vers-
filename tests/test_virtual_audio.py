import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from androidlink.audio.virtual_audio import (
    VirtualMicrophoneSink,
    VirtualMicrophoneUnavailableError,
    find_virtual_cable_output_device,
)


def test_find_virtual_cable_output_device_returns_none_when_not_installed(qapp):
    """This machine has no VB-Audio/VoiceMeeter driver installed, so this
    genuinely exercises the real not-found path rather than mocking it."""
    assert find_virtual_cable_output_device() is None


def test_raises_clear_error_when_no_backend_available(qapp):
    with pytest.raises(VirtualMicrophoneUnavailableError) as exc_info:
        VirtualMicrophoneSink()

    message = str(exc_info.value).lower()
    assert "virtual audio cable" in message or "voicemeeter" in message
