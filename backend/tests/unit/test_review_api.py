import uuid
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Alert, Document, Firm, Matter
from app.domain.states import DocumentStatus
from app.storage import LocalStorage
from tests.conftest import auth_headers, fake_pdf


def _h(firm: Firm) -> dict[str, str]:
    return auth_headers(firm)


def _doc(db: Session, storage: LocalStorage, firm: Firm, status: DocumentStatus) -> Document:
    data = fake_pdf(str(uuid.uuid4()))
    path, digest = storage.save(firm.id, data)
    doc = Document(
        firm_id=firm.id,
        original_filename="x.pdf",
        content_type="application/pdf",
        size_bytes=len(data),
        sha256=digest,
        storage_path=path,
        status=status,
    )
    db.add(doc)
    db.commit()
    return doc


def _matter(db: Session, firm: Firm, case: str = "1:24-cv-00001") -> Matter:
    m = Matter(firm_id=firm.id, case_number=case, title="A v. B", client_name="A")
    db.add(m)
    db.commit()
    return m


def test_resolve_review_moves_to_matched_and_enqueues_filing(
    client: TestClient,
    db: Session,
    storage: LocalStorage,
    firm: Firm,
    enqueued: list[uuid.UUID],
) -> None:
    doc = _doc(db, storage, firm, DocumentStatus.NEEDS_REVIEW)
    matter = _matter(db, firm)

    resp = client.post(
        f"/documents/{doc.id}/review",
        json={"doc_type": "pleading", "matter_id": str(matter.id), "note": "checked"},
        headers=_h(firm),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "matched"
    assert body["doc_type"] == "pleading"
    assert body["events"][-1]["detail"] == "reviewed by human: checked"
    assert enqueued == [doc.id]


def test_review_requires_needs_review_status(
    client: TestClient, db: Session, storage: LocalStorage, firm: Firm
) -> None:
    doc = _doc(db, storage, firm, DocumentStatus.FILED)
    matter = _matter(db, firm)
    resp = client.post(
        f"/documents/{doc.id}/review",
        json={"doc_type": "pleading", "matter_id": str(matter.id)},
        headers=_h(firm),
    )
    assert resp.status_code == 409


def test_review_cannot_use_other_firms_matter(
    client: TestClient, db: Session, storage: LocalStorage, firm: Firm, other_firm: Firm
) -> None:
    doc = _doc(db, storage, firm, DocumentStatus.NEEDS_REVIEW)
    foreign = _matter(db, other_firm)
    resp = client.post(
        f"/documents/{doc.id}/review",
        json={"doc_type": "pleading", "matter_id": str(foreign.id)},
        headers=_h(firm),
    )
    assert resp.status_code == 404


def test_retry_failed_document(
    client: TestClient,
    db: Session,
    storage: LocalStorage,
    firm: Firm,
    enqueued: list[uuid.UUID],
) -> None:
    doc = _doc(db, storage, firm, DocumentStatus.FAILED)

    resp = client.post(f"/documents/{doc.id}/retry", headers=_h(firm))

    assert resp.status_code == 200
    assert resp.json()["status"] == "received"
    assert enqueued == [doc.id]
    assert client.post(f"/documents/{doc.id}/retry", headers=_h(firm)).status_code == 409


def test_download_file(client: TestClient, db: Session, storage: LocalStorage, firm: Firm) -> None:
    doc = _doc(db, storage, firm, DocumentStatus.FILED)
    resp = client.get(f"/documents/{doc.id}/file", headers=_h(firm))
    assert resp.status_code == 200
    assert resp.content.startswith(b"%PDF")


def test_rules_default_update_and_validation(client: TestClient, firm: Firm) -> None:
    default = client.get("/rules", headers=_h(firm)).json()
    assert default["naming_template"] == "{date}_{doc_type}_{client}"

    new = {**default, "naming_template": "{case_number}_{doc_type}", "default_assignee": "pool"}
    assert client.put("/rules", json=new, headers=_h(firm)).status_code == 200
    assert client.get("/rules", headers=_h(firm)).json()["default_assignee"] == "pool"

    bad = {**default, "naming_template": "{ssn}"}
    assert client.put("/rules", json=bad, headers=_h(firm)).status_code == 422


def test_alerts_are_scoped_and_resolvable(
    client: TestClient,
    db: Session,
    storage: LocalStorage,
    firm: Firm,
    other_firm: Firm,
) -> None:
    doc = _doc(db, storage, firm, DocumentStatus.FILED)
    alert = Alert(
        firm_id=firm.id,
        document_id=doc.id,
        kind="hearing",
        due_date=date(2030, 1, 1),
        description="Court hearing",
    )
    db.add(alert)
    db.commit()

    assert len(client.get("/alerts", headers=_h(firm)).json()) == 1
    assert client.get("/alerts", headers=_h(other_firm)).json() == []
    assert client.post(f"/alerts/{alert.id}/resolve", headers=_h(other_firm)).status_code == 404
    assert client.post(f"/alerts/{alert.id}/resolve", headers=_h(firm)).json()["resolved"]
    assert client.get("/alerts", headers=_h(firm)).json() == []


def test_stats_counts_by_status(
    client: TestClient, db: Session, storage: LocalStorage, firm: Firm
) -> None:
    _doc(db, storage, firm, DocumentStatus.FILED)
    _doc(db, storage, firm, DocumentStatus.FILED)
    _doc(db, storage, firm, DocumentStatus.NEEDS_REVIEW)
    counts = {c["status"]: c["count"] for c in client.get("/stats", headers=_h(firm)).json()}
    assert counts == {"filed": 2, "needs_review": 1}
