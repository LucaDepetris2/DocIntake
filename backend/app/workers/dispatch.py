"""Hand-off point between the API and the async pipeline.

The API depends on these two callables (injected via FastAPI dependencies), not on Celery
directly, so API tests can replace them with an in-memory list.
"""

import uuid
from collections.abc import Callable

Enqueuer = Callable[[uuid.UUID], None]


def enqueue_processing(document_id: uuid.UUID) -> None:
    """Publish the whole pipeline for a newly received (or retried) document."""
    from app.workers.tasks import processing_chain  # lazy: keep Celery out of API import time

    processing_chain(document_id).apply_async()


def enqueue_filing(document_id: uuid.UUID) -> None:
    """After human review: only the filing stage (rules + alerts) is left to run."""
    from app.workers.tasks import file_document

    file_document.apply_async(args=[str(document_id)])
