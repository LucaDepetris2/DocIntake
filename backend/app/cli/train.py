"""Train the document-type classifier from a generated synthetic corpus.

It extracts text with the *same* code the pipeline uses (pdfplumber/OCR), so the model
is trained on exactly what it will see in production.

Usage:
  uv run python -m app.cli.train --data ../scripts/output --out models/classifier.joblib
"""

import argparse
import json
from pathlib import Path

from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split

from app.domain.classification import SklearnClassifier, train_model
from app.processing.extraction import extract_text


def load_corpus(data_dir: Path) -> tuple[list[str], list[str]]:
    manifest = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    texts: list[str] = []
    labels: list[str] = []
    for entry in manifest:
        text = extract_text((data_dir / entry["file"]).read_bytes()).text
        if len(text) < 50:  # scanned page without OCR available: nothing to learn from
            continue
        texts.append(text)
        labels.append(entry["doc_type"])
    return texts, labels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("../scripts/output"))
    parser.add_argument("--out", type=Path, default=Path("models/classifier.joblib"))
    args = parser.parse_args()

    texts, labels = load_corpus(args.data)
    x_train, x_test, y_train, y_test = train_test_split(
        texts, labels, test_size=0.25, stratify=labels, random_state=42
    )
    evaluation = SklearnClassifier(train_model(x_train, y_train))
    predictions = [evaluation.classify(t).doc_type.value for t in x_test]
    print(classification_report(y_test, predictions, zero_division=0))

    # Final model: train on everything we have.
    SklearnClassifier(train_model(texts, labels)).save(args.out)
    print(f"Saved model trained on {len(texts)} documents to {args.out}")


if __name__ == "__main__":
    main()
