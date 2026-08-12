"""Regression tests for the "device list refreshes on its own" bug: every
devices_changed emission -- including ones caused by a field arriving
asynchronously that the list rows don't even display, e.g. getprop/dumpsys
metadata landing a few seconds after connect -- used to tear down and
rebuild the entire device list unconditionally. DevicePanel now only does
that when what the list would actually show has changed (prompt.md: "old
list == new list -> do nothing"). Automatic polling (DeviceManager's own
timer) still drives detection; there is no manual Refresh button anymore
(it called DeviceManager.refresh_now(), which was a redundant no-op most of
the time given the automatic poll -- removed rather than fixed).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.device.device_model import AndroidDevice, ConnectionState
from androidlink.device.manager import DeviceManager
from androidlink.ui.panels.device_panel import DevicePanel


def _make_panel(qtbot) -> DevicePanel:
    device_manager = DeviceManager()
    panel = DevicePanel(device_manager)
    qtbot.addWidget(panel)
    return panel


def test_identical_devices_changed_emission_does_not_rebuild_the_list(qtbot, monkeypatch):
    panel = _make_panel(qtbot)
    device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE)

    panel._on_devices_changed([device])
    rebuild_calls = []
    monkeypatch.setattr(panel, "_clear_device_list", lambda: rebuild_calls.append(1))

    # A brand new AndroidDevice instance, but with the exact same rendered
    # content -- e.g. what a routine poll tick produces for an unchanged
    # device. Must not be treated as a reason to rebuild.
    same_device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE)
    panel._on_devices_changed([same_device])

    assert rebuild_calls == []


def test_a_field_not_shown_in_the_list_does_not_trigger_a_rebuild(qtbot, monkeypatch):
    """refresh_rate_hz is real, useful data (shown in the active-device info
    label), but _build_device_row() never renders it -- getprop/dumpsys
    landing must not by itself count as "the device list changed"."""
    panel = _make_panel(qtbot)
    device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE)
    panel._on_devices_changed([device])

    rebuild_calls = []
    monkeypatch.setattr(panel, "_clear_device_list", lambda: rebuild_calls.append(1))

    device.refresh_rate_hz = 120
    device.supported_refresh_rates_hz = (60, 120)
    panel._on_devices_changed([device])

    assert rebuild_calls == []


def test_a_new_connection_state_does_trigger_a_rebuild(qtbot, monkeypatch):
    panel = _make_panel(qtbot)
    device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.OFFLINE)
    panel._on_devices_changed([device])

    rebuild_calls = []
    monkeypatch.setattr(panel, "_clear_device_list", lambda: rebuild_calls.append(1))

    device.connection_state = ConnectionState.DEVICE
    panel._on_devices_changed([device])

    assert rebuild_calls == [1]


def test_a_model_name_arriving_does_trigger_a_rebuild(qtbot, monkeypatch):
    """Unlike refresh_rate_hz, model *is* shown in the row (display_name
    falls back to it) -- this genuinely needs a rebuild."""
    panel = _make_panel(qtbot)
    device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE)
    panel._on_devices_changed([device])

    rebuild_calls = []
    monkeypatch.setattr(panel, "_clear_device_list", lambda: rebuild_calls.append(1))

    device.model = "Pixel 8"
    panel._on_devices_changed([device])

    assert rebuild_calls == [1]


def test_device_disappearing_triggers_a_rebuild(qtbot, monkeypatch):
    panel = _make_panel(qtbot)
    device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE)
    panel._on_devices_changed([device])

    rebuild_calls = []
    monkeypatch.setattr(panel, "_clear_device_list", lambda: rebuild_calls.append(1))

    panel._on_devices_changed([])

    assert rebuild_calls == [1]


def test_repeated_identical_emissions_never_accumulate_rebuilds(qtbot, monkeypatch):
    """The "refresh -> refresh -> refresh -> ..." loop scenario: many
    emissions in a row for an unchanged device must collapse to the one
    real rebuild, not one per emission."""
    panel = _make_panel(qtbot)
    device = AndroidDevice(serial="SERIAL1", connection_state=ConnectionState.DEVICE)

    rebuild_calls = []
    monkeypatch.setattr(panel, "_clear_device_list", lambda: rebuild_calls.append(1))

    for _ in range(5):
        panel._on_devices_changed([device])

    assert rebuild_calls == [1]  # only the first emission actually changed anything
