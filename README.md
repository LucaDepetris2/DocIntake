# DocIntake

A mini document-intake platform for U.S. law firms (litigation / personal injury).
It receives legal and medical documents, extracts their text, classifies them,
extracts key entities, matches them to the right case (matter) and files them
automatically — or routes them to human review when confidence is low.

> All documents used in this project are **synthetic**. No real PHI is ever stored.

## Stack

Python 3.12 · FastAPI · PostgreSQL · SQLAlchemy · Alembic · RabbitMQ · Celery ·
Docker · GitHub Actions · React + TypeScript

## Repository layout

```
backend/    FastAPI app, domain logic, Celery workers and tests
docs/       Architecture notes and ADRs
scripts/    Dev utilities (e.g. synthetic document generator)
frontend/   React dashboard
```

## Getting started

Requirements: [uv](https://docs.astral.sh/uv/) and git.

```bash
cd backend
uv sync                          # creates .venv with Python 3.12 + dev tools
uv run pre-commit install        # enables git hooks
```

Run the quality checks:

```bash
cd backend
uv run ruff check .
uv run ruff format --check .
uv run mypy app tests
uv run pytest
```
