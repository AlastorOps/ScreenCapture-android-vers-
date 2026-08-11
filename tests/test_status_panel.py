import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.streaming.diagnostics import DiagnosticsSample
from androidlink.ui.panels.status_panel import StatusPanel, _format_bitrate


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
    )
    panel.set_stream_stats(sample)

    assert panel._value_labels["stream_fps"].text() == "60"
    assert panel._value_labels["dropped"].text() == "3"
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
    panel.reset_stream_stats()

    for key in ("stream_fps", "render_fps", "dropped", "decode", "bitrate", "resolution", "codec"):
        assert panel._value_labels[key].text() == "—"


def test_set_render_fps_and_system_stats(qtbot):
    panel = StatusPanel()
    qtbot.addWidget(panel)

    panel.set_render_fps(29.6)
    assert panel._value_labels["render_fps"].text() == "30"

    panel.set_system_stats(12.3, 456.7)
    assert panel._value_labels["cpu"].text() == "12%"
    assert panel._value_labels["ram"].text() == "457 MB"
