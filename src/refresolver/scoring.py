"""Deterministic match scoring: how likely is it that a candidate is the cited work?

score = 0.6 × title + 0.2 × year + 0.2 × authors, each between 0 and 1.

- Title: the better of (a) character-level similarity of the two titles and (b) word
  containment, which handles subtitles and truncated titles. Containment needs at least three
  content words on the shorter side, so a one-word title cannot match everything. Both are
  also tried against the candidate's main title (before any subtitle).
- Year: 1 if equal, 0.6 if one year apart (online-first versus print), 0 otherwise, 0.5 if
  unknown. The year is what separates editions of a series (Employment Outlook 2005 vs 2023).
- Authors: share of the candidate's first surnames that appear in the citation, 0.5 if unknown.

Every score comes with its parts, so a reviewer can see why a candidate ranked where it did.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .models import Candidate, Reference
from .text import content_words, normalise

WEIGHTS = {"title": 0.6, "year": 0.2, "authors": 0.2}
MIN_CONTAINMENT_WORDS = 3


def main_title(title: str) -> str:
    """The part before a subtitle: 'Robots and Jobs: Evidence...' -> 'Robots and Jobs'."""
    return re.split(r"[:?]|\s[-–—]\s", title, maxsplit=1)[0]


def title_similarity(cited: str, candidate: str) -> float:
    """Best match against the full title and against the main title alone, because
    citations often drop subtitles."""
    return max(_title_similarity(cited, candidate), _title_similarity(cited, main_title(candidate)))


def _title_similarity(cited: str, candidate: str) -> float:
    a, b = normalise(cited), normalise(candidate)
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    wa, wb = content_words(a), content_words(b)
    smaller = min(len(wa), len(wb))
    containment = len(wa & wb) / smaller if smaller >= MIN_CONTAINMENT_WORDS else 0.0
    return max(ratio, containment)


def year_similarity(cited: int | None, candidate: int | None) -> float:
    if cited is None or candidate is None:
        return 0.5
    gap = abs(cited - candidate)
    return 1.0 if gap == 0 else 0.6 if gap == 1 else 0.0


def author_similarity(ref: Reference, candidate: Candidate) -> float:
    cand = [normalise(a) for a in candidate.authors[:3] if a]
    if not cand:
        return 0.5
    if ref.authors:
        cited = {normalise(a).split()[-1] for a in ref.authors if normalise(a)}
        found = sum(1 for a in cand if a.split() and a.split()[-1] in cited)
    else:  # no parsed authors: look for the surnames in the raw citation
        words = set(normalise(ref.raw).split())
        found = sum(1 for a in cand if a.split() and a.split()[-1] in words)
    return found / len(cand)


def score(ref: Reference, candidate: Candidate) -> Candidate:
    cited_title = ref.title or ref.raw  # without a parsed title, compare with the whole citation
    parts = {
        "title": title_similarity(cited_title, candidate.title),
        "year": year_similarity(ref.year, candidate.year),
        "authors": author_similarity(ref, candidate),
    }
    candidate.score = round(sum(WEIGHTS[k] * v for k, v in parts.items()), 3)
    candidate.score_detail = {k: round(v, 3) for k, v in parts.items()}
    return candidate


def rank(ref: Reference, candidates: list[Candidate]) -> list[Candidate]:
    return sorted((score(ref, c) for c in candidates), key=lambda c: c.score, reverse=True)
