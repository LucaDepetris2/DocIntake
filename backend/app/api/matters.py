from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentFirm, DbSession
from app.api.schemas import MatterIn, MatterOut
from app.db import repositories as repo
from app.db.models import Matter

router = APIRouter(prefix="/matters", tags=["matters"])


@router.get("")
def list_matters(session: DbSession, firm: CurrentFirm) -> list[MatterOut]:
    return [MatterOut.model_validate(m) for m in repo.list_matters(session, firm.id)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_matter(body: MatterIn, session: DbSession, firm: CurrentFirm) -> MatterOut:
    matter = Matter(firm_id=firm.id, **body.model_dump())
    session.add(matter)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Case number already exists") from exc
    return MatterOut.model_validate(matter)
