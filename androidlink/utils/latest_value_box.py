import threading
from typing import Generic, TypeVar

T = TypeVar("T")


class LatestValueBox(Generic[T]):
    """Holds at most one pending value, so a consumer that falls behind gets
    the newest value instead of a backlog of stale ones (prompt.md section
    34: prefer fresh frames over old ones). Thread-safe put/take."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: T | None = None

    def put(self, value: T) -> None:
        with self._lock:
            self._value = value

    def take(self) -> T | None:
        with self._lock:
            value, self._value = self._value, None
            return value
