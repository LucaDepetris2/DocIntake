import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentFirm, DbSession, EnqueuerDep, SettingsDep, StorageDep
from app.api.schemas import DocumentDetail, DocumentPage, DocumentSummary, UploadResult
from app.db import repositories as repo
from app.db.models import Document
from app.domain.states import DocumentStatus

router = APIRouter(prefix="/documents", tags=["documents"])
log = structlog.get_logger("app.documents")

PDF_MAGIC = b"%PDF-"
ALLOWED_CONTENT_TYPES = {"application/pdf", "application/octet-stream"}


async def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "File too large")
    return data


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    response: Response,
    session: DbSession,
    firm: CurrentFirm,
    settings: SettingsDep,
    storage: StorageDep,
    enqueue: EnqueuerDep,
) -> UploadResult:
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Only PDF files are accepted")
    data = await _read_limited(file, settings.max_upload_bytes)
    # Never trust the declared content type: check the file signature too.
    if not data.startswith(PDF_MAGIC):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "File is not a valid PDF")

    storage_path, digest = storage.save(firm.id, data)

    existing = repo.get_document_by_sha(session, firm.id, digest)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return UploadResult(document=DocumentSummary.model_validate(existing), duplicate=True)

    document = Document(
        firm_id=firm.id,
        original_filename=(file.filename or "upload.pdf")[:255],
        content_type="application/pdf",
        size_bytes=len(data),
        sha256=digest,
        storage_path=storage_path,
        status=DocumentStatus.RECEIVED,
    )
    session.add(document)
    session.flush()
    repo.add_event(session, document, None, DocumentStatus.RECEIVED, "uploaded")
    try:
        session.commit()
    except IntegrityError:
        # Race: the same file was uploaded concurrently and the unique constraint caught it.
        session.rollback()
        existing = repo.get_document_by_sha(session, firm.id, digest)
        if existing is None:
            raise
        response.status_code = status.HTTP_200_OK
        return UploadResult(document=DocumentSummary.model_validate(existing), duplicate=True)

    # Publish only AFTER commit: a worker must never receive an id it cannot find yet.
    enqueue(document.id)
    log.info("document received", document_id=str(document.id), size_bytes=len(data))
    return UploadResult(document=DocumentSummary.model_validate(document), duplicate=False)


@router.get("")
def list_documents(
    session: DbSession,
    firm: CurrentFirm,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DocumentPage:
    items, total = repo.list_documents(
        session, firm.id, status=status_filter, limit=limit, offset=offset
    )
    return DocumentPage(
        items=[DocumentSummary.model_validate(d) for d in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}")
def get_document(document_id: uuid.UUID, session: DbSession, firm: CurrentFirm) -> DocumentDetail:
    document = repo.get_document(session, firm.id, document_id)
    if document is None:
        # 404 (not 403) for other firms' documents: don't leak that the id exists.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return DocumentDetail.model_validate(document)
