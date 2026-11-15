"""Match a document to one of the firm's matters (cases).

Scoring per candidate matter:
  * an extracted case number equal to the matter's -> 1.0 (decisive)
  * otherwise a weighted blend of
      client name similarity     (best of labelled people / caption parties / free text)
      defendant similarity       (caption parties / free text)
      date evidence              (the incident date appears in the document)

Decision:
  score >= auto and clearly ahead of the runner-up -> "auto"   (file it)
  score >= review                                  -> "review" (a human confirms)
  otherwise                                        -> "none"   (a human picks the matter)
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from rapidfuzz import fuzz

from app.domain.entities import Entities, normalize_case_number

Outcome = Literal["auto", "review", "none"]

W_CLIENT = 0.65
W_DEFENDANT = 0.25
W_DATE = 0.10
AMBIGUITY_MARGIN = 0.05


@dataclass(frozen=True)
class MatterCandidate:
    id: uuid.UUID
    case_number: str
    client_name: str
    defendant: str | None
    incident_date: date | None


@dataclass
class MatchDecision:
    matter_id: uuid.UUID | None
    confidence: float
    outcome: Outcome
    reason: str
    candidates: list[tuple[uuid.UUID, float]] = field(default_factory=list)


def _name_similarity(name: str, mentions: list[str], text: str) -> float:
    """Best similarity of `name` against explicit mentions, or the raw text as a weaker hint."""
    if not name:
        return 0.0
    best = max((fuzz.token_sort_ratio(name, m) / 100 for m in mentions), default=0.0)
    # partial_ratio finds the name anywhere in the text; discounted because it is noisier.
    in_text = fuzz.partial_ratio(name.lower(), text.lower()) / 100 * 0.9
    return max(best, in_text)


def _score(candidate: MatterCandidate, entities: Entities, text: str) -> tuple[float, str]:
    wanted = normalize_case_number(candidate.case_number)
    if any(normalize_case_number(c) == wanted for c in entities.case_numbers):
        return 1.0, "case number"

    plaintiffs = [p for p, _ in entities.parties]
    defendants = [d for _, d in entities.parties]
    client = _name_similarity(candidate.client_name, entities.people + plaintiffs, text)
    defendant = (
        _name_similarity(candidate.defendant, defendants, text) if candidate.defendant else 0.0
    )
    has_date = (
        candidate.incident_date is not None and candidate.incident_date in entities.all_dates()
    )

    # Names below ~0.75 similarity are mostly noise: don't let them accumulate score.
    client = client if client >= 0.75 else 0.0
    defendant = defendant if defendant >= 0.75 else 0.0
    score = W_CLIENT * client + W_DEFENDANT * defendant + W_DATE * float(has_date)
    # Many documents (letters, medical records) never name the defendant. A strong client
    # match is then good evidence on its own: give it a floor that can reach "auto", and
    # let the date still add on top (more evidence must never lower the score).
    if client >= 0.9 and defendant == 0.0:
        score = max(score, 0.85 * client + W_DATE * float(has_date))
    reason = f"client={client:.2f} defendant={defendant:.2f} date={'yes' if has_date else 'no'}"
    return round(min(score, 0.99), 4), reason


def match_matter(
    entities: Entities,
    text: str,
    matters: list[MatterCandidate],
    *,
    auto: float,
    review: float,
) -> MatchDecision:
    if not matters:
        return MatchDecision(None, 0.0, "none", "firm has no matters")

    scored = sorted(
        ((m, *_score(m, entities, text)) for m in matters), key=lambda t: t[1], reverse=True
    )
    ranking = [(m.id, s) for m, s, _ in scored[:5]]
    best, best_score, reason = scored[0]
    runner_up = scored[1][1] if len(scored) > 1 else 0.0

    if best_score < review:
        return MatchDecision(
            None, best_score, "none", f"no candidate above review threshold ({reason})", ranking
        )
    if best_score - runner_up < AMBIGUITY_MARGIN and best_score < 1.0:
        return MatchDecision(
            best.id,
            best_score,
            "review",
            f"ambiguous: top candidates within {AMBIGUITY_MARGIN}",
            ranking,
        )
    if best_score >= auto:
        return MatchDecision(best.id, best_score, "auto", reason, ranking)
    return MatchDecision(best.id, best_score, "review", f"low confidence ({reason})", ranking)
