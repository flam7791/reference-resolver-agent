"""Deterministic match scoring: how likely is it that a candidate is the cited work?

score = 0.6 × title + 0.2 × year + 0.2 × authors, each between 0 and 1.

- Title: the better of (a) character-level similarity of the two titles and (b) word
  containment: the share of the cited title's words found in the candidate's, which handles
  truncated citations. Containment counts in that direction only: a short candidate title
  inside a long citation is not evidence ("FAIR principles for data stewardship" sits inside
  "The FAIR Guiding Principles for scientific data management and stewardship", a different
  paper). It needs at least three content words, so a one-word title cannot match everything.
  Subtitles are handled by also comparing the main titles (before any subtitle) of each side.
- Year: 1 if equal, 0.6 if one year apart (online-first versus print), 0 otherwise, 0.5 if
  unknown. The year is what separates editions of a series (Employment Outlook 2005 vs 2023).
- Authors: share of the candidate's first surnames that appear in the citation, 0.5 if unknown.
  Cited names may come in either order ("Wilkinson, M. D." or "M. D. Wilkinson").

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


def title_similarity(cited: str, candidate: str, whole_citation: bool = False) -> float:
    """Best match of the full titles, or with a subtitle left out on either side: citations
    often drop the registry's subtitle, and registries often store the subtitle separately.

    With whole_citation (no title could be parsed), `cited` is the entire citation, full of
    names and numbers, so containment then asks the opposite question: are all the
    candidate's title words somewhere in the citation?"""
    return max(
        _title_similarity(cited, candidate, whole_citation),
        _title_similarity(cited, main_title(candidate), whole_citation),
        _title_similarity(main_title(cited), candidate, whole_citation),
    )


def _title_similarity(cited: str, candidate: str, whole_citation: bool) -> float:
    a, b = normalise(cited), normalise(candidate)
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    wa, wb = content_words(a), content_words(b)
    inner = wb if whole_citation else wa  # the side whose words must all be found
    containment = len(wa & wb) / len(inner) if len(inner) >= MIN_CONTAINMENT_WORDS else 0.0
    return max(ratio, containment)


def year_similarity(cited: int | None, candidate: int | None) -> float:
    if cited is None or candidate is None:
        return 0.5
    gap = abs(cited - candidate)
    return 1.0 if gap == 0 else 0.6 if gap == 1 else 0.0


def cited_surnames(names: list[str]) -> set[str]:
    """Surnames from cited names in either order: "Wilkinson, M. D." or "M. D. Wilkinson"."""
    surnames = set()
    for name in names:
        name = re.sub(r"\bet al\b\.?", " ", name, flags=re.IGNORECASE)
        family = name.split(",")[0] if "," in name else name
        words = [w for w in normalise(family).split() if len(w) > 1]
        if words:
            surnames.add(words[-1])
    return surnames


def author_similarity(ref: Reference, candidate: Candidate) -> float:
    cand = [normalise(a) for a in candidate.authors[:3] if a]
    if not cand:
        return 0.5
    if ref.authors:
        cited = cited_surnames(ref.authors)
        found = sum(1 for a in cand if a.split() and a.split()[-1] in cited)
    else:  # no parsed authors: look for the surnames in the raw citation
        words = set(normalise(ref.raw).split())
        found = sum(1 for a in cand if a.split() and a.split()[-1] in words)
    return found / len(cand)


def score(ref: Reference, candidate: Candidate) -> Candidate:
    cited_title = ref.title or ref.raw  # without a parsed title, compare with the whole citation
    parts = {
        "title": title_similarity(cited_title, candidate.title, whole_citation=not ref.title),
        "year": year_similarity(ref.year, candidate.year),
        "authors": author_similarity(ref, candidate),
    }
    candidate.score = round(sum(WEIGHTS[k] * v for k, v in parts.items()), 3)
    candidate.score_detail = {k: round(v, 3) for k, v in parts.items()}
    return candidate


def rank(ref: Reference, candidates: list[Candidate]) -> list[Candidate]:
    return sorted((score(ref, c) for c in candidates), key=lambda c: c.score, reverse=True)
