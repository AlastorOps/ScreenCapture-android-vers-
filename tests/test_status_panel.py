import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from androidlink.streaming.diagnostics import DiagnosticsSample
from androidlink.ui.panels.status_panel import StatusPanel, _format_bitrate
from androidlink.ui.widgets.status_dot import StatusState


def test_format_bitrate_scales_units():
    assert _format_bitrate(500) == "500 bps"
    assert _format_bitrate(2_500) == "2 kbps"
    assert _format_bitrate(24_500_000) == "24.5 Mbps"


def test_set_stream_stats_updates_labels(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)

    sample = DiagnosticsSample(
        stream_fps=59.8,
        dropped_frames=3,
        decode_latency_ms=4.2,
        bitrate_bps=24_500_000,
        resolution=(2560, 1440),
        codec="h264",
        late_frames=1,
    )
    panel.set_stream_stats(sample)

    assert panel._value_labels["stream_fps"].text() == "59.8"
    assert panel._value_labels["dropped"].text() == "3"
    assert panel._value_labels["late"].text() == "1"
    assert panel._value_labels["decode"].text() == "4.2 ms"
    assert panel._value_labels["bitrate"].text() == "24.5 Mbps"
    assert panel._value_labels["resolution"].text() == "2560 × 1440"
    assert panel._value_labels["codec"].text() == "H264"


def test_set_stream_stats_shows_hardware_decode_status(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)

    hw_sample = DiagnosticsSample(
        stream_fps=60.0, dropped_frames=0, decode_latency_ms=1.0, bitrate_bps=1_000_000,
        resolution=(1920, 1080), codec="h264", hardware_decode=True,
    )
    panel.set_stream_stats(hw_sample)
    assert panel._value_labels["codec"].text() == "H264 (HW)"

    sw_sample = DiagnosticsSample(
        stream_fps=60.0, dropped_frames=0, decode_latency_ms=1.0, bitrate_bps=1_000_000,
        resolution=(1920, 1080), codec="h264", hardware_decode=False,
    )
    panel.set_stream_stats(sw_sample)
    assert panel._value_labels["codec"].text() == "H264 (SW)"


def test_reset_stream_stats_clears_to_em_dash(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)

    sample = DiagnosticsSample(
        stream_fps=60.0,
        dropped_frames=0,
        decode_latency_ms=1.0,
        bitrate_bps=1_000_000,
        resolution=(1920, 1080),
        codec="h264",
    )
    panel.set_stream_stats(sample)
    panel.set_target_fps(165)
    panel.set_display_refresh(165)
    panel.set_max_supported_refresh((60, 90, 120, 144, 165))
    panel.reset_stream_stats()

    for key in (
        "display_refresh",
        "max_supported_refresh",
        "target_fps",
        "stream_fps",
        "render_fps",
        "dropped",
        "late",
        "decode",
        "bitrate",
        "resolution",
        "codec",
    ):
        assert panel._value_labels[key].text() == "—"


def test_set_performance_quality_survives_reset_stream_stats(qtbot):
    # Unlike the stream-scoped rows, Performance/Quality reflects a current
    # setting (the Device panel slider position), not a live measurement --
    # it must stay visible across a cast session stopping.
    panel = StatusPanel()
    qtbot.addWidget(panel)

    panel.set_performance_quality(70)
    assert panel._value_labels["performance_quality"].text() == "70%"

    panel.reset_stream_stats()
    assert panel._value_labels["performance_quality"].text() == "70%"


def test_set_target_fps_and_display_refresh(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)

    panel.set_target_fps(165)
    assert panel._value_labels["target_fps"].text() == "165"

    panel.set_display_refresh(165)
    assert panel._value_labels["display_refresh"].text() == "165 Hz"

    panel.set_display_refresh(None)
    assert panel._value_labels["display_refresh"].text() == "—"


def test_set_max_supported_refresh(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)

    # Item 4/5: active vs supported are distinct rows -- max supported must
    # reflect the highest of the list, independent of the active rate.
    panel.set_display_refresh(60)
    panel.set_max_supported_refresh((60, 90, 120))

    assert panel._value_labels["display_refresh"].text() == "60 Hz"
    assert panel._value_labels["max_supported_refresh"].text() == "120 Hz"

    panel.set_max_supported_refresh(None)
    assert panel._value_labels["max_supported_refresh"].text() == "—"

    panel.set_max_supported_refresh(())
    assert panel._value_labels["max_supported_refresh"].text() == "—"


def test_set_render_fps_and_system_stats(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)

    panel.set_render_fps(29.6)
    assert panel._value_labels["render_fps"].text() == "29.6"

    panel.set_system_stats(12.3, 456.7)
    assert panel._value_labels["cpu"].text() == "12%"
    assert panel._value_labels["ram"].text() == "457 MB"


def test_camera_preview_defaults_to_disconnected_with_no_frame(qtbot):
    # A fresh StatusPanel reports the same idle default as the widget did
    # before moving here (device_panel.py used to own this) -- "Disabled"
    # is reserved for "a real device is present but Camera is off".
    panel = StatusPanel()
    qtbot.addWidget(panel)

    assert panel._camera_preview_status_text.text() == "Disabled"
    assert panel._camera_preview_status_dot.state() == StatusState.DISCONNECTED
    assert panel._camera_preview_widget.has_frame() is False
    assert panel._camera_preview_label.text() == "Camera: —"


def test_set_camera_preview_frame_shows_it_and_marks_active(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)
    frame = np.zeros((100, 100, 3), dtype=np.uint8)

    panel.set_camera_preview_frame(frame)

    assert panel._camera_preview_widget.has_frame() is True
    assert panel._camera_preview_status_text.text() == "Active"
    assert panel._camera_preview_status_dot.state() == StatusState.CONNECTED


def test_camera_preview_status_transitions(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)
    panel.set_camera_preview_frame(np.zeros((10, 10, 3), dtype=np.uint8))

    panel.set_camera_preview_status_connecting()
    assert panel._camera_preview_status_text.text() == "Connecting…"

    panel.set_camera_preview_frame(np.zeros((10, 10, 3), dtype=np.uint8))
    panel.set_camera_preview_status_disabled()
    assert panel._camera_preview_status_text.text() == "Disabled"
    assert panel._camera_preview_widget.has_frame() is False  # released

    panel.set_camera_preview_frame(np.zeros((10, 10, 3), dtype=np.uint8))
    panel.set_camera_preview_status_disconnected()
    assert panel._camera_preview_status_text.text() == "Disconnected"
    assert panel._camera_preview_widget.has_frame() is False  # released
    assert panel._camera_preview_label.text() == "Camera: —"


def test_set_camera_preview_label(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)
    panel.set_camera_preview_label("Rear camera (1920x1080)")
    assert panel._camera_preview_label.text() == "Camera: Rear camera (1920x1080)"


def test_camera_preview_grows_with_the_panel_and_stays_large(qtbot):
    """Item 4/5 of the "camera UI fix" request: the preview must use
    available space rather than stay pinned at a small fixed size, and must
    grow as the Status dock is resized -- verified against real Qt layout
    geometry (offscreen platform still computes real widget sizes), not
    just that a size policy was set."""
    panel = StatusPanel()
    qtbot.addWidget(panel)
    panel.show()

    panel.resize(260, 500)
    qtbot.wait(0)
    short_height = panel._camera_preview_widget.height()
    # Substantially larger than the old 80px-tall/220px-capped preview even
    # at a modest dock height.
    assert short_height >= 200

    panel.resize(260, 900)
    qtbot.wait(0)
    tall_height = panel._camera_preview_widget.height()
    assert tall_height > short_height  # claimed the extra vertical room

    panel.resize(480, 900)
    qtbot.wait(0)
    wide_width = panel._camera_preview_widget.width()
    panel.resize(260, 900)
    qtbot.wait(0)
    narrow_width = panel._camera_preview_widget.width()
    assert wide_width > narrow_width  # claimed the extra horizontal room too

    # The rows below the preview must still be present and sized, not
    # crushed to nothing or pushed off-panel by the preview's growth.
    assert panel._camera_preview_label.isVisible()
    assert panel._camera_preview_status_text.isVisible()
    assert panel._screenshot_button.isVisible()
