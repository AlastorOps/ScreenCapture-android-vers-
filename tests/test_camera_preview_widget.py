"""CameraPreviewWidget reuses VideoRenderWidget's real-frame rendering
wholesale (aspect-preserving, no stretch, no placeholder) -- these tests
cover only what it changes: focus policy and height bounds.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy

from androidlink.ui.widgets.camera_preview import CameraPreviewWidget


def test_does_not_accept_keyboard_focus(qtbot):
    """A small panel-embedded preview must never steal focus from the main
    screen mirror's keyboard control input."""
    widget = CameraPreviewWidget()
    qtbot.addWidget(widget)
    assert widget.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_renders_a_real_frame(qtbot):
    widget = CameraPreviewWidget()
    qtbot.addWidget(widget)
    frame = np.zeros((240, 320, 3), dtype=np.uint8)

    widget.set_frame(frame)

    assert widget.has_frame() is True
    assert widget.frame_size().width() == 320
    assert widget.frame_size().height() == 240


def test_clear_frame_removes_it(qtbot):
    widget = CameraPreviewWidget()
    qtbot.addWidget(widget)
    widget.set_frame(np.zeros((64, 64, 3), dtype=np.uint8))

    widget.clear_frame()

    assert widget.has_frame() is False


def test_has_a_substantial_minimum_height_and_no_maximum(qtbot):
    """"Camera UI fix" item 4: the preview used to be capped at a small
    fixed size (max 220px); it now has a much larger floor and no ceiling
    at all, so it can grow to fill whatever space the Status dock actually
    has -- see test_status_panel.py's resize test for the layout-level
    behavior this enables."""
    widget = CameraPreviewWidget()
    qtbot.addWidget(widget)
    assert widget.minimumHeight() >= 200
    assert widget.maximumHeight() == 16_777_215  # Qt's QWIDGETSIZE_MAX -- i.e. no cap set


def test_size_policy_is_expanding_on_both_axes(qtbot):
    widget = CameraPreviewWidget()
    qtbot.addWidget(widget)
    policy = widget.sizePolicy()
    assert policy.horizontalPolicy() == QSizePolicy.Policy.Expanding
    assert policy.verticalPolicy() == QSizePolicy.Policy.Expanding
