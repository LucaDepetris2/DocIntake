from fastapi import FastAPI

from app.api import auth, documents, firm, health, matters, review
from app.config import get_settings
from app.db.session import get_sessionmaker
from app.observability.correlation import correlation_middleware
from app.observability.logging import configure_logging
from app.observability.metrics import register_document_collector


def create_app() -> FastAPI:
    """Build the FastAPI application (app factory, so tests can create isolated instances)."""
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    register_document_collector(lambda: get_sessionmaker()())

    app = FastAPI(title="DocIntake", version="0.1.0")
    app.middleware("http")(correlation_middleware)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(matters.router)
    app.include_router(documents.router)
    app.include_router(review.router)
    app.include_router(firm.router)
    return app


app = create_app()
