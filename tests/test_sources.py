import httpx
import pytest

from refresolver.fetch import CacheMiss, JsonFetcher
from refresolver.models import Reference
from refresolver.scoring import rank
from refresolver.sources import (
    CrossrefSource,
    OpenAlexSource,
    crossref_candidate,
    merge_candidates,
    openalex_candidate,
)

from .conftest import load


def test_crossref_item_with_subtitle_and_organisation_author():
    item = load("crossref_search_fr.json")["message"]["items"][2]
    c = crossref_candidate(item)
    assert c.identifier == "10.1787/aae5dba0-fr"
    assert (
        c.title
        == "Perspectives de l'emploi de l'OCDE 2023: Intelligence artificielle et marché du travail"
    )
    assert c.authors == ["OCDE"]
    assert c.year == 2023 and c.language == "fr"


def test_crossref_person_authors_use_family_names():
    c = crossref_candidate(load("crossref_work.json")["message"])
    assert c.authors[:2] == ["Bender", "Gebru"]


def test_openalex_result_strips_doi_prefix_and_keeps_surnames():
    work = load("openalex_search.json")["results"][0]
    c = openalex_candidate(work)
    assert c.identifier == "10.1086/705716"
    assert c.authors == ["Acemoglu", "Restrepo"]
    assert c.container == "Journal of Political Economy"


def test_openalex_work_without_doi_uses_openalex_id():
    c = openalex_candidate(load("openalex_search.json")["results"][1])
    assert c.identifier == "https://openalex.org/W3000000002"


def test_merge_combines_same_doi_from_two_sources():
    cr = crossref_candidate(load("crossref_work.json")["message"])
    oa = openalex_candidate(load("openalex_search.json")["results"][0])
    oa_dup = openalex_candidate({**load("openalex_search.json")["results"][0], "doi": cr.doi})
    merged = merge_candidates([[cr], [oa, oa_dup]])
    assert len(merged) == 2
    assert merged[0].source == "crossref+openalex"


def test_right_book_wins_even_when_the_registry_ranks_it_third():
    # Real case: Crossref's top two hits for this French citation are unrelated 2009 tables.
    ref = Reference(
        "R1",
        "OCDE (2023), Perspectives de l'emploi de l'OCDE 2023 : Intelligence artificielle et "
        "marché du travail, Éditions OCDE, Paris.",
        year=2023,
    )
    items = load("crossref_search_fr.json")["message"]["items"]
    ranked = rank(ref, [crossref_candidate(i) for i in items])
    assert ranked[0].identifier == "10.1787/aae5dba0-fr"
    assert ranked[0].score >= 0.85


def fetcher_with(settings, handler):
    return JsonFetcher(settings, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_sources_parse_http_responses(settings):
    def handler(request):
        if "openalex" in request.url.host:
            return httpx.Response(200, json=load("openalex_search.json"))
        return httpx.Response(200, json=load("crossref_search_fr.json"))

    fetcher = fetcher_with(settings, handler)
    assert CrossrefSource(fetcher).search("perspectives emploi")[2].language == "fr"
    assert OpenAlexSource(fetcher).search("robots and jobs")[0].year == 2020


def test_cache_answers_repeat_requests_and_offline_mode_replays(settings):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, json={"message": {"items": []}})

    fetcher = fetcher_with(settings, handler)
    fetcher.get_json("https://api.crossref.org/works", {"query.bibliographic": "x"})
    fetcher.get_json("https://api.crossref.org/works", {"query.bibliographic": "x"})
    assert len(calls) == 1

    from dataclasses import replace

    offline = JsonFetcher(replace(settings, offline=True), client=fetcher.client)
    assert offline.get_json("https://api.crossref.org/works", {"query.bibliographic": "x"})
    with pytest.raises(CacheMiss):
        offline.get_json("https://api.crossref.org/works", {"query.bibliographic": "never seen"})


def test_unregistered_doi_returns_none(settings):
    fetcher = fetcher_with(settings, lambda request: httpx.Response(404))
    assert CrossrefSource(fetcher).get("10.9999/does-not-exist") is None


def test_transient_errors_are_retried(settings, monkeypatch):
    monkeypatch.setattr("refresolver.fetch.time.sleep", lambda s: None)
    replies = iter([httpx.Response(503), httpx.Response(200, json={"ok": True})])
    fetcher = fetcher_with(settings, lambda request: next(replies))
    assert fetcher.get_json("https://api.openalex.org/works", {"search": "x"}) == {"ok": True}


def test_contact_email_is_sent_for_the_polite_pool(settings):
    from dataclasses import replace

    seen = {}

    def handler(request):
        seen["ua"] = request.headers["User-Agent"]
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"message": {"items": []}})

    polite = replace(settings, contact_email="me@example.org")
    CrossrefSource(fetcher_with(polite, handler)).search("anything")
    assert "mailto:me@example.org" in seen["ua"]
    assert "mailto=me%40example.org" in seen["url"]


def test_crossref_search_asks_only_for_fields_crossref_accepts(settings):
    seen = []

    def handler(request):
        seen.append(request.url.params["select"])
        return httpx.Response(200, json={"message": {"items": []}})

    CrossrefSource(fetcher_with(settings, handler)).search("anything")
    # "language" is not accepted in select: asking for it made every search fail (HTTP 400).
    assert "language" not in seen[0].split(",")


def test_openalex_search_drops_wildcard_characters(settings):
    seen = []

    def handler(request):
        seen.append(request.url.params["search"])
        return httpx.Response(200, json={"results": []})

    OpenAlexSource(fetcher_with(settings, handler)).search(
        "Why are there still so many jobs? The history*"
    )
    assert seen == ["Why are there still so many jobs The history"]


def test_rejected_requests_are_recorded_and_replayed_as_rejections(settings):
    from dataclasses import replace

    from refresolver.fetch import RequestRejected

    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, json={"message": "bad request"})

    fetcher = fetcher_with(settings, handler)
    with pytest.raises(RequestRejected):
        fetcher.get_json("https://api.crossref.org/works", {"query.bibliographic": "x"})
    assert len(calls) == 1  # a rejection is not retried

    offline = JsonFetcher(replace(settings, offline=True), client=fetcher.client)
    with pytest.raises(RequestRejected):  # replayed as the same failure, not a cache miss
        offline.get_json("https://api.crossref.org/works", {"query.bibliographic": "x"})
