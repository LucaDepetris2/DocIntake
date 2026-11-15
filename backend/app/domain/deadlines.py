"""Deadline rules derived from a document (simplified, California-flavoured).

Real calendaring rules depend on jurisdiction and court holidays; these are illustrative,
explicit and unit-tested, which is the point: a missed deadline is malpractice, so the
logic must be easy to read and verify.
"""

import re
from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.entities import Entities
from app.domain.states import DocumentType

DISCOVERY_RESPONSE_DAYS = 30
MAIL_SERVICE_EXTENSION_DAYS = 5  # e.g. CA CCP 1013(a)
OPPOSITION_DAYS_BEFORE_HEARING = 14
LIEN_REVIEW_DAYS = 30

_MAIL_SERVICE = re.compile(r"served by mail|via (u\.s\. )?mail|certified mail", re.I)


@dataclass(frozen=True)
class Deadline:
    kind: str
    due_date: date
    description: str


def next_business_day(day: date) -> date:
    while day.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        day += timedelta(days=1)
    return day


def previous_business_day(day: date) -> date:
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def compute_deadlines(doc_type: DocumentType, entities: Entities, text: str) -> list[Deadline]:
    deadlines: list[Deadline] = []

    if doc_type is DocumentType.DISCOVERY_REQUEST and entities.dates.get("service"):
        served = entities.dates["service"][0]
        days = DISCOVERY_RESPONSE_DAYS
        if _MAIL_SERVICE.search(text):
            days += MAIL_SERVICE_EXTENSION_DAYS
        deadlines.append(
            Deadline(
                "discovery_response_due",
                next_business_day(served + timedelta(days=days)),
                f"Discovery responses due ({days} days from service on {served.isoformat()})",
            )
        )

    if doc_type is DocumentType.PLEADING and entities.dates.get("hearing"):
        hearing = entities.dates["hearing"][0]
        deadlines.append(Deadline("hearing", hearing, "Court hearing"))
        deadlines.append(
            Deadline(
                "opposition_due",
                previous_business_day(hearing - timedelta(days=OPPOSITION_DAYS_BEFORE_HEARING)),
                f"Opposition due {OPPOSITION_DAYS_BEFORE_HEARING} days before hearing",
            )
        )

    if doc_type is DocumentType.LIEN_NOTICE:
        notice_date = max(entities.dates.get("mentioned", []), default=None)
        if notice_date is not None:
            deadlines.append(
                Deadline(
                    "lien_review",
                    next_business_day(notice_date + timedelta(days=LIEN_REVIEW_DAYS)),
                    "Review lien before any settlement disbursement",
                )
            )

    return deadlines
