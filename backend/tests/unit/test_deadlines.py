from datetime import date

from app.domain.deadlines import compute_deadlines
from app.domain.entities import Entities
from app.domain.states import DocumentType


def test_discovery_response_due_30_days_after_service_plus_5_for_mail() -> None:
    entities = Entities(dates={"service": [date(2024, 6, 3)]})
    deadlines = compute_deadlines(DocumentType.DISCOVERY_REQUEST, entities, "served by mail")
    assert [(d.kind, d.due_date) for d in deadlines] == [
        ("discovery_response_due", date(2024, 7, 8))
    ]


def test_discovery_without_mail_service_is_30_days() -> None:
    entities = Entities(dates={"service": [date(2024, 6, 3)]})
    deadline = compute_deadlines(DocumentType.DISCOVERY_REQUEST, entities, "")[0]
    assert deadline.due_date == date(2024, 7, 3)


def test_deadline_on_weekend_rolls_to_next_monday() -> None:
    entities = Entities(dates={"service": [date(2024, 6, 1)]})  # +30 = Mon Jul 1
    assert compute_deadlines(DocumentType.DISCOVERY_REQUEST, entities, "")[0].due_date == date(
        2024, 7, 1
    )
    entities = Entities(dates={"service": [date(2024, 6, 6)]})  # +30 = Sat Jul 6
    assert compute_deadlines(DocumentType.DISCOVERY_REQUEST, entities, "")[0].due_date == date(
        2024, 7, 8
    )


def test_pleading_hearing_creates_hearing_and_opposition_deadlines() -> None:
    entities = Entities(dates={"hearing": [date(2024, 9, 12)]})
    kinds = {d.kind: d.due_date for d in compute_deadlines(DocumentType.PLEADING, entities, "")}
    assert kinds["hearing"] == date(2024, 9, 12)
    assert kinds["opposition_due"] == date(2024, 8, 29)


def test_lien_notice_creates_review_reminder() -> None:
    entities = Entities(dates={"mentioned": [date(2024, 1, 10), date(2023, 5, 1)]})
    deadline = compute_deadlines(DocumentType.LIEN_NOTICE, entities, "")[0]
    assert deadline.kind == "lien_review"
    assert deadline.due_date == date(2024, 2, 9)


def test_no_dates_no_deadlines() -> None:
    assert compute_deadlines(DocumentType.DISCOVERY_REQUEST, Entities(), "") == []
    assert compute_deadlines(DocumentType.MEDICAL_RECORD, Entities(), "") == []
