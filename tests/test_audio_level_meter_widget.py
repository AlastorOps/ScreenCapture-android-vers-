"""AudioLevelMeter's display smoothing (attack faster than release) and
theme independence -- it never reads a hardcoded color, only palette.
current()/current_accent() at paint time, same pattern as StatusDot/
ToggleSwitch/VideoRenderWidget.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from androidlink.ui.themes import palette
from androidlink.ui.widgets.audio_level_meter import AudioLevelMeter


def test_starts_at_zero(qtbot):
    meter = AudioLevelMeter()
    qtbot.addWidget(meter)
    assert meter._displayed_level == 0.0


def test_set_level_ramps_rather_than_jumping(qtbot):
    meter = AudioLevelMeter()
    qtbot.addWidget(meter)

    meter.set_level(1.0)

    assert 0.0 < meter._displayed_level < 1.0


def test_repeated_set_level_converges_to_the_target(qtbot):
    meter = AudioLevelMeter()
    qtbot.addWidget(meter)

    for _ in range(30):
        meter.set_level(0.8)

    assert abs(meter._displayed_level - 0.8) < 0.01


def test_attack_is_faster_than_release(qtbot):
    """Standard VU-meter ballistics (item 6: smooth without excessive
    flicker) -- rises quickly to a loud sound, decays more gradually."""
    rising = AudioLevelMeter()
    qtbot.addWidget(rising)
    rising.set_level(1.0)  # single step up from 0
    attack_step = rising._displayed_level

    falling = AudioLevelMeter()
    qtbot.addWidget(falling)
    for _ in range(30):
        falling.set_level(1.0)  # settle near 1.0
    falling.set_level(0.0)  # single step down
    release_step = 1.0 - falling._displayed_level

    assert attack_step > release_step


def test_reset_snaps_to_zero_immediately(qtbot):
    meter = AudioLevelMeter()
    qtbot.addWidget(meter)
    for _ in range(30):
        meter.set_level(1.0)
    assert meter._displayed_level > 0.9

    meter.reset()

    assert meter._displayed_level == 0.0


def test_set_level_clamps_out_of_range_input(qtbot):
    meter = AudioLevelMeter()
    qtbot.addWidget(meter)

    meter.set_level(5.0)
    assert meter._displayed_level <= 1.0

    meter.reset()
    meter.set_level(-3.0)
    assert meter._displayed_level >= 0.0


def test_paints_without_error_in_every_theme(qtbot):
    """Never hardcodes a color -- must render cleanly under every palette,
    dark and light alike."""
    meter = AudioLevelMeter()
    qtbot.addWidget(meter)
    meter.set_level(0.5)
    meter.show()

    original = palette.current()
    try:
        for preset in palette.PRESETS.values():
            palette.set_theme(preset.id)
            meter.repaint()  # must not raise regardless of theme
    finally:
        palette.set_theme(original.id)
