"""create firms, matters, documents and document_events

Revision ID: 0001
Revises:
Create Date: 2026-11-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

STATUSES = (
    "received",
    "text_extracted",
    "classified",
    "entities_extracted",
    "matched",
    "filed",
    "needs_review",
    "failed",
)
TYPES = (
    "medical_record",
    "medical_bill",
    "pleading",
    "correspondence",
    "discovery_request",
    "lien_notice",
    "other",
)


def _enum(values: tuple[str, ...], name: str) -> sa.types.TypeEngine[str]:
    # On Postgres the named ENUM type is created once, explicitly (see upgrade());
    # create_type=False stops each create_table from trying to create it again.
    return sa.Enum(*values, name=name).with_variant(
        postgresql.ENUM(*values, name=name, create_type=False), "postgresql"
    )


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(*STATUSES, name="document_status").create(bind, checkfirst=True)
        postgresql.ENUM(*TYPES, name="document_type").create(bind, checkfirst=True)

    op.create_table(
        "firms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_firms")),
        sa.UniqueConstraint("slug", name=op.f("uq_firms_slug")),
    )
    op.create_table(
        "matters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("firm_id", sa.Uuid(), nullable=False),
        sa.Column("case_number", sa.String(length=100), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("client_name", sa.String(length=200), nullable=False),
        sa.Column("defendant", sa.String(length=200), nullable=True),
        sa.Column("incident_date", sa.Date(), nullable=True),
        sa.Column("opened_at", sa.Date(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["firm_id"], ["firms.id"], name=op.f("fk_matters_firm_id_firms")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_matters")),
        sa.UniqueConstraint("firm_id", "case_number", name=op.f("uq_matters_firm_id_case_number")),
    )
    op.create_index(op.f("ix_matters_firm_id"), "matters", ["firm_id"])

    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("firm_id", sa.Uuid(), nullable=False),
        sa.Column("matter_id", sa.Uuid(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=500), nullable=False),
        sa.Column("status", _enum(STATUSES, "document_status"), nullable=False),
        sa.Column("doc_type", _enum(TYPES, "document_type"), nullable=True),
        sa.Column("classification_confidence", sa.Float(), nullable=True),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column("extracted_text", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "entities",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("filed_name", sa.String(length=255), nullable=True),
        sa.Column("filed_folder", sa.String(length=255), nullable=True),
        sa.Column("assignee", sa.String(length=200), nullable=True),
        sa.Column("review_reason", sa.String(length=500), nullable=True),
        sa.Column("error", sa.String(length=1000), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["firm_id"], ["firms.id"], name=op.f("fk_documents_firm_id_firms")),
        sa.ForeignKeyConstraint(
            ["matter_id"], ["matters.id"], name=op.f("fk_documents_matter_id_matters")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint("firm_id", "sha256", name=op.f("uq_documents_firm_id_sha256")),
    )
    op.create_index(op.f("ix_documents_firm_id"), "documents", ["firm_id"])
    op.create_index(op.f("ix_documents_matter_id"), "documents", ["matter_id"])
    op.create_index(op.f("ix_documents_status"), "documents", ["status"])

    op.create_table(
        "document_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("from_status", _enum(STATUSES, "document_status"), nullable=True),
        sa.Column("to_status", _enum(STATUSES, "document_status"), nullable=False),
        sa.Column("detail", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_events_document_id_documents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_events")),
    )
    op.create_index(op.f("ix_document_events_document_id"), "document_events", ["document_id"])


def downgrade() -> None:
    op.drop_table("document_events")
    op.drop_table("documents")
    op.drop_table("matters")
    op.drop_table("firms")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        postgresql.ENUM(name="document_type").drop(bind, checkfirst=True)
        postgresql.ENUM(name="document_status").drop(bind, checkfirst=True)
