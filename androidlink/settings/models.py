from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

DEFAULT_ACCENT_COLOR = "#7aa2f7"


class GeneralSettings(BaseModel):
    #: A palette.py preset id (e.g. "dark"/"light"/"nord"/"solarized_dark").
    #: Deliberately a plain str rather than a Literal -- the whole point of
    #: palette.py's PRESETS registry is that new themes can be added there
    #: without a matching change here; an unrecognized id (a preset removed
    #: after being persisted, or a config from an older build) falls back to
    #: "dark" in palette.set_theme() rather than failing validation.
    theme: str = "dark"
    accent_color: str = DEFAULT_ACCENT_COLOR
    setup_wizard_completed: bool = False
    logging_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    debug_mode: bool = False
    #: prompt.md section 16: base64-encoded QByteArray from
    #: QMainWindow.saveState(), or None to use the default dock layout.
    layout_state: str | None = None


class StreamingSettings(BaseModel):
    """prompt.md section 29: persist the performance/quality setting, plus
    optional advanced overrides (prompt.md section 27) layered on top of the
    slider-derived profile -- see streaming/performance.py's
    resolve_streaming_profile(). None means "let the slider decide"."""

    performance_slider_value: int = 50
    resolution_override: int | None = None  # max_size in pixels; None = automatic
    fps_override: int | None = None  # None = automatic (60)
    bitrate_override_mbps: float | None = None  # None = automatic


class AudioSettings(BaseModel):
    """prompt.md section 29: persist audio volume (Android audio -> PC).
    Defaults to enabled -- most users casting the screen also want to hear
    the device's audio without an extra click."""

    enabled: bool = True
    volume: int = 100
    muted: bool = False
    #: hex-encoded QAudioDevice.id() (a QByteArray) of the preferred PC
    #: output device; None = system default. See audio/playback.py.
    output_device_id: str | None = None
    #: hex-encoded QAudioDevice.id() of an optional second device to play
    #: the same audio to at once (e.g. real speakers *and* a virtual-audio-
    #: cable so another app can pick it up too); None = single output only.
    secondary_output_device_id: str | None = None


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


class RecordingSettings(BaseModel):
    """prompt.md section 27/29: PC-side recording preferences.
    save_directory overrides utils/platform.py's get_recordings_dir() /
    get_screenshots_dir() defaults when set. format has one real value today
    (recording/recorder.py always muxes to MP4/H.264+AAC); quality maps to a
    target video bitrate passed to the encoder (None/"standard" leaves the
    encoder's own default, which is what the app used before this setting
    existed)."""

    save_directory: str | None = None
    format: Literal["mp4"] = "mp4"
    quality: Literal["standard", "high", "maximum"] = "standard"


class AppSettings(BaseModel):
    schema_version: int = SCHEMA_VERSION
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    streaming: StreamingSettings = Field(default_factory=StreamingSettings)
    audio: AudioSettings = Field(default_factory=AudioSettings)
    camera: CameraSettings = Field(default_factory=CameraSettings)
    microphone: MicrophoneSettings = Field(default_factory=MicrophoneSettings)
    recording: RecordingSettings = Field(default_factory=RecordingSettings)
