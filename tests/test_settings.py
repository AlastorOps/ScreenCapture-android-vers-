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


def test_reset_to_defaults_persists(tmp_path):
    config_path = tmp_path / "config.json"
    manager = SettingsManager(config_path)
    manager.load()
    manager.settings.general.accent_color = "#123456"
    manager.save()

    manager.reset_to_defaults()

    reloaded = SettingsManager(config_path).load()
    assert reloaded.general.accent_color == AppSettings().general.accent_color
