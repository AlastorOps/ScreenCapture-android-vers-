import threading
from typing import Generic, TypeVar

T = TypeVar("T")


class LatestValueBox(Generic[T]):
    """Holds at most one pending value, so a consumer that falls behind gets
    the newest value instead of a backlog of stale ones (prompt.md section
    34: prefer fresh frames over old ones). Thread-safe put/take.

    Tracks how many values were overwritten before ever being taken, so
    callers can report a genuine "dropped frames" count (prompt.md section
    20/34: measure real performance, never fabricate "0 dropped frames").
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: T | None = None
        self._dropped_count = 0

    def put(self, value: T) -> None:
        with self._lock:
            if self._value is not None:
                self._dropped_count += 1
            self._value = value

    def take(self) -> T | None:
        with self._lock:
            value, self._value = self._value, None
            return value

    def take_dropped_count(self) -> int:
        """Returns the number of values dropped since the last call, then
        resets the counter -- for periodic stats reporting."""
        with self._lock:
            count, self._dropped_count = self._dropped_count, 0
            return count
