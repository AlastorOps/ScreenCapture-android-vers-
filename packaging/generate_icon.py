"""Rasterizes packaging/androidlink_icon.svg into androidlink/assets/icons/
androidlink.ico -- a real multi-resolution Windows icon (16/32/48/64/128/256
px, each a genuine re-render of the vector source at that size via Qt's own
SVG renderer, not a single bitmap scaled up/down) used for AndroidLink.exe,
Uninstall.exe, the MSI's Add/Remove Programs entry, and the app's own window
icon at runtime.

No new dependency: PySide6 (already required) ships QtSvg, which this uses
for rendering. The .ico container itself is assembled by hand (see
_build_ico() below) rather than via a Pillow dependency -- ICO is a small,
well-documented format (an ICONDIR header + one ICONDIRENTRY per image,
each entry's payload being a plain PNG, which every Windows version since
Vista accepts) not worth adding a new library for.

Usage:
    python packaging/generate_icon.py
"""

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

REPO_ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = Path(__file__).resolve().parent / "androidlink_icon.svg"
ICO_PATH = REPO_ROOT / "androidlink" / "assets" / "icons" / "androidlink.ico"
PNG_PATH = REPO_ROOT / "androidlink" / "assets" / "icons" / "androidlink.png"

ICON_SIZES = (16, 32, 48, 64, 128, 256)


def _render_png(renderer: QSvgRenderer, size: int) -> bytes:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    data = bytes(buffer.data())
    buffer.close()
    return data


def _build_ico(images: list[tuple[int, bytes]]) -> bytes:
    """images: list of (size, png_bytes), largest-appropriate first is fine
    -- order doesn't matter, Windows picks by size/bit depth as needed."""
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)  # reserved, type=1 (icon), count

    entries = bytearray()
    payload = bytearray()
    offset = 6 + 16 * count  # header + one 16-byte ICONDIRENTRY per image

    for size, png_bytes in images:
        # width/height fields are bytes; 0 means "256" per the ICO spec.
        dim_byte = 0 if size >= 256 else size
        entry = struct.pack(
            "<BBBBHHII",
            dim_byte, dim_byte,
            0,  # color count (0 = not a palette image)
            0,  # reserved
            1,  # color planes
            32,  # bits per pixel
            len(png_bytes),
            offset,
        )
        entries += entry
        payload += png_bytes
        offset += len(png_bytes)

    return bytes(header) + bytes(entries) + bytes(payload)


def main() -> None:
    app = QApplication.instance() or QApplication([])

    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        raise SystemExit(f"error: could not parse {SVG_PATH}")

    images = [(size, _render_png(renderer, size)) for size in ICON_SIZES]

    ICO_PATH.parent.mkdir(parents=True, exist_ok=True)
    ICO_PATH.write_bytes(_build_ico(images))

    # Also keep a standalone 256px PNG -- handy for anything that wants a
    # plain raster image rather than an .ico container (e.g. quick preview).
    largest = next(png for size, png in images if size == max(ICON_SIZES))
    PNG_PATH.write_bytes(largest)

    print(f"Wrote {ICO_PATH} ({ICO_PATH.stat().st_size} bytes, sizes {ICON_SIZES})")
    print(f"Wrote {PNG_PATH}")


if __name__ == "__main__":
    main()
