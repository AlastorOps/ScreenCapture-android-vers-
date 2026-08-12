"""DevicePanel's Performance/Quality slider (directly under Microphone --
the only copy of this control in the app, see main_window.py's docks) and
its live "N%" readout.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.device.manager import DeviceManager
from androidlink.ui.panels.device_panel import DevicePanel


def _make_panel(qtbot) -> DevicePanel:
    device_manager = DeviceManager()
    panel = DevicePanel(device_manager)
    qtbot.addWidget(panel)
    return panel


def test_default_slider_value_and_readout(qtbot):
    panel = _make_panel(qtbot)

    assert panel.performance_slider.value() == 50
    assert panel._performance_readout_label.text() == "50%"


def test_dragging_emits_performance_slider_changed_and_updates_readout(qtbot):
    panel = _make_panel(qtbot)
    events = []
    panel.performance_slider_changed.connect(events.append)

    panel.performance_slider.setValue(80)

    assert events == [80]
    assert panel._performance_readout_label.text() == "80%"


def test_releasing_emits_performance_slider_committed(qtbot):
    panel = _make_panel(qtbot)
    events = []
    panel.performance_slider_committed.connect(lambda: events.append(1))

    panel.performance_slider.committed.emit()

    assert events == [1]


def test_set_initial_performance_slider_value_does_not_emit(qtbot):
    panel = _make_panel(qtbot)
    events = []
    panel.performance_slider_changed.connect(events.append)

    panel.set_initial_performance_slider_value(90)

    assert events == []
    assert panel.performance_slider.value() == 90
    assert panel._performance_readout_label.text() == "90%"
