"""Document type classification.

Two strategies behind one small interface (`Classifier`):

* `SklearnClassifier`: TF-IDF (word 1-2 grams) + logistic regression. Its
  `predict_proba` gives a probability per class; the highest one is the confidence.
* `KeywordClassifier`: weighted regex rules. Transparent, needs no training data, and is
  the fallback when there is no trained model or the model is unsure.

`FallbackClassifier` combines them. Anything below the confidence threshold is sent to
human review by the pipeline instead of being filed automatically.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline

from app.domain.states import DocumentType


@dataclass(frozen=True)
class Classification:
    doc_type: DocumentType
    confidence: float
    method: str


class Classifier(Protocol):
    def classify(self, text: str) -> Classification: ...


# --- Rules ---------------------------------------------------------------------

KEYWORDS: dict[DocumentType, list[tuple[str, float]]] = {
    DocumentType.MEDICAL_BILL: [
        (r"itemized statement|statement of charges|billing statement", 3.0),
        (r"balance due|total charges|amount due", 2.0),
        (r"\bcpt\b|account #", 1.5),
    ],
    DocumentType.MEDICAL_RECORD: [
        (r"progress note|clinical note|office visit note|discharge summary", 3.0),
        (r"chief complaint|history of present illness|physical examination", 2.0),
        (r"assessment|diagnosis|attending physician", 1.0),
    ],
    DocumentType.PLEADING: [
        (r"complaint for damages|answer to complaint|motion to|summary judgment", 3.0),
        (r"\bplaintiff,|\bdefendant\.|wherefore|prays for judgment", 2.0),
        (r"respectfully submitted|hearing date", 1.0),
    ],
    DocumentType.DISCOVERY_REQUEST: [
        (r"interrogator(y|ies)|request(s)? for (production|admission)", 3.0),
        (r"propounding party|responding party", 2.5),
        (r"proof of service|set no\.", 1.0),
    ],
    DocumentType.LIEN_NOTICE: [
        (r"notice of (medical )?lien|conditional payment", 3.0),
        (r"asserts a lien|lien (in the amount|reference)", 2.5),
        (r"settlement|subrogation|recovery", 1.0),
    ],
    DocumentType.CORRESPONDENCE: [
        (r"dear (counsel|sir|madam|mr\.|ms\.)", 3.0),
        (r"sincerely|very truly yours|regards,", 2.0),
        (r"via (email|facsimile|certified mail)|claim no\.", 1.0),
    ],
}

_COMPILED = {
    doc_type: [(re.compile(pattern, re.IGNORECASE), weight) for pattern, weight in rules]
    for doc_type, rules in KEYWORDS.items()
}


class KeywordClassifier:
    """Scores each type by the weighted rules that fire; confidence = winner's share."""

    min_score = 2.0  # below this there is no real signal -> OTHER

    def classify(self, text: str) -> Classification:
        scores = {
            doc_type: sum(weight for rx, weight in rules if rx.search(text))
            for doc_type, rules in _COMPILED.items()
        }
        best, best_score = max(scores.items(), key=lambda kv: kv[1])
        if best_score < self.min_score:
            return Classification(DocumentType.OTHER, 0.3, "keywords")
        total = sum(scores.values())
        # Share of the evidence, damped when the absolute evidence is weak.
        share = best_score / total
        strength = min(1.0, best_score / 5.0)
        return Classification(best, round(share * (0.5 + 0.5 * strength), 4), "keywords")


# --- Model ---------------------------------------------------------------------


def train_model(texts: list[str], labels: list[str]) -> Pipeline:
    pipeline = Pipeline(
        [
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    ngram_range=(1, 2),
                    min_df=2,
                    sublinear_tf=True,
                    # Ignore numbers/ids: they identify cases, not document types.
                    token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z]+\b",  # noqa: S106 (regex, not a secret)
                ),
            ),
            ("clf", LogisticRegression(max_iter=2000, C=4.0)),
        ]
    )
    pipeline.fit(texts, labels)
    return pipeline


class SklearnClassifier:
    def __init__(self, pipeline: Pipeline) -> None:
        self.pipeline = pipeline

    def classify(self, text: str) -> Classification:
        probabilities: Any = self.pipeline.predict_proba([text])[0]
        classes: Any = self.pipeline.classes_
        best = int(probabilities.argmax())
        return Classification(
            DocumentType(str(classes[best])), round(float(probabilities[best]), 4), "model"
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipeline, path)

    @classmethod
    def load(cls, path: Path) -> "SklearnClassifier":
        return cls(joblib.load(path))


class FallbackClassifier:
    def __init__(self, primary: Classifier, fallback: Classifier, threshold: float) -> None:
        self.primary = primary
        self.fallback = fallback
        self.threshold = threshold

    def classify(self, text: str) -> Classification:
        first = self.primary.classify(text)
        if first.confidence >= self.threshold:
            return first
        second = self.fallback.classify(text)
        if second.doc_type is first.doc_type:
            # Two independent methods agree: combine as independent evidence.
            combined = 1 - (1 - first.confidence) * (1 - second.confidence)
            return Classification(
                first.doc_type, round(combined, 4), f"{first.method}+{second.method}"
            )
        return second if second.confidence > first.confidence else first


def load_classifier(model_path: Path, threshold: float) -> Classifier:
    """Model + rules if a trained model exists, otherwise rules only."""
    if model_path.exists():
        return FallbackClassifier(
            SklearnClassifier.load(model_path), KeywordClassifier(), threshold
        )
    return KeywordClassifier()
