"""Human-in-the-loop endpoints: resolve reviews, retry failures, download the file."""

import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.api.deps import CurrentFirm, DbSession, EnqueuerDep, FilingEnqueuerDep, StorageDep
from app.api.schemas import DocumentDetail, ReviewDecision
from app.db import repositories as repo
from app.db.models import Document
from app.domain.states import DocumentStatus

router = APIRouter(prefix="/documents", tags=["review"])


def _get_or_404(session: DbSession, firm: CurrentFirm, document_id: uuid.UUID) -> Document:
    document = repo.get_document(session, firm.id, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return document


@router.post("/{document_id}/review")
def resolve_review(
    document_id: uuid.UUID,
    decision: ReviewDecision,
    session: DbSession,
    firm: CurrentFirm,
    enqueue_filing: FilingEnqueuerDep,
) -> DocumentDetail:
    """A human confirms (or corrects) the type and the matter; filing then runs async."""
    document = _get_or_404(session, firm, document_id)
    if document.status is not DocumentStatus.NEEDS_REVIEW:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Document is {document.status}")
    # The matter must belong to the same firm (tenant isolation on writes, too).
    if repo.get_matter(session, firm.id, decision.matter_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Matter not found")

    document.doc_type = decision.doc_type
    document.matter_id = decision.matter_id
    document.classification_confidence = 1.0
    document.match_confidence = 1.0
    document.review_reason = None
    detail = "reviewed by human" + (f": {decision.note}" if decision.note else "")
    repo.transition(session, document, DocumentStatus.MATCHED, detail=detail)
    session.commit()

    enqueue_filing(document.id)
    session.refresh(document)
    return DocumentDetail.model_validate(document)


@router.post("/{document_id}/retry")
def retry_failed(
    document_id: uuid.UUID, session: DbSession, firm: CurrentFirm, enqueue: EnqueuerDep
) -> DocumentDetail:
    """Re-run the whole pipeline for a failed document (e.g. after fixing an outage)."""
    document = _get_or_404(session, firm, document_id)
    if document.status is not DocumentStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Document is {document.status}")
    repo.transition(session, document, DocumentStatus.RECEIVED, detail="manual retry")
    document.error = None
    session.commit()

    enqueue(document.id)
    session.refresh(document)
    return DocumentDetail.model_validate(document)


@router.get("/{document_id}/file", response_class=FileResponse)
def download_file(
    document_id: uuid.UUID, session: DbSession, firm: CurrentFirm, storage: StorageDep
) -> FileResponse:
    document = _get_or_404(session, firm, document_id)
    return FileResponse(
        storage.path_of(document.storage_path),
        media_type="application/pdf",
        filename=document.filed_name or document.original_filename,
        content_disposition_type="inline",
    )
