"""Behaviour that only a real Postgres can prove: migrations, JSONB, enums, constraints,
concurrency guards and the full pipeline end-to-end."""

import random
import threading
from datetime import date

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from faker import Faker
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.config import Settings
from app.db import repositories as repo
from app.db.base import Base
from app.db.models import Alert, Document, DocumentEvent, Firm, Matter
from app.domain.classification import KeywordClassifier
from app.domain.states import DocumentStatus
from app.storage import LocalStorage
from app.workers.stages import StageDeps, run_pipeline
from tests.conftest import auth_headers, fake_pdf, make_firm
from tests.integration.conftest import BACKEND_DIR
from tests.synthetic import generator

pytestmark = pytest.mark.integration


def _firm(db: Session, slug: str = "acme") -> Firm:
    return make_firm(db, slug)


def test_migrations_match_models(pg_engine: Engine) -> None:
    """If someone changes a model without a migration, this fails."""
    with pg_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_upload_dedup_is_enforced_by_the_database(pg_db: Session) -> None:
    firm = _firm(pg_db)
    common = {
        "firm_id": firm.id,
        "original_filename": "a.pdf",
        "content_type": "application/pdf",
        "size_bytes": 1,
        "sha256": "f" * 64,
        "storage_path": "x",
    }
    pg_db.add(Document(**common))
    pg_db.commit()
    pg_db.add(Document(**common))
    with pytest.raises(IntegrityError):
        pg_db.commit()


def test_concurrent_advance_has_exactly_one_winner(
    pg_session_factory: sessionmaker[Session],
) -> None:
    """Two workers race on the same document: the compare-and-set UPDATE lets one win."""
    with pg_session_factory() as s:
        firm = _firm(s)
        doc = Document(
            firm_id=firm.id,
            original_filename="a.pdf",
            content_type="application/pdf",
            size_bytes=1,
            sha256="e" * 64,
            storage_path="x",
        )
        s.add(doc)
        s.commit()
        doc_id = doc.id

    results: list[bool] = []
    barrier = threading.Barrier(8)

    def worker() -> None:
        with pg_session_factory() as s:
            barrier.wait()
            ok = repo.advance(
                s,
                doc_id,
                expected=DocumentStatus.RECEIVED,
                target=DocumentStatus.TEXT_EXTRACTED,
            )
            s.commit()
            results.append(ok)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count(True) == 1
    with pg_session_factory() as s:
        events = s.scalar(
            select(func.count())
            .select_from(DocumentEvent)
            .where(DocumentEvent.document_id == doc_id)
        )
    assert events == 1


def test_api_roundtrip_on_postgres(pg_client: TestClient, pg_db: Session) -> None:
    firm = _firm(pg_db)
    headers = auth_headers(firm)
    resp = pg_client.post(
        "/documents", headers=headers, files={"file": ("a.pdf", fake_pdf("pg"), "application/pdf")}
    )
    assert resp.status_code == 201
    doc_id = resp.json()["document"]["id"]
    detail = pg_client.get(f"/documents/{doc_id}", headers=headers).json()
    assert detail["events"][0]["to_status"] == "received"
    assert pg_client.get("/documents?status=received", headers=headers).json()["total"] == 1


def test_full_pipeline_on_postgres(
    pg_db: Session, storage: LocalStorage, settings: Settings
) -> None:
    firm = _firm(pg_db)
    matter = Matter(
        firm_id=firm.id,
        case_number="2:24-cv-04321",
        title="Ann Lee v. Big Rig Inc",
        client_name="Ann Lee",
        defendant="Big Rig Inc",
        incident_date=date(2024, 2, 2),
    )
    pg_db.add(matter)
    pg_db.commit()

    gen = generator()
    fake = Faker()
    fake.seed_instance(5)
    gm = gen.Matter(
        "acme",
        matter.case_number,
        matter.title,
        "Ann Lee",
        "Big Rig Inc",
        "2024-02-02",
        "2024-02-20",
    )
    data = gen._render_text_pdf(
        gen.TEMPLATES["discovery_request"](fake, random.Random(5), gm, "Ann Lee", True)
    )
    path, digest = storage.save(firm.id, data)
    doc = Document(
        firm_id=firm.id,
        original_filename="d.pdf",
        content_type="application/pdf",
        size_bytes=len(data),
        sha256=digest,
        storage_path=path,
    )
    pg_db.add(doc)
    pg_db.commit()

    deps = StageDeps(settings=settings, storage=storage, classifier=KeywordClassifier())
    assert run_pipeline(pg_db, doc.id, deps) is DocumentStatus.FILED

    pg_db.refresh(doc)
    assert doc.entities is not None
    assert doc.entities["case_numbers"] == ["2:24-cv-04321"]  # JSONB roundtrip
    assert pg_db.scalar(select(func.count()).select_from(Alert)) == 1


def test_migrations_downgrade_and_upgrade_again(pg_url: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", pg_url)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
