"""Firm-level endpoints: filing rules, deadline alerts and inbox stats."""

import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import CurrentFirm, DbSession
from app.api.schemas import AlertOut, StatusCount
from app.db.models import Alert, Document, FirmRuleSet
from app.domain.rules import FirmRules
from app.workers.stages import firm_rules

router = APIRouter(tags=["firm"])


@router.get("/rules")
def get_rules(session: DbSession, firm: CurrentFirm) -> FirmRules:
    return firm_rules(session, firm.id)


@router.put("/rules")
def put_rules(rules: FirmRules, session: DbSession, firm: CurrentFirm) -> FirmRules:
    """Replace the firm's rules. Pydantic validation rejects unknown placeholders and
    unsafe folders with a 422 before anything is stored."""
    row = session.get(FirmRuleSet, firm.id)
    if row is None:
        session.add(FirmRuleSet(firm_id=firm.id, config=rules.model_dump()))
    else:
        row.config = rules.model_dump()
    session.commit()
    return rules


@router.get("/alerts")
def list_alerts(
    session: DbSession,
    firm: CurrentFirm,
    resolved: Annotated[bool, Query()] = False,
) -> list[AlertOut]:
    stmt = (
        select(Alert)
        .where(Alert.firm_id == firm.id, Alert.resolved == resolved)
        .order_by(Alert.due_date)
    )
    return [AlertOut.model_validate(a) for a in session.scalars(stmt)]


@router.post("/alerts/{alert_id}/resolve")
def resolve_alert(alert_id: uuid.UUID, session: DbSession, firm: CurrentFirm) -> AlertOut:
    alert = session.scalars(
        select(Alert).where(Alert.id == alert_id, Alert.firm_id == firm.id)
    ).one_or_none()
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert not found")
    alert.resolved = True
    session.commit()
    return AlertOut.model_validate(alert)


@router.get("/stats")
def stats(session: DbSession, firm: CurrentFirm) -> list[StatusCount]:
    rows = session.execute(
        select(Document.status, func.count())
        .where(Document.firm_id == firm.id)
        .group_by(Document.status)
    ).all()
    return [StatusCount(status=s, count=c) for s, c in rows]
