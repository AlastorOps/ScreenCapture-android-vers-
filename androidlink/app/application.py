import logging
import sys

from PySide6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


class AndroidLinkApplication(QApplication):
    def __init__(self) -> None:
        super().__init__(sys.argv)
        self.setApplicationName("AndroidLink")
        self.setOrganizationName("AndroidLink")
        sys.excepthook = self._handle_uncaught_exception

    @staticmethod
    def _handle_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:  # noqa: ANN001
        logger.critical(
            "Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback)
        )
