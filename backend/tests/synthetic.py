"""Access to the synthetic document generator (scripts/generate_fake_docs.py) from tests.

Tests use the generator's text templates directly (no PDF rendering) to build a labelled
corpus quickly and deterministically.
"""

import importlib.util
import random
import sys
from functools import cache
from pathlib import Path
from types import ModuleType

from faker import Faker

GENERATOR_PATH = Path(__file__).resolve().parents[2] / "scripts" / "generate_fake_docs.py"


@cache
def generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_fake_docs", GENERATOR_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_fake_docs"] = module
    spec.loader.exec_module(module)
    return module


def corpus(n: int, seed: int) -> tuple[list[str], list[str], list[dict[str, object]]]:
    """Return (texts, labels, meta) for n synthetic documents."""
    gen = generator()
    rng = random.Random(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)
    matters = gen.make_matters(fake, rng, per_firm=10)
    texts: list[str] = []
    labels: list[str] = []
    meta: list[dict[str, object]] = []
    for i in range(n):
        doc_type = gen.DOC_TYPES[i % len(gen.DOC_TYPES)]
        m = rng.choice(matters)
        with_case = rng.random() > 0.25
        misspelled = rng.random() < 0.15
        client = gen._misspell(rng, m.client_name) if misspelled else m.client_name
        lines = gen.TEMPLATES[doc_type](fake, rng, m, client, with_case)
        texts.append("\n".join(lines))
        labels.append(doc_type)
        meta.append(
            {
                "matter": m,
                "with_case": with_case,
                "misspelled": misspelled,
                "matters": matters,
            }
        )
    return texts, labels, meta
