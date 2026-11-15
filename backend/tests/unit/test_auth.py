import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.orm import Session

from app.auth import create_access_token
from app.config import Settings
from app.db.models import Firm, User
from tests.conftest import TEST_PASSWORD, auth_headers, user_id_for


def _login(client: TestClient, email: str, password: str) -> tuple[int, dict]:  # type: ignore[type-arg]
    resp = client.post("/auth/token", data={"username": email, "password": password})
    return resp.status_code, resp.json()


def test_login_returns_token_and_user(client: TestClient, firm: Firm) -> None:
    status, body = _login(client, "STAFF@acme.test", TEST_PASSWORD)  # email is case-insensitive

    assert status == 200
    assert body["token_type"] == "bearer"
    assert body["user"]["firm_id"] == str(firm.id)
    me = client.get("/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["email"] == "staff@acme.test"


@pytest.mark.parametrize(
    ("email", "password"),
    [("staff@acme.test", "wrong"), ("nobody@acme.test", TEST_PASSWORD)],
)
def test_bad_credentials_get_the_same_401(
    client: TestClient, firm: Firm, email: str, password: str
) -> None:
    status, body = _login(client, email, password)
    assert status == 401
    assert body["detail"] == "Incorrect email or password"  # no user enumeration


def test_inactive_user_cannot_login_or_use_token(
    client: TestClient, db: Session, firm: Firm
) -> None:
    headers = auth_headers(firm)
    user = db.get(User, user_id_for(firm))
    assert user is not None
    user.is_active = False
    db.commit()

    assert _login(client, "staff@acme.test", TEST_PASSWORD)[0] == 401
    assert client.get("/documents", headers=headers).status_code == 401


def test_requests_without_token_are_rejected(client: TestClient) -> None:
    resp = client.get("/documents")
    assert resp.status_code == 401
    assert resp.headers["www-authenticate"] == "Bearer"


def test_tampered_or_foreign_tokens_are_rejected(client: TestClient, firm: Firm) -> None:
    settings = Settings()
    forged = jwt.encode(
        {"sub": str(user_id_for(firm)), "firm_id": str(firm.id), "exp": 9999999999},
        "another-secret-that-is-long-enough-32b",
        algorithm="HS256",
    )
    expired = jwt.encode(
        {
            "sub": str(user_id_for(firm)),
            "firm_id": str(firm.id),
            "exp": datetime.now(UTC) - timedelta(minutes=1),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    unsigned = jwt.encode(
        {"sub": str(user_id_for(firm)), "firm_id": str(firm.id), "exp": 9999999999},
        key="",
        algorithm="none",
    )
    for token in (forged, expired, unsigned, "garbage"):
        resp = client.get("/documents", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401, token


def test_token_firm_must_match_users_firm(client: TestClient, firm: Firm, other_firm: Firm) -> None:
    """A valid user cannot switch tenants by minting a token with another firm_id."""
    token = create_access_token(user_id_for(firm), other_firm.id, Settings())
    resp = client.get("/documents", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_unknown_user_in_token_is_rejected(client: TestClient, firm: Firm) -> None:
    token = create_access_token(uuid.uuid4(), firm.id, Settings())
    assert client.get("/documents", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_default_or_short_secret_is_refused_outside_dev() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="production")
    with pytest.raises(ValidationError):
        Settings(environment="production", jwt_secret=SecretStr("too-short"))
    Settings(environment="production", jwt_secret=SecretStr("x" * 32))
