"""AndroidLinkApplication's crash-diagnostic hooks -- both are @staticmethod,
so these call them directly without needing to construct a real QApplication
(only one is allowed per process, and pytest-qt's qapp fixture already owns
it). Verifies the hooks log full exception info *and* the current
crash_state snapshot -- prompt.md: never hide the crash, just make sure it
leaves behind everything needed to diagnose it.
"""

import logging
import sys
import types

from androidlink.app.application import AndroidLinkApplication
from androidlink.utils import crash_state


def test_handle_uncaught_exception_logs_type_message_traceback_and_state(caplog):
    crash_state.update("casting", state="running", target_fps=165)

    try:
        raise ValueError("boom")
    except ValueError:
        exc_type, exc_value, exc_tb = sys.exc_info()

    with caplog.at_level(logging.CRITICAL):
        AndroidLinkApplication._handle_uncaught_exception(exc_type, exc_value, exc_tb)

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelno == logging.CRITICAL
    assert "casting" in record.message
    assert "running" in record.message
    assert record.exc_info[0] is ValueError
    assert str(record.exc_info[1]) == "boom"
    assert record.exc_info[2] is not None  # a real traceback, not stripped


def test_handle_uncaught_thread_exception_logs_thread_name_and_state(caplog):
    crash_state.update("mic", state="starting")

    try:
        raise RuntimeError("thread boom")
    except RuntimeError:
        exc_type, exc_value, exc_tb = sys.exc_info()

    fake_thread = types.SimpleNamespace(name="worker-1")
    args = types.SimpleNamespace(
        exc_type=exc_type, exc_value=exc_value, exc_traceback=exc_tb, thread=fake_thread
    )

    with caplog.at_level(logging.CRITICAL):
        AndroidLinkApplication._handle_uncaught_thread_exception(args)

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert "worker-1" in record.message
    assert "mic" in record.message
    assert record.exc_info[0] is RuntimeError


def test_handle_uncaught_thread_exception_survives_a_missing_thread_name():
    args = types.SimpleNamespace(
        exc_type=RuntimeError, exc_value=RuntimeError("x"), exc_traceback=None, thread=None
    )

    AndroidLinkApplication._handle_uncaught_thread_exception(args)  # must not raise
