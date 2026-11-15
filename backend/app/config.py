"""Application settings, loaded from environment variables (12-factor style).

Never hard-code secrets: every value here can be overridden via env vars or a local
`.env` file (which is git-ignored).
"""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Placeholder (>= 32 bytes so HS256 doesn't warn in dev); rejected outside dev.
DEV_JWT_SECRET = "dev-only-insecure-secret-change-me-0000"  # noqa: S105
MIN_JWT_SECRET_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "dev"

    # Infrastructure
    database_url: str = "postgresql+psycopg://docintake:docintake@localhost:5432/docintake"
    broker_url: str = "amqp://guest:guest@localhost:5672//"
    storage_dir: Path = Path("./storage")

    # Uploads
    max_upload_bytes: int = 20 * 1024 * 1024

    # Processing
    classification_threshold: float = 0.6
    match_auto_threshold: float = 0.85
    match_review_threshold: float = 0.6
    classifier_model_path: Path = Path("./models/classifier.joblib")
    task_max_retries: int = 3
    celery_task_always_eager: bool = False

    # Auth
    jwt_secret: SecretStr = SecretStr(DEV_JWT_SECRET)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60

    # Observability
    log_level: str = "INFO"
    log_json: bool = True
    worker_metrics_port: int = 9100

    @model_validator(mode="after")
    def _no_default_secret_outside_dev(self) -> "Settings":
        if self.environment in {"dev", "test"}:
            return self
        secret = self.jwt_secret.get_secret_value()
        if secret == DEV_JWT_SECRET:
            raise ValueError("JWT_SECRET must be set outside the dev environment")
        if len(secret.encode()) < MIN_JWT_SECRET_BYTES:
            # RFC 7518 3.2: an HS256 key must be at least as long as the hash output.
            raise ValueError(f"JWT_SECRET must be at least {MIN_JWT_SECRET_BYTES} bytes")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
