"""PC-side screenshot capture (prompt.md section 14). Saves a single
decoded RGB24 frame to a PNG file, reusing the same zero-copy RGB888
QImage construction as streaming/renderer.py's VideoRenderWidget.set_frame().
"""

from pathlib import Path

import numpy as np
from PySide6.QtGui import QImage


def save_screenshot(frame: np.ndarray, path: Path) -> bool:
    if not frame.flags["C_CONTIGUOUS"]:
        frame = np.ascontiguousarray(frame)

    height, width, _channels = frame.shape
    image = QImage(frame.data, width, height, frame.strides[0], QImage.Format.Format_RGB888)
    return image.save(str(path), "PNG")
