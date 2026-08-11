from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

DEFAULT_ACCENT_COLOR = "#7aa2f7"


class GeneralSettings(BaseModel):
    theme: Literal["dark"] = "dark"
    accent_color: str = DEFAULT_ACCENT_COLOR
    setup_wizard_completed: bool = False


class StreamingSettings(BaseModel):
    """prompt.md section 29: persist the performance/quality setting."""

    performance_slider_value: int = 50


class AudioSettings(BaseModel):
    """prompt.md section 29: persist audio volume (Android audio -> PC).
    Defaults to enabled -- most users casting the screen also want to hear
    the device's audio without an extra click."""

    enabled: bool = True
    volume: int = 100
    muted: bool = False


class CameraSettings(BaseModel):
    """prompt.md section 29: persist camera selection. camera_id is
    matched against whatever the device actually reports on reconnect --
    if it's no longer present, selection just falls back to none."""

    camera_id: str | None = None
    fps: int = 0  # 0 = automatic


class MicrophoneSettings(BaseModel):
    """prompt.md section 29: persist microphone selection and volume."""

    audio_source: str = "mic"
    volume: int = 100
    muted: bool = False


class AppSettings(BaseModel):
    schema_version: int = SCHEMA_VERSION
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    streaming: StreamingSettings = Field(default_factory=StreamingSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    camera: CameraSettings = Field(default_factory=CameraSettings)
    microphone: MicrophoneSettings = Field(default_factory=MicrophoneSettings)
