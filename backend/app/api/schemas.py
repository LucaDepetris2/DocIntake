import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.states import DocumentStatus, DocumentType


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MatterIn(BaseModel):
    case_number: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=300)
    client_name: str = Field(min_length=1, max_length=200)
    defendant: str | None = None
    incident_date: date | None = None
    opened_at: date | None = None


class MatterOut(ORMModel, MatterIn):
    id: uuid.UUID


class DocumentEventOut(ORMModel):
    from_status: DocumentStatus | None
    to_status: DocumentStatus
    detail: str | None
    created_at: datetime


class DocumentSummary(ORMModel):
    id: uuid.UUID
    original_filename: str
    status: DocumentStatus
    doc_type: DocumentType | None
    classification_confidence: float | None
    matter_id: uuid.UUID | None
    match_confidence: float | None
    filed_name: str | None
    review_reason: str | None
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentSummary):
    content_type: str
    size_bytes: int
    sha256: str
    page_count: int | None
    extracted_text: str | None
    entities: dict[str, Any] | None
    filed_folder: str | None
    assignee: str | None
    error: str | None
    events: list[DocumentEventOut]


class DocumentPage(BaseModel):
    items: list[DocumentSummary]
    total: int
    limit: int
    offset: int


class UploadResult(BaseModel):
    document: DocumentSummary
    duplicate: bool


class ReviewDecision(BaseModel):
    doc_type: DocumentType
    matter_id: uuid.UUID
    note: str | None = Field(default=None, max_length=300)


class AlertOut(ORMModel):
    id: uuid.UUID
    document_id: uuid.UUID
    matter_id: uuid.UUID | None
    kind: str
    due_date: date
    description: str
    resolved: bool


class StatusCount(BaseModel):
    status: DocumentStatus
    count: int
