import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

from androidlink.recording.screenshots import save_screenshot


def test_save_screenshot_writes_a_readable_png(qapp, tmp_path):
    frame = np.zeros((32, 48, 3), dtype=np.uint8)
    frame[:, :, 0] = 200  # solid red-ish fill

    path = tmp_path / "shot.png"
    assert save_screenshot(frame, path) is True
    assert path.exists()

    from PySide6.QtGui import QImage

    image = QImage(str(path))
    assert not image.isNull()
    assert image.width() == 48
    assert image.height() == 32


def test_save_screenshot_handles_non_contiguous_array(qapp, tmp_path):
    base = np.zeros((32, 32, 6), dtype=np.uint8)
    frame = base[:, :, :3]  # a view, not C-contiguous
    assert not frame.flags["C_CONTIGUOUS"]

    path = tmp_path / "shot2.png"
    assert save_screenshot(frame, path) is True
    assert path.exists()
