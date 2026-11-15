"""Pipeline stages as plain functions: (session, document_id, deps) -> StageOutcome.

They hold all the processing logic but know nothing about Celery, so they can be tested
with a SQLite session and no broker. Celery tasks (app.workers.tasks) are thin wrappers.

Idempotency: every stage first checks the document is in the status it expects, and
writes its result with a compare-and-set UPDATE (repositories.advance). A redelivered
message therefore becomes a no-op instead of duplicated work.
"""

import uuid
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import repositories as repo
from app.db.models import Alert, Document, FirmRuleSet, Matter
from app.domain.classification import Classifier, load_classifier
from app.domain.deadlines import compute_deadlines
from app.domain.entities import Entities, extract_entities
from app.domain.matching import MatterCandidate, match_matter
from app.domain.rules import FilingContext, FirmRules, apply_rules
from app.domain.states import DocumentStatus, DocumentType
from app.processing.extraction import extract_text
from app.storage import LocalStorage

MIN_TEXT_CHARS = 20


class StageOutcome(StrEnum):
    ADVANCED = "advanced"  # moved to the next pipeline status
    REVIEW = "review"  # stopped: needs a human
    SKIPPED = "skipped"  # not in the expected status (already done / redelivery)


@dataclass
class StageDeps:
    settings: Settings
    storage: LocalStorage
    classifier: Classifier


@lru_cache
def get_stage_deps() -> StageDeps:
    """Built once per worker process (loading the model is the expensive part)."""
    settings = get_settings()
    return StageDeps(
        settings=settings,
        storage=LocalStorage(settings.storage_dir),
        classifier=load_classifier(
            settings.classifier_model_path, settings.classification_threshold
        ),
    )


def _load(session: Session, document_id: uuid.UUID, expected: DocumentStatus) -> Document | None:
    # populate_existing: re-read from the DB, ignoring any stale copy in the session.
    document = session.get(Document, document_id, populate_existing=True)
    if document is None or document.status is not expected:
        return None
    return document


def _finish(
    session: Session,
    document_id: uuid.UUID,
    expected: DocumentStatus,
    target: DocumentStatus,
    detail: str,
    **fields: Any,
) -> StageOutcome:
    if not repo.advance(
        session, document_id, expected=expected, target=target, detail=detail, **fields
    ):
        session.rollback()
        return StageOutcome.SKIPPED  # another worker got there first
    session.commit()
    return StageOutcome.REVIEW if target is DocumentStatus.NEEDS_REVIEW else StageOutcome.ADVANCED


# --- 1. Text extraction ----------------------------------------------------------


def stage_extract_text(session: Session, document_id: uuid.UUID, deps: StageDeps) -> StageOutcome:
    expected = DocumentStatus.RECEIVED
    document = _load(session, document_id, expected)
    if document is None:
        return StageOutcome.SKIPPED

    result = extract_text(deps.storage.read(document.storage_path))
    readable = "".join(line for line in result.text.splitlines() if not line.startswith("[page"))
    fields: dict[str, Any] = {"extracted_text": result.text, "page_count": result.page_count}
    detail = f"{result.page_count} pages, {len(result.ocr_pages)} OCR"

    if len(readable.strip()) < MIN_TEXT_CHARS:
        return _finish(
            session,
            document_id,
            expected,
            DocumentStatus.NEEDS_REVIEW,
            detail,
            review_reason="No readable text (scanned document without OCR?)",
            **fields,
        )
    return _finish(session, document_id, expected, DocumentStatus.TEXT_EXTRACTED, detail, **fields)


# --- 2. Classification -------------------------------------------------------------


def stage_classify(session: Session, document_id: uuid.UUID, deps: StageDeps) -> StageOutcome:
    expected = DocumentStatus.TEXT_EXTRACTED
    document = _load(session, document_id, expected)
    if document is None:
        return StageOutcome.SKIPPED

    result = deps.classifier.classify(document.extracted_text or "")
    fields = {"doc_type": result.doc_type, "classification_confidence": result.confidence}
    detail = f"{result.doc_type} ({result.confidence:.2f}, {result.method})"

    if result.confidence < deps.settings.classification_threshold:
        return _finish(
            session,
            document_id,
            expected,
            DocumentStatus.NEEDS_REVIEW,
            detail,
            review_reason=f"Low classification confidence ({result.confidence:.2f})",
            **fields,
        )
    return _finish(session, document_id, expected, DocumentStatus.CLASSIFIED, detail, **fields)


# --- 3. Entity extraction ------------------------------------------------------------


def stage_extract_entities(
    session: Session, document_id: uuid.UUID, deps: StageDeps
) -> StageOutcome:
    expected = DocumentStatus.CLASSIFIED
    document = _load(session, document_id, expected)
    if document is None:
        return StageOutcome.SKIPPED

    entities = extract_entities(document.extracted_text or "")
    detail = f"{len(entities.case_numbers)} case numbers, {len(entities.all_dates())} dates"
    return _finish(
        session,
        document_id,
        expected,
        DocumentStatus.ENTITIES_EXTRACTED,
        detail,
        entities=entities.to_dict(),
    )


# --- 4. Matter matching --------------------------------------------------------------


def _candidates(session: Session, firm_id: uuid.UUID) -> list[MatterCandidate]:
    return [
        MatterCandidate(
            id=m.id,
            case_number=m.case_number,
            client_name=m.client_name,
            defendant=m.defendant,
            incident_date=m.incident_date,
        )
        for m in repo.list_matters(session, firm_id)
    ]


def stage_match(session: Session, document_id: uuid.UUID, deps: StageDeps) -> StageOutcome:
    expected = DocumentStatus.ENTITIES_EXTRACTED
    document = _load(session, document_id, expected)
    if document is None:
        return StageOutcome.SKIPPED

    entities = Entities.from_dict(document.entities or {})
    decision = match_matter(
        entities,
        document.extracted_text or "",
        _candidates(session, document.firm_id),
        auto=deps.settings.match_auto_threshold,
        review=deps.settings.match_review_threshold,
    )
    fields: dict[str, Any] = {
        "matter_id": decision.matter_id,  # on review: the suggestion for the human
        "match_confidence": decision.confidence,
        "entities": {
            **(document.entities or {}),
            "match_candidates": [
                {"matter_id": str(mid), "score": score} for mid, score in decision.candidates
            ],
        },
    }
    detail = f"{decision.outcome} ({decision.confidence:.2f})"
    if decision.outcome != "auto":
        return _finish(
            session,
            document_id,
            expected,
            DocumentStatus.NEEDS_REVIEW,
            detail,
            review_reason=f"Matter match needs confirmation: {decision.reason}",
            **fields,
        )
    return _finish(session, document_id, expected, DocumentStatus.MATCHED, detail, **fields)


# --- 5 + 6. Filing rules and deadline alerts -------------------------------------------


def firm_rules(session: Session, firm_id: uuid.UUID) -> FirmRules:
    row = session.get(FirmRuleSet, firm_id)
    return FirmRules.model_validate(row.config) if row else FirmRules()


def _document_date(doc_type: DocumentType, entities: Entities) -> Any:
    for label in ("service", "signed", "statement", "hearing", "mentioned"):
        if entities.dates.get(label):
            return entities.dates[label][-1] if label == "mentioned" else entities.dates[label][0]
    return None


def _create_alerts(session: Session, document: Document, entities: Entities) -> int:
    deadlines = compute_deadlines(
        document.doc_type or DocumentType.OTHER, entities, document.extracted_text or ""
    )
    existing = set(session.scalars(select(Alert.kind).where(Alert.document_id == document.id)))
    created = 0
    for deadline in deadlines:
        if deadline.kind in existing:
            continue  # idempotent: re-filing does not duplicate alerts
        session.add(
            Alert(
                firm_id=document.firm_id,
                document_id=document.id,
                matter_id=document.matter_id,
                kind=deadline.kind,
                due_date=deadline.due_date,
                description=deadline.description,
            )
        )
        created += 1
    return created


def stage_file(session: Session, document_id: uuid.UUID, deps: StageDeps) -> StageOutcome:
    expected = DocumentStatus.MATCHED
    document = _load(session, document_id, expected)
    if document is None:
        return StageOutcome.SKIPPED

    # Documents resolved by a human may have skipped entity extraction.
    entities_dict = document.entities
    if not entities_dict or "case_numbers" not in entities_dict:
        entities_dict = {
            **(entities_dict or {}),
            **extract_entities(document.extracted_text or "").to_dict(),
        }
    entities = Entities.from_dict(entities_dict)
    matter = session.get(Matter, document.matter_id) if document.matter_id else None
    doc_type = document.doc_type or DocumentType.OTHER

    decision = apply_rules(
        firm_rules(session, document.firm_id),
        FilingContext(
            doc_type=doc_type,
            case_number=matter.case_number if matter else None,
            client_name=matter.client_name if matter else None,
            document_date=_document_date(doc_type, entities),
            provider=entities.providers[0] if entities.providers else None,
            original_filename=document.original_filename,
        ),
    )
    alerts = _create_alerts(session, document, entities)
    return _finish(
        session,
        document_id,
        expected,
        DocumentStatus.FILED,
        f"{decision.folder}/{decision.filed_name}; {alerts} alerts",
        filed_name=decision.filed_name,
        filed_folder=decision.folder,
        assignee=decision.assignee,
        entities=entities_dict,
        review_reason=None,
    )


PIPELINE = (
    stage_extract_text,
    stage_classify,
    stage_extract_entities,
    stage_match,
    stage_file,
)


def run_pipeline(session: Session, document_id: uuid.UUID, deps: StageDeps) -> DocumentStatus:
    """Run every stage in-process (used by tests and the eager mode)."""
    for stage in PIPELINE:
        if stage(session, document_id, deps) is StageOutcome.REVIEW:
            break
    session.expire_all()
    # populate_existing: re-read from the DB, ignoring any stale copy in the session.
    document = session.get(Document, document_id, populate_existing=True)
    assert document is not None  # noqa: S101
    return document.status


def mark_failed(session: Session, document_id: uuid.UUID, error: str) -> bool:
    """Move a document to FAILED (from any non-final status). Returns False if not applicable."""
    # populate_existing: re-read from the DB, ignoring any stale copy in the session.
    document = session.get(Document, document_id, populate_existing=True)
    if document is None or document.status in (DocumentStatus.FILED, DocumentStatus.FAILED):
        return False
    repo.transition(session, document, DocumentStatus.FAILED, detail=error[:500])
    document.error = error[:1000]
    session.commit()
    return True
