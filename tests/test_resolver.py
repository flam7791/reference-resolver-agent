"""Every decision path of the pipeline, with fake sources and a scripted model."""

from refresolver.llm import LLMReply

from .conftest import FakeSource, ScriptedLLM, cand, make_resolver, tool_reply

AUTOR = cand(
    "10.1257/jep.29.3.3",
    "Why Are There Still So Many Jobs? The History and Future of Workplace Automation",
    ["Autor"],
    2015,
    "Journal of Economic Perspectives",
)
FREY = cand(
    "10.1016/j.techfore.2016.08.019",
    "The future of employment: How susceptible are jobs to computerisation?",
    ["Frey", "Osborne"],
    2017,
)


def test_doi_in_citation_is_confirmed_against_the_registry(settings):
    crossref = FakeSource("crossref")
    crossref.works["10.1257/jep.29.3.3"] = AUTOR
    resolver = make_resolver(settings, crossref=crossref)
    ref = resolver.parse(
        ["Autor, D. (2015), Why are there still so many jobs?, JEP, doi:10.1257/jep.29.3.3"]
    )[0]
    res = resolver.resolve(ref)
    assert (res.status, res.method, res.identifier) == ("linked", "doi_in_text", AUTOR.identifier)
    assert crossref.queries == []  # no search needed


def test_mistyped_doi_pointing_to_another_work_falls_back_to_search(settings):
    crossref = FakeSource("crossref", {"future of employment": [FREY]})
    crossref.works["10.1016/j.techfore.2016.08.091"] = cand(
        "10.1016/j.techfore.2016.08.091", "Unrelated article on energy markets", ["Other"], 2016
    )
    resolver = make_resolver(settings, crossref=crossref)
    ref = resolver.parse(
        [
            "Frey, C. and M. Osborne (2017), The future of employment: how susceptible are jobs "
            "to computerisation?, doi:10.1016/j.techfore.2016.08.091"
        ]
    )[0]
    res = resolver.resolve(ref)
    assert res.identifier == FREY.identifier and res.status == "linked"
    assert any("different work" in step for step in res.trace)


def test_clear_match_is_linked_without_calling_the_model(settings):
    llm = ScriptedLLM([tool_reply("record_references", {"references": []})])
    crossref = FakeSource("crossref", {"so many jobs": [AUTOR]})
    resolver = make_resolver(settings, crossref=crossref, llm=llm)
    ref = resolver.parse(["Autor, D. (2015), Why are there still so many jobs?, JEP 29(3)."])[0]
    res = resolver.resolve(ref)
    assert (res.status, res.method) == ("linked", "deterministic")
    assert resolver.meter.by_step == {"extract": 1}  # no adjudication, no agent


def test_two_near_identical_candidates_are_not_auto_linked(settings):
    twin = cand("10.9999/copy", AUTOR.title, ["Autor"], 2015)
    crossref = FakeSource("crossref", {"so many jobs": [AUTOR, twin]})
    resolver = make_resolver(settings, crossref=crossref)  # no model
    ref = resolver.parse(["Autor, D. (2015), Why are there still so many jobs?"])[0]
    res = resolver.resolve(ref)
    assert res.status == "review"  # the margin rule stops a coin-flip link
    assert len(res.candidates) == 2


def test_model_adjudication_links_an_ambiguous_case(settings):
    # The working paper and the journal article share a title; no year in the citation.
    wp = cand(
        "10.3386/w23285", "Robots and Jobs: Evidence from US Labor Markets", ["Acemoglu"], 2017
    )
    jpe = cand(
        "10.1086/705716", "Robots and Jobs: Evidence from US Labor Markets", ["Acemoglu"], 2020
    )
    parsed = {
        "index": 1,
        "authors": ["Acemoglu", "Restrepo"],
        "year": None,
        "title": "Robots and jobs",
        "container": "Journal of Political Economy",
    }
    llm = ScriptedLLM(
        [
            tool_reply("record_references", {"references": [parsed]}),
            tool_reply(
                "choose_candidate",
                {"choice": 2, "confidence": 0.93, "rationale": "Journal version cited, JPE 2020."},
            ),
        ]
    )
    crossref = FakeSource("crossref", {"robots": [wp, jpe]})
    resolver = make_resolver(settings, crossref=crossref, llm=llm)
    ref = resolver.parse(
        ["Acemoglu, D. and P. Restrepo, Robots and jobs, Journal of Political Economy"]
    )[0]
    res = resolver.resolve(ref)
    assert (res.status, res.method, res.identifier) == (
        "linked",
        "llm_adjudication",
        "10.1086/705716",
    )
    assert "JPE" in res.rationale
    # The model saw numbered candidates and could only answer with a number.
    tool = llm.requests[1]["tools"][0]
    assert tool["input_schema"]["properties"]["choice"]["enum"] == [0, 1, 2]


def test_invalid_model_choice_is_ignored(settings):
    llm = ScriptedLLM(
        [
            tool_reply("record_references", {"references": []}),
            tool_reply("choose_candidate", {"choice": 9, "confidence": 1.0, "rationale": "?"}),
        ]
    )
    twin = cand("10.9999/copy", AUTOR.title, ["Autor"], 2015)
    crossref = FakeSource("crossref", {"so many jobs": [AUTOR, twin]})
    resolver = make_resolver(settings, crossref=crossref, llm=llm, use_agent=False)
    res = resolver.resolve(
        resolver.parse(["Autor, D. (2015), Why are there still so many jobs?"])[0]
    )
    assert res.status == "review" and res.method == "none"


ENGLISH = cand("10.1787/eedfee77-en", "Artificial Intelligence in Society", ["OECD"], 2019)


def agent_script(query):
    return ScriptedLLM(
        [
            tool_reply("record_references", {"references": []}),
            tool_reply("search_openalex", {"query": query}),
            tool_reply(
                "submit_resolution",
                {"identifier": ENGLISH.identifier, "confidence": 0.9, "rationale": "Same work."},
                call_id="call_2",
            ),
        ]
    )


def test_agent_finds_the_work_with_a_reformulated_query(settings):
    # The citation misspells the title, so the first searches find nothing.
    openalex = FakeSource("openalex", {"artificial intelligence in society": [ENGLISH]})
    llm = agent_script("Artificial Intelligence in Society OECD 2019")
    resolver = make_resolver(settings, openalex=openalex, llm=llm)
    ref = resolver.parse(
        ["OECD (2019), Artificial inteligence in society, OECD Publishing, Paris."]
    )[0]
    res = resolver.resolve(ref)
    assert (res.status, res.method, res.identifier) == (
        "linked",
        "agent_search",
        ENGLISH.identifier,
    )
    # The search result went back to the model before it submitted.
    assert llm.requests[-1]["messages"][-1]["content"][0]["type"] == "tool_result"


def test_agent_proposal_without_deterministic_support_goes_to_review(settings):
    # A French citation: the agent proposes the English edition, which is a different work.
    openalex = FakeSource("openalex", {"artificial intelligence in society": [ENGLISH]})
    llm = agent_script("Artificial Intelligence in Society OECD 2019")
    resolver = make_resolver(settings, openalex=openalex, llm=llm)
    ref = resolver.parse(
        ["OCDE (2019), L'intelligence artificielle dans la société, Éditions OCDE."]
    )[0]
    res = resolver.resolve(ref)
    assert (res.status, res.method) == ("review", "agent_search")


def test_agent_cannot_submit_an_identifier_it_never_retrieved(settings):
    llm = ScriptedLLM(
        [
            tool_reply("record_references", {"references": []}),
            tool_reply(
                "submit_resolution",
                {"identifier": "10.1234/invented", "confidence": 0.99, "rationale": "I recall it."},
            ),
            tool_reply("search_crossref", {"query": "anything"}, call_id="call_2"),
            tool_reply("search_crossref", {"query": "anything else"}, call_id="call_3"),
        ]
    )
    resolver = make_resolver(settings, llm=llm)  # settings: 3 agent steps
    res = resolver.resolve(resolver.parse(["Martin, J. (2024), personal communication, Paris."])[0])
    assert res.status == "unresolved"
    assert any("rejected unretrieved id" in step for step in res.trace)
    assert resolver.meter.by_step["agent"] == 3  # the budget is a hard limit


def test_model_extraction_fills_fields_and_keeps_the_regex_doi(settings):
    llm = ScriptedLLM(
        [
            tool_reply(
                "record_references",
                {
                    "references": [
                        {
                            "index": 1,
                            "authors": ["Wilkinson"],
                            "year": 2016,
                            "title": "The FAIR Guiding Principles",
                            "container": "Scientific Data",
                        }
                    ]
                },
            )
        ]
    )
    resolver = make_resolver(settings, llm=llm)
    ref = resolver.parse(
        ["WILKINSON ET AL. (2016). THE FAIR GUIDING PRINCIPLES. doi:10.1038/sdata.2016.18"]
    )[0]
    assert ref.parsed_by == "llm" and ref.title == "The FAIR Guiding Principles"
    assert ref.doi == "10.1038/sdata.2016.18"


def test_model_failure_degrades_to_heuristic_parsing(settings):
    class BrokenLLM:
        def create(self, **kwargs):
            raise RuntimeError("API down")

    resolver = make_resolver(settings, llm=BrokenLLM(), use_agent=False)
    ref = resolver.parse(["Autor, D. (2015), Why are there still so many jobs?"])[0]
    assert ref.parsed_by == "heuristic" and ref.year == 2015


def test_nothing_found_without_a_model_is_unresolved(settings):
    resolver = make_resolver(settings)
    res = resolver.resolve(
        resolver.parse(["Aurora Institute (2025), Internal note, unpublished."])[0]
    )
    assert res.status == "unresolved" and res.identifier is None


def test_usage_meter_prices_tokens(settings):
    llm = ScriptedLLM([tool_reply("record_references", {"references": []})])
    resolver = make_resolver(settings, llm=llm)
    resolver.parse(["Autor, D. (2015), Why are there still so many jobs?"])
    # 1,000 input tokens at $2/M + 100 output tokens at $10/M
    assert abs(resolver.meter.cost_usd - 0.003) < 1e-9
    assert isinstance(llm.replies, list) and isinstance(LLMReply, type)


def test_unreachable_sources_are_reported_as_such(settings):
    from refresolver.fetch import FetchError

    class DownSource(FakeSource):
        def search(self, query, rows=5):
            raise FetchError("timeout")

    resolver = make_resolver(
        settings, crossref=DownSource("crossref"), openalex=DownSource("openalex")
    )
    res = resolver.resolve(
        resolver.parse(["Autor, D. (2015), Why are there still so many jobs?"])[0]
    )
    assert res.status == "unresolved" and "could not be reached" in res.rationale


def test_offline_replay_gaps_fail_loudly_instead_of_changing_results(settings, tmp_path):
    import pytest

    from refresolver.llm import RecordingClient, ReplayMiss

    replay_only = RecordingClient(None, tmp_path / "empty", model="m", offline=True)
    resolver = make_resolver(settings, llm=replay_only)
    with pytest.raises(ReplayMiss):
        resolver.parse(["Autor, D. (2015), Why are there still so many jobs?"])


def test_a_match_without_a_doi_goes_to_review_not_to_a_link(settings):
    # First live evaluation: a repository copy of an OECD manual (OpenAlex record, no DOI)
    # was linked instead of the published version. Records without a DOI are now reviewed.
    copy = cand(
        "https://openalex.org/W2743915155",
        "Frascati Manual 2015: Guidelines for Collecting and Reporting Data on Research and "
        "Experimental Development",
        ["OECD"],
        2015,
        source="openalex",
    )
    openalex = FakeSource("openalex", {"frascati": [copy]})
    resolver = make_resolver(settings, openalex=openalex)  # no model
    ref = resolver.parse(
        [
            "OECD (2015), Frascati Manual 2015: Guidelines for Collecting and Reporting Data on "
            "Research and Experimental Development, OECD Publishing, Paris."
        ]
    )[0]
    res = resolver.resolve(ref)
    assert res.status == "review" and res.identifier == copy.identifier
    assert "no DOI" in res.rationale
    assert any("sent to review instead of linking" in step for step in res.trace)
