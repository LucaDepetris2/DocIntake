from typing import Literal

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

router = APIRouter(tags=["ops"])


class HealthResponse(BaseModel):
    status: Literal["ok"]


@router.get("/health")
def health() -> HealthResponse:
    """Liveness probe: the process is up and serving requests."""
    return HealthResponse(status="ok")


@router.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    """Prometheus scrape endpoint. Not exposed publicly: nginx blocks it (see nginx.conf)."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
