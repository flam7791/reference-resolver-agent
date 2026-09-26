"""The three records that flow through the pipeline: Reference -> Candidate(s) -> Resolution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Reference:
    """A reference as cited in a document, before resolution."""

    ref_id: str
    raw: str
    authors: list[str] = field(default_factory=list)  # surnames or organisation names
    year: int | None = None
    title: str | None = None
    container: str | None = None  # journal, series or book the work appeared in
    doi: str | None = None  # a DOI written in the citation itself, if any
    parsed_by: str = "heuristic"  # "heuristic" or "llm"


@dataclass
class Candidate:
    """A registered work returned by a scholarly database."""

    source: str  # "crossref", "openalex" or both, e.g. "crossref+openalex"
    identifier: str  # the DOI when there is one, otherwise the OpenAlex id
    title: str
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    container: str | None = None
    publisher: str | None = None
    work_type: str | None = None
    language: str | None = None
    doi: str | None = None
    score: float = 0.0  # filled in by scoring
    score_detail: dict = field(default_factory=dict)

    def label(self) -> str:
        who = ", ".join(self.authors[:3]) + (" et al." if len(self.authors) > 3 else "")
        parts = [who or "(no author)", f"({self.year or 'n.d.'})", self.title]
        if self.container:
            parts.append(f"In: {self.container}")
        return " ".join(parts) + f" [{self.identifier}]"


@dataclass
class Resolution:
    ref_id: str
    raw: str
    status: str  # "linked", "review" or "unresolved"
    method: str  # how the decision was reached, see resolver.py
    identifier: str | None = None
    title: str | None = None
    confidence: float = 0.0
    rationale: str = ""
    candidates: list[dict] = field(default_factory=list)  # top candidates, for reviewers
    trace: list[str] = field(default_factory=list)  # audit trail of steps taken

    def to_dict(self) -> dict:
        return asdict(self)


STATUSES = ("linked", "review", "unresolved")
