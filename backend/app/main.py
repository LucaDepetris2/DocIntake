from fastapi import FastAPI

from app.api import auth, documents, firm, health, matters, review


def create_app() -> FastAPI:
    """Build the FastAPI application (app factory, so tests can create isolated instances)."""
    app = FastAPI(title="DocIntake", version="0.1.0")
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(matters.router)
    app.include_router(documents.router)
    app.include_router(review.router)
    app.include_router(firm.router)
    return app


app = create_app()
