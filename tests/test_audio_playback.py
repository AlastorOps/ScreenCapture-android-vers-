import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtMultimedia import QAudio, QMediaDevices

from androidlink.audio.playback import AudioPlayback


def _silence(seconds: float) -> bytes:
    sample_count = int(48000 * seconds)
    return b"\x00\x00\x00\x00" * sample_count  # stereo, 16-bit silence


def test_start_write_stop_against_real_audio_backend(qapp):
    # Comparing QAudio.State enum instances with `==` is unreliable in this
    # PySide6 build (verified: identical name/value, but `==` still returns
    # False for values from different binding paths) -- compare .value.
    playback = AudioPlayback()
    playback.start()

    # Real hardware can drain the buffer between statements, so this only
    # asserts the write doesn't raise and that state is a valid post-start
    # value -- not any specific one (Active vs. Idle is a timing race).
    playback.write(_silence(0.05))
    assert playback._sinks[0][0].state().value != QAudio.State.StoppedState.value

    playback.stop()
    assert playback._sinks[0][0].state().value == QAudio.State.StoppedState.value


def test_volume_and_mute_affect_underlying_sink_volume(qapp):
    playback = AudioPlayback()
    playback.start()

    playback.set_volume(0.5)
    assert abs(playback._sinks[0][0].volume() - 0.5) < 0.01

    playback.set_muted(True)
    assert playback._sinks[0][0].volume() == 0.0

    playback.set_muted(False)
    assert abs(playback._sinks[0][0].volume() - 0.5) < 0.01

    playback.stop()


def test_volume_clamped_to_valid_range(qapp):
    playback = AudioPlayback()
    playback.set_volume(2.0)
    assert playback._volume == 1.0
    playback.set_volume(-1.0)
    assert playback._volume == 0.0


def _second_real_output_device(qapp):
    """A real device on this machine that isn't the system default, for
    exercising the dual-output path against genuine hardware rather than a
    mock. None if this machine only has one output device."""
    default = QMediaDevices.defaultAudioOutput()
    for device in QMediaDevices.audioOutputs():
        if bytes(device.id()) != bytes(default.id()):
            return device
    return None


def test_secondary_device_plays_to_both_sinks_at_once(qapp):
    secondary = _second_real_output_device(qapp)
    if secondary is None:
        return  # this machine only has one output device -- nothing to pair

    playback = AudioPlayback(secondary_device_id=bytes(secondary.id()))
    assert len(playback._sinks) == 2

    playback.start()
    playback.write(_silence(0.05))
    for sink, _io in playback._sinks:
        assert sink.state().value != QAudio.State.StoppedState.value
    playback.stop()


def test_volume_and_mute_apply_to_both_sinks(qapp):
    secondary = _second_real_output_device(qapp)
    if secondary is None:
        return

    playback = AudioPlayback(secondary_device_id=bytes(secondary.id()))
    playback.start()

    playback.set_volume(0.5)
    for sink, _io in playback._sinks:
        assert abs(sink.volume() - 0.5) < 0.01

    playback.set_muted(True)
    for sink, _io in playback._sinks:
        assert sink.volume() == 0.0

    playback.stop()


def test_secondary_device_same_as_primary_is_ignored(qapp):
    default = QMediaDevices.defaultAudioOutput()
    playback = AudioPlayback(secondary_device_id=bytes(default.id()))
    assert len(playback._sinks) == 1  # not duplicated


def test_unknown_secondary_device_id_falls_back_to_primary_only(qapp):
    playback = AudioPlayback(secondary_device_id=b"not-a-real-device-id")
    assert len(playback._sinks) == 1
