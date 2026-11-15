"""Correlation id: one id per upload, carried from the HTTP request through every
Celery task of the pipeline, and attached to every log line via structlog contextvars."""

import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import Request, Response

from app.observability.metrics import observe_request

CORRELATION_HEADER = "X-Correlation-ID"
# Not "correlation_id": that name is an AMQP message property Celery already fills with
# the task id, so it would silently shadow ours.
TASK_HEADER = "x_correlation_id"
_VALID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")  # untrusted input: no log injection

log = structlog.get_logger("app.request")


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def get_correlation_id() -> str | None:
    value = structlog.contextvars.get_contextvars().get("correlation_id")
    return str(value) if value is not None else None


async def correlation_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    incoming = request.headers.get(CORRELATION_HEADER, "")
    correlation_id = incoming if _VALID.match(incoming) else new_correlation_id()
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id)

    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers[CORRELATION_HEADER] = correlation_id
        return response
    finally:
        seconds = time.perf_counter() - started
        route = request.scope.get("route")
        # The route template (/documents/{document_id}), not the raw path: keeps ids out
        # of logs and keeps metric label cardinality bounded. Unmatched paths share one
        # label so random URLs (scanners) can't explode the number of time series.
        path = getattr(route, "path", "<unmatched>")
        observe_request(request.method, path, status, seconds)
        log.info(
            "request",
            method=request.method,
            path=path,
            status=status,
            duration_ms=round(seconds * 1000, 1),
        )


# --- Celery propagation (connected to signals in app.workers.celery_app) -------------


def inject_into_task_headers(headers: dict[str, Any] | None = None, **_: Any) -> None:
    """before_task_publish: copy the current correlation id into the message headers."""
    correlation_id = get_correlation_id()
    if headers is not None and correlation_id:
        headers.setdefault(TASK_HEADER, correlation_id)


def bind_from_task_headers(task: Any = None, **_: Any) -> None:
    """task_prerun: restore the correlation id inside the worker (or start a new one)."""
    structlog.contextvars.clear_contextvars()
    correlation_id = getattr(getattr(task, "request", None), TASK_HEADER, None)
    structlog.contextvars.bind_contextvars(correlation_id=correlation_id or new_correlation_id())
