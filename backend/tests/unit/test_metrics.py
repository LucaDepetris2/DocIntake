import uuid

from fastapi.testclient import TestClient
from prometheus_client import REGISTRY
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Document, Firm
from app.domain.states import DocumentStatus
from app.observability.metrics import DocumentStatusCollector, observe_stage
from tests.conftest import auth_headers


def _sample(name: str, labels: dict[str, str]) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_requests_are_counted_by_route_template(client: TestClient, firm: Firm) -> None:
    labels = {"method": "GET", "path": "/documents/{document_id}", "status": "404"}
    before = _sample("http_requests_total", labels)

    client.get(f"/documents/{uuid.uuid4()}", headers=auth_headers(firm))

    # The raw id is not a label: one series per route, not per document.
    assert _sample("http_requests_total", labels) == before + 1


def test_unknown_paths_share_one_label(client: TestClient) -> None:
    labels = {"method": "GET", "path": "<unmatched>", "status": "404"}
    before = _sample("http_requests_total", labels)
    client.get("/wp-admin/random-1")
    client.get("/wp-admin/random-2")
    assert _sample("http_requests_total", labels) == before + 2


def test_metrics_endpoint_exposes_prometheus_text(client: TestClient) -> None:
    body = client.get("/metrics").text
    assert "http_request_duration_seconds_bucket" in body
    assert "pipeline_stage_runs_total" in body


def test_stage_observations() -> None:
    labels = {"stage": "pipeline.match", "outcome": "review"}
    before = _sample("pipeline_stage_runs_total", labels)
    observe_stage("pipeline.match", "review", 0.2)
    assert _sample("pipeline_stage_runs_total", labels) == before + 1


def test_document_status_collector_counts_from_db(
    db: Session, session_factory: sessionmaker[Session], firm: Firm
) -> None:
    for i, status in enumerate([DocumentStatus.FILED, DocumentStatus.FILED, DocumentStatus.FAILED]):
        db.add(
            Document(
                firm_id=firm.id,
                original_filename="a.pdf",
                content_type="application/pdf",
                size_bytes=1,
                sha256=f"{i:064d}",
                storage_path="x",
                status=status,
            )
        )
    db.commit()

    (family,) = DocumentStatusCollector(session_factory).collect()

    assert {s.labels["status"]: s.value for s in family.samples} == {"filed": 2, "failed": 1}


def test_document_status_collector_survives_db_outage() -> None:
    def broken() -> Session:
        raise OperationalError("SELECT 1", {}, Exception("db down"))

    assert list(DocumentStatusCollector(broken).collect()) == []
