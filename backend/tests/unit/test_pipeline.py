import random
import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from faker import Faker
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Alert, Document, DocumentEvent, Firm, FirmRuleSet, Matter
from app.domain.classification import FallbackClassifier, KeywordClassifier, SklearnClassifier
from app.domain.classification import train_model as fit
from app.domain.states import DocumentStatus, DocumentType
from app.processing.extraction import ExtractionError
from app.storage import LocalStorage
from app.workers import stages
from app.workers.stages import StageDeps, StageOutcome, run_pipeline
from tests.conftest import fake_pdf
from tests.synthetic import corpus, generator


@pytest.fixture(scope="session")
def classifier() -> FallbackClassifier:
    texts, labels, _ = corpus(350, seed=3)
    return FallbackClassifier(SklearnClassifier(fit(texts, labels)), KeywordClassifier(), 0.6)


@pytest.fixture
def deps(settings: Settings, storage: LocalStorage, classifier: FallbackClassifier) -> StageDeps:
    return StageDeps(settings=settings, storage=storage, classifier=classifier)


@pytest.fixture
def matter(db: Session, firm: Firm) -> Matter:
    m = Matter(
        firm_id=firm.id,
        case_number="2:24-cv-01234",
        title="Jane Doe v. Acme Trucking LLC",
        client_name="Jane Doe",
        defendant="Acme Trucking LLC",
        incident_date=date(2024, 3, 3),
    )
    db.add(m)
    db.commit()
    return m


def _gen_matter(matter: Matter) -> object:
    gen = generator()
    return gen.Matter(
        firm_slug="acme",
        case_number=matter.case_number,
        title=matter.title,
        client_name=matter.client_name,
        defendant=matter.defendant or "",
        incident_date=(matter.incident_date or date(2024, 1, 1)).isoformat(),
        opened_at="2024-03-20",
    )


def _store(db: Session, storage: LocalStorage, firm: Firm, data: bytes) -> Document:
    path, digest = storage.save(firm.id, data)
    doc = Document(
        firm_id=firm.id,
        original_filename="incoming.pdf",
        content_type="application/pdf",
        size_bytes=len(data),
        sha256=digest,
        storage_path=path,
    )
    db.add(doc)
    db.commit()
    return doc


def _synthetic_pdf(
    doc_type: str, matter: Matter, *, with_case: bool = True, seed: int = 1
) -> bytes:
    gen = generator()
    fake = Faker("en_US")
    fake.seed_instance(seed)
    lines = gen.TEMPLATES[doc_type](
        fake, random.Random(seed), _gen_matter(matter), matter.client_name, with_case
    )
    data: bytes = gen._render_text_pdf(lines)
    return data


def test_discovery_request_is_filed_with_deadline_alert(
    db: Session, storage: LocalStorage, firm: Firm, matter: Matter, deps: StageDeps
) -> None:
    doc = _store(db, storage, firm, _synthetic_pdf("discovery_request", matter))

    assert run_pipeline(db, doc.id, deps) is DocumentStatus.FILED

    db.refresh(doc)
    assert doc.doc_type is DocumentType.DISCOVERY_REQUEST
    assert doc.matter_id == matter.id
    assert doc.filed_folder == "2-24-cv-01234/Discovery/Requests"
    assert doc.filed_name
    assert doc.filed_name.endswith("_discovery_request_jane-doe.pdf")
    alerts = db.scalars(select(Alert).where(Alert.document_id == doc.id)).all()
    assert [a.kind for a in alerts] == ["discovery_response_due"]
    statuses = [
        e.to_status
        for e in db.scalars(
            select(DocumentEvent)
            .where(DocumentEvent.document_id == doc.id)
            .order_by(DocumentEvent.created_at)
        )
    ]
    assert statuses == [
        DocumentStatus.TEXT_EXTRACTED,
        DocumentStatus.CLASSIFIED,
        DocumentStatus.ENTITIES_EXTRACTED,
        DocumentStatus.MATCHED,
        DocumentStatus.FILED,
    ]


def test_firm_rules_are_applied(
    db: Session, storage: LocalStorage, firm: Firm, matter: Matter, deps: StageDeps
) -> None:
    db.add(
        FirmRuleSet(
            firm_id=firm.id,
            config={"naming_template": "{case_number}_{doc_type}", "default_assignee": "pool"},
        )
    )
    db.commit()
    doc = _store(db, storage, firm, _synthetic_pdf("lien_notice", matter))

    run_pipeline(db, doc.id, deps)

    db.refresh(doc)
    assert doc.filed_name == "2-24-cv-01234_lien_notice.pdf"
    assert doc.assignee == "pool"


def test_unreadable_text_goes_to_review(
    db: Session, storage: LocalStorage, firm: Firm, deps: StageDeps, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.processing.extraction.ocr_available", lambda: False)
    doc = _store(db, storage, firm, generator()._render_image_pdf(["SCANNED"]))

    assert run_pipeline(db, doc.id, deps) is DocumentStatus.NEEDS_REVIEW
    db.refresh(doc)
    assert doc.review_reason
    assert "No readable text" in doc.review_reason


def test_unknown_client_goes_to_review_without_matter(
    db: Session, storage: LocalStorage, firm: Firm, matter: Matter, deps: StageDeps
) -> None:
    stranger = Matter(
        firm_id=firm.id,
        case_number="X-1",
        title="t",
        client_name="Zed Unknown",
        defendant="Nobody Inc",
        incident_date=date(2020, 1, 1),
    )
    doc = _store(db, storage, firm, _synthetic_pdf("pleading", stranger, with_case=False))

    assert run_pipeline(db, doc.id, deps) is DocumentStatus.NEEDS_REVIEW
    db.refresh(doc)
    assert doc.matter_id is None
    assert doc.review_reason
    assert doc.review_reason.startswith("Matter match")


def test_low_classification_confidence_goes_to_review(
    db: Session,
    storage: LocalStorage,
    firm: Firm,
    settings: Settings,
    classifier: FallbackClassifier,
) -> None:
    settings.classification_threshold = 0.999
    deps = StageDeps(settings=settings, storage=storage, classifier=classifier)
    doc = _store(
        db,
        storage,
        firm,
        generator()._render_text_pdf(
            ["Some short note about a meeting with the client next week."]
        ),
    )

    assert run_pipeline(db, doc.id, deps) is DocumentStatus.NEEDS_REVIEW
    db.refresh(doc)
    assert doc.doc_type is not None
    assert doc.review_reason
    assert "classification" in doc.review_reason


def test_stages_are_idempotent(
    db: Session, storage: LocalStorage, firm: Firm, matter: Matter, deps: StageDeps
) -> None:
    doc = _store(db, storage, firm, _synthetic_pdf("pleading", matter))
    run_pipeline(db, doc.id, deps)

    # Redelivery of every message after the document is filed: nothing changes.
    for stage in stages.PIPELINE:
        assert stage(db, doc.id, deps) is StageOutcome.SKIPPED
    events = db.scalar(
        select(func.count()).select_from(DocumentEvent).where(DocumentEvent.document_id == doc.id)
    )
    alerts = db.scalar(select(func.count()).select_from(Alert).where(Alert.document_id == doc.id))
    assert events == 5
    assert alerts == 2  # hearing + opposition, not duplicated


def test_stage_on_missing_document_is_skipped(db: Session, deps: StageDeps) -> None:
    assert stages.stage_extract_text(db, uuid.uuid4(), deps) is StageOutcome.SKIPPED


def test_mark_failed_records_error_and_is_noop_when_filed(
    db: Session, storage: LocalStorage, firm: Firm, matter: Matter, deps: StageDeps
) -> None:
    doc = _store(db, storage, firm, fake_pdf("broken"))
    assert stages.mark_failed(db, doc.id, "pipeline.extract_text: ExtractionError")
    db.refresh(doc)
    assert doc.status is DocumentStatus.FAILED
    assert doc.error == "pipeline.extract_text: ExtractionError"
    assert not stages.mark_failed(db, doc.id, "again")


# --- Celery wiring (eager mode: tasks run in-process, no broker) -----------------------


@pytest.fixture
def eager_celery(
    session_factory: sessionmaker[Session], deps: StageDeps, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    from app.workers import tasks
    from app.workers.celery_app import celery_app

    monkeypatch.setattr(tasks, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(stages, "get_stage_deps", lambda: deps)
    celery_app.conf.task_always_eager = True
    yield
    celery_app.conf.task_always_eager = False


@pytest.mark.usefixtures("eager_celery")
def test_celery_chain_files_document(
    db: Session, storage: LocalStorage, firm: Firm, matter: Matter
) -> None:
    from app.workers.dispatch import enqueue_processing

    doc = _store(db, storage, firm, _synthetic_pdf("medical_bill", matter))
    enqueue_processing(doc.id)

    db.expire_all()
    assert db.get(Document, doc.id).status is DocumentStatus.FILED  # type: ignore[union-attr]


@pytest.mark.usefixtures("eager_celery")
def test_permanent_failure_marks_document_failed(
    db: Session, storage: LocalStorage, firm: Firm
) -> None:
    from app.workers.dispatch import enqueue_processing

    doc = _store(db, storage, firm, fake_pdf("not really a pdf body"))
    # Eager mode re-raises to the caller; a real worker rejects the message into the DLQ.
    with pytest.raises(ExtractionError):
        enqueue_processing(doc.id)

    db.expire_all()
    failed = db.get(Document, doc.id)
    assert failed is not None
    assert failed.status is DocumentStatus.FAILED
    assert failed.error
    assert failed.error.startswith("pipeline.extract_text: ExtractionError")


def test_sanitize_error_hides_library_messages() -> None:
    from app.workers.tasks import sanitize_error

    message = sanitize_error("pipeline.match", RuntimeError("Patient Jane Doe SSN 123"))
    assert message == "pipeline.match: RuntimeError"
