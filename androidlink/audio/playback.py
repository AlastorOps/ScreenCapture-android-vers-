"""Plays interleaved 16-bit PCM audio through the default Windows output
device via QtMultimedia's QAudioSink (prompt.md section 10: Android audio ->
PC, with PC-side volume/mute control).

Lives on the same worker thread as decoding (see streaming/transport.py) so
neither decode nor audio I/O ever touches the UI thread. QAudioSink is a
QObject and Qt Multimedia backends generally expect to be driven from the
thread that created them with a running event loop, which the worker
thread's QThread already provides.
"""

import logging

from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices

from androidlink.streaming.protocol import AUDIO_CHANNELS, AUDIO_SAMPLE_RATE

logger = logging.getLogger(__name__)


class AudioPlayback:
    def __init__(self) -> None:
        audio_format = QAudioFormat()
        audio_format.setSampleRate(AUDIO_SAMPLE_RATE)
        audio_format.setChannelCount(AUDIO_CHANNELS)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)

        device = QMediaDevices.defaultAudioOutput()
        if device.isNull():
            raise RuntimeError("No default audio output device")
        if not device.isFormatSupported(audio_format):
            logger.warning("Default audio device does not natively support %s", audio_format)

        self._sink = QAudioSink(device, audio_format)
        self._io_device = None
        self._volume = 1.0
        self._muted = False

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
