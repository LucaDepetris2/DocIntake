from datetime import date
from decimal import Decimal

from app.domain.entities import extract_entities, normalize_case_number

PLEADING = """SUPERIOR COURT OF THE STATE OF CALIFORNIA, COUNTY OF LOS ANGELES
JANE DOE,
Plaintiff,
v.
ACME TRUCKING LLC,
Defendant.
Case No. 2:24-cv-01234
COMPLAINT FOR DAMAGES
2. On March 3, 2024, Defendant negligently caused the collision
Hearing Date: September 12, 2024 at 9:00 a.m., Department 4
Dated: July 1, 2024
"""

BILL = """RIVERSIDE ORTHOPEDIC ASSOCIATES
ITEMIZED STATEMENT
Account #: 12345678    Statement Date: May 2, 2024
Patient: John Q. Smith
03/10/2024        99284  Emergency department visit   $1,250.00
TOTAL CHARGES: $1,700.50
BALANCE DUE: $1,450.25
"""

DISCOVERY = """Jane Doe v. Acme Trucking LLC
Case No. 2024-L-123456
PROPOUNDING PARTY: Defendant Acme Trucking LLC
RESPONDING PARTY: Plaintiff Jane Doe
Date of Service: June 3, 2024
"""


def test_extracts_federal_and_state_case_numbers() -> None:
    assert extract_entities(PLEADING).case_numbers == ["2:24-cv-01234"]
    assert extract_entities(DISCOVERY).case_numbers == ["2024-L-123456"]


def test_blank_case_number_is_ignored() -> None:
    assert extract_entities("Case No. ____________").case_numbers == []


def test_normalize_case_number_ignores_case_and_spacing() -> None:
    assert normalize_case_number(" 2:24-CV-01234 ") == normalize_case_number("2:24-cv-01234")


def test_extracts_caption_parties_from_pleading() -> None:
    entities = extract_entities(PLEADING)
    assert ("Jane Doe", "Acme Trucking Llc") in entities.parties


def test_extracts_parties_from_inline_caption() -> None:
    assert ("Jane Doe", "Acme Trucking LLC") in extract_entities(DISCOVERY).parties


def test_extracts_labelled_people() -> None:
    assert "John Q. Smith" in extract_entities(BILL).people
    assert "Jane Doe" in extract_entities(DISCOVERY).people


def test_extracts_provider_from_letterhead() -> None:
    assert extract_entities(BILL).providers == ["Riverside Orthopedic Associates"]


def test_extracts_labelled_dates() -> None:
    entities = extract_entities(PLEADING)
    assert entities.dates["hearing"] == [date(2024, 9, 12)]
    assert entities.dates["signed"] == [date(2024, 7, 1)]
    assert date(2024, 3, 3) in entities.dates["mentioned"]


def test_extracts_service_and_numeric_dates() -> None:
    assert extract_entities(DISCOVERY).dates["service"] == [date(2024, 6, 3)]
    assert date(2024, 3, 10) in extract_entities(BILL).dates["mentioned"]


def test_extracts_amounts_and_balance_due() -> None:
    entities = extract_entities(BILL)
    assert Decimal("1250.00") in entities.amounts
    assert entities.balance_due == Decimal("1450.25")


def test_to_dict_is_json_friendly() -> None:
    data = extract_entities(BILL).to_dict()
    assert data["balance_due"] == "1450.25"
    assert all(isinstance(d, str) for d in data["dates"]["mentioned"])


def test_roundtrip_from_dict() -> None:
    entities = extract_entities(PLEADING)
    assert type(entities).from_dict(entities.to_dict()) == entities
