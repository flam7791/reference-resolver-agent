"""Candidate retrieval from two open scholarly databases.

- Crossref: the registry behind most DOIs (journals, books, reports, including OECD Publishing).
  Its `query.bibliographic` parameter is designed to match a raw citation string.
- OpenAlex: an open index of works that also covers items without a Crossref DOI.

Using two sources raises recall; candidates that point to the same DOI are merged.
Both APIs are free and public; a contact email in the settings is good manners.
"""

from __future__ import annotations

import re
from typing import Protocol

from .fetch import JsonFetcher
from .models import Candidate

CROSSREF = "https://api.crossref.org/works"
OPENALEX = "https://api.openalex.org/works"
# Ask only for the fields we read: smaller, faster responses (and smaller recordings). Every
# field must be one Crossref accepts in `select`: a single field it does not accept makes it
# reject the whole search with HTTP 400. ("language" did, in the first live run.)
CROSSREF_FIELDS = (
    "DOI,title,subtitle,author,issued,published-print,published-online,created,"
    "container-title,publisher,type"
)
OPENALEX_FIELDS = (
    "id,doi,title,display_name,publication_year,type,language,authorships,primary_location"
)


class Source(Protocol):
    name: str

    def search(self, query: str, rows: int = 5) -> list[Candidate]: ...


def _clean_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        if value.startswith(prefix):
            value = value[len(prefix) :]
    return value or None


def _first(values) -> str | None:
    if isinstance(values, list):
        return values[0] if values else None
    return values


# --------------------------------------------------------------------------- Crossref


def crossref_candidate(item: dict) -> Candidate:
    title = _first(item.get("title")) or ""
    subtitle = _first(item.get("subtitle"))
    if subtitle:
        title = f"{title}: {subtitle}"  # Crossref stores subtitles separately
    authors = [a.get("family") or a.get("name") or "" for a in item.get("author", [])]
    year = None
    for key in ("issued", "published-print", "published-online", "created"):
        parts = (item.get(key) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break
    doi = _clean_doi(item.get("DOI"))
    return Candidate(
        source="crossref",
        identifier=doi or "",
        doi=doi,
        title=title,
        authors=[a for a in authors if a],
        year=year,
        container=_first(item.get("container-title")),
        publisher=item.get("publisher"),
        work_type=item.get("type"),
        language=item.get("language"),
    )


class CrossrefSource:
    name = "crossref"

    def __init__(self, fetcher: JsonFetcher):
        self.fetcher = fetcher

    def _params(self, extra: dict) -> dict:
        params = dict(extra)
        if self.fetcher.settings.contact_email:
            params["mailto"] = self.fetcher.settings.contact_email
        return params

    def search(self, query: str, rows: int = 5) -> list[Candidate]:
        body = self.fetcher.get_json(
            CROSSREF,
            self._params(
                {"query.bibliographic": query[:500], "rows": rows, "select": CROSSREF_FIELDS}
            ),
        )
        items = ((body or {}).get("message") or {}).get("items") or []
        return [c for c in (crossref_candidate(i) for i in items) if c.identifier and c.title]

    def get(self, doi: str) -> Candidate | None:
        """Look up one DOI. None means it is not registered with Crossref."""
        body = self.fetcher.get_json(f"{CROSSREF}/{doi}", self._params({}))
        message = (body or {}).get("message")
        return crossref_candidate(message) if message else None


# --------------------------------------------------------------------------- OpenAlex


def openalex_candidate(work: dict) -> Candidate:
    doi = _clean_doi(work.get("doi"))
    authors = []
    for authorship in work.get("authorships") or []:
        name = ((authorship or {}).get("author") or {}).get("display_name") or ""
        if name:
            authors.append(name.split()[-1])  # keep the surname, as Crossref does
    source = ((work.get("primary_location") or {}).get("source") or {}).get("display_name")
    return Candidate(
        source="openalex",
        identifier=doi or (work.get("id") or ""),
        doi=doi,
        title=work.get("display_name") or work.get("title") or "",
        authors=authors,
        year=work.get("publication_year"),
        container=source,
        work_type=work.get("type"),
        language=work.get("language"),
    )


def openalex_query(text: str) -> str:
    """OpenAlex rejects search text containing wildcard characters (HTTP 400), and titles such as
    "Why are there still so many jobs?" contain them. They carry no meaning for the search."""
    return " ".join(re.sub(r"[?*]", " ", text).split())


class OpenAlexSource:
    name = "openalex"

    def __init__(self, fetcher: JsonFetcher):
        self.fetcher = fetcher

    def search(self, query: str, rows: int = 5) -> list[Candidate]:
        params: dict = {
            "search": openalex_query(query)[:300],
            "per_page": rows,
            "select": OPENALEX_FIELDS,
        }
        if self.fetcher.settings.contact_email:
            params["mailto"] = self.fetcher.settings.contact_email
        if self.fetcher.settings.openalex_api_key:
            params["api_key"] = self.fetcher.settings.openalex_api_key
        body = self.fetcher.get_json(OPENALEX, params)
        results = (body or {}).get("results") or []
        return [c for c in (openalex_candidate(w) for w in results) if c.identifier and c.title]


# --------------------------------------------------------------------------- merging


def merge_candidates(groups: list[list[Candidate]]) -> list[Candidate]:
    """Merge candidates from several sources; the same DOI from two sources becomes one."""
    merged: dict[str, Candidate] = {}
    for group in groups:
        for cand in group:
            key = cand.identifier.lower()
            if key not in merged:
                merged[key] = cand
                continue
            kept = merged[key]
            if cand.source not in kept.source:
                kept.source = f"{kept.source}+{cand.source}"
            # Fill gaps from the second source without overwriting the first.
            kept.authors = kept.authors or cand.authors
            kept.year = kept.year or cand.year
            kept.container = kept.container or cand.container
            kept.language = kept.language or cand.language
    return list(merged.values())
