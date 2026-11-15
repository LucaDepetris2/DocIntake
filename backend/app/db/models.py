import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, JSONType
from app.domain.states import DocumentStatus, DocumentType


def utcnow() -> datetime:
    return datetime.now(UTC)


def _enum(enum_cls: type[DocumentStatus] | type[DocumentType], name: str) -> Enum:
    # Store the enum *values* ("needs_review"), not the Python member names.
    return Enum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Firm(TimestampMixin, Base):
    """A law firm: the tenant. Every other row belongs to exactly one firm."""

    __tablename__ = "firms"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(100), unique=True)

    matters: Mapped[list["Matter"]] = relationship(back_populates="firm")


class Matter(TimestampMixin, Base):
    """A legal case handled by a firm."""

    __tablename__ = "matters"
    __table_args__ = (UniqueConstraint("firm_id", "case_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firms.id"), index=True)
    case_number: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(300))
    client_name: Mapped[str] = mapped_column(String(200))
    defendant: Mapped[str | None] = mapped_column(String(200))
    incident_date: Mapped[date | None] = mapped_column(Date)
    opened_at: Mapped[date | None] = mapped_column(Date)

    firm: Mapped[Firm] = relationship(back_populates="matters")


class Document(TimestampMixin, Base):
    __tablename__ = "documents"
    # Same file uploaded twice to the same firm -> same row (idempotent upload).
    __table_args__ = (UniqueConstraint("firm_id", "sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firms.id"), index=True)
    matter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("matters.id"), index=True)

    original_filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(500))

    status: Mapped[DocumentStatus] = mapped_column(
        _enum(DocumentStatus, "document_status"), default=DocumentStatus.RECEIVED, index=True
    )
    doc_type: Mapped[DocumentType | None] = mapped_column(_enum(DocumentType, "document_type"))
    classification_confidence: Mapped[float | None] = mapped_column(Float)
    match_confidence: Mapped[float | None] = mapped_column(Float)

    extracted_text: Mapped[str | None] = mapped_column(Text)
    page_count: Mapped[int | None] = mapped_column(Integer)
    entities: Mapped[dict[str, Any] | None] = mapped_column(JSONType)

    filed_name: Mapped[str | None] = mapped_column(String(255))
    filed_folder: Mapped[str | None] = mapped_column(String(255))
    assignee: Mapped[str | None] = mapped_column(String(200))

    review_reason: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(String(1000))

    matter: Mapped[Matter | None] = relationship()
    events: Mapped[list["DocumentEvent"]] = relationship(
        back_populates="document", order_by="DocumentEvent.created_at"
    )


class DocumentEvent(Base):
    """Audit trail: one row per status change (powers the timeline in the UI)."""

    __tablename__ = "document_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    from_status: Mapped[DocumentStatus | None] = mapped_column(
        _enum(DocumentStatus, "document_status")
    )
    to_status: Mapped[DocumentStatus] = mapped_column(_enum(DocumentStatus, "document_status"))
    detail: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    document: Mapped[Document] = relationship(back_populates="events")


class FirmRuleSet(TimestampMixin, Base):
    """Per-firm filing rules (validated by app.domain.rules.FirmRules), stored as JSON."""

    __tablename__ = "firm_rules"

    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firms.id"), primary_key=True)
    config: Mapped[dict[str, Any]] = mapped_column(JSONType)


class Alert(TimestampMixin, Base):
    """A deadline derived from a document (e.g. discovery responses due)."""

    __tablename__ = "alerts"
    # Re-processing a document must not duplicate its alerts (idempotency).
    __table_args__ = (UniqueConstraint("document_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firms.id"), index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id"), index=True)
    matter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("matters.id"))
    kind: Mapped[str] = mapped_column(String(50))
    due_date: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(String(300))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class User(TimestampMixin, Base):
    """A firm employee. Belongs to exactly one firm: the tenant comes from the user."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    firm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("firms.id"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    firm: Mapped[Firm] = relationship()
