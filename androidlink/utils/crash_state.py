"""A tiny, dependency-free "what was happening right before this" registry
for the crash handler (app/application.py's AndroidLinkApplication) to log
alongside an uncaught exception -- prompt.md: a crash report should include
current streaming state, current FPS state, device state, decoder state,
and transport state, not just the traceback.

Deliberately not a big observability framework: each component calls
update(component, **fields) whenever one of its key fields changes (session
started/stopped, target FPS resolved, device connected, etc.), overwriting
its own namespace each time. snapshot() returns the latest values for every
component that has ever reported in -- always genuinely-set values from the
components themselves, never guessed/fabricated.

update() is safe to call from any thread (guarded by a lock) since some
callers (e.g. decoder state) may eventually want to report from a worker
QThread, even though today's callers are all on the GUI thread.
"""

import threading

_lock = threading.Lock()
_state: dict[str, dict] = {}


def update(component: str, **fields: object) -> None:
    with _lock:
        _state.setdefault(component, {}).update(fields)


def snapshot() -> dict[str, dict]:
    with _lock:
        return {component: dict(fields) for component, fields in _state.items()}
