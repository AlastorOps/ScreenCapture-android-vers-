"""Exercises the real load-into-UI / persist-on-change round trip for
settings that prompt.md section 29 requires to survive a restart: audio
volume/mute, microphone selection/volume/mute, and camera selection. Builds
real widgets (via qtbot) and real controllers wired to a real SettingsManager
pointed at a temp config file -- no mocking of the persistence path.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.audio.mic_controller import MicController
from androidlink.camera.camera_controller import CameraController
from androidlink.camera.camera_list import CameraInfo
from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.streaming.controller import CastingController
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.panels.screen_panel import ScreenPanel
from androidlink.ui.panels.status_panel import StatusPanel


def _settings_manager(tmp_path) -> SettingsManager:
    manager = SettingsManager(tmp_path / "config.json")
    manager.load()
    return manager


def test_casting_controller_restores_and_persists_audio_state(qtbot, tmp_path):
    settings_manager = _settings_manager(tmp_path)
    settings_manager.settings.audio.volume = 42
    settings_manager.settings.audio.muted = True
    settings_manager.save()

    device_manager = DeviceManager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    screen_panel = ScreenPanel()
    qtbot.addWidget(screen_panel)

    # Must be kept alive: an unreferenced, unparented QObject can be
    # garbage-collected, silently dropping its signal connections.
    controller = CastingController(device_manager, device_panel, screen_panel, settings_manager)

    assert device_panel._volume_slider.value() == 42
    assert device_panel._mute_toggle.isChecked() is True

    device_panel.audio_volume_committed.emit(77)
    reloaded = SettingsManager(tmp_path / "config.json").load()
    assert reloaded.audio.volume == 77


def test_audio_defaults_on_and_stays_checked_across_recast(qtbot, tmp_path):
    """Audio defaults to enabled (settings.audio.enabled defaults True), and
    the Audio toggle must reflect that as soon as Cast becomes available --
    not just internally in CastingController while the UI silently shows it
    off. Also a regression check for the bug this surfaced while building
    it: cycling Cast dependent-features availability off/on used to leave
    Audio stuck unchecked even when the desired state was still "on".

    Drives DevicePanel's availability toggling directly rather than through
    a full CastingController._start_casting() -- that path requires a real
    connected device to succeed, which isn't available in this unit test;
    the availability toggling is exactly what implements the fix, so
    testing it directly is the more precise regression check anyway.
    """
    settings_manager = _settings_manager(tmp_path)  # fresh: audio.enabled defaults True

    device_manager = DeviceManager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    screen_panel = ScreenPanel()
    qtbot.addWidget(screen_panel)

    controller = CastingController(device_manager, device_panel, screen_panel, settings_manager)
    assert controller._audio_enabled is True

    audio_toggle = device_panel._feature_toggles["Audio"]

    device_panel._set_cast_dependent_features_availability(True)
    assert audio_toggle.isChecked() is True

    device_panel._set_cast_dependent_features_availability(False)
    device_panel._set_cast_dependent_features_availability(True)
    assert audio_toggle.isChecked() is True


def test_audio_disabled_preference_persists_across_recast(qtbot, tmp_path):
    settings_manager = _settings_manager(tmp_path)
    settings_manager.settings.audio.enabled = False
    settings_manager.save()

    device_manager = DeviceManager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    screen_panel = ScreenPanel()
    qtbot.addWidget(screen_panel)

    CastingController(device_manager, device_panel, screen_panel, settings_manager)

    audio_toggle = device_panel._feature_toggles["Audio"]
    device_panel._set_cast_dependent_features_availability(True)

    assert audio_toggle.isChecked() is False


def test_mic_controller_restores_and_persists_state(qtbot, tmp_path):
    settings_manager = _settings_manager(tmp_path)
    settings_manager.settings.microphone.volume = 33
    settings_manager.settings.microphone.audio_source = "mic-camcorder"
    settings_manager.save()

    device_manager = DeviceManager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)

    controller = MicController(device_manager, device_panel, settings_manager)

    assert device_panel._mic_volume_slider.value() == 33
    assert device_panel._mic_source_combo.currentData() == "mic-camcorder"

    device_panel.mic_mute_toggled.emit(True)
    reloaded = SettingsManager(tmp_path / "config.json").load()
    assert reloaded.microphone.muted is True


def test_camera_controller_restores_persisted_camera_selection(qtbot, tmp_path):
    settings_manager = _settings_manager(tmp_path)
    settings_manager.settings.camera.camera_id = "1"
    settings_manager.settings.camera.fps = 60
    settings_manager.save()

    device_manager = DeviceManager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    status_panel = StatusPanel()
    qtbot.addWidget(status_panel)

    controller = CameraController(device_manager, device_panel, status_panel, settings_manager)

    cameras = [
        CameraInfo(camera_id="0", facing="back", width=1920, height=1080, fps_options=(30, 60)),
        CameraInfo(camera_id="1", facing="front", width=1280, height=960, fps_options=(30, 60)),
    ]
    controller._on_cameras_listed(cameras)

    assert device_panel._camera_combo.currentData().camera_id == "1"
    assert device_panel._camera_fps_combo.currentData() == 60


def test_camera_controller_persists_selection_change(qtbot, tmp_path):
    settings_manager = _settings_manager(tmp_path)
    device_manager = DeviceManager()
    device_panel = DevicePanel(device_manager)
    qtbot.addWidget(device_panel)
    status_panel = StatusPanel()
    qtbot.addWidget(status_panel)
    controller = CameraController(device_manager, device_panel, status_panel, settings_manager)

    controller._on_camera_selection_changed("2")
    controller._on_camera_fps_changed(30)

    reloaded = SettingsManager(tmp_path / "config.json").load()
    assert reloaded.camera.camera_id == "2"
    assert reloaded.camera.fps == 30
