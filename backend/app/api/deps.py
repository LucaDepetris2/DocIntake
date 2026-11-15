from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth import InvalidTokenError, decode_access_token
from app.config import Settings, get_settings
from app.db import repositories as repo
from app.db.models import Firm, User
from app.db.session import get_db
from app.storage import LocalStorage, get_storage
from app.workers.dispatch import Enqueuer, enqueue_filing, enqueue_processing

DbSession = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
StorageDep = Annotated[LocalStorage, Depends(get_storage)]


def get_enqueuer() -> Enqueuer:
    return enqueue_processing


EnqueuerDep = Annotated[Enqueuer, Depends(get_enqueuer)]


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED,
    "Invalid or expired credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    session: DbSession, settings: SettingsDep, token: Annotated[str, Depends(oauth2_scheme)]
) -> User:
    try:
        claims = decode_access_token(token, settings)
    except InvalidTokenError:
        raise _UNAUTHORIZED from None
    user = session.get(User, claims.user_id)
    # The firm in the token must still be the user's firm (e.g. user moved/disabled).
    if user is None or not user.is_active or user.firm_id != claims.firm_id:
        raise _UNAUTHORIZED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_firm(session: DbSession, user: CurrentUser) -> Firm:
    """The tenant always comes from the authenticated user, never from client input."""
    firm = repo.get_firm(session, user.firm_id)
    if firm is None:
        raise _UNAUTHORIZED
    return firm


CurrentFirm = Annotated[Firm, Depends(get_current_firm)]


def get_filing_enqueuer() -> Enqueuer:
    return enqueue_filing


FilingEnqueuerDep = Annotated[Enqueuer, Depends(get_filing_enqueuer)]
