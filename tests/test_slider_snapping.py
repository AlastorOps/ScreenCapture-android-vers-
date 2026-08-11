"""The Performance/Quality slider snaps into discrete steps as it's dragged
(both the main window's LabeledSlider and the Settings dialog's plain
QSlider copy), rather than landing on an arbitrary pixel-derived value.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.device.manager import DeviceManager
from androidlink.settings.manager import SettingsManager
from androidlink.ui.widgets.slider_labeled import LabeledSlider, snap_value

from tests.conftest import build_settings_dialog


def test_snap_value_rounds_to_nearest_multiple():
    assert snap_value(37, 0, 100, 10) == 40
    assert snap_value(42, 0, 100, 10) == 40
    assert snap_value(44, 0, 100, 10) == 40
    assert snap_value(46, 0, 100, 10) == 50
    assert snap_value(0, 0, 100, 10) == 0
    assert snap_value(100, 0, 100, 10) == 100


def test_snap_value_clamps_to_range():
    assert snap_value(96, 0, 100, 10) == 100
    assert snap_value(4, 0, 100, 10) == 0


def test_labeled_slider_without_snap_interval_is_fully_continuous(qtbot):
    slider = LabeledSlider("PERFORMANCE", "QUALITY", value=50)
    qtbot.addWidget(slider)

    slider.setValue(37)
    assert slider.value() == 37


def test_labeled_slider_with_snap_interval_snaps_dragged_values(qtbot):
    slider = LabeledSlider("PERFORMANCE", "QUALITY", value=50, snap_interval=10)
    qtbot.addWidget(slider)

    events = []
    slider.valueChanged.connect(events.append)

    slider.setValue(37)
    assert slider.value() == 40
    assert events == [40]  # only the final snapped value is emitted, not the raw 37


def test_labeled_slider_normalizes_a_non_multiple_initial_value(qtbot):
    slider = LabeledSlider("PERFORMANCE", "QUALITY", value=53, snap_interval=10)
    qtbot.addWidget(slider)

    assert slider.value() == 50


def test_settings_dialog_streaming_slider_snaps(qtbot, tmp_path):
    settings_manager = SettingsManager(tmp_path / "config.json")
    settings_manager.load()
    device_manager = DeviceManager()

    dialog = build_settings_dialog(qtbot, settings_manager, device_manager)

    dialog._perf_slider.setValue(37)
    assert dialog._perf_slider.value() == 40
    assert dialog._perf_value_label.text() == "40"
