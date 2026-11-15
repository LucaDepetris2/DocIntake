from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.rules import FilingContext, FirmRules, apply_rules
from app.domain.states import DocumentType

CTX = FilingContext(
    doc_type=DocumentType.MEDICAL_BILL,
    case_number="2:24-cv-01234",
    client_name="Jane O'Doe",
    document_date=date(2024, 5, 2),
    provider="Riverside Orthopedic Associates",
    original_filename="scan 001.PDF",
)


def test_default_rules_build_name_and_folder() -> None:
    decision = apply_rules(FirmRules(), CTX)
    assert decision.filed_name == "2024-05-02_medical_bill_jane-odoe.pdf"
    assert decision.folder == "2-24-cv-01234/Medical/Bills"
    assert decision.assignee is None


def test_custom_template_and_assignee_per_type() -> None:
    rules = FirmRules(
        naming_template="{case_number}_{doc_type}_{provider}_{date}",
        assignees={"medical_bill": "billing-team"},
        default_assignee="paralegal-pool",
    )
    decision = apply_rules(rules, CTX)
    assert (
        decision.filed_name
        == "2-24-cv-01234_medical_bill_riverside-orthopedic-associates_2024-05-02.pdf"
    )
    assert decision.assignee == "billing-team"


def test_default_assignee_when_type_not_listed() -> None:
    rules = FirmRules(default_assignee="paralegal-pool")
    assert apply_rules(rules, CTX).assignee == "paralegal-pool"


def test_missing_values_use_placeholders() -> None:
    ctx = FilingContext(
        doc_type=DocumentType.OTHER,
        case_number=None,
        client_name=None,
        document_date=None,
        provider=None,
        original_filename="x.pdf",
    )
    decision = apply_rules(FirmRules(), ctx)
    assert decision.filed_name == "undated_other_unknown.pdf"
    assert decision.folder == "unassigned/Misc"


def test_unknown_placeholder_is_rejected() -> None:
    with pytest.raises(ValidationError):
        FirmRules(naming_template="{date}_{ssn}")


def test_path_traversal_in_folders_is_rejected() -> None:
    with pytest.raises(ValidationError):
        FirmRules(folders={"other": "../../etc"})


def test_rules_roundtrip_through_dict() -> None:
    rules = FirmRules(default_assignee="pool")
    assert FirmRules.model_validate(rules.model_dump()) == rules
