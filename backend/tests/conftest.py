"""Shared fixtures: an in-memory SQLite database and a TestClient with dependencies overridden.

SQLite keeps unit tests fast and infra-free; Postgres-specific behaviour is covered by
tests/integration (testcontainers or pgserver).
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_enqueuer, get_filing_enqueuer
from app.auth import create_access_token, hash_password
from app.config import Settings, get_settings
from app.db.base import Base
from app.db.models import Firm, User
from app.db.session import get_db
from app.main import create_app
from app.storage import LocalStorage, get_storage


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared connection, so the in-memory DB survives
    )

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def db(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(storage_dir=tmp_path / "storage", log_json=False)


@pytest.fixture
def storage(settings: Settings) -> LocalStorage:
    return LocalStorage(settings.storage_dir)


@pytest.fixture
def enqueued() -> list[uuid.UUID]:
    """Captures the ids the API publishes to the pipeline."""
    return []


@pytest.fixture
def client(
    session_factory: sessionmaker[Session],
    settings: Settings,
    storage: LocalStorage,
    enqueued: list[uuid.UUID],
) -> Iterator[TestClient]:
    app = create_app()

    def _db() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_enqueuer] = lambda: enqueued.append
    app.dependency_overrides[get_filing_enqueuer] = lambda: enqueued.append
    with TestClient(app) as c:
        yield c


TEST_PASSWORD = "correct horse battery staple"
_PASSWORD_HASH = hash_password(TEST_PASSWORD)  # bcrypt is slow on purpose: hash once


def user_id_for(firm: Firm) -> uuid.UUID:
    return uuid.uuid5(firm.id, "staff")


def make_firm(db: Session, slug: str = "acme") -> Firm:
    """A firm plus one active user (staff@<slug>.test) to authenticate as."""
    firm = Firm(name=f"{slug.title()} Law", slug=slug)
    db.add(firm)
    db.flush()
    db.add(
        User(
            id=user_id_for(firm),
            firm_id=firm.id,
            email=f"staff@{slug}.test",
            full_name=f"{slug.title()} Staff",
            password_hash=_PASSWORD_HASH,
        )
    )
    db.commit()
    return firm


def auth_headers(firm: Firm) -> dict[str, str]:
    token = create_access_token(user_id_for(firm), firm.id, Settings())
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def firm(db: Session) -> Firm:
    return make_firm(db, "acme")


@pytest.fixture
def other_firm(db: Session) -> Firm:
    return make_firm(db, "globex")


def fake_pdf(content: str = "hello") -> bytes:
    """Minimal bytes with a PDF signature (enough for upload validation)."""
    return b"%PDF-1.4\n% " + content.encode() + b"\n%%EOF\n"
