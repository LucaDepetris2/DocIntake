"""Celery tasks: thin wrappers that open a DB session and run one pipeline stage.

Error policy:
  * transient errors (DB/broker connectivity, timeouts) -> retried with exponential
    backoff + jitter, up to `task_max_retries`;
  * anything else, or retries exhausted -> document marked `failed` (sanitized error,
    no document content) and the message is rejected into the dead-letter queue.
"""

import uuid
from collections.abc import Callable
from typing import Any

from celery import Task, chain
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.processing.extraction import ExtractionError
from app.workers import stages
from app.workers.celery_app import celery_app

TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
    OperationalError,
    ConnectionError,
    TimeoutError,
)

# Our own exceptions carry messages written by us (safe to store); for anything else we
# keep only the type name, because library messages may echo document content or SQL.
SAFE_MESSAGE_ERRORS: tuple[type[Exception], ...] = (ExtractionError,)


def sanitize_error(stage: str, exc: BaseException) -> str:
    if isinstance(exc, SAFE_MESSAGE_ERRORS):
        return f"{stage}: {type(exc).__name__}: {exc}"
    if isinstance(exc, DBAPIError):
        return f"{stage}: {type(exc).__name__} (database error)"
    return f"{stage}: {type(exc).__name__}"


class PipelineTask(Task):
    autoretry_for = TRANSIENT_ERRORS
    retry_backoff = 2  # 2s, 4s, 8s, ...
    retry_backoff_max = 60
    retry_jitter = True  # spread retries so workers don't stampede a recovering DB
    max_retries = get_settings().task_max_retries
    acks_late = True

    def on_failure(
        self,
        exc: BaseException,
        task_id: str,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        einfo: Any,
    ) -> None:
        document_id = uuid.UUID(str(args[0] if args else kwargs["document_id"]))
        with get_sessionmaker()() as session:
            stages.mark_failed(session, document_id, sanitize_error(self.name, exc))


StageFn = Callable[[Session, uuid.UUID, stages.StageDeps], stages.StageOutcome]


def _run(task: Task, stage: StageFn, document_id: str) -> str:
    with get_sessionmaker()() as session:
        outcome = stage(session, uuid.UUID(document_id), stages.get_stage_deps())
    if outcome is not stages.StageOutcome.ADVANCED:
        # Needs review or already processed: stop the rest of the chain.
        task.request.chain = None
    return outcome.value


@celery_app.task(bind=True, base=PipelineTask, name="pipeline.extract_text")
def extract_text(self: Task, document_id: str) -> str:
    return _run(self, stages.stage_extract_text, document_id)


@celery_app.task(bind=True, base=PipelineTask, name="pipeline.classify")
def classify(self: Task, document_id: str) -> str:
    return _run(self, stages.stage_classify, document_id)


@celery_app.task(bind=True, base=PipelineTask, name="pipeline.extract_entities")
def extract_entities(self: Task, document_id: str) -> str:
    return _run(self, stages.stage_extract_entities, document_id)


@celery_app.task(bind=True, base=PipelineTask, name="pipeline.match")
def match(self: Task, document_id: str) -> str:
    return _run(self, stages.stage_match, document_id)


@celery_app.task(bind=True, base=PipelineTask, name="pipeline.file")
def file_document(self: Task, document_id: str) -> str:
    return _run(self, stages.stage_file, document_id)


def processing_chain(document_id: uuid.UUID) -> Any:
    """The full pipeline as a Celery chain. `.si` = immutable signature: every task gets
    only the document id and reloads state from Postgres (no data travels in messages)."""
    doc = str(document_id)
    return chain(
        extract_text.si(doc),
        classify.si(doc),
        extract_entities.si(doc),
        match.si(doc),
        file_document.si(doc),
    )
