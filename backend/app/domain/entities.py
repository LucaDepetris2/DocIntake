"""Entity extraction: case numbers, parties, people, providers, dates and amounts.

Deterministic regex + dateutil. Cheap, explainable and easy to unit-test; good enough for
the semi-structured documents a PI firm receives. Labelled dates ("Hearing Date: ...")
are kept separately from dates merely mentioned, because deadlines depend on the label.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from dateutil import parser as date_parser

# --- Patterns ------------------------------------------------------------------

_MONTH = (
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
)
DATE_RX = rf"(?:{_MONTH}\.? \d{{1,2}}, \d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{4}})"

CASE_NUMBER_PATTERNS = [
    re.compile(r"\b\d{1,2}:\d{2}-[a-z]{2}-\d{3,6}\b", re.IGNORECASE),  # federal 2:24-cv-01234
    re.compile(r"\b\d{4}-[A-Z]{1,3}-\d{4,7}\b"),  # state 2024-L-123456
]

LABELLED_DATES = {
    "service": re.compile(rf"Date of Service:\s*({DATE_RX})|served by mail on ({DATE_RX})", re.I),
    "hearing": re.compile(rf"Hearing Date:\s*({DATE_RX})", re.I),
    "signed": re.compile(rf"\bDated:\s*({DATE_RX})", re.I),
    "incident": re.compile(rf"Date of (?:Incident|Loss|Accident):\s*({DATE_RX})", re.I),
    "statement": re.compile(rf"Statement Date:\s*({DATE_RX})", re.I),
}
ANY_DATE = re.compile(DATE_RX)

PEOPLE_LABELS = re.compile(
    r"^(?:Patient|Client|Beneficiary/Patient|Our Insured/Claimant|Patient/Client|Employee|"
    r"Name|Guarantor|RESPONDING PARTY: Plaintiff)\s*:?\s+"
    r"(?P<name>[A-Z][A-Za-z'.-]+(?: [A-Z][A-Za-z'.-]+){1,3})",
    re.MULTILINE,
)
INLINE_CAPTION = re.compile(
    r"^(?:Re: )?(?P<p>[A-Z][\w'.-]+(?: [A-Z][\w'.,-]+){1,4}) v\. "
    r"(?P<d>[A-Z][\w'.-]+(?: [A-Z][\w'.&-]+){0,5}?)(?:,| *$)",
    re.MULTILINE,
)
BLOCK_CAPTION = re.compile(
    r"^(?P<p>[A-Z][A-Z'.\- ]+),\s*\n\s*Plaintiffs?,\s*\n\s*v(?:s)?\.\s*\n"
    r"(?P<d>[A-Z][A-Z0-9'.,&\- ]+?),?\s*\n\s*Defendants?\.",
    re.MULTILINE,
)
PROVIDER_RX = re.compile(
    r"^(?P<name>[A-Z][A-Z.&' ]*(?:HOSPITAL|CLINIC|CENTER|ASSOCIATES|MEDICINE|THERAPY|"
    r"IMAGING|ORTHOPEDICS?|MEDICAL GROUP)[A-Z.&' ]*)$",
    re.MULTILINE,
)
AMOUNT_RX = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)")
BALANCE_RX = re.compile(r"(?:BALANCE DUE|AMOUNT DUE)\s*:?\s*\$\s?([\d,]+\.\d{2})", re.I)


@dataclass
class Entities:
    case_numbers: list[str] = field(default_factory=list)
    parties: list[tuple[str, str]] = field(default_factory=list)  # (plaintiff, defendant)
    people: list[str] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    dates: dict[str, list[date]] = field(default_factory=dict)
    amounts: list[Decimal] = field(default_factory=list)
    balance_due: Decimal | None = None

    def all_dates(self) -> list[date]:
        return sorted({d for values in self.dates.values() for d in values})

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_numbers": self.case_numbers,
            "parties": [list(p) for p in self.parties],
            "people": self.people,
            "providers": self.providers,
            "dates": {k: [d.isoformat() for d in v] for k, v in self.dates.items()},
            "amounts": [str(a) for a in self.amounts],
            "balance_due": str(self.balance_due) if self.balance_due is not None else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Entities":
        return cls(
            case_numbers=list(data.get("case_numbers", [])),
            parties=[(p[0], p[1]) for p in data.get("parties", [])],
            people=list(data.get("people", [])),
            providers=list(data.get("providers", [])),
            dates={k: [date.fromisoformat(d) for d in v] for k, v in data.get("dates", {}).items()},
            amounts=[Decimal(a) for a in data.get("amounts", [])],
            balance_due=Decimal(data["balance_due"]) if data.get("balance_due") else None,
        )


def normalize_case_number(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _unique(items: list[Any]) -> list[Any]:
    return list(dict.fromkeys(items))


def _parse_date(raw: str) -> date | None:
    try:
        return date_parser.parse(raw, fuzzy=False).date()
    except (ValueError, OverflowError):
        return None


def _title(name: str) -> str:
    return " ".join(w.capitalize() if w.isupper() and len(w) > 1 else w for w in name.split())


def _money(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def extract_entities(text: str) -> Entities:
    entities = Entities()

    for rx in CASE_NUMBER_PATTERNS:
        entities.case_numbers += [m.group(0) for m in rx.finditer(text)]
    entities.case_numbers = _unique(entities.case_numbers)

    for m in BLOCK_CAPTION.finditer(text):
        entities.parties.append((_title(m["p"].strip()), _title(m["d"].strip().rstrip(","))))
    for m in INLINE_CAPTION.finditer(text):
        entities.parties.append((m["p"].strip(), m["d"].strip().rstrip(",")))
    entities.parties = _unique(entities.parties)

    entities.people = _unique([m["name"].strip() for m in PEOPLE_LABELS.finditer(text)])
    entities.providers = _unique([_title(m["name"].strip()) for m in PROVIDER_RX.finditer(text)])

    for label, rx in LABELLED_DATES.items():
        found = [
            d
            for m in rx.finditer(text)
            for raw in m.groups()
            if raw and (d := _parse_date(raw)) is not None
        ]
        if found:
            entities.dates[label] = _unique(found)
    mentioned = [d for m in ANY_DATE.finditer(text) if (d := _parse_date(m.group(0)))]
    if mentioned:
        entities.dates["mentioned"] = sorted(set(mentioned))

    entities.amounts = _unique(
        [a for m in AMOUNT_RX.finditer(text) if (a := _money(m.group(1))) is not None]
    )
    if (balance := BALANCE_RX.search(text)) is not None:
        entities.balance_due = _money(balance.group(1))
    return entities
