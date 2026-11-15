"""Document lifecycle: the states a document goes through and which transitions are legal.

Pure domain logic (no DB, no Celery) so it can be unit-tested in isolation and reused
by the API, the workers and the review flow.
"""

from enum import StrEnum
from itertools import pairwise


class DocumentStatus(StrEnum):
    RECEIVED = "received"
    TEXT_EXTRACTED = "text_extracted"
    CLASSIFIED = "classified"
    ENTITIES_EXTRACTED = "entities_extracted"
    MATCHED = "matched"
    FILED = "filed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class DocumentType(StrEnum):
    MEDICAL_RECORD = "medical_record"
    MEDICAL_BILL = "medical_bill"
    PLEADING = "pleading"
    CORRESPONDENCE = "correspondence"
    DISCOVERY_REQUEST = "discovery_request"
    LIEN_NOTICE = "lien_notice"
    OTHER = "other"


PIPELINE_ORDER: tuple[DocumentStatus, ...] = (
    DocumentStatus.RECEIVED,
    DocumentStatus.TEXT_EXTRACTED,
    DocumentStatus.CLASSIFIED,
    DocumentStatus.ENTITIES_EXTRACTED,
    DocumentStatus.MATCHED,
    DocumentStatus.FILED,
)

TERMINAL_STATES: frozenset[DocumentStatus] = frozenset(
    {DocumentStatus.FILED, DocumentStatus.NEEDS_REVIEW, DocumentStatus.FAILED}
)


def _build_transitions() -> dict[DocumentStatus, frozenset[DocumentStatus]]:
    transitions: dict[DocumentStatus, set[DocumentStatus]] = {s: set() for s in DocumentStatus}
    for current, nxt in pairwise(PIPELINE_ORDER):
        transitions[current] |= {nxt, DocumentStatus.NEEDS_REVIEW, DocumentStatus.FAILED}
    # Human review resolves a document: assign a matter (matched) or file it directly.
    transitions[DocumentStatus.NEEDS_REVIEW] |= {
        DocumentStatus.MATCHED,
        DocumentStatus.FILED,
        DocumentStatus.FAILED,
    }
    # Manual retry re-runs the whole pipeline.
    transitions[DocumentStatus.FAILED] |= {DocumentStatus.RECEIVED}
    return {k: frozenset(v) for k, v in transitions.items()}


ALLOWED_TRANSITIONS = _build_transitions()


class InvalidTransitionError(ValueError):
    def __init__(self, current: DocumentStatus, target: DocumentStatus) -> None:
        super().__init__(f"Invalid transition {current} -> {target}")
        self.current = current
        self.target = target


def can_transition(current: DocumentStatus, target: DocumentStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def ensure_transition(current: DocumentStatus, target: DocumentStatus) -> None:
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)
