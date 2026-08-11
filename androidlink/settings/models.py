from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

DEFAULT_ACCENT_COLOR = "#7aa2f7"


class GeneralSettings(BaseModel):
    theme: Literal["dark"] = "dark"
    accent_color: str = DEFAULT_ACCENT_COLOR


class AppSettings(BaseModel):
    schema_version: int = SCHEMA_VERSION
    general: GeneralSettings = Field(default_factory=GeneralSettings)
