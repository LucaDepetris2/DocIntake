"""Structured logging: JSON lines with level, timestamp and correlation_id.

Both structlog loggers (our code) and stdlib loggers (uvicorn, celery, sqlalchemy) go
through the same processor chain, so every line has the same shape and the same
redaction rules. Documents contain PHI: their content must never reach the logs.
"""

import logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog
from structlog.types import EventDict, Processor

REDACTED = "[redacted]"

# Keys whose values may contain document content, PHI or credentials.
SENSITIVE_KEYS = frozenset(
    {
        "extracted_text",
        "text",
        "entities",
        "client_name",
        "defendant",
        "people",
        "parties",
        "password",
        "token",
        "access_token",
        "authorization",
        "jwt_secret",
    }
)


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            k: REDACTED if str(k).lower() in SENSITIVE_KEYS else _redact(v)
            for k, v in value.items()
        }
    return value


def redact_sensitive(_: Any, __: str, event_dict: EventDict) -> EventDict:
    redacted: MutableMapping[str, Any] = _redact(event_dict)
    return dict(redacted)


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,  # adds correlation_id, document_id...
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        redact_sensitive,
    ]
    renderer: Processor = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,  # stdlib records get the same enrichment
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())

    # uvicorn installs its own handlers; route them through ours. Its access log is
    # replaced by our request log (which has the correlation id and duration).
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True
    logging.getLogger("uvicorn.access").disabled = True
