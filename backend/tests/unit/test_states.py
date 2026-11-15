import pytest

from app.domain.states import (
    PIPELINE_ORDER,
    TERMINAL_STATES,
    DocumentStatus,
    InvalidTransitionError,
    can_transition,
    ensure_transition,
)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (DocumentStatus.RECEIVED, DocumentStatus.TEXT_EXTRACTED),
        (DocumentStatus.TEXT_EXTRACTED, DocumentStatus.CLASSIFIED),
        (DocumentStatus.CLASSIFIED, DocumentStatus.ENTITIES_EXTRACTED),
        (DocumentStatus.ENTITIES_EXTRACTED, DocumentStatus.MATCHED),
        (DocumentStatus.MATCHED, DocumentStatus.FILED),
    ],
)
def test_happy_path_transitions_are_allowed(
    current: DocumentStatus, target: DocumentStatus
) -> None:
    assert can_transition(current, target)


@pytest.mark.parametrize("current", [s for s in DocumentStatus if s not in TERMINAL_STATES])
def test_any_active_stage_can_go_to_review_or_failed(current: DocumentStatus) -> None:
    assert can_transition(current, DocumentStatus.NEEDS_REVIEW)
    assert can_transition(current, DocumentStatus.FAILED)


def test_skipping_stages_is_not_allowed() -> None:
    assert not can_transition(DocumentStatus.RECEIVED, DocumentStatus.FILED)


def test_filed_is_terminal() -> None:
    assert not can_transition(DocumentStatus.FILED, DocumentStatus.RECEIVED)
    assert not can_transition(DocumentStatus.FILED, DocumentStatus.FAILED)


def test_review_and_failed_can_be_resumed() -> None:
    # A human resolves the review -> the document is filed (or re-processed).
    assert can_transition(DocumentStatus.NEEDS_REVIEW, DocumentStatus.MATCHED)
    assert can_transition(DocumentStatus.NEEDS_REVIEW, DocumentStatus.FILED)
    # A failed document can be retried from the beginning.
    assert can_transition(DocumentStatus.FAILED, DocumentStatus.RECEIVED)


def test_ensure_transition_raises_on_invalid() -> None:
    with pytest.raises(InvalidTransitionError):
        ensure_transition(DocumentStatus.RECEIVED, DocumentStatus.MATCHED)


def test_pipeline_order_starts_received_and_ends_filed() -> None:
    assert PIPELINE_ORDER[0] is DocumentStatus.RECEIVED
    assert PIPELINE_ORDER[-1] is DocumentStatus.FILED
