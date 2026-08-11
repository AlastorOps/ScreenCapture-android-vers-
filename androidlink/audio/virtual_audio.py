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


class VirtualMicrophoneSink:
    """Writes interleaved 16-bit PCM into a virtual audio cable's playback
    endpoint via QAudioSink. Mirrors audio/playback.py's AudioPlayback
    structure but targets a specific (non-default) output device rather
    than QMediaDevices.defaultAudioOutput()."""

    def __init__(self) -> None:
        device = find_virtual_cable_output_device()
        if device is None:
            raise VirtualMicrophoneUnavailableError(
                "No virtual audio cable driver found. Install VB-Audio "
                "Virtual Cable (or VoiceMeeter), then try again."
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
