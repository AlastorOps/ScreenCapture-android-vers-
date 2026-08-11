"""Feeds Android microphone PCM audio into a Windows virtual-audio-cable's
playback endpoint (prompt.md section 12: expose the Android mic as a
Windows input device for Discord/OBS/Zoom/Teams/etc.).

Unlike the virtual webcam (Phase 6, via pyvirtualcam), Windows has no
first-party "virtual microphone" API. The standard approach -- and the one
this module takes -- is a third-party virtual-audio-cable driver (VB-Audio
Virtual Cable, VoiceMeeter, ...) that exposes a loopback pair of devices:
audio written to its playback ("Input"/"Line") endpoint reappears on its
matching recording endpoint, which other applications can then select as a
microphone. We detect that we're the writer, not the driver's owner: we
never bundle or auto-install one (prompt.md section 25 -- never silently
install drivers), only detect a known one and name what to install if none
is found, mirroring virtual_camera.py's honesty about its own backend
requirement.
"""

import logging

from PySide6.QtMultimedia import QAudioDevice, QAudioFormat, QAudioSink, QMediaDevices

from androidlink.streaming.protocol import AUDIO_CHANNELS, AUDIO_SAMPLE_RATE

logger = logging.getLogger(__name__)

# Playback-endpoint description substrings used by common virtual-audio-
# cable drivers on Windows, matched case-insensitively. Not exhaustive --
# just the well-known free/common ones.
_KNOWN_VIRTUAL_CABLE_NAMES = (
    "cable input",  # VB-Audio Virtual Cable
    "voicemeeter input",  # VoiceMeeter / Banana / Potato
    "voicemeeter aux input",
    "voicemeeter vaio3 input",
)


class VirtualMicrophoneUnavailableError(Exception):
    pass


def find_virtual_cable_output_device() -> QAudioDevice | None:
    for device in QMediaDevices.audioOutputs():
        description = device.description().lower()
        if any(name in description for name in _KNOWN_VIRTUAL_CABLE_NAMES):
            return device
    return None


def is_likely_virtual_cable(device: QAudioDevice) -> bool:
    """True if `device` looks like a virtual-audio-cable's playback
    endpoint (same name-matching find_virtual_cable_output_device() uses).

    Used the other direction from that function's own purpose: not to find
    a cable to route the *microphone* into, but to warn when Android Audio
    (prompt.md section 10, PC playback of the device's audio) is about to
    play into one via QMediaDevices.defaultAudioOutput() -- confirmed via a
    real installed VB-Audio Virtual Cable to silently become the Windows
    default output device, which makes AndroidLink's audio pipeline work
    perfectly while producing no audible sound at all, since nothing
    "listens" to a cable's input side without a separate monitoring setup.
    """
    return any(name in device.description().lower() for name in _KNOWN_VIRTUAL_CABLE_NAMES)


class VirtualMicrophoneSink:
    """Writes interleaved 16-bit PCM into a virtual audio cable's playback
    endpoint via QAudioSink. Mirrors audio/playback.py's AudioPlayback
    structure but targets a specific (non-default) output device rather
    than QMediaDevices.defaultAudioOutput()."""

    def __init__(self) -> None:
        device = find_virtual_cable_output_device()
        if device is None:
            # Just the technical fact -- utils/errors.py's
            # virtual_microphone_unavailable() supplies the actionable
            # "install X" guidance at the call site (mic_session.py), so
            # this message isn't duplicated when the two are combined.
            raise VirtualMicrophoneUnavailableError(
                "No virtual audio cable driver (e.g. VB-Audio Virtual Cable, VoiceMeeter) was detected"
            )

        audio_format = QAudioFormat()
        audio_format.setSampleRate(AUDIO_SAMPLE_RATE)
        audio_format.setChannelCount(AUDIO_CHANNELS)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        if not device.isFormatSupported(audio_format):
            logger.warning("Virtual cable device does not natively support %s", audio_format)

        self._device_name = device.description()
        self._sink = QAudioSink(device, audio_format)
        self._io_device = None
        self._volume = 1.0
        self._muted = False

    @property
    def backend_device_name(self) -> str:
        return self._device_name

    def start(self) -> None:
        self._io_device = self._sink.start()
        self._apply_volume()

    def stop(self) -> None:
        self._sink.stop()
        self._io_device = None

    def write(self, pcm_bytes: bytes) -> None:
        if self._io_device is not None:
            self._io_device.write(pcm_bytes)

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))
        self._apply_volume()

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self._apply_volume()

    def _apply_volume(self) -> None:
        self._sink.setVolume(0.0 if self._muted else self._volume)
