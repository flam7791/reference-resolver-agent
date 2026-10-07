"""Evaluation against a gold set of citations with known answers.

Gold file (JSON Lines): {"id": "g01", "citation": "...", "expected": "10.1086/705716"}
`expected` is null when the cited item has no registered identifier (an unpublished note,
a web page): linking those is a false link.

The metrics reflect what matters in practice:
- precision of automatic links: a wrong link is worse than no link, because nobody checks it;
- false links on unresolvable items: the system should say "not found", not guess;
- recall: share of resolvable citations linked correctly without a person;
- review rate, and whether the right answer is in the review queue's suggestions (does review
  save the reviewer time?);
- cost per reference;
- calibration: for each band of the top candidate's deterministic score, and of the model's
  stated confidence on the choices it made, how often the choice was the right work. The
  thresholds (`REFRESOLVER_AUTO_ACCEPT`, `REFRESOLVER_LLM_ACCEPT`) are policy; these tables are
  the evidence for setting them. A model's stated confidence is not calibrated by itself.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .models import Resolution
from .resolver import Resolver


@dataclass
class EvalResult:
    total: int = 0
    resolvable: int = 0
    linked: int = 0
    correct_links: int = 0
    wrong_links: int = 0
    false_links: int = 0  # linked although nothing should have been
    review: int = 0
    review_has_answer: int = 0
    unresolved: int = 0
    source_errors: int = 0  # searches a scholarly database failed or refused
    cost_usd: float = 0.0
    errors: list[dict] = field(default_factory=list)
    score_bands: list[dict] = field(default_factory=list)  # top deterministic score vs correct
    confidence_bands: list[dict] = field(default_factory=list)  # model confidence vs correct

    @property
    def precision(self) -> float:
        return self.correct_links / self.linked if self.linked else 1.0

    @property
    def recall(self) -> float:
        return self.correct_links / self.resolvable if self.resolvable else 0.0

    @property
    def review_rate(self) -> float:
        return self.review / self.total if self.total else 0.0

    def table(self) -> str:
        rows = [
            ("References", self.total),
            ("Precision of automatic links", f"{self.precision:.2f}"),
            ("Recall (resolvable, linked correctly)", f"{self.recall:.2f}"),
            ("Wrong links", self.wrong_links),
            ("False links on unresolvable items", self.false_links),
            ("Sent to review", f"{self.review} ({self.review_rate:.0%})"),
            ("Review items with the answer among suggestions", self.review_has_answer),
            ("Unresolved", self.unresolved),
            ("Source errors (searches that failed)", self.source_errors),
            ("Model cost", f"${self.cost_usd:.4f} (${self.cost_usd / (self.total or 1):.5f}/ref)"),
        ]
        return "\n".join(["| Metric | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows])

    def calibration_table(self) -> str:
        """Accuracy per band. Empty bands are shown, so a reader sees where there is no data."""
        lines = [
            "Top candidate's deterministic score: is the top candidate the expected work?",
            "",
            "| Score band | References | Top candidate correct | Accuracy |",
            "|---|---|---|---|",
        ]
        lines += [_band_row(b) for b in self.score_bands]
        lines += [
            "",
            "Model's stated confidence on the candidate it chose (adjudication or search agent),",
            "whether or not the choice was linked: is the chosen record the expected work?",
            "",
            "| Confidence band | Model choices | Correct | Accuracy |",
            "|---|---|---|---|",
        ]
        lines += [_band_row(b) for b in self.confidence_bands]
        return "\n".join(lines)

    def passed(self, min_precision: float) -> bool:
        # A run where a database failed measures the outage, not the resolver: it does not pass.
        return self.false_links == 0 and self.precision >= min_precision and self.source_errors == 0


SCORE_BANDS = (0.0, 0.55, 0.70, 0.85, 0.95, 1.0001)
CONFIDENCE_BANDS = (0.0, 0.50, 0.80, 0.90, 1.0001)
MODEL_METHODS = ("llm_adjudication", "agent_search")


def _bands(edges: tuple[float, ...], pairs: list[tuple[float, bool]]) -> list[dict]:
    """Group (value, correct) pairs into half-open bands [low, high); the last band includes 1.0."""
    bands = []
    for low, high in zip(edges, edges[1:], strict=False):
        inside = [ok for value, ok in pairs if low <= value < high]
        bands.append(
            {
                "low": low,
                "high": min(high, 1.0),
                "n": len(inside),
                "correct": sum(inside),
                "accuracy": round(sum(inside) / len(inside), 2) if inside else None,
            }
        )
    return bands


def _band_row(b: dict) -> str:
    closing = "]" if b["high"] >= 1.0 else ")"
    label = f"[{b['low']:.2f}, {b['high']:.2f}{closing}"
    accuracy = f"{b['accuracy']:.2f}" if b["accuracy"] is not None else "no data"
    return f"| {label} | {b['n']} | {b['correct']} | {accuracy} |"


def calibration(gold: list[dict], resolutions: list[Resolution]) -> tuple[list[dict], list[dict]]:
    """Two calibration tables from one run.

    - Deterministic: for every reference with candidates, the top candidate's score, and whether
      that candidate is the expected work. An item with no expected identifier counts as correct
      only if nothing would be linked, so any top candidate there counts as wrong.
    - Model: for every reference where the model chose a record (its result's method is
      adjudication or the search agent), its stated confidence and whether the record is right.
      This includes choices sent to review, which is where low confidence should land.
    """
    scores, confidences = [], []
    for item, res in zip(gold, resolutions, strict=True):
        expected = _norm(item.get("expected"))
        if res.candidates and "score" in res.candidates[0]:
            top = res.candidates[0]
            scores.append((float(top["score"]), _norm(top["identifier"]) == expected))
        if res.method in MODEL_METHODS and res.identifier:
            confidences.append((res.confidence, _norm(res.identifier) == expected))
    return _bands(SCORE_BANDS, scores), _bands(CONFIDENCE_BANDS, confidences)


def load_gold(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("//"):
            rows.append(json.loads(line))
    return rows


def _norm(identifier: str | None) -> str | None:
    return identifier.strip().lower() if identifier else None


def score_resolutions(gold: list[dict], resolutions: list[Resolution]) -> EvalResult:
    result = EvalResult(total=len(gold))
    for item, res in zip(gold, resolutions, strict=True):
        result.source_errors += sum(" unavailable: " in step for step in res.trace)
        expected = _norm(item.get("expected"))
        got = _norm(res.identifier)
        result.resolvable += expected is not None
        if res.status == "linked":
            result.linked += 1
            if expected is None:
                result.false_links += 1
                result.errors.append({"id": item["id"], "error": "false link", "got": got})
            elif got == expected:
                result.correct_links += 1
            else:
                result.wrong_links += 1
                result.errors.append(
                    {"id": item["id"], "error": "wrong link", "got": got, "expected": expected}
                )
        elif res.status == "review":
            result.review += 1
            suggested = {_norm(c["identifier"]) for c in res.candidates} | {got}
            if expected and expected in suggested:
                result.review_has_answer += 1
        else:
            result.unresolved += 1
            if expected:
                result.errors.append({"id": item["id"], "error": "missed", "expected": expected})
    result.score_bands, result.confidence_bands = calibration(gold, resolutions)
    return result


def evaluate(resolver: Resolver, gold: list[dict]) -> tuple[EvalResult, list[Resolution]]:
    refs = resolver.parse([item["citation"] for item in gold])
    resolutions = resolver.resolve_all(refs)
    result = score_resolutions(gold, resolutions)
    result.cost_usd = resolver.meter.cost_usd
    return result, resolutions
