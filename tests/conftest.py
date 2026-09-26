"""Fakes for the network and the model, so every test runs offline and deterministically."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from refresolver.config import Settings
from refresolver.llm import LLMReply, ToolCall
from refresolver.models import Candidate
from refresolver.resolver import Resolver

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[1]


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def cand(identifier, title, authors=(), year=None, container=None, source="crossref"):
    return Candidate(
        source=source,
        identifier=identifier,
        doi=identifier if identifier.startswith("10.") else None,
        title=title,
        authors=list(authors),
        year=year,
        container=container,
    )


class FakeSource:
    """Returns the candidates registered for the first key found in the query."""

    def __init__(self, name: str, catalogue: dict[str, list[Candidate]] | None = None):
        self.name = name
        self.catalogue = catalogue or {}
        self.queries: list[str] = []
        self.works: dict[str, Candidate] = {}

    def search(self, query: str, rows: int = 5) -> list[Candidate]:
        self.queries.append(query)
        for key, found in self.catalogue.items():
            if key.lower() in query.lower():
                return [Candidate(**vars(c)) for c in found][:rows]  # copies
        return []

    def get(self, doi: str) -> Candidate | None:
        work = self.works.get(doi.lower())
        return Candidate(**vars(work)) if work else None


class ScriptedLLM:
    """Replies from a script, in order, and records every request."""

    def __init__(self, replies: list[LLMReply]):
        self.replies = list(replies)
        self.requests: list[dict] = []

    def create(self, *, system, messages, tools, tool_choice=None, max_tokens=2000) -> LLMReply:
        self.requests.append(
            copy.deepcopy({"system": system, "messages": messages, "tools": tools})
        )
        if not self.replies:
            raise AssertionError("ScriptedLLM ran out of replies")
        return self.replies.pop(0)


def tool_reply(name: str, data: dict, call_id: str = "call_1") -> LLMReply:
    return LLMReply(
        content=[{"type": "tool_use", "id": call_id, "name": name, "input": data}],
        tool_calls=[ToolCall(call_id, name, data)],
        text="",
        input_tokens=1000,
        output_tokens=100,
    )


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(cache_dir=tmp_path / "cache", max_agent_steps=3)


def make_resolver(settings, crossref=None, openalex=None, llm=None, use_agent=True):
    crossref = crossref or FakeSource("crossref")
    openalex = openalex or FakeSource("openalex")
    return Resolver(settings, crossref, [crossref, openalex], llm=llm, use_agent=use_agent)
