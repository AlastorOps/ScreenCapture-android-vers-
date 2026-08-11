from PySide6.QtCore import QPointF, QSize

from androidlink.input.touch_mapper import (
    clamp_widget_point_to_frame,
    compute_video_rect,
    map_widget_point_to_frame,
)


def test_compute_video_rect_matches_widget_when_aspect_ratio_equal():
    rect = compute_video_rect(QSize(1000, 500), QSize(1080, 540))
    assert rect.x() == 0
    assert rect.width() == 1000
    assert rect.height() == 500


def test_compute_video_rect_letterboxes_wider_widget():
    # Widget wider than the frame's aspect ratio -> pillarboxed (bars on sides)
    rect = compute_video_rect(QSize(1000, 500), QSize(500, 500))  # frame is square
    assert rect.width() == 500
    assert rect.height() == 500
    assert rect.x() == 250  # centered horizontally
    assert rect.y() == 0


def test_compute_video_rect_letterboxes_taller_widget():
    # Widget taller than the frame's aspect ratio -> letterboxed (bars top/bottom)
    rect = compute_video_rect(QSize(500, 1000), QSize(500, 500))
    assert rect.width() == 500
    assert rect.height() == 500
    assert rect.x() == 0
    assert rect.y() == 250


def test_compute_video_rect_empty_when_sizes_empty():
    assert compute_video_rect(QSize(0, 0), QSize(100, 100)).isEmpty()
    assert compute_video_rect(QSize(100, 100), QSize(0, 0)).isEmpty()


def test_map_widget_point_to_frame_center():
    widget_size = QSize(1000, 500)
    frame_size = QSize(1080, 540)  # same aspect ratio, no letterboxing

    point = map_widget_point_to_frame(QPointF(500, 250), widget_size, frame_size)

    assert point is not None
    assert abs(point.x() - 540) < 0.01
    assert abs(point.y() - 270) < 0.01


def test_map_widget_point_to_frame_top_left_corner():
    point = map_widget_point_to_frame(QPointF(0, 0), QSize(1000, 500), QSize(1080, 540))
    assert point is not None
    assert abs(point.x()) < 0.01
    assert abs(point.y()) < 0.01


def test_map_widget_point_to_frame_returns_none_in_letterbox_padding():
    # Frame is a narrow square inside a wide widget -> the left/right bars
    # are outside the actual video image.
    widget_size = QSize(1000, 500)
    frame_size = QSize(500, 500)

    point = map_widget_point_to_frame(QPointF(10, 250), widget_size, frame_size)

    assert point is None


def test_map_widget_point_to_frame_none_when_frame_size_empty():
    point = map_widget_point_to_frame(QPointF(10, 10), QSize(1000, 500), QSize(0, 0))
    assert point is None


def test_clamp_widget_point_to_frame_clamps_into_padding():
    widget_size = QSize(1000, 500)
    frame_size = QSize(500, 500)  # pillarboxed: video occupies x in [250, 750]

    point = clamp_widget_point_to_frame(QPointF(10, 250), widget_size, frame_size)

    assert point is not None
    assert abs(point.x()) < 0.01  # clamped to the left edge of the video image


def test_clamp_widget_point_to_frame_matches_map_inside_video_area():
    widget_size = QSize(1000, 500)
    frame_size = QSize(1080, 540)

    mapped = map_widget_point_to_frame(QPointF(500, 250), widget_size, frame_size)
    clamped = clamp_widget_point_to_frame(QPointF(500, 250), widget_size, frame_size)

    assert abs(mapped.x() - clamped.x()) < 0.01
    assert abs(mapped.y() - clamped.y()) < 0.01
