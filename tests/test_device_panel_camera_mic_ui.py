"""DevicePanel's Microphone Input Level meter/status -- the widget-level
public API mic_controller.py drives (see test_mic_controller_level.py for
the controller-side wiring). The Camera Live Preview equivalent now lives in
the Status panel's right-side bar -- see test_status_panel.py and
test_camera_controller_preview.py.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.device.manager import DeviceManager
from androidlink.ui.panels.device_panel import DevicePanel
from androidlink.ui.widgets.status_dot import StatusState


def _make_panel(qtbot) -> DevicePanel:
    device_manager = DeviceManager()
    panel = DevicePanel(device_manager)
    qtbot.addWidget(panel)
    return panel


def test_mic_meter_and_status_default_state(qtbot):
    # Same reasoning as the camera preview default-state test above.
    panel = _make_panel(qtbot)
    assert panel._mic_status_text.text() == "Disconnected"
    assert panel._mic_status_dot.state() == StatusState.DISCONNECTED
    assert panel._mic_level_meter._displayed_level == 0.0


def test_set_mic_level_feeds_the_meter(qtbot):
    panel = _make_panel(qtbot)
    panel.set_mic_level(0.7)
    assert panel._mic_level_meter._displayed_level > 0.0


def test_mic_status_transitions(qtbot):
    panel = _make_panel(qtbot)

    panel.set_mic_status_connecting()
    assert panel._mic_status_text.text() == "Connecting…"

    panel.set_mic_status_active()
    assert panel._mic_status_text.text() == "Active"
    assert panel._mic_status_dot.state() == StatusState.CONNECTED

    panel.set_mic_status_no_signal()
    assert panel._mic_status_text.text() == "No Signal"

    panel.set_mic_level(0.5)
    panel.set_mic_status_disabled()
    assert panel._mic_status_text.text() == "Disabled"
    assert panel._mic_level_meter._displayed_level == 0.0  # released

    panel.set_mic_level(0.5)
    panel.set_mic_status_disconnected()
    assert panel._mic_status_text.text() == "Disconnected"
    assert panel._mic_level_meter._displayed_level == 0.0  # released
