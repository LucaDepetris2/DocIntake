"""Integration fixtures: a real PostgreSQL with the schema built by Alembic migrations.

Backend selection (env INTEGRATION_DB):
  testcontainers -> throwaway postgres:16 container (needs Docker; used in CI)
  pgserver       -> embedded Postgres binary from the `pgserver` wheel (no Docker needed)
  auto (default) -> testcontainers if Docker is reachable, else pgserver, else skip
"""

import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from alembic import command
from app.api.deps import get_enqueuer, get_filing_enqueuer
from app.config import Settings, get_settings
from app.db.session import get_db
from app.main import create_app
from app.storage import LocalStorage, get_storage

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        import docker

        docker.from_env().ping()
        return True
    except Exception:
        return False


def _start_postgres() -> Iterator[str]:
    mode = os.environ.get("INTEGRATION_DB", "auto")
    if mode == "testcontainers" or (mode == "auto" and _docker_available()):
        from testcontainers.community.postgres import PostgresContainer

        with PostgresContainer("postgres:16-alpine", driver="psycopg") as pg:
            yield pg.get_connection_url()
        return
    try:
        import pgserver
    except ImportError:
        pytest.skip("No Docker and no pgserver: integration tests skipped")
    server = pgserver.get_server(tempfile.mkdtemp(prefix="docintake-pg-"), cleanup_mode="stop")  # type: ignore[attr-defined]
    yield server.get_uri().replace("postgresql://", "postgresql+psycopg://")


@pytest.fixture(scope="session")
def pg_url() -> Iterator[str]:
    yield from _start_postgres()


@pytest.fixture(scope="session")
def pg_engine(pg_url: str) -> Iterator[Engine]:
    """Schema created by running the real migrations (this also tests the migrations)."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", pg_url)
    command.upgrade(cfg, "head")
    engine = create_engine(pg_url)
    yield engine
    engine.dispose()


@pytest.fixture
def pg_session_factory(pg_engine: Engine) -> Iterator[sessionmaker[Session]]:
    yield sessionmaker(bind=pg_engine, expire_on_commit=False)
    # Isolation between tests: wipe data, keep the schema.
    with pg_engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE alerts, document_events, documents, matters, firm_rules, users, firms "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture
def pg_db(pg_session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with pg_session_factory() as session:
        yield session


@pytest.fixture
def pg_client(
    pg_session_factory: sessionmaker[Session],
    settings: Settings,
    storage: LocalStorage,
    enqueued: list[object],
) -> Iterator[TestClient]:
    app = create_app()

    def _db() -> Iterator[Session]:
        with pg_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_storage] = lambda: storage
    app.dependency_overrides[get_enqueuer] = lambda: enqueued.append
    app.dependency_overrides[get_filing_enqueuer] = lambda: enqueued.append
    with TestClient(app) as client:
        yield client
