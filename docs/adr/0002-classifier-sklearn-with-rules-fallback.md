# ADR 0002 — Document classification: scikit-learn model with a rules fallback

- Status: accepted
- Date: 2026-11-15

## Context

Each incoming document must be labelled with one of seven types. A wrong label files a
document in the wrong folder; a missing label costs a paralegal a minute. We need a
confidence score to decide between auto-filing and human review, and the classifier must
run offline, deterministically and cheaply in CI.

## Options

1. **Keyword rules only** — transparent and zero-training, but brittle to wording changes
   and hard to calibrate.
2. **TF-IDF + logistic regression (scikit-learn)** — trains in seconds, runs in
   milliseconds, `predict_proba` gives a usable confidence, deterministic, no external
   calls (good for PHI).
3. **LLM (e.g. Claude) zero/few-shot** — best on messy real-world documents and needs no
   training data, but adds latency, cost, an external dependency and a data-processing
   agreement for PHI; tests need mocks.
4. **Fine-tuned transformer** — overkill for seven classes and a small corpus.

## Decision

Option 2 with option 1 as fallback, behind a small `Classifier` protocol:

- `SklearnClassifier`: word 1–2 grams, numbers ignored (they identify cases, not types),
  logistic regression. Confidence = max class probability.
- `KeywordClassifier`: weighted regex rules; used when no model is trained, and as a
  second opinion when the model is below the threshold. If both agree, their confidences
  are combined as independent evidence.
- Below 0.6 confidence the document goes to `needs_review`.

## Consequences

- Reported accuracy (100% on held-out synthetic data) is optimistic: the corpus comes from
  templates. Real documents would need labelled data — the review queue is where it comes
  from (reviewer corrections are stored and can become training data).
- Swapping in an LLM later only means adding a `Classifier` implementation; the pipeline,
  the threshold logic and the tests stay the same.
