from androidlink.utils.latest_value_box import LatestValueBox


def test_take_returns_none_when_empty():
    box: LatestValueBox[int] = LatestValueBox()
    assert box.take() is None


def test_put_then_take_roundtrips():
    box: LatestValueBox[int] = LatestValueBox()
    box.put(42)
    assert box.take() == 42
    assert box.take() is None  # consumed


def test_overwriting_an_unread_value_counts_as_dropped():
    box: LatestValueBox[int] = LatestValueBox()
    box.put(1)
    box.put(2)  # overwrites 1 before it was ever read
    box.put(3)  # overwrites 2

    assert box.take() == 3
    assert box.take_dropped_count() == 2


def test_take_dropped_count_resets_after_reading():
    box: LatestValueBox[int] = LatestValueBox()
    box.put(1)
    box.put(2)
    assert box.take_dropped_count() == 1
    assert box.take_dropped_count() == 0


def test_no_drop_counted_when_value_is_read_between_puts():
    box: LatestValueBox[int] = LatestValueBox()
    box.put(1)
    box.take()
    box.put(2)
    assert box.take_dropped_count() == 0
