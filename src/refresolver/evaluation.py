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
- cost per reference.
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

    def passed(self, min_precision: float) -> bool:
        # A run where a database failed measures the outage, not the resolver: it does not pass.
        return self.false_links == 0 and self.precision >= min_precision and self.source_errors == 0


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
    return result


def evaluate(resolver: Resolver, gold: list[dict]) -> tuple[EvalResult, list[Resolution]]:
    refs = resolver.parse([item["citation"] for item in gold])
    resolutions = resolver.resolve_all(refs)
    result = score_resolutions(gold, resolutions)
    result.cost_usd = resolver.meter.cost_usd
    return result, resolutions
