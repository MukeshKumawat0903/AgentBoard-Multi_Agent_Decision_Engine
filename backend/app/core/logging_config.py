"""
Structured logging configuration for AgentBoard.

Provides JSON-formatted log output for production observability
and human-readable output during development.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from app.core.request_context import get_request_id

_RESERVED_LOG_RECORD_ATTRS = set(logging.makeLogRecord({}).__dict__.keys()) | {"message"}
_BASE_RECORD_FACTORY = logging.getLogRecordFactory()


class RequestContextFilter(logging.Filter):
    """Inject request-scoped values into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id") or record.request_id is None:
            record.request_id = get_request_id()
        return True


def _record_factory(*args, **kwargs) -> logging.LogRecord:
    record = _BASE_RECORD_FACTORY(*args, **kwargs)
    if not hasattr(record, "request_id") or record.request_id is None:
        record.request_id = get_request_id()
    return record


logging.setLogRecordFactory(_record_factory)


class JSONFormatter(logging.Formatter):
    """Formats log records as JSON for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _RESERVED_LOG_RECORD_ATTRS and not key.startswith("_")
        }
        if extras:
            log_entry.update(extras)
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, default=str)


def setup_logging(log_level: str = "INFO") -> None:
    """
    Configure application-wide logging.

    Args:
        log_level: Logging level string (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    # Root agentboard logger
    logger = logging.getLogger("agentboard")
    logger.setLevel(numeric_level)
    logging.setLogRecordFactory(_record_factory)

    # Avoid duplicate handlers on re-init
    if logger.handlers:
        logger.handlers.clear()
    if logger.filters:
        logger.filters.clear()

    formatter = JSONFormatter()
    context_filter = RequestContextFilter()
    logger.addFilter(context_filter)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler – daily rotating, kept for 30 days
    # Resolves to: backend/logs/agentboard_YYYY-MM-DD.log
    logs_dir = Path(__file__).resolve().parent.parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = logs_dir / f"agentboard_{today}.log"

    file_handler = TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
        utc=False,
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    # Suffix so rotated files are named agentboard_YYYY-MM-DD.log.YYYY-MM-DD
    file_handler.suffix = "%Y-%m-%d"
    logger.addHandler(file_handler)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger.info("Logging initialized", extra={"log_level": log_level, "log_file": str(log_file)})
