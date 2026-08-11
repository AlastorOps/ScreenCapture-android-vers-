import logging
import os
from pathlib import Path

from pydantic import ValidationError

from androidlink.settings.models import AppSettings
from androidlink.utils.platform import get_app_data_dir

logger = logging.getLogger(__name__)

CONFIG_FILENAME = "config.json"


class SettingsManager:
    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or (get_app_data_dir() / CONFIG_FILENAME)
        self._settings = AppSettings()

    @property
    def settings(self) -> AppSettings:
        return self._settings

    @property
    def config_path(self) -> Path:
        return self._config_path

    def load(self) -> AppSettings:
        if not self._config_path.exists():
            logger.info("No config file found, writing defaults to %s", self._config_path)
            self._settings = AppSettings()
            self.save()
            return self._settings

        try:
            raw = self._config_path.read_text(encoding="utf-8")
            self._settings = AppSettings.model_validate_json(raw)
        except (ValidationError, ValueError) as exc:
            logger.warning(
                "Config file at %s is invalid (%s); falling back to defaults",
                self._config_path,
                exc,
            )
            self._settings = AppSettings()

        return self._settings

    def save(self) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._config_path.with_suffix(".tmp")
        tmp_path.write_text(self._settings.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp_path, self._config_path)
        logger.debug("Settings saved to %s", self._config_path)

    def reset_to_defaults(self) -> AppSettings:
        self._settings = AppSettings()
        self.save()
        return self._settings
