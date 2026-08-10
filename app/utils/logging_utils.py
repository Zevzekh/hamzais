"""Audit and application logging (specification section 52).

Every database changing operation emits a structured, greppable line:

``2026-08-10 15:41:22 | INFO | event=EXTENSION_CREATED application_id=EXT-2026-000001 user=user123``

Document contents are never logged - only metadata.
"""

from __future__ import annotations

import logging
from enum import Enum
from logging.handlers import RotatingFileHandler
from typing import Any

LOGGER_NAME = "extension_management"
_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured_for: str | None = None


class AuditEvent(str, Enum):
    """Named events written to the audit log."""

    USER_LOGIN = "USER_LOGIN"
    QVD_LOAD = "QVD_LOAD"
    QVD_LOOKUP = "QVD_LOOKUP"
    QVD_REFRESH = "QVD_REFRESH"
    EXTENSION_CREATED = "EXTENSION_CREATED"
    EXPORT_CREATED = "EXPORT_CREATED"
    EXPORT_FAILED = "EXPORT_FAILED"
    EXTENSION_DELETED = "EXTENSION_DELETED"
    EXTENSION_COMPLETED = "EXTENSION_COMPLETED"
    PARQUET_WRITE = "PARQUET_WRITE"
    PARQUET_WRITE_FAILED = "PARQUET_WRITE_FAILED"
    PARQUET_BACKUP = "PARQUET_BACKUP"
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    DOCUMENT_REJECTED = "DOCUMENT_REJECTED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    LOCK_TIMEOUT = "LOCK_TIMEOUT"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


def configure_logging(settings=None, *, force: bool = False) -> logging.Logger:
    """Attach a rotating file handler and a console handler once per process."""

    global _configured_for

    if settings is None:
        from app.config.settings import get_settings

        settings = get_settings()

    key = str(settings.log_file)
    logger = logging.getLogger(LOGGER_NAME)
    if _configured_for == key and not force:
        return logger

    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    logger.setLevel(getattr(logging, settings.log_level, logging.INFO))
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = RotatingFileHandler(
        settings.log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.WARNING)
    logger.addHandler(console)

    _configured_for = key
    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return an application logger. Logging config is applied lazily."""

    if _configured_for is None:
        try:
            configure_logging()
        except Exception:  # pragma: no cover - logging must never break the app
            logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)
    return logging.getLogger(LOGGER_NAME if not name else f"{LOGGER_NAME}.{name}")


def _render(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, Enum):
        value = value.value
    text = str(value)
    return text.replace(" ", "_") if " " in text else text


def format_event(event: AuditEvent | str, **fields: Any) -> str:
    parts = [f"event={_render(event)}"]
    parts.extend(f"{key}={_render(value)}" for key, value in fields.items())
    return " ".join(parts)


def log_event(
    logger: logging.Logger,
    event: AuditEvent | str,
    *,
    level: int = logging.INFO,
    **fields: Any,
) -> None:
    """Write one structured audit line."""

    logger.log(level, format_event(event, **fields))
