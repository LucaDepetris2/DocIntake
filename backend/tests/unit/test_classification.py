from pathlib import Path

import pytest

from app.domain.classification import (
    Classification,
    FallbackClassifier,
    KeywordClassifier,
    SklearnClassifier,
    load_classifier,
    train_model,
)
from app.domain.states import DocumentType
from tests.synthetic import corpus


class _Fixed:
    def __init__(self, result: Classification) -> None:
        self.result = result

    def classify(self, text: str) -> Classification:
        return self.result


# --- Keyword classifier (rules) ------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ITEMIZED STATEMENT ... CPT 99284 ... BALANCE DUE: $1,200.00", DocumentType.MEDICAL_BILL),
        (
            "PROGRESS NOTE Chief complaint: neck pain. ASSESSMENT / DIAGNOSIS",
            DocumentType.MEDICAL_RECORD,
        ),
        ("COMPLAINT FOR DAMAGES Plaintiff, v. Defendant. WHEREFORE", DocumentType.PLEADING),
        ("SPECIAL INTERROGATORIES, SET ONE. PROPOUNDING PARTY", DocumentType.DISCOVERY_REQUEST),
        ("NOTICE OF LIEN asserts a lien against any settlement", DocumentType.LIEN_NOTICE),
        ("Dear Counsel: thank you for your letter. Sincerely,", DocumentType.CORRESPONDENCE),
    ],
)
def test_keyword_classifier_recognises_each_type(text: str, expected: DocumentType) -> None:
    result = KeywordClassifier().classify(text)
    assert result.doc_type is expected
    assert result.method == "keywords"


def test_keyword_classifier_without_signals_returns_other_with_low_confidence() -> None:
    result = KeywordClassifier().classify("lorem ipsum dolor sit amet")
    assert result.doc_type is DocumentType.OTHER
    assert result.confidence < 0.5


def test_confidence_is_between_zero_and_one() -> None:
    result = KeywordClassifier().classify("NOTICE OF LIEN lien settlement Dear Counsel")
    assert 0.0 <= result.confidence <= 1.0


# --- Fallback composition ------------------------------------------------------


def test_fallback_keeps_primary_when_confident() -> None:
    primary = _Fixed(Classification(DocumentType.PLEADING, 0.9, "model"))
    fallback = _Fixed(Classification(DocumentType.OTHER, 0.95, "keywords"))
    assert (
        FallbackClassifier(primary, fallback, 0.6).classify("x").doc_type is DocumentType.PLEADING
    )


def test_fallback_used_when_primary_unsure_and_fallback_more_confident() -> None:
    primary = _Fixed(Classification(DocumentType.PLEADING, 0.4, "model"))
    fallback = _Fixed(Classification(DocumentType.LIEN_NOTICE, 0.7, "keywords"))
    result = FallbackClassifier(primary, fallback, 0.6).classify("x")
    assert result.doc_type is DocumentType.LIEN_NOTICE


def test_agreement_between_both_boosts_confidence() -> None:
    primary = _Fixed(Classification(DocumentType.PLEADING, 0.5, "model"))
    fallback = _Fixed(Classification(DocumentType.PLEADING, 0.5, "keywords"))
    result = FallbackClassifier(primary, fallback, 0.6).classify("x")
    assert result.doc_type is DocumentType.PLEADING
    assert result.confidence > 0.5
    assert result.method == "model+keywords"


# --- Trained model on the synthetic corpus -------------------------------------


@pytest.fixture(scope="module")
def trained() -> SklearnClassifier:
    texts, labels, _ = corpus(350, seed=1)
    return SklearnClassifier(train_model(texts, labels))


def test_model_accuracy_on_unseen_synthetic_documents(trained: SklearnClassifier) -> None:
    texts, labels, _ = corpus(140, seed=999)  # different seed: unseen documents
    correct = sum(
        trained.classify(t).doc_type.value == y for t, y in zip(texts, labels, strict=True)
    )
    assert correct / len(texts) >= 0.9


def test_model_is_unsure_about_gibberish(trained: SklearnClassifier) -> None:
    assert trained.classify("qwerty zxcvb asdf").confidence < 0.6


def test_load_classifier_without_model_falls_back_to_keywords(tmp_path: Path) -> None:
    clf = load_classifier(tmp_path / "missing.joblib", threshold=0.6)
    assert isinstance(clf, KeywordClassifier)


def test_saved_model_roundtrip(tmp_path: Path, trained: SklearnClassifier) -> None:
    path = tmp_path / "clf.joblib"
    trained.save(path)
    clf = load_classifier(path, threshold=0.6)
    assert isinstance(clf, FallbackClassifier)
    assert clf.classify("NOTICE OF LIEN against settlement").doc_type is DocumentType.LIEN_NOTICE
