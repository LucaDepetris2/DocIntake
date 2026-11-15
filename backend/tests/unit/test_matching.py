import uuid
from datetime import date

from app.domain.entities import Entities, extract_entities
from app.domain.matching import MatchDecision, MatterCandidate, match_matter
from tests.synthetic import corpus

DOE = MatterCandidate(
    id=uuid.uuid4(),
    case_number="2:24-cv-01234",
    client_name="Jane Doe",
    defendant="Acme Trucking LLC",
    incident_date=date(2024, 3, 3),
)
ROE = MatterCandidate(
    id=uuid.uuid4(),
    case_number="2024-L-555555",
    client_name="Richard Roe",
    defendant="Globex Corp",
    incident_date=date(2023, 1, 9),
)
MATTERS = [DOE, ROE]


def _match(text: str, matters: list[MatterCandidate] = MATTERS) -> MatchDecision:
    return match_matter(extract_entities(text), text, matters, auto=0.85, review=0.6)


def test_exact_case_number_is_an_automatic_match() -> None:
    result = _match("Re: something\nCase No. 2:24-CV-01234\nunrelated words")
    assert result.matter_id == DOE.id
    assert result.confidence == 1.0
    assert result.outcome == "auto"


def test_client_name_and_defendant_without_case_number_match_automatically() -> None:
    result = _match("Re: Jane Doe v. Acme Trucking LLC\nDear Counsel:")
    assert result.matter_id == DOE.id
    assert result.outcome == "auto"


def test_misspelled_client_name_still_matches() -> None:
    result = _match("Patient: Jnae Doe\nDate of Incident: March 3, 2024\nDear Counsel:")
    assert result.matter_id == DOE.id
    assert result.outcome in {"auto", "review"}


def test_more_evidence_never_lowers_the_score() -> None:
    """Regression: an exact client name plus the incident date scored *lower* than the
    client name alone (found by the end-to-end benchmark)."""
    client_only = _match("Patient: Richard Roe\nDear Counsel:")
    with_date = _match("Patient: Richard Roe\nDate of Incident: January 9, 2023\nDear Counsel:")
    assert with_date.confidence >= client_only.confidence
    assert with_date.outcome == "auto"
    assert with_date.matter_id == ROE.id


def test_nothing_recognisable_is_no_match() -> None:
    result = _match("Lorem ipsum, nothing to see here.")
    assert result.matter_id is None
    assert result.outcome == "none"


def test_ambiguous_clients_go_to_review() -> None:
    twin = MatterCandidate(
        id=uuid.uuid4(),
        case_number="2024-L-999999",
        client_name="Jane Doe",
        defendant="Initech",
        incident_date=None,
    )
    result = _match("Patient: Jane Doe\nDear Counsel:", [DOE, twin])
    assert result.outcome == "review"
    assert "ambiguous" in result.reason


def test_unknown_case_number_falls_back_to_names() -> None:
    result = _match("Case No. 9:99-cv-99999\nRe: Richard Roe v. Globex Corp")
    assert result.matter_id == ROE.id


def test_candidates_are_ranked() -> None:
    result = _match("Re: Jane Doe v. Acme Trucking LLC")
    assert result.candidates[0][0] == DOE.id
    assert result.candidates[0][1] >= result.candidates[1][1]


def test_empty_matter_list() -> None:
    result = match_matter(Entities(), "", [], auto=0.85, review=0.6)
    assert result.outcome == "none"


def test_auto_matches_on_synthetic_corpus_are_precise() -> None:
    """Auto-filing must almost never pick the wrong case; recall can go to review."""
    texts, _, meta = corpus(210, seed=7)
    auto = correct_auto = 0
    for text, m in zip(texts, meta, strict=True):
        matter = m["matter"]
        candidates = [
            MatterCandidate(
                id=uuid.uuid5(uuid.NAMESPACE_DNS, x.case_number),
                case_number=x.case_number,
                client_name=x.client_name,
                defendant=x.defendant,
                incident_date=date.fromisoformat(x.incident_date),
            )
            for x in m["matters"]  # type: ignore[attr-defined]
            if x.firm_slug == matter.firm_slug  # type: ignore[attr-defined]
        ]
        result = match_matter(extract_entities(text), text, candidates, auto=0.85, review=0.6)
        if result.outcome == "auto":
            auto += 1
            correct_auto += result.matter_id == uuid.uuid5(uuid.NAMESPACE_DNS, matter.case_number)  # type: ignore[attr-defined]
    assert auto / len(texts) >= 0.7  # most documents are filed without a human
    assert correct_auto / auto >= 0.98
