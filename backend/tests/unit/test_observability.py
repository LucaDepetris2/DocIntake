import json
import logging

import pytest
import structlog
from fastapi.testclient import TestClient

from app.observability.correlation import (
    CORRELATION_HEADER,
    TASK_HEADER,
    bind_from_task_headers,
    get_correlation_id,
    inject_into_task_headers,
    new_correlation_id,
)
from app.observability.logging import REDACTED, configure_logging, redact_sensitive


def test_redaction_removes_sensitive_fields_recursively() -> None:
    event = {
        "event": "stage done",
        "document_id": "abc",
        "extracted_text": "Patient Jane Doe ...",
        "password": "hunter2",
        "nested": {"client_name": "Jane Doe", "stage": "match"},
    }
    out = redact_sensitive(None, "info", event)
    assert out["document_id"] == "abc"
    assert out["extracted_text"] == REDACTED
    assert out["password"] == REDACTED
    assert out["nested"] == {"client_name": REDACTED, "stage": "match"}


def test_logs_are_json_with_correlation_id(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(level="INFO", json_logs=True)
    structlog.contextvars.bind_contextvars(correlation_id="cid-123")
    try:
        structlog.get_logger("test").info("hello", document_id="d1", extracted_text="secret")
        logging.getLogger("stdlib").warning("from stdlib")  # libraries go through the same pipeline
    finally:
        structlog.contextvars.clear_contextvars()

    lines = [json.loads(line) for line in capsys.readouterr().out.strip().splitlines()]
    first, second = lines[-2], lines[-1]
    assert first["event"] == "hello"
    assert first["correlation_id"] == "cid-123"
    assert first["extracted_text"] == REDACTED
    assert first["level"] == "info"
    assert "timestamp" in first
    assert second["event"] == "from stdlib"
    assert second["correlation_id"] == "cid-123"


def test_middleware_echoes_incoming_correlation_id(client: TestClient) -> None:
    resp = client.get("/health", headers={CORRELATION_HEADER: "req-42"})
    assert resp.headers[CORRELATION_HEADER] == "req-42"


def test_middleware_generates_id_when_missing_or_invalid(client: TestClient) -> None:
    generated = client.get("/health").headers[CORRELATION_HEADER]
    assert len(generated) == 32
    # Untrusted input: anything weird (log injection, huge values) is replaced.
    weird = client.get("/health", headers={CORRELATION_HEADER: "bad\nvalue"}).headers
    assert weird[CORRELATION_HEADER] != "bad\nvalue"


def test_correlation_id_travels_through_celery_headers() -> None:
    structlog.contextvars.bind_contextvars(correlation_id="from-api")
    headers: dict[str, object] = {}
    inject_into_task_headers(headers=headers)
    structlog.contextvars.clear_contextvars()

    class Request:
        pass

    setattr(Request, TASK_HEADER, headers[TASK_HEADER])

    class Task:
        request = Request()

    bind_from_task_headers(task=Task())
    try:
        assert get_correlation_id() == "from-api"
    finally:
        structlog.contextvars.clear_contextvars()


def test_task_without_header_gets_a_fresh_id() -> None:
    class Task:
        request = object()

    bind_from_task_headers(task=Task())
    try:
        assert get_correlation_id() not in (None, "")
    finally:
        structlog.contextvars.clear_contextvars()


def test_new_correlation_id_is_hex() -> None:
    assert int(new_correlation_id(), 16) >= 0
