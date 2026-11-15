"""Celery application: broker, queues (with dead-lettering) and reliability settings."""

import os

from celery import Celery
from celery.signals import (
    before_task_publish,
    setup_logging,
    task_prerun,
    worker_init,
    worker_process_shutdown,
    worker_ready,
)
from kombu.entity import Exchange, Queue

from app.config import get_settings
from app.observability.correlation import bind_from_task_headers, inject_into_task_headers
from app.observability.logging import configure_logging
from app.observability.metrics import (
    mark_child_dead,
    reset_multiprocess_dir,
    serve_worker_metrics,
)

settings = get_settings()

DOCUMENTS_QUEUE = "documents"
DEAD_LETTER_EXCHANGE = "documents.dlx"
DEAD_LETTER_QUEUE = "documents.dlq"

documents_exchange = Exchange(DOCUMENTS_QUEUE, type="direct")
dead_letter_exchange = Exchange(DEAD_LETTER_EXCHANGE, type="direct")

celery_app = Celery("docintake", broker=settings.broker_url, include=["app.workers.tasks"])

celery_app.conf.update(
    # JSON only: never unpickle data coming off the network.
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    # State lives in Postgres (Document.status); we don't need a result backend.
    task_ignore_result=True,
    # Reliability: ack only after the task finishes, one message at a time per process.
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    # A task that fails for good is *rejected* (not acked) -> RabbitMQ dead-letters it.
    task_acks_on_failure_or_timeout=False,
    task_time_limit=300,
    task_soft_time_limit=240,
    task_default_queue=DOCUMENTS_QUEUE,
    task_queues=(
        Queue(
            DOCUMENTS_QUEUE,
            documents_exchange,
            routing_key=DOCUMENTS_QUEUE,
            queue_arguments={
                "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
                "x-dead-letter-routing-key": DEAD_LETTER_QUEUE,
            },
        ),
    ),
    task_always_eager=settings.celery_task_always_eager,
    # Workers consume only `documents` (-Q documents). The DLQ must exist anyway, or
    # RabbitMQ silently drops dead-lettered messages: see declare_dead_letter_queue().
    task_eager_propagates=False,
    worker_hijack_root_logger=False,
    broker_connection_retry_on_startup=True,
)

dead_letter_queue = Queue(DEAD_LETTER_QUEUE, dead_letter_exchange, routing_key=DEAD_LETTER_QUEUE)


@worker_ready.connect
def declare_dead_letter_queue(**_: object) -> None:
    """Declare the DLQ (exchange + queue + binding) without consuming from it.

    Consuming it would re-run permanently failed tasks; it is meant to be inspected
    (RabbitMQ UI) and replayed deliberately after the cause is fixed.
    """
    with celery_app.connection_for_write() as conn:
        dead_letter_queue.bind(conn).declare()


@setup_logging.connect
def _configure_worker_logging(**_: object) -> None:
    """Connecting this signal stops Celery from installing its own log handlers."""
    configure_logging(settings.log_level, settings.log_json)


# Correlation id: API -> message headers -> worker context -> next task's headers...
before_task_publish.connect(inject_into_task_headers, weak=False)
task_prerun.connect(bind_from_task_headers, weak=False)


# --- Prometheus (multiprocess: see app.observability.metrics) ------------------------


@worker_init.connect
def _reset_metrics(**_: object) -> None:
    reset_multiprocess_dir()  # parent process, before the children are forked


@worker_ready.connect
def _serve_metrics(**_: object) -> None:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        serve_worker_metrics(settings.worker_metrics_port)


@worker_process_shutdown.connect
def _child_exit(pid: int | None = None, **_: object) -> None:
    mark_child_dead(pid or os.getpid())
