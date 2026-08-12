"""Settings changed while a cast/mic session is already running now apply
live instead of requiring the user to manually disconnect and reconnect
(toggle Cast/Audio/Mic off and back on) to see them take effect:

- Streaming's Resolution/FPS/Bitrate overrides restart an active cast
  session (scrcpy can't change these on an already-running session, same as
  Control/Audio always could). The Performance/Quality slider itself now
  lives in the Device panel, not this dialog -- see
  test_performance_slider_live_apply.py for its live-apply behavior.
- Audio's Output Device / Also Output To likewise restart casting (a
  running QAudioSink can't be repointed at a different device).
- Audio/Microphone Volume and Mute apply directly to the live session with
  no restart needed (QAudioSink.setVolume() works on a running sink).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager

from tests.conftest import build_settings_dialog


def _build_dialog(qtbot, tmp_path):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()
    dialog = build_settings_dialog(qtbot, settings_manager, device_manager)
    return settings_manager, dialog


def _fake_restart_counter(dialog):
    calls = {"n": 0}
    dialog._casting_controller.restart_if_casting = lambda: calls.__setitem__("n", calls["n"] + 1)
    return calls


def test_resolution_override_restarts_an_active_cast_session(qtbot, tmp_path):
    _settings, dialog = _build_dialog(qtbot, tmp_path)
    calls = _fake_restart_counter(dialog)

    dialog._resolution_combo.setCurrentIndex(2)  # "Up to 1920×1080"

    assert calls["n"] == 1


def test_fps_override_restarts_an_active_cast_session(qtbot, tmp_path):
    _settings, dialog = _build_dialog(qtbot, tmp_path)
    calls = _fake_restart_counter(dialog)

    dialog._fps_combo.setCurrentIndex(1)  # "30"

    assert calls["n"] == 1


def test_bitrate_override_restarts_an_active_cast_session(qtbot, tmp_path):
    _settings, dialog = _build_dialog(qtbot, tmp_path)
    calls = _fake_restart_counter(dialog)

    dialog._bitrate_spin.setValue(8)
    dialog._bitrate_spin.editingFinished.emit()

    assert calls["n"] == 1


def test_output_device_change_restarts_an_active_cast_session(qtbot, tmp_path):
    _settings, dialog = _build_dialog(qtbot, tmp_path)
    calls = _fake_restart_counter(dialog)

    if dialog._audio_output_combo.count() > 1:
        dialog._audio_output_combo.setCurrentIndex(1)
        assert calls["n"] == 1


def test_secondary_output_device_change_restarts_an_active_cast_session(qtbot, tmp_path):
    _settings, dialog = _build_dialog(qtbot, tmp_path)
    calls = _fake_restart_counter(dialog)

    if dialog._audio_secondary_output_combo.count() > 1:
        dialog._audio_secondary_output_combo.setCurrentIndex(1)
        assert calls["n"] == 1


def test_audio_volume_applies_live_without_restarting(qtbot, tmp_path):
    _settings, dialog = _build_dialog(qtbot, tmp_path)
    restart_calls = _fake_restart_counter(dialog)
    volume_calls = []
    dialog._casting_controller.apply_audio_volume = volume_calls.append

    dialog._audio_volume_slider.setValue(42)
    dialog._audio_volume_slider.sliderReleased.emit()

    assert volume_calls == [42]
    assert restart_calls["n"] == 0  # a volume change never needs a full restart


def test_mic_volume_applies_live_without_restarting(qtbot, tmp_path):
    _settings, dialog = _build_dialog(qtbot, tmp_path)
    volume_calls = []
    dialog._mic_controller.apply_volume = volume_calls.append

    dialog._mic_volume_slider.setValue(33)
    dialog._mic_volume_slider.sliderReleased.emit()

    assert volume_calls == [33]


def test_mic_mute_applies_live(qtbot, tmp_path):
    _settings, dialog = _build_dialog(qtbot, tmp_path)
    mute_calls = []
    dialog._mic_controller.apply_muted = mute_calls.append

    dialog._mic_mute_toggle.setChecked(True)

    assert mute_calls == [True]


def test_restart_if_casting_is_a_noop_when_not_casting(qtbot, tmp_path):
    """CastingController.restart_if_casting() itself (not the dialog) must
    not explode/start a session when nothing is running."""
    _settings, dialog = _build_dialog(qtbot, tmp_path)

    dialog._casting_controller.restart_if_casting()  # must not raise
    assert dialog._casting_controller.is_casting is False


def test_apply_audio_volume_is_a_noop_when_not_casting(qtbot, tmp_path):
    _settings, dialog = _build_dialog(qtbot, tmp_path)

    dialog._casting_controller.apply_audio_volume(50)  # must not raise
