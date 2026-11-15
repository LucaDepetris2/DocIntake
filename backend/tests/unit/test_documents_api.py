import uuid

from fastapi.testclient import TestClient

from app.db.models import Firm
from tests.conftest import auth_headers, fake_pdf


def _headers(firm: Firm) -> dict[str, str]:
    return auth_headers(firm)


def _upload(client: TestClient, firm: Firm, data: bytes, name: str = "a.pdf") -> dict:  # type: ignore[type-arg]
    resp = client.post(
        "/documents", headers=_headers(firm), files={"file": (name, data, "application/pdf")}
    )
    return {"status": resp.status_code, "json": resp.json()}


def test_upload_creates_received_document_and_enqueues(
    client: TestClient, firm: Firm, enqueued: list[uuid.UUID]
) -> None:
    result = _upload(client, firm, fake_pdf("one"))

    assert result["status"] == 201
    doc = result["json"]["document"]
    assert doc["status"] == "received"
    assert result["json"]["duplicate"] is False
    assert enqueued == [uuid.UUID(doc["id"])]


def test_uploading_same_file_twice_is_idempotent(
    client: TestClient, firm: Firm, enqueued: list[uuid.UUID]
) -> None:
    first = _upload(client, firm, fake_pdf("same"))
    second = _upload(client, firm, fake_pdf("same"), name="renamed.pdf")

    assert second["status"] == 200
    assert second["json"]["duplicate"] is True
    assert second["json"]["document"]["id"] == first["json"]["document"]["id"]
    assert len(enqueued) == 1  # not processed twice


def test_same_file_in_two_firms_creates_two_documents(
    client: TestClient, firm: Firm, other_firm: Firm
) -> None:
    a = _upload(client, firm, fake_pdf("shared"))
    b = _upload(client, other_firm, fake_pdf("shared"))

    assert a["status"] == b["status"] == 201
    assert a["json"]["document"]["id"] != b["json"]["document"]["id"]


def test_rejects_non_pdf_content(client: TestClient, firm: Firm) -> None:
    result = _upload(client, firm, b"MZ\x90\x00 not a pdf")
    assert result["status"] == 415


def test_rejects_wrong_content_type(client: TestClient, firm: Firm) -> None:
    resp = client.post(
        "/documents",
        headers=_headers(firm),
        files={"file": ("a.txt", fake_pdf(), "text/plain")},
    )
    assert resp.status_code == 415


def test_rejects_too_large_file(client: TestClient, firm: Firm) -> None:
    big = fake_pdf("x" * (20 * 1024 * 1024))
    assert _upload(client, firm, big)["status"] == 413


def test_list_filters_by_status_and_paginates(client: TestClient, firm: Firm) -> None:
    for i in range(3):
        _upload(client, firm, fake_pdf(f"doc-{i}"))

    page = client.get("/documents?limit=2", headers=_headers(firm)).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2

    filed = client.get("/documents?status=filed", headers=_headers(firm)).json()
    assert filed["total"] == 0


def test_get_document_returns_detail_with_timeline(client: TestClient, firm: Firm) -> None:
    doc_id = _upload(client, firm, fake_pdf("detail"))["json"]["document"]["id"]

    detail = client.get(f"/documents/{doc_id}", headers=_headers(firm)).json()

    assert detail["sha256"]
    assert [e["to_status"] for e in detail["events"]] == ["received"]


def test_cannot_read_other_firms_document(client: TestClient, firm: Firm, other_firm: Firm) -> None:
    doc_id = _upload(client, firm, fake_pdf("private"))["json"]["document"]["id"]

    resp = client.get(f"/documents/{doc_id}", headers=_headers(other_firm))

    assert resp.status_code == 404


def test_matters_crud_and_duplicate_case_number(client: TestClient, firm: Firm) -> None:
    body = {"case_number": "2:24-cv-01234", "title": "Doe v. Acme", "client_name": "Jane Doe"}
    assert client.post("/matters", json=body, headers=_headers(firm)).status_code == 201
    assert client.post("/matters", json=body, headers=_headers(firm)).status_code == 409
    assert len(client.get("/matters", headers=_headers(firm)).json()) == 1
