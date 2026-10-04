"""The resolution pipeline: deterministic first, model where it adds value, people for the rest.

For each reference, in order, stopping at the first step that settles it:

1. DOI in the citation   -> look it up; link it if the registered title agrees with the citation.
2. Search and score      -> query Crossref and OpenAlex, score every candidate (scoring.py);
                            link automatically only if the top score is high AND clearly ahead
                            of the runner-up.
3. Model adjudication    -> for plausible but ambiguous cases, the model picks among the
                            retrieved candidates, or none. It can only choose a listed number,
                            so it cannot invent a work.
4. Search agent          -> for the remainder, a bounded tool-using agent reformulates queries
                            (title only, translated title...) with a hard step budget. It may
                            only submit an identifier it has actually retrieved.
5. Human review          -> anything still uncertain goes to the review queue with the best
                            candidates and the reasons, instead of being guessed.

A model-assisted link also needs deterministic corroboration (a minimum match score).
Otherwise the model's proposal goes to review. Every step is written to the trace.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from .config import Settings
from .fetch import CacheMiss, FetchError
from .llm import LLMClient, ReplayMiss, UsageMeter
from .models import Candidate, Reference, Resolution
from .scoring import rank, score
from .sources import CrossrefSource, Source, merge_candidates
from .text import (
    bibliography_section,
    content_words,
    find_dois,
    find_quoted_title,
    find_year,
    split_entries,
)

log = logging.getLogger(__name__)

EXTRACT_BATCH = 20
TOP_FOR_REVIEW = 3
TOP_FOR_MODEL = 5

# --------------------------------------------------------------------------- prompts and tools

EXTRACT_SYSTEM = (
    "You extract bibliographic fields from citations. Copy each field exactly as written in the "
    "citation. Never correct, complete or guess: use null for a field that is not present."
)
EXTRACT_TOOL = {
    "name": "record_references",
    "description": "Record the bibliographic fields of each numbered citation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "references": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "authors": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Surnames of people, or names of organisations.",
                        },
                        "year": {"type": ["integer", "null"]},
                        "title": {
                            "type": ["string", "null"],
                            "description": "Title of the cited work, including any subtitle.",
                        },
                        "container": {
                            "type": ["string", "null"],
                            "description": "Journal, series, proceedings or book it appeared in.",
                        },
                    },
                    "required": ["index", "authors", "year", "title", "container"],
                },
            }
        },
        "required": ["references"],
    },
}

ADJUDICATE_SYSTEM = (
    "You decide whether a citation refers to one of the numbered candidate works. The same work "
    "means the same edition, year and language as cited: another year of a report series, a "
    "chapter instead of the whole book, or a translation is a different work unless the citation "
    "points to it. Answer 0 if no candidate is the cited work. Be calibrated: give a confidence "
    "above 0.9 only when title, year and authors all agree."
)

AGENT_SYSTEM = (
    "You resolve one bibliographic citation to a registered work, using the search tools. Try "
    "different formulations: the exact title, the title without its subtitle, the title "
    "translated into English, author surnames with key title words. Only submit an identifier "
    "that appeared in a search result. Submit null if nothing matches. You have at most "
    "{steps} turns."
)
AGENT_TOOLS = [
    {
        "name": "search_crossref",
        "description": "Search Crossref, the main DOI registry, with a free-text query.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "search_openalex",
        "description": "Search OpenAlex, an open index of scholarly works, with a free-text query.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "submit_resolution",
        "description": "Finish: submit the identifier of the cited work, or null if not found.",
        "input_schema": {
            "type": "object",
            "properties": {
                "identifier": {"type": ["string", "null"]},
                "confidence": {"type": "number"},
                "rationale": {"type": "string"},
            },
            "required": ["identifier", "confidence", "rationale"],
        },
    },
]


def _summaries(candidates: list[Candidate]) -> list[dict]:
    return [
        {
            "identifier": c.identifier,
            "title": c.title,
            "authors": c.authors[:5],
            "year": c.year,
            "container": c.container,
            "language": c.language,
            "type": c.work_type,
        }
        for c in candidates
    ]


def _for_review(candidates: list[Candidate]) -> list[dict]:
    return [
        {
            "identifier": c.identifier,
            "label": c.label(),
            "score": c.score,
            "score_detail": c.score_detail,
            "source": c.source,
        }
        for c in candidates[:TOP_FOR_REVIEW]
    ]


# --------------------------------------------------------------------------- resolver


@dataclass
class Resolver:
    settings: Settings
    crossref: CrossrefSource
    sources: list[Source]
    llm: LLMClient | None = None
    use_agent: bool = True
    meter: UsageMeter = field(init=False)

    def __post_init__(self):
        self.reset_meter()

    def reset_meter(self) -> None:
        """Start counting model usage from zero (for example at the start of each request)."""
        self.meter = UsageMeter(
            self.settings.price_input_per_mtok, self.settings.price_output_per_mtok
        )

    # ------------------------------------------------------------------ parsing

    def references_from_text(self, text: str) -> list[Reference]:
        return self.parse(split_entries(bibliography_section(text)))

    def parse(self, citations: list[str]) -> list[Reference]:
        refs = []
        for i, raw in enumerate(citations, start=1):
            dois = find_dois(raw)
            refs.append(
                Reference(
                    ref_id=f"R{i:03d}",
                    raw=raw,
                    year=find_year(raw),
                    title=find_quoted_title(raw),
                    doi=dois[0] if dois else None,
                )
            )
        if self.llm:
            for start in range(0, len(refs), EXTRACT_BATCH):
                self._extract_with_model(refs[start : start + EXTRACT_BATCH])
        return refs

    def _extract_with_model(self, batch: list[Reference]) -> None:
        listing = "\n".join(f"{n}. {ref.raw}" for n, ref in enumerate(batch, start=1))
        try:
            reply = self.llm.create(
                system=EXTRACT_SYSTEM,
                messages=[{"role": "user", "content": f"Citations:\n{listing}"}],
                tools=[EXTRACT_TOOL],
                tool_choice={"type": "tool", "name": "record_references"},
            )
        except ReplayMiss:
            raise
        except Exception as exc:  # degrade to heuristic parsing rather than fail the run
            log.warning("Model extraction failed, using heuristic parsing: %s", exc)
            return
        self.meter.add("extract", reply)
        records = reply.tool_calls[0].input.get("references", []) if reply.tool_calls else []
        for record in records:
            if not isinstance(record, dict):
                continue
            index = record.get("index")
            if not isinstance(index, int) or not 1 <= index <= len(batch):
                continue
            ref = batch[index - 1]
            ref.authors = [str(a) for a in record.get("authors") or [] if a]
            ref.title = record.get("title") or ref.title  # keep the heuristic title if none
            ref.container = record.get("container") or None
            year = record.get("year")
            ref.year = year if isinstance(year, int) else ref.year
            ref.parsed_by = "llm"  # the DOI stays from the regex: code is more reliable there

    # ------------------------------------------------------------------ resolution

    def resolve_all(self, refs: list[Reference]) -> list[Resolution]:
        return [self.resolve(ref) for ref in refs]

    def resolve(self, ref: Reference) -> Resolution:
        trace: list[str] = [f"parsed by {ref.parsed_by}: title={ref.title!r} year={ref.year}"]
        s = self.settings

        # 1. A DOI written in the citation.
        if ref.doi:
            linked = self._check_cited_doi(ref, trace)
            if linked:
                return linked

        # 2. Search both sources and score.
        groups = []
        for source in self.sources:
            query = ref.raw if source.name == "crossref" else (ref.title or ref.raw)
            try:
                found = source.search(query)
                trace.append(f"{source.name}: {len(found)} candidates")
                groups.append(found)
            except CacheMiss:
                raise
            except FetchError as exc:
                trace.append(f"{source.name} unavailable: {exc}")
        candidates = rank(ref, merge_candidates(groups))
        top = candidates[0] if candidates else None
        runner_up = candidates[1].score if len(candidates) > 1 else 0.0
        if top:
            trace.append(f"top score {top.score} {top.score_detail}, runner-up {runner_up}")

        def outcome(status, method, cand=None, confidence=0.0, rationale=""):
            return Resolution(
                ref_id=ref.ref_id,
                raw=ref.raw,
                status=status,
                method=method,
                identifier=cand.identifier if cand else None,
                title=cand.title if cand else None,
                confidence=round(confidence, 3),
                rationale=rationale,
                candidates=_for_review(candidates),
                trace=trace,
            )

        def link(method, cand, confidence, rationale):
            # The output of this tool is a DOI. A record without one is often a repository copy
            # or a duplicate of a work that does have a DOI (found in the first live evaluation:
            # a university-repository copy of an OECD manual). A person confirms those.
            if not cand.doi:
                trace.append(f"{cand.identifier} has no DOI: sent to review instead of linking")
                return outcome(
                    "review",
                    method,
                    cand,
                    confidence,
                    (rationale + " " if rationale else "")
                    + "The match has no DOI (often a repository copy or a duplicate record), "
                    "so a person should confirm it or find the published version.",
                )
            return outcome("linked", method, cand, confidence, rationale)

        def model_link(method, cand, confidence, rationale):
            # A model may pick among candidates, but not against the evidence: if the candidate
            # lists authors and none of them is in the citation, a person decides. Found in the
            # live run with Qwen 2.5 7B, which linked a web page (no DOI exists) to an unrelated
            # Zenodo record, choosing it among three tied candidates with confidence 0.95.
            if cand.score_detail.get("authors", 0.5) == 0.0:
                trace.append(
                    f"{cand.identifier}: no cited author among its authors, sent to review"
                )
                return outcome(
                    "review",
                    method,
                    cand,
                    confidence,
                    (rationale + " " if rationale else "")
                    + "None of the candidate's authors appear in the citation, "
                    "so a person should confirm it.",
                )
            return link(method, cand, confidence, rationale)

        if not groups:  # every source failed: say so, rather than "not found"
            return outcome(
                "unresolved", "none", rationale="The scholarly databases could not be reached."
            )

        if top and top.score >= s.auto_accept and top.score - runner_up >= s.min_margin:
            return link("deterministic", top, top.score, "High score, clear lead.")

        # 3. Model adjudication for plausible but ambiguous cases.
        model_rationale = ""
        if self.llm and top and top.score >= s.review_floor:
            choice, confidence, model_rationale = self._adjudicate(ref, candidates[:TOP_FOR_MODEL])
            trace.append(f"model chose {choice} with confidence {confidence}")
            if choice:
                chosen = candidates[choice - 1]
                if confidence >= s.llm_accept and chosen.score >= s.review_floor:
                    return model_link("llm_adjudication", chosen, confidence, model_rationale)
                return outcome("review", "llm_adjudication", chosen, confidence, model_rationale)

        # 4. Search agent for what is left.
        if self.llm and self.use_agent:
            proposal = self._run_agent(ref, candidates, trace)
            if proposal:
                cand, confidence, rationale = proposal
                score(ref, cand)
                trace.append(f"agent proposal scores {cand.score} {cand.score_detail}")
                if confidence >= s.llm_accept and cand.score >= s.review_floor:
                    return model_link("agent_search", cand, confidence, rationale)
                return outcome("review", "agent_search", cand, confidence, rationale)

        # 5. Human review, or unresolved.
        if top and top.score >= s.review_floor:
            reason = model_rationale or "Plausible match, but not certain enough to link."
            return outcome("review", "none", top, top.score, reason)
        return outcome("unresolved", "none", rationale="No plausible registered work found.")

    def _check_cited_doi(self, ref: Reference, trace: list[str]) -> Resolution | None:
        try:
            registered = self.crossref.get(ref.doi)
        except CacheMiss:
            raise
        except FetchError as exc:
            trace.append(f"could not check the cited DOI: {exc}")
            return None
        if registered is None:
            trace.append(f"cited DOI {ref.doi} is not registered; searching instead")
            return None
        score(ref, registered)
        remainder = re.sub(r"(https?://(dx\.)?doi\.org/|doi:)?\s*10\.\S+", " ", ref.raw, flags=re.I)
        doi_only = len(content_words(remainder)) < 3  # nothing else to cross-check against
        if doi_only or registered.score_detail["title"] >= 0.6:
            trace.append(
                "citation is only a DOI; registered record used"
                if doi_only
                else "cited DOI is registered and its title agrees with the citation"
            )
            return Resolution(
                ref_id=ref.ref_id,
                raw=ref.raw,
                status="linked",
                method="doi_in_text",
                identifier=registered.identifier,
                title=registered.title,
                confidence=0.99,
                rationale="DOI given in the citation, confirmed against the registry.",
                trace=trace,
            )
        trace.append(f"cited DOI points to a different work ({registered.title!r}); searching")
        return None

    def _adjudicate(self, ref: Reference, candidates: list[Candidate]) -> tuple[int, float, str]:
        numbered = "\n".join(
            f"{n}. {json.dumps(summary, ensure_ascii=False)}"
            for n, summary in enumerate(_summaries(candidates), start=1)
        )
        tool = {
            "name": "choose_candidate",
            "description": "Choose the candidate number that is the cited work, or 0 for none.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "choice": {"type": "integer", "enum": list(range(len(candidates) + 1))},
                    "confidence": {"type": "number"},
                    "rationale": {"type": "string"},
                },
                "required": ["choice", "confidence", "rationale"],
            },
        }
        try:
            reply = self.llm.create(
                system=ADJUDICATE_SYSTEM,
                messages=[
                    {"role": "user", "content": f"Citation: {ref.raw}\n\nCandidates:\n{numbered}"}
                ],
                tools=[tool],
                tool_choice={"type": "tool", "name": "choose_candidate"},
                max_tokens=600,
            )
        except ReplayMiss:
            raise
        except Exception as exc:
            log.warning("Model adjudication failed: %s", exc)
            return 0, 0.0, ""
        self.meter.add("adjudicate", reply)
        if not reply.tool_calls:
            return 0, 0.0, ""
        data = reply.tool_calls[0].input
        choice = data.get("choice")
        if not isinstance(choice, int) or not 0 <= choice <= len(candidates):
            return 0, 0.0, "Model returned an invalid choice; ignored."  # guard
        confidence = float(data.get("confidence") or 0.0)
        return choice, max(0.0, min(confidence, 1.0)), str(data.get("rationale") or "")

    def _run_agent(
        self, ref: Reference, initial: list[Candidate], trace: list[str]
    ) -> tuple[Candidate, float, str] | None:
        by_name = {source.name: source for source in self.sources}
        seen = {c.identifier.lower(): c for c in initial}
        steps = self.settings.max_agent_steps
        messages: list[dict] = [
            {
                "role": "user",
                "content": (
                    f"Citation: {ref.raw}\n"
                    f"Parsed title: {ref.title}\nYear: {ref.year}\nAuthors: {ref.authors}\n"
                    f"A first search found these candidates, none of them certain:\n"
                    f"{json.dumps(_summaries(initial[:TOP_FOR_MODEL]), ensure_ascii=False)}"
                ),
            }
        ]
        for step in range(1, steps + 1):
            try:
                reply = self.llm.create(
                    system=AGENT_SYSTEM.format(steps=steps),
                    messages=messages,
                    tools=AGENT_TOOLS,
                    tool_choice={"type": "any"},  # every turn must use a tool
                    max_tokens=800,
                )
            except ReplayMiss:
                raise
            except Exception as exc:
                trace.append(f"agent stopped: model error {exc}")
                return None
            self.meter.add("agent", reply)
            messages.append({"role": "assistant", "content": reply.content})
            if not reply.tool_calls:
                trace.append(f"agent step {step}: no tool call, stopping")
                return None

            results = []
            for call in reply.tool_calls:
                if call.name == "submit_resolution":
                    identifier = call.input.get("identifier")
                    rationale = str(call.input.get("rationale") or "")
                    if not identifier:
                        trace.append(f"agent step {step}: submitted no match ({rationale})")
                        return None
                    if identifier.lower() not in seen:
                        trace.append(f"agent step {step}: rejected unretrieved id {identifier}")
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": call.id,
                                "is_error": True,
                                "content": "Rejected: that identifier was not in any search "
                                "result. Search again, or submit null.",
                            }
                        )
                        continue
                    confidence = max(0.0, min(float(call.input.get("confidence") or 0), 1.0))
                    trace.append(f"agent step {step}: submitted {identifier} ({confidence})")
                    return seen[identifier.lower()], confidence, rationale

                source = by_name.get(call.name.removeprefix("search_"))
                if source is None:
                    content, is_error = f"Unknown tool {call.name}.", True
                else:
                    query = str(call.input.get("query") or "")[:300]
                    try:
                        found = source.search(query)
                        for cand in found:
                            seen[cand.identifier.lower()] = cand
                        content, is_error = json.dumps(_summaries(found), ensure_ascii=False), False
                        trace.append(f"agent step {step}: {call.name}({query!r}) -> {len(found)}")
                    except CacheMiss:
                        raise
                    except FetchError as exc:
                        content, is_error = f"Search failed: {exc}", True
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "is_error": is_error,
                        "content": content,
                    }
                )
            messages.append({"role": "user", "content": results})

        trace.append(f"agent used its {steps}-step budget without a match")
        return None
