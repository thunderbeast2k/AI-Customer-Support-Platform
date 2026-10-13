"""
Structured JSON Logging Module.
Formats application logs as single-line JSON entries suitable for cloud log aggregators
and local production environments, while strictly redacting sensitive fields.
"""
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict


REDACTED_KEYS = {"password", "token", "secret", "authorization", "api_key", "secret_key"}


class JSONLogFormatter(logging.Formatter):
    """Formats log records as JSON objects with standardized timestamps and levels."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Include extra attributes if passed in the log record
        if hasattr(record, "request_id"):
            log_entry["request_id"] = getattr(record, "request_id")
        if hasattr(record, "user_id"):
            log_entry["user_id"] = getattr(record, "user_id")
        if hasattr(record, "extra_data"):
            extra = getattr(record, "extra_data")
            if isinstance(extra, dict):
                # Redact potential sensitive fields
                cleaned_extra = {
                    k: ("[REDACTED]" if k.lower() in REDACTED_KEYS else v)
                    for k, v in extra.items()
                }
                log_entry["data"] = cleaned_extra

        # Include exception trace if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def setup_logging(log_level: str = "INFO", log_format: str = "json") -> None:
    """Configures root logger with JSON or standard formatting."""
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    console_handler = logging.StreamHandler(sys.stdout)
    if log_format.lower() == "json":
        console_handler.setFormatter(JSONLogFormatter())
    else:
        standard_formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d): %(message)s"
        )
        console_handler.setFormatter(standard_formatter)

    root_logger.addHandler(console_handler)

    # Silence overly verbose third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
