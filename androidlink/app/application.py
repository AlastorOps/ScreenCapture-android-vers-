import logging
import sys
import threading

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from androidlink.utils import crash_state
from androidlink.utils.platform import get_resource_path

logger = logging.getLogger(__name__)


class AndroidLinkApplication(QApplication):
    """Installs two crash-diagnostic hooks so an unhandled exception is
    always recorded to the existing log file (androidlink.log) with full
    context, rather than the app just vanishing:

    - sys.excepthook: catches exceptions that reach the top of the main
      (GUI) thread's call stack -- this covers essentially every Qt slot in
      this codebase, since almost all of them (including callbacks invoked
      via queued cross-thread signals from the worker QThreads) ultimately
      execute as part of the main thread's event loop.
    - threading.excepthook: catches exceptions on a genuine Python
      threading.Thread, for completeness/defense-in-depth (this codebase
      doesn't currently spawn any directly -- all background work runs on
      QThreads, which are dispatched through Qt's own event loop rather
      than Python's threading module -- but installing this costs nothing
      and covers it if that ever changes).

    Neither hook *handles* the crash in the sense of recovering from it --
    per prompt.md's crash-investigation guidance, hiding the exception would
    make the real bug harder to find, not easier. They exist purely to make
    sure a genuine crash always leaves behind the exception type, message,
    full traceback, and a snapshot of what the app's key components were
    doing right before it happened (see utils/crash_state.py) -- then let
    the exception continue exactly as it would have otherwise.
    """

    def __init__(self) -> None:
        super().__init__(sys.argv)
        self.setApplicationName("AndroidLink")
        self.setOrganizationName("AndroidLink")
        # Sets the icon for every window (title bar, taskbar, Alt-Tab) that
        # doesn't set its own -- MainWindow and every dialog inherit this
        # automatically. .ico (not .png) so Windows gets the pre-rendered
        # 16/32/48 px frames for crisp small icons instead of downscaling
        # one large image (see packaging/generate_icon.py).
        icon_path = get_resource_path("androidlink/assets/icons/androidlink.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        sys.excepthook = self._handle_uncaught_exception
        threading.excepthook = self._handle_uncaught_thread_exception

    @staticmethod
    def _handle_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:  # noqa: ANN001
        logger.critical(
            "Uncaught exception -- current state: %s",
            crash_state.snapshot(),
            exc_info=(exc_type, exc_value, exc_traceback),
        )

    @staticmethod
    def _handle_uncaught_thread_exception(args) -> None:  # noqa: ANN001
        logger.critical(
            "Uncaught exception on thread %r -- current state: %s",
            args.thread.name if args.thread else "?",
            crash_state.snapshot(),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
