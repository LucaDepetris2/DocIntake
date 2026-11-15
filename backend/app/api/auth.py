import secrets
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, SettingsDep
from app.auth import create_access_token, hash_password, verify_password
from app.db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])

# Verifying against a dummy hash when the user doesn't exist keeps response time similar,
# so the endpoint doesn't reveal which emails are registered (timing side channel).
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    firm_id: uuid.UUID
    firm_name: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 (token type, not a secret)
    user: UserOut


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        firm_id=user.firm_id,
        firm_name=user.firm.name,
    )


@router.post("/token")
def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: DbSession,
    settings: SettingsDep,
) -> TokenOut:
    """OAuth2 password flow (form fields `username` = email, `password`)."""
    user = session.scalars(
        select(User).where(func.lower(User.email) == form.username.strip().lower())
    ).one_or_none()
    password_ok = verify_password(form.password, user.password_hash if user else _DUMMY_HASH)
    if user is None or not password_ok or not user.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(user.id, user.firm_id, settings)
    return TokenOut(access_token=token, user=_user_out(user))


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return _user_out(user)
