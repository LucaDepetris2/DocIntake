"""Prometheus metrics.

* API process: request latency/count (from the request middleware) and a business gauge
  (documents per status) computed from Postgres at scrape time.
* Worker processes: stage duration/outcome. Celery prefork runs several child processes,
  each with its own memory, so the worker uses prometheus_client's multiprocess mode
  (PROMETHEUS_MULTIPROC_DIR): children write samples to files, and the parent process
  serves the aggregate on WORKER_METRICS_PORT.
"""

import os
import shutil
from collections.abc import Callable, Iterator
from pathlib import Path

import structlog
from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    multiprocess,
    start_http_server,
)
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import Document

log = structlog.get_logger("app.metrics")

HTTP_REQUESTS = Counter("http_requests_total", "HTTP requests", ["method", "path", "status"])
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5),
)
STAGE_RUNS = Counter(
    "pipeline_stage_runs_total",
    "Pipeline stage executions by outcome (advanced/review/skipped/failed/retry)",
    ["stage", "outcome"],
)
STAGE_LATENCY = Histogram(
    "pipeline_stage_duration_seconds",
    "Pipeline stage duration",
    ["stage"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)


def observe_request(method: str, path: str, status: int, seconds: float) -> None:
    HTTP_REQUESTS.labels(method, path, str(status)).inc()
    HTTP_LATENCY.labels(method, path).observe(seconds)


def observe_stage(stage: str, outcome: str, seconds: float | None = None) -> None:
    STAGE_RUNS.labels(stage, outcome).inc()
    if seconds is not None:
        STAGE_LATENCY.labels(stage).observe(seconds)


class DocumentStatusCollector(Collector):
    """`docintake_documents{status}`: current documents per status (all firms).

    Read from the database on each scrape, so it's always correct, even with several API
    replicas or after restarts (a gauge kept in memory would drift)."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def collect(self) -> Iterator[GaugeMetricFamily]:
        gauge = GaugeMetricFamily("docintake_documents", "Documents by status", labels=["status"])
        try:
            with self.session_factory() as session:
                rows = session.execute(
                    select(Document.status, func.count()).group_by(Document.status)
                ).all()
        except SQLAlchemyError:
            # A DB outage must not break the scrape: the other metrics are still useful
            # (and the missing series is itself visible in Grafana).
            log.warning("document status metric unavailable")
            return
        for status, count in rows:
            gauge.add_metric([str(status)], count)
        yield gauge


_document_collector: DocumentStatusCollector | None = None


def register_document_collector(session_factory: Callable[[], Session]) -> None:
    """Idempotent: create_app() may run several times in one process (tests)."""
    global _document_collector
    if _document_collector is None:
        _document_collector = DocumentStatusCollector(session_factory)
        REGISTRY.register(_document_collector)
    else:
        _document_collector.session_factory = session_factory


# --- Worker (multiprocess) -----------------------------------------------------------


def reset_multiprocess_dir() -> None:
    """Called once in the worker parent before children start: drop stale samples."""
    directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if directory:
        shutil.rmtree(directory, ignore_errors=True)
        Path(directory).mkdir(parents=True, exist_ok=True)


def serve_worker_metrics(port: int) -> None:
    registry = CollectorRegistry()
    multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
    start_http_server(port, registry=registry)


def mark_child_dead(pid: int) -> None:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        multiprocess.mark_process_dead(pid)  # type: ignore[no-untyped-call]
