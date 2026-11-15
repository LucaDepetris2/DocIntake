"""Password hashing (bcrypt) and access tokens (JWT, HS256)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.config import Settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode(), password_hash.encode())


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    firm_id: uuid.UUID


class InvalidTokenError(Exception):
    pass


def create_access_token(user_id: uuid.UUID, firm_id: uuid.UUID, settings: Settings) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "firm_id": str(firm_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )


def decode_access_token(token: str, settings: Settings) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],  # explicit list: never accept "none"
            options={"require": ["sub", "firm_id", "exp"]},
        )
        return TokenClaims(uuid.UUID(payload["sub"]), uuid.UUID(payload["firm_id"]))
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise InvalidTokenError(type(exc).__name__) from exc
