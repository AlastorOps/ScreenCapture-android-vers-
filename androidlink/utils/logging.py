import logging
from logging.handlers import RotatingFileHandler

from androidlink.utils.platform import get_logs_dir

LOG_FILENAME = "androidlink.log"
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 5

_FORMAT = "%(asctime)s %(levelname)-8s %(name)s:%(lineno)d %(message)s"

_LEVEL_NAME_TO_INT = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def resolve_log_level(logging_level: str, debug_mode: bool) -> int:
    """Maps settings.general's logging_level/debug_mode (prompt.md section
    27's Diagnostics > Logging/Debug mode) to a stdlib logging level.
    debug_mode wins outright -- it's meant as a one-click "give me
    everything" override of whatever level is otherwise selected."""
    if debug_mode:
        return logging.DEBUG
    return _LEVEL_NAME_TO_INT.get(logging_level, logging.INFO)


def set_log_level(level: int) -> None:
    """Applies a new level to the already-configured root logger (e.g. when
    the user changes Diagnostics settings while the app is running) without
    tearing down and recreating the file/console handlers setup_logging()
    installed at startup."""
    logging.getLogger().setLevel(level)


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    formatter = logging.Formatter(_FORMAT)

    log_path = get_logs_dir() / LOG_FILENAME
    file_handler = RotatingFileHandler(
        log_path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    _setup_av_logging()

    logging.getLogger(__name__).info("Logging initialized (%s)", log_path)


def _setup_av_logging() -> None:
    """Route PyAV/FFmpeg's own internal decode/encode logs (e.g. corrupt
    bitstream warnings, unsupported profile features) into our logger —
    PyAV logs through Python's stdlib `logging` under `libav.*` loggers once
    a level is set, but does nothing until we opt in here."""
    try:
        import av.logging

        av.logging.set_level(av.logging.WARNING)
    except ImportError:
        pass
