"""Plays interleaved 16-bit PCM audio through a Windows output device via
QtMultimedia's QAudioSink (prompt.md section 10: Android audio -> PC, with
PC-side volume/mute control). Optionally plays the same audio to a *second*
device at the same time (prompt.md section 27's Settings > Audio) -- the
practical use case being "hear the device's audio through real speakers
*and* feed it into a virtual-audio-cable at the same time" so another app
(Discord/OBS/etc.) can pick it up too, since a device can only have one
Windows-wide default output at a time.

Lives on the same worker thread as decoding (see streaming/transport.py) so
neither decode nor audio I/O ever touches the UI thread. QAudioSink is a
QObject and Qt Multimedia backends generally expect to be driven from the
thread that created them with a running event loop, which the worker
thread's QThread already provides.
"""

import logging

from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

from androidlink.streaming.protocol import AUDIO_CHANNELS, AUDIO_SAMPLE_RATE
from androidlink.utils.errors import NO_AUDIO_OUTPUT_DEVICE

logger = logging.getLogger(__name__)


def find_audio_output_by_id(device_id: bytes):
    """Looks up one of QMediaDevices.audioOutputs() by its stable id
    (prompt.md section 27: Settings > Audio > Output device). Returns None
    if the device isn't currently present (unplugged, renamed, etc.) so
    callers can fall back to the system default rather than fail."""
    for device in QMediaDevices.audioOutputs():
        if bytes(device.id()) == device_id:
            return device
    return None


class AudioPlayback:
    def __init__(
        self,
        preferred_device_id: bytes | None = None,
        secondary_device_id: bytes | None = None,
    ) -> None:
        audio_format = QAudioFormat()
        audio_format.setSampleRate(AUDIO_SAMPLE_RATE)
        audio_format.setChannelCount(AUDIO_CHANNELS)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)

        primary_device = self._resolve_device(preferred_device_id)
        if primary_device.isNull():
            raise RuntimeError(NO_AUDIO_OUTPUT_DEVICE.text)

        # Each entry is [QAudioSink, io_device] -- io_device is filled in by
        # start() (QAudioSink.start() returns the writable QIODevice).
        self._sinks: list[list] = [self._make_sink(primary_device, audio_format)]

        if secondary_device_id is not None:
            secondary_device = find_audio_output_by_id(secondary_device_id)
            if secondary_device is None:
                logger.warning(
                    "Secondary audio output device not found; playing to the primary device only"
                )
            elif bytes(secondary_device.id()) == bytes(primary_device.id()):
                logger.warning("Secondary audio output device is the same as the primary; ignoring it")
            else:
                self._sinks.append(self._make_sink(secondary_device, audio_format))

        self._volume = 1.0
        self._muted = False

    @staticmethod
    def _resolve_device(preferred_device_id: bytes | None):
        device = None
        if preferred_device_id is not None:
            device = find_audio_output_by_id(preferred_device_id)
            if device is None:
                logger.warning(
                    "Preferred audio output device not found; falling back to the system default"
                )
        if device is None:
            device = QMediaDevices.defaultAudioOutput()
        return device

    @staticmethod
    def _make_sink(device, audio_format: QAudioFormat) -> list:
        if not device.isFormatSupported(audio_format):
            logger.warning(
                "Audio device %r does not natively support %s", device.description(), audio_format
            )
        return [QAudioSink(device, audio_format), None]

    def start(self) -> None:
        for entry in self._sinks:
            entry[1] = entry[0].start()
        self._apply_volume()

    def stop(self) -> None:
        for entry in self._sinks:
            entry[0].stop()
            entry[1] = None

    def write(self, pcm_bytes: bytes) -> None:
        for _sink, io_device in self._sinks:
            if io_device is not None:
                io_device.write(pcm_bytes)

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(1.0, volume))
        self._apply_volume()

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self._apply_volume()

    def _apply_volume(self) -> None:
        for entry in self._sinks:
            entry[0].setVolume(0.0 if self._muted else self._volume)
