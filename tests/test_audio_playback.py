import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtMultimedia import QAudio

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
    assert playback._sink.state().value != QAudio.State.StoppedState.value

    playback.stop()
    assert playback._sink.state().value == QAudio.State.StoppedState.value


def test_volume_and_mute_affect_underlying_sink_volume(qapp):
    playback = AudioPlayback()
    playback.start()

    playback.set_volume(0.5)
    assert abs(playback._sink.volume() - 0.5) < 0.01

    playback.set_muted(True)
    assert playback._sink.volume() == 0.0

    playback.set_muted(False)
    assert abs(playback._sink.volume() - 0.5) < 0.01

    playback.stop()


def test_volume_clamped_to_valid_range(qapp):
    playback = AudioPlayback()
    playback.set_volume(2.0)
    assert playback._volume == 1.0
    playback.set_volume(-1.0)
    assert playback._volume == 0.0
