"""Regression tests for a real bug found via live testing: installing a
virtual-audio-cable driver (for the Mic feature) can silently become
Windows' system-wide default playback device, which makes Android Audio's
"System Default" output setting route decoded audio into the cable instead
of real speakers -- the whole pipeline succeeds with no error anywhere, but
the user hears nothing. The Settings dialog now warns about this explicitly
(prompt.md section 21/33: never fail silently) -- see
audio/virtual_audio.py's is_likely_virtual_cable().
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.audio.virtual_audio import is_likely_virtual_cable
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
import androidlink.ui.windows.settings_dialog as settings_dialog_module

from tests.conftest import build_settings_dialog


class _FakeDevice:
    def __init__(self, description: str, is_null: bool = False) -> None:
        self._description = description
        self._is_null = is_null

    def description(self) -> str:
        return self._description

    def isNull(self) -> bool:  # noqa: N802 - matches Qt's naming
        return self._is_null


def test_is_likely_virtual_cable_matches_known_driver_names():
    assert is_likely_virtual_cable(_FakeDevice("CABLE Input (VB-Audio Virtual Cable)"))
    assert is_likely_virtual_cable(_FakeDevice("VoiceMeeter Input"))


def test_is_likely_virtual_cable_rejects_real_devices():
    assert not is_likely_virtual_cable(_FakeDevice("Speakers (Realtek(R) Audio)"))
    assert not is_likely_virtual_cable(_FakeDevice("Headphones (Realtek(R) Audio)"))


def _build_dialog(qtbot, tmp_path, monkeypatch, *, default_output_is_cable: bool):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()

    monkeypatch.setattr(
        settings_dialog_module,
        "is_likely_virtual_cable",
        lambda _device: default_output_is_cable,
    )
    monkeypatch.setattr(
        settings_dialog_module.QMediaDevices,
        "defaultAudioOutput",
        staticmethod(lambda: _FakeDevice("irrelevant -- is_likely_virtual_cable is stubbed above")),
    )

    dialog = build_settings_dialog(qtbot, settings_manager, device_manager)
    return settings_manager, dialog


def test_warning_shown_when_system_default_is_a_virtual_cable(qtbot, tmp_path, monkeypatch):
    _settings, dialog = _build_dialog(qtbot, tmp_path, monkeypatch, default_output_is_cable=True)

    assert dialog._audio_output_warning_label.isHidden() is False
    assert "virtual audio cable" in dialog._audio_output_warning_label.text().lower()


def test_no_warning_when_system_default_is_a_real_device(qtbot, tmp_path, monkeypatch):
    _settings, dialog = _build_dialog(qtbot, tmp_path, monkeypatch, default_output_is_cable=False)

    assert dialog._audio_output_warning_label.isHidden() is True


def test_warning_disappears_once_a_specific_device_is_selected(qtbot, tmp_path, monkeypatch):
    _settings, dialog = _build_dialog(qtbot, tmp_path, monkeypatch, default_output_is_cable=True)
    assert dialog._audio_output_warning_label.isHidden() is False

    # Index 0 is "System Default"; pick anything else if one exists on this
    # machine (there always is at least one real device in CI/dev envs the
    # existing audio tests already depend on).
    if dialog._audio_output_combo.count() > 1:
        dialog._audio_output_combo.setCurrentIndex(1)
        assert dialog._audio_output_warning_label.isHidden() is True
