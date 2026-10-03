"""The OpenAI-compatible adapter: local open-weight models (Ollama, vLLM, llama.cpp) or a gateway.

The resolver keeps its Messages-style requests; these tests check the translation both ways and
run a full adjudication against a scripted endpoint that behaves like a small local model,
including one that ignores the forced tool choice and answers in plain JSON.
"""

import json

import httpx
import pytest

from refresolver.config import Settings
from refresolver.factory import build_resolver
from refresolver.llm import OpenAICompatibleClient, RecordingClient, _json_object

from .conftest import FakeSource, cand, make_resolver


def scripted_endpoint(replies: list[dict], seen: list[dict]):
    """An OpenAI-compatible endpoint that returns `replies` in order and records requests."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        seen.append(json.loads(request.content))
        message = replies.pop(0)
        return httpx.Response(
            200,
            json={
                "choices": [{"index": 0, "message": {"role": "assistant", **message}}],
                "usage": {"prompt_tokens": 400, "completion_tokens": 40},
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def tool_call(name: str, args: dict, call_id: str = "call_1") -> dict:
    return {
        "content": None,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


def test_messages_with_tool_use_and_results_translate_to_chat_format():
    messages = [
        {"role": "user", "content": "Find the work."},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Searching."},
                {"type": "tool_use", "id": "t1", "name": "search_crossref", "input": {"q": "x"}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t1", "content": "[]", "is_error": True}
            ],
        },
    ]
    chat = OpenAICompatibleClient.to_chat("sys", messages)
    assert chat[0] == {"role": "system", "content": "sys"}
    assert chat[2]["tool_calls"][0]["function"] == {
        "name": "search_crossref",
        "arguments": '{"q": "x"}',
    }
    assert chat[3] == {"role": "tool", "tool_call_id": "t1", "content": "ERROR: []"}


def test_tools_and_tool_choice_translate():
    tools = OpenAICompatibleClient.to_tools(
        [{"name": "choose", "description": "d", "input_schema": {"type": "object"}}]
    )
    assert tools[0]["function"]["parameters"] == {"type": "object"}
    assert OpenAICompatibleClient.to_tool_choice({"type": "any"}) == "required"
    assert OpenAICompatibleClient.to_tool_choice({"type": "tool", "name": "choose"}) == {
        "type": "function",
        "function": {"name": "choose"},
    }
    assert OpenAICompatibleClient.to_tool_choice(None) == "auto"


def test_json_object_is_found_inside_text():
    assert _json_object('Sure:\n```json\n{"choice": 2, "x": {"y": 1}}\n```') == {
        "choice": 2,
        "x": {"y": 1},
    }
    assert _json_object("no json here") is None


def test_full_adjudication_with_a_local_model_that_ignores_forced_tools(settings):
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
    seen: list[dict] = []
    replies = [
        tool_call("record_references", {"references": [parsed]}),
        # The second reply ignores the forced tool and answers in text, as small models do.
        {"content": '{"choice": 2, "confidence": 0.9, "rationale": "JPE 2020 cited."}'},
    ]
    client = OpenAICompatibleClient(
        "http://localhost:11434/v1", "llama3.1:8b", http_client=scripted_endpoint(replies, seen)
    )
    resolver = make_resolver(
        settings, crossref=FakeSource("crossref", {"robots": [wp, jpe]}), llm=client
    )
    ref = resolver.parse(
        ["Acemoglu, D. and P. Restrepo, Robots and jobs, Journal of Political Economy"]
    )[0]
    res = resolver.resolve(ref)
    assert (res.status, res.method, res.identifier) == (
        "linked",
        "llm_adjudication",
        "10.1086/705716",
    )
    assert seen[0]["model"] == "llama3.1:8b" and seen[0]["temperature"] == 0
    assert seen[1]["tool_choice"] == {"type": "function", "function": {"name": "choose_candidate"}}
    assert resolver.meter.input_tokens == 800


def test_unparseable_text_is_no_decision_not_a_crash():
    client = OpenAICompatibleClient(
        "http://x/v1", "m", http_client=scripted_endpoint([{"content": "I think 2."}], [])
    )
    reply = client.create(
        system="s",
        messages=[{"role": "user", "content": "q"}],
        tools=[{"name": "choose", "input_schema": {}}],
        tool_choice={"type": "tool", "name": "choose"},
    )
    assert reply.tool_calls == [] and reply.text == "I think 2."


def test_factory_builds_the_local_client_without_an_anthropic_key(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    settings = Settings(
        provider="openai_compatible", model="qwen2.5:7b", cache_dir=tmp_path / "cache"
    )
    resolver = build_resolver(settings)
    assert isinstance(resolver.llm, RecordingClient)
    assert isinstance(resolver.llm.inner, OpenAICompatibleClient)
    assert resolver.llm.inner.url == "http://localhost:11434/v1/chat/completions"


def test_unknown_provider_is_refused(tmp_path):
    with pytest.raises(ValueError, match="REFRESOLVER_PROVIDER"):
        build_resolver(Settings(provider="other", cache_dir=tmp_path))


def test_provider_from_environment(monkeypatch):
    monkeypatch.setenv("REFRESOLVER_PROVIDER", "openai_compatible")
    monkeypatch.setenv("REFRESOLVER_BASE_URL", "http://gpu-server:8000/v1")
    settings = Settings.from_env()
    assert settings.provider == "openai_compatible"
    assert settings.base_url == "http://gpu-server:8000/v1"
