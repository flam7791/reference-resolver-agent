import json

import pytest

from refresolver.evaluation import load_gold, score_resolutions
from refresolver.llm import RecordedFailure, RecordingClient
from refresolver.models import Resolution
from refresolver.report import write_outputs

from .conftest import ROOT, ScriptedLLM, tool_reply


def test_recording_client_replays_identical_requests_offline(tmp_path):
    inner = ScriptedLLM([tool_reply("record_references", {"references": []})])
    recorder = RecordingClient(inner, tmp_path, model="m")
    request = dict(system="s", messages=[{"role": "user", "content": "x"}], tools=[])
    first = recorder.create(**request)
    assert not first.cached

    replay = RecordingClient(None, tmp_path, model="m", offline=True)
    second = replay.create(**request)
    assert second.cached and second.tool_calls[0].name == "record_references"
    with pytest.raises(RuntimeError):
        replay.create(system="s", messages=[{"role": "user", "content": "new"}], tools=[])


def test_a_failed_model_call_is_recorded_and_replayed_as_a_failure(tmp_path):
    class TimesOut:
        def create(self, **_):
            raise TimeoutError("timed out")

    request = dict(system="s", messages=[{"role": "user", "content": "x"}], tools=[])
    with pytest.raises(TimeoutError):
        RecordingClient(TimesOut(), tmp_path, model="m").create(**request)
    replay = RecordingClient(None, tmp_path, model="m", offline=True)
    with pytest.raises(RecordedFailure, match="timed out"):
        replay.create(**request)


def res(status, identifier=None, candidates=()):
    return Resolution(
        "R",
        "raw",
        status,
        "m",
        identifier=identifier,
        candidates=[{"identifier": c, "label": c} for c in candidates],
    )


def test_metrics_reward_correct_links_and_punish_false_ones():
    gold = [
        {"id": "a", "expected": "10.1/a"},
        {"id": "b", "expected": "10.1/b"},
        {"id": "c", "expected": "10.1/c"},
        {"id": "d", "expected": None},
    ]
    result = score_resolutions(
        gold,
        [
            res("linked", "10.1/A"),  # correct (case-insensitive)
            res("review", "10.1/x", candidates=["10.1/b"]),  # answer is in the suggestions
            res("unresolved"),  # missed
            res("unresolved"),  # correctly not linked
        ],
    )
    assert (result.precision, result.recall) == (1.0, pytest.approx(1 / 3))
    assert result.review_has_answer == 1 and result.false_links == 0
    assert result.passed(0.95)

    result = score_resolutions(gold[3:], [res("linked", "10.1/guess")])
    assert result.false_links == 1 and not result.passed(0.95)


def test_gold_file_is_well_formed():
    gold = load_gold(ROOT / "evals" / "gold_references.jsonl")
    ids = [g["id"] for g in gold]
    assert len(ids) == len(set(ids)) >= 20
    for g in gold:
        assert g["expected"] is None or g["expected"].startswith("10.")
        assert len(g["citation"]) >= 15


def test_outputs_are_written(tmp_path):
    from refresolver.llm import UsageMeter

    resolutions = [res("linked", "10.1/a"), res("review", "10.1/b", ["10.1/b", "10.1/c"])]
    facts = write_outputs(resolutions, UsageMeter(2.0, 10.0), tmp_path)
    assert facts["by_status"] == {"linked": 1, "review": 1, "unresolved": 0}
    queue = (tmp_path / "review_queue.csv").read_text(encoding="utf-8").splitlines()
    assert len(queue) == 2  # header + one review item
    assert json.loads((tmp_path / "resolutions.json").read_text())["summary"]["references"] == 2
    assert "doi.org/10.1/a" in (tmp_path / "report.md").read_text()


def test_a_recorded_run_replays_offline_with_identical_results(tmp_path):
    from dataclasses import replace

    import httpx

    from refresolver.config import Settings
    from refresolver.evaluation import evaluate
    from refresolver.fetch import JsonFetcher
    from refresolver.resolver import Resolver
    from refresolver.sources import CrossrefSource, OpenAlexSource

    from .conftest import load

    gold = [
        {
            "id": "a",
            "citation": "Acemoglu, D. and P. Restrepo (2020), Robots and jobs: Evidence from US "
            "labor markets, Journal of Political Economy.",
            "expected": "10.1086/705716",
        }
    ]

    def api(request):
        if "openalex" in request.url.host:
            return httpx.Response(200, json=load("openalex_search.json"))
        return httpx.Response(200, json={"message": {"items": []}})

    def build(settings, llm, client=None):
        fetcher = JsonFetcher(settings, client=client)
        crossref = CrossrefSource(fetcher)
        return Resolver(settings, crossref, [crossref, OpenAlexSource(fetcher)], llm=llm)

    live = Settings(cache_dir=tmp_path / "rec")
    parsed = {
        "index": 1,
        "authors": ["Acemoglu", "Restrepo"],
        "year": 2020,
        "title": "Robots and jobs: Evidence from US labor markets",
        "container": "JPE",
    }
    recorder = RecordingClient(
        ScriptedLLM([tool_reply("record_references", {"references": [parsed]})]),
        live.cache_dir / "llm",
        model=live.model,
    )
    client = httpx.Client(transport=httpx.MockTransport(api))
    first, first_res = evaluate(build(live, recorder, client), gold)

    offline = replace(live, offline=True)
    replayer = RecordingClient(None, offline.cache_dir / "llm", model=offline.model, offline=True)
    second, second_res = evaluate(build(offline, replayer), gold)  # no network client at all

    assert first.correct_links == second.correct_links == 1
    assert [r.to_dict() for r in first_res] == [r.to_dict() for r in second_res]


def test_a_run_where_a_database_failed_does_not_pass_the_gate():
    failed = res("linked", "10.1/a")
    failed.trace = ["crossref unavailable: api.crossref.org returned HTTP 400"]
    result = score_resolutions([{"id": "a", "expected": "10.1/a"}], [failed])
    assert result.precision == 1.0 and result.source_errors == 1
    assert not result.passed(0.95)  # it measured the outage, not the resolver
    assert "| Source errors (searches that failed) | 1 |" in result.table()
