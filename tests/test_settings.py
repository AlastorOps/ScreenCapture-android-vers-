from androidlink.settings.manager import SettingsManager
from androidlink.settings.models import AppSettings


def test_load_writes_defaults_when_missing(tmp_path):
    config_path = tmp_path / "config.json"
    manager = SettingsManager(config_path)

    settings = manager.load()

    assert config_path.exists()
    assert settings.general.accent_color == AppSettings().general.accent_color


def test_save_and_reload_round_trips_changes(tmp_path):
    config_path = tmp_path / "config.json"
    manager = SettingsManager(config_path)
    manager.load()

    manager.settings.general.accent_color = "#ff8800"
    manager.save()

    reloaded = SettingsManager(config_path).load()
    assert reloaded.general.accent_color == "#ff8800"


def test_load_falls_back_to_defaults_on_corrupt_file(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("not valid json{{{", encoding="utf-8")

    manager = SettingsManager(config_path)
    settings = manager.load()

    assert settings.general.accent_color == AppSettings().general.accent_color


def test_streaming_audio_camera_microphone_settings_round_trip(tmp_path):
    """prompt.md section 29: performance/quality, audio volume, camera
    selection, and microphone selection must all persist."""
    config_path = tmp_path / "config.json"
    manager = SettingsManager(config_path)
    manager.load()

    manager.settings.streaming.performance_slider_value = 75
    manager.settings.audio.enabled = False
    manager.settings.audio.volume = 40
    manager.settings.audio.muted = True
    manager.settings.camera.camera_id = "1"
    manager.settings.camera.fps = 60
    manager.settings.microphone.audio_source = "mic-voice-communication"
    manager.settings.microphone.volume = 20
    manager.settings.microphone.muted = True
    manager.save()

    reloaded = SettingsManager(config_path).load()
    assert reloaded.streaming.performance_slider_value == 75
    assert reloaded.audio.enabled is False
    assert reloaded.audio.volume == 40
    assert reloaded.audio.muted is True
    assert reloaded.camera.camera_id == "1"
    assert reloaded.camera.fps == 60
    assert reloaded.microphone.audio_source == "mic-voice-communication"
    assert reloaded.microphone.volume == 20
    assert reloaded.microphone.muted is True


def test_new_settings_sections_have_sensible_defaults():
    settings = AppSettings()
    assert settings.streaming.performance_slider_value == 50
    assert settings.audio.enabled is True  # audio should default on
    assert settings.audio.volume == 100
    assert settings.audio.muted is False
    assert settings.camera.camera_id is None
    assert settings.camera.fps == 0
    assert settings.microphone.audio_source == "mic"
    assert settings.microphone.volume == 100
    assert settings.microphone.muted is False


def test_reset_to_defaults_persists(tmp_path):
    config_path = tmp_path / "config.json"
    manager = SettingsManager(config_path)
    manager.load()
    manager.settings.general.accent_color = "#123456"
    manager.save()

    manager.reset_to_defaults()

    reloaded = SettingsManager(config_path).load()
    assert reloaded.general.accent_color == AppSettings().general.accent_color
