"""Data access. Every query that touches tenant data takes a firm_id (multi-tenancy)."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.db.models import Document, DocumentEvent, Firm, Matter
from app.domain.states import DocumentStatus, ensure_transition


def get_firm(session: Session, firm_id: uuid.UUID) -> Firm | None:
    return session.get(Firm, firm_id)


# --- Matters -----------------------------------------------------------------


def list_matters(session: Session, firm_id: uuid.UUID) -> Sequence[Matter]:
    stmt = select(Matter).where(Matter.firm_id == firm_id).order_by(Matter.case_number)
    return session.scalars(stmt).all()


def get_matter(session: Session, firm_id: uuid.UUID, matter_id: uuid.UUID) -> Matter | None:
    stmt = select(Matter).where(Matter.firm_id == firm_id, Matter.id == matter_id)
    return session.scalars(stmt).one_or_none()


# --- Documents ---------------------------------------------------------------


def get_document(session: Session, firm_id: uuid.UUID, document_id: uuid.UUID) -> Document | None:
    stmt = (
        select(Document)
        .where(Document.firm_id == firm_id, Document.id == document_id)
        .options(selectinload(Document.events))
    )
    return session.scalars(stmt).one_or_none()


def get_document_by_sha(session: Session, firm_id: uuid.UUID, sha256: str) -> Document | None:
    stmt = select(Document).where(Document.firm_id == firm_id, Document.sha256 == sha256)
    return session.scalars(stmt).one_or_none()


def list_documents(
    session: Session,
    firm_id: uuid.UUID,
    *,
    status: DocumentStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[Sequence[Document], int]:
    base = select(Document).where(Document.firm_id == firm_id)
    if status is not None:
        base = base.where(Document.status == status)
    total = session.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = session.scalars(
        base.order_by(Document.created_at.desc()).limit(limit).offset(offset)
    ).all()
    return items, total


def add_event(
    session: Session,
    document: Document,
    from_status: DocumentStatus | None,
    to_status: DocumentStatus,
    detail: str | None = None,
) -> None:
    session.add(
        DocumentEvent(
            document_id=document.id, from_status=from_status, to_status=to_status, detail=detail
        )
    )


def transition(
    session: Session, document: Document, target: DocumentStatus, detail: str | None = None
) -> None:
    """Validated status change on a loaded document (+ audit event). Caller commits."""
    ensure_transition(document.status, target)
    add_event(session, document, document.status, target, detail)
    document.status = target


def advance(
    session: Session,
    document_id: uuid.UUID,
    *,
    expected: DocumentStatus,
    target: DocumentStatus,
    detail: str | None = None,
    **fields: Any,
) -> bool:
    """Compare-and-set status change used by workers (idempotency guard).

    The UPDATE only matches if the row is still in `expected`. If two workers process the
    same document, exactly one wins; the other sees rowcount == 0 and does nothing.
    Caller commits.
    """
    ensure_transition(expected, target)
    stmt = (
        update(Document)
        .where(Document.id == document_id, Document.status == expected)
        .values(status=target, **fields)
        .execution_options(synchronize_session=False)
    )
    result = session.execute(stmt)
    if result.rowcount != 1:  # type: ignore[attr-defined]
        return False
    session.add(
        DocumentEvent(
            document_id=document_id, from_status=expected, to_status=target, detail=detail
        )
    )
    return True
