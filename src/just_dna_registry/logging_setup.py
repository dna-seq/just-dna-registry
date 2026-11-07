"""
Logging configuration. `REGISTRY_DEBUG=true` turns everything up to DEBUG on stdout so a live
server's console/journal shows exactly what happened — request tracing, the compiler/duckdb/uvicorn
internals, and the Eliot-structured publish/import steps.

Eliot messages (the app's structured action logs) are bridged into stdlib logging at DEBUG level,
so they surface only when debug is on and share one stdout stream with everything else.
"""

import copy
import json
import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from typing import Any

from eliot import add_destinations
from uvicorn.config import LOGGING_CONFIG

from just_dna_registry.config import Settings

# Third-party loggers that are too chatty at DEBUG — pinned to WARNING.
NOISY_LOGGERS: tuple[str, ...] = (
    "polars", "duckdb", "httpx", "httpcore", "multipart", "python_multipart",
    # huggingface-hub 2.0 sends its requests through these two, under their own logger names.
    "httpx2", "httpcore2",
    "huggingface_hub", "urllib3", "asyncio",
)

_eliot_wired = False

#: One line format for the terminal, the server's log file and a run's log.
LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"

_API_KEY = re.compile(r"\bmk_(live|test)_[A-Za-z0-9_-]+")


def redact(text: str) -> str:
    """A log that outlives the terminal (a run's log, the server's file) never holds an API key."""
    return _API_KEY.sub(lambda m: f"mk_{m.group(1)}_…(redacted)", text)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def log_file_handler(settings: Settings) -> RotatingFileHandler | None:
    """The server's own log file (`REGISTRY_LOG_FILE`), rotated by size, or `None` when unset.

    `serve` is not a maintenance run (its writes are requests), so before 0.28.4 a server's only log
    was its stdout, and a box answering 502 with its output lost left nothing to read. Plain text,
    API keys redacted, the parent directory created."""
    if settings.log_file is None:
        return None
    path = settings.log_file.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        path, maxBytes=settings.log_file_max_bytes, backupCount=settings.log_file_backups,
        encoding="utf-8", delay=True,
    )
    handler.setFormatter(RedactingFormatter(LOG_FORMAT))
    return handler


def uvicorn_log_config(settings: Settings) -> dict[str, Any]:
    """uvicorn's own logging config, plus the log file on its loggers when `REGISTRY_LOG_FILE` is set.

    uvicorn's loggers do not reach the root (`uvicorn.access` does not propagate, `uvicorn` has its own
    handler), and a worker that fails to import the app logs only through them. So the file goes on
    those loggers here, before the app exists, or the one failure the file is for would miss it."""
    config = copy.deepcopy(LOGGING_CONFIG)
    if settings.log_file is None:
        return config
    path = settings.log_file.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    config["formatters"]["registry_file"] = {"()": RedactingFormatter, "fmt": LOG_FORMAT}
    config["handlers"]["registry_file"] = {
        "class": "logging.handlers.RotatingFileHandler", "formatter": "registry_file",
        "filename": str(path), "maxBytes": settings.log_file_max_bytes,
        "backupCount": settings.log_file_backups, "encoding": "utf-8", "delay": True,
    }
    for name in ("uvicorn", "uvicorn.access"):
        config["loggers"][name]["handlers"] = [*config["loggers"][name]["handlers"], "registry_file"]
    return config


def _eliot_to_stdlib(message: dict) -> None:
    """Forward each Eliot message to the `eliot` stdlib logger as a JSON line (DEBUG)."""
    logging.getLogger("eliot").debug(json.dumps(message, default=str))


def configure_logging(settings: Settings) -> None:
    """Configure stdout logging from settings. Safe to call repeatedly (tests re-create the app)."""
    level = (
        logging.DEBUG
        if settings.debug
        else getattr(logging, settings.log_level.upper(), logging.INFO)
    )
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(LOG_FORMAT))
    handlers: list[logging.Handler] = [console]
    if (file := log_file_handler(settings)) is not None:
        handlers.append(file)
    logging.basicConfig(level=level, handlers=handlers, force=True)
    for name in NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    global _eliot_wired
    if not _eliot_wired:
        add_destinations(_eliot_to_stdlib)
        _eliot_wired = True

    logging.getLogger("registry").debug("logging configured (debug=%s)", settings.debug)
