"""Firm-configurable filing rules: file name template, folder per type and routing.

Rules are data (stored as JSON per firm), validated with Pydantic so a bad configuration
is rejected when it is saved, not when a document is being filed at 3 a.m.
"""

import re
import string
from dataclasses import dataclass
from datetime import date

from pydantic import BaseModel, Field, field_validator

from app.domain.states import DocumentType

ALLOWED_PLACEHOLDERS = {"date", "doc_type", "client", "case_number", "provider", "original"}

DEFAULT_FOLDERS: dict[str, str] = {
    DocumentType.MEDICAL_RECORD: "Medical/Records",
    DocumentType.MEDICAL_BILL: "Medical/Bills",
    DocumentType.PLEADING: "Pleadings",
    DocumentType.CORRESPONDENCE: "Correspondence",
    DocumentType.DISCOVERY_REQUEST: "Discovery/Requests",
    DocumentType.LIEN_NOTICE: "Liens",
    DocumentType.OTHER: "Misc",
}


class FirmRules(BaseModel):
    naming_template: str = "{date}_{doc_type}_{client}"
    folders: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_FOLDERS))
    assignees: dict[str, str] = Field(default_factory=dict)
    default_assignee: str | None = None

    @field_validator("naming_template")
    @classmethod
    def _check_template(cls, value: str) -> str:
        fields = {name for _, name, _, _ in string.Formatter().parse(value) if name is not None}
        unknown = fields - ALLOWED_PLACEHOLDERS
        if unknown:
            raise ValueError(f"Unknown placeholders: {sorted(unknown)}")
        return value

    @field_validator("folders")
    @classmethod
    def _check_folders(cls, value: dict[str, str]) -> dict[str, str]:
        for folder in value.values():
            parts = folder.replace("\\", "/").split("/")
            if folder.startswith("/") or ".." in parts:
                raise ValueError(f"Folder must be a relative path: {folder!r}")
        return value


@dataclass(frozen=True)
class FilingContext:
    doc_type: DocumentType
    case_number: str | None
    client_name: str | None
    document_date: date | None
    provider: str | None
    original_filename: str


@dataclass(frozen=True)
class FilingDecision:
    filed_name: str
    folder: str
    assignee: str | None


def slugify(value: str) -> str:
    value = value.lower().replace("'", "")
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "unknown"


def apply_rules(rules: FirmRules, ctx: FilingContext) -> FilingDecision:
    values = {
        "date": ctx.document_date.isoformat() if ctx.document_date else "undated",
        "doc_type": ctx.doc_type.value,
        "client": slugify(ctx.client_name) if ctx.client_name else "unknown",
        "case_number": slugify(ctx.case_number) if ctx.case_number else "no-case",
        "provider": slugify(ctx.provider) if ctx.provider else "unknown",
        "original": slugify(ctx.original_filename.rsplit(".", 1)[0]),
    }
    name = rules.naming_template.format(**values)
    folder_for_type = rules.folders.get(ctx.doc_type.value, DEFAULT_FOLDERS[ctx.doc_type])
    matter_folder = slugify(ctx.case_number) if ctx.case_number else "unassigned"
    return FilingDecision(
        filed_name=f"{name}.pdf",
        folder=f"{matter_folder}/{folder_for_type}",
        assignee=rules.assignees.get(ctx.doc_type.value, rules.default_assignee),
    )
