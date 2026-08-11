"""Maps widget-local pixel positions to Android video-frame coordinates.

This is the single source of truth for the letterboxed aspect-ratio-preserving
layout: VideoRenderWidget.paintEvent() and the mouse input handler both use
compute_video_rect() so a click always lands exactly where the pixel appears
on screen, even as the window is resized, the device rotates, or the video
session restarts at a different resolution (prompt.md section 9).
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt


def compute_video_rect(widget_size: QSize, frame_size: QSize) -> QRectF:
    """The centered, aspect-ratio-preserving rect the video frame is drawn
    into within a widget of the given size. Empty if either size is empty."""
    if widget_size.isEmpty() or frame_size.isEmpty():
        return QRectF()

    scaled = frame_size.scaled(widget_size, Qt.AspectRatioMode.KeepAspectRatio)
    x = (widget_size.width() - scaled.width()) / 2
    y = (widget_size.height() - scaled.height()) / 2
    return QRectF(x, y, scaled.width(), scaled.height())


def map_widget_point_to_frame(
    widget_pos: QPointF, widget_size: QSize, frame_size: QSize
) -> QPointF | None:
    """Convert a point in widget-local pixel coordinates to a point in video
    frame coordinates (i.e. what to send as x/y in a touch event, with
    screen_size = frame_size). Returns None if the point falls in the
    letterbox padding, outside the actual video image."""
    rect = compute_video_rect(widget_size, frame_size)
    if rect.isEmpty() or not rect.contains(widget_pos):
        return None

    relative_x = (widget_pos.x() - rect.x()) / rect.width()
    relative_y = (widget_pos.y() - rect.y()) / rect.height()
    return QPointF(relative_x * frame_size.width(), relative_y * frame_size.height())


def clamp_widget_point_to_frame(
    widget_pos: QPointF, widget_size: QSize, frame_size: QSize
) -> QPointF | None:
    """Like map_widget_point_to_frame, but clamps points in the letterbox
    padding to the nearest edge instead of returning None — used for drag
    events, where the pointer may briefly leave the video image while a
    button is still held (prompt.md section 9: drag/swipe must keep working)."""
    rect = compute_video_rect(widget_size, frame_size)
    if rect.isEmpty():
        return None

    clamped_x = min(max(widget_pos.x(), rect.left()), rect.right())
    clamped_y = min(max(widget_pos.y(), rect.top()), rect.bottom())
    relative_x = (clamped_x - rect.x()) / rect.width()
    relative_y = (clamped_y - rect.y()) / rect.height()
    return QPointF(relative_x * frame_size.width(), relative_y * frame_size.height())
