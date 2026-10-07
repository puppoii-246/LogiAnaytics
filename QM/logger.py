"""
Logger

Sets up the application-wide logger with simultaneous console (stderr) and
rotating file output. Log records are handed off through a queue to a single
background thread (QueueListener) that does the actual console/file I/O, so
that logging calls on the network/event threads never block on disk writes.
Call setup_logger() once at startup and shutdown_logger() once at shutdown
to flush and stop that background thread. All other modules obtain the same
logger via get_logger().
"""

import logging
import logging.handlers
import queue
from pathlib import Path
from typing import Optional

from config_manager import LoggingConfig

LOGGER_NAME = "qmds"

# Console: lightweight — time and level are enough for real-time watching
_CONSOLE_FMT      = "[{asctime}] {levelname:<8} | {message}"
_CONSOLE_DATEFMT  = "%H:%M:%S"

# File: detailed — module and line number help with post-analysis
_FILE_FMT         = "{asctime} | {levelname:<8} | {module}:{lineno} | {message}"
_FILE_DATEFMT     = "%Y-%m-%d %H:%M:%S"

_listener: Optional[logging.handlers.QueueListener] = None


def setup_logger(config: LoggingConfig, base_dir: Path) -> logging.Logger:
    """
    Configure and return the application logger.

    The logger only enqueues records (via QueueHandler); a background
    QueueListener thread performs the actual console/file writes. Safe to
    call multiple times — the previous listener is stopped and handlers are
    replaced, not duplicated.
    """
    global _listener

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(config.log_level)
    logger.handlers.clear()
    logger.propagate = False

    if _listener is not None:
        _listener.stop()
        _listener = None

    log_queue: queue.SimpleQueue = queue.SimpleQueue()
    logger.addHandler(logging.handlers.QueueHandler(log_queue))

    _listener = logging.handlers.QueueListener(
        log_queue,
        _console_handler(config.log_level),
        _file_handler(config, base_dir),
        respect_handler_level=True,
    )
    _listener.start()

    return logger


def shutdown_logger() -> None:
    """Flush pending records and stop the background logging thread."""
    global _listener
    if _listener is not None:
        _listener.stop()
        _listener = None


def get_logger() -> logging.Logger:
    """Return the application logger. Must be called after setup_logger()."""
    return logging.getLogger(LOGGER_NAME)


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _console_handler(log_level: str) -> logging.StreamHandler:
    handler = logging.StreamHandler()  # defaults to sys.stderr
    handler.setLevel(log_level)
    handler.setFormatter(
        logging.Formatter(fmt=_CONSOLE_FMT, datefmt=_CONSOLE_DATEFMT, style="{")
    )
    return handler


def _file_handler(config: LoggingConfig, base_dir: Path) -> logging.handlers.RotatingFileHandler:
    log_path = base_dir / config.log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    handler = logging.handlers.RotatingFileHandler(
        filename=log_path,
        maxBytes=config.rotation_policy.max_bytes,
        backupCount=config.rotation_policy.backup_count,
        encoding="utf-8",
    )
    handler.setLevel(config.log_level)
    handler.setFormatter(
        logging.Formatter(fmt=_FILE_FMT, datefmt=_FILE_DATEFMT, style="{")
    )
    return handler