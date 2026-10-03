"""A thin, testable layer over the model API.

The resolver talks to a small `LLMClient` interface, not to a vendor SDK directly:
- `AnthropicClient` calls Claude through the official SDK;
- `OpenAICompatibleClient` calls any OpenAI-compatible endpoint: a local open-weight model
  through Ollama, vLLM or llama.cpp, an LLM gateway, or a cloud deployment. It translates the
  resolver's Messages-style requests (tool use, tool results) to the chat-completions format
  and back, so the resolver code does not change;
- `RecordingClient` wraps any client with a disk cache, so a run can be replayed offline with
  identical model answers (reproducible evaluations, no cost for repeats);
- tests use a scripted fake client, so every decision path is tested without an API key.

`UsageMeter` counts tokens and converts them to cost, because cost per reference is a
first-class metric in the evaluation.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)


class ReplayMiss(RuntimeError):
    """Offline replay found no recorded reply: the run must fail, not silently change."""


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class LLMReply:
    content: list[dict]  # the assistant's content blocks, reusable in the next request
    tool_calls: list[ToolCall]
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached: bool = False


class LLMClient(Protocol):
    def create(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
        tool_choice: dict | None = None,
        max_tokens: int = 2000,
    ) -> LLMReply: ...


@dataclass
class UsageMeter:
    price_input_per_mtok: float
    price_output_per_mtok: float
    calls: int = 0
    replayed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    by_step: dict = field(default_factory=dict)

    def add(self, step: str, reply: LLMReply) -> None:
        self.calls += 1
        self.by_step[step] = self.by_step.get(step, 0) + 1
        if reply.cached:
            self.replayed_calls += 1
        self.input_tokens += reply.input_tokens
        self.output_tokens += reply.output_tokens

    @property
    def cost_usd(self) -> float:
        """What the calls cost (or would cost, when replayed), in US dollars."""
        return (
            self.input_tokens * self.price_input_per_mtok
            + self.output_tokens * self.price_output_per_mtok
        ) / 1_000_000

    def summary(self) -> dict:
        data = asdict(self)
        data["cost_usd"] = round(self.cost_usd, 4)
        return data


class AnthropicClient:
    def __init__(self, model: str, api_client=None):
        import anthropic  # imported here so the package works without a key or the SDK in use

        self.model = model
        self.api = api_client or anthropic.Anthropic()

    def create(self, *, system, messages, tools, tool_choice=None, max_tokens=2000) -> LLMReply:
        kwargs = {
            "model": self.model,
            "system": system,
            "messages": messages,
            "tools": tools,
            "max_tokens": max_tokens,
        }
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        response = self.api.messages.create(**kwargs)
        content, calls, text = [], [], []
        for block in response.content:
            if block.type == "text":
                content.append({"type": "text", "text": block.text})
                text.append(block.text)
            elif block.type == "tool_use":
                content.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )
                calls.append(ToolCall(block.id, block.name, dict(block.input)))
        return LLMReply(
            content=content,
            tool_calls=calls,
            text="\n".join(text),
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )


class OpenAICompatibleClient:
    """Any OpenAI-compatible chat endpoint, with tool calling.

    Requests and replies keep the resolver's Messages-style shape (content blocks, `tool_use`,
    `tool_result`); only this class knows the chat-completions format. Small local models do not
    always honour a forced tool choice: when a tool was required and the reply is plain text, a
    JSON object in that text is accepted as the tool's input, and anything else is returned as
    text, which the resolver already treats as "no decision".
    """

    def __init__(
        self, base_url: str, model: str, api_key: str = "", timeout: float = 300.0, http_client=None
    ):
        import httpx

        self.model = model
        self.url = base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.http = http_client or httpx.Client(timeout=timeout, headers=headers)

    @staticmethod
    def to_chat(system: str, messages: list[dict]) -> list[dict]:
        out = [{"role": "system", "content": system}]
        for m in messages:
            content = m["content"]
            if isinstance(content, str):
                out.append({"role": m["role"], "content": content})
                continue
            if m["role"] == "assistant":
                text = "\n".join(b["text"] for b in content if b.get("type") == "text")
                calls = [
                    {
                        "id": b["id"],
                        "type": "function",
                        "function": {"name": b["name"], "arguments": json.dumps(b["input"])},
                    }
                    for b in content
                    if b.get("type") == "tool_use"
                ]
                msg = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = calls
                out.append(msg)
                continue
            texts = []
            for b in content:  # user turn: tool results become "tool" messages
                if b.get("type") == "tool_result":
                    body = b.get("content", "")
                    if isinstance(body, list):
                        body = "\n".join(x.get("text", "") for x in body if isinstance(x, dict))
                    if b.get("is_error"):
                        body = f"ERROR: {body}"
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": body})
                elif b.get("type") == "text":
                    texts.append(b["text"])
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
        return out

    @staticmethod
    def to_tools(tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object"}),
                },
            }
            for t in tools
        ]

    @staticmethod
    def to_tool_choice(choice: dict | None):
        if not choice or choice.get("type") == "auto":
            return "auto"
        if choice.get("type") == "any":
            return "required"
        return {"type": "function", "function": {"name": choice["name"]}}

    def create(self, *, system, messages, tools, tool_choice=None, max_tokens=2000) -> LLMReply:
        body = {
            "model": self.model,
            "messages": self.to_chat(system, messages),
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        if tools:
            body["tools"] = self.to_tools(tools)
            body["tool_choice"] = self.to_tool_choice(tool_choice)
        response = self.http.post(self.url, json=body)
        response.raise_for_status()
        data = response.json()
        message = data["choices"][0]["message"]
        text = message.get("content") or ""
        calls = []
        for i, c in enumerate(message.get("tool_calls") or []):
            fn = c.get("function", {})
            args = fn.get("arguments") or "{}"
            try:
                parsed = json.loads(args) if isinstance(args, str) else dict(args)
            except ValueError:
                continue  # malformed arguments: treated as no call
            calls.append(ToolCall(c.get("id") or f"call_{i}", fn.get("name", ""), parsed))
        forced = tool_choice and tool_choice.get("type") == "tool"
        if not calls and forced and text:
            parsed = _json_object(text)
            if parsed is not None:
                calls.append(ToolCall("call_text_0", tool_choice["name"], parsed))
        content = [{"type": "text", "text": text}] if text else []
        content += [
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in calls
        ]
        usage = data.get("usage") or {}
        return LLMReply(
            content=content,
            tool_calls=calls,
            text=text,
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
        )


def _json_object(text: str) -> dict | None:
    """The first JSON object in a text reply (models sometimes wrap it in a code fence)."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for end in range(start, len(text)):
            depth += {"{": 1, "}": -1}.get(text[end], 0)
            if depth == 0:
                try:
                    value = json.loads(text[start : end + 1])
                except ValueError:
                    break
                return value if isinstance(value, dict) else None
        start = text.find("{", start + 1)
    return None


class RecordingClient:
    """Cache model replies on disk, keyed by the full request. Offline mode = replay only."""

    def __init__(self, inner: LLMClient | None, root: Path, model: str, offline: bool = False):
        self.inner = inner
        self.root = root
        self.model = model
        self.offline = offline

    def create(self, *, system, messages, tools, tool_choice=None, max_tokens=2000) -> LLMReply:
        request = {
            "model": self.model,
            "system": system,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
        }
        key = hashlib.sha256(json.dumps(request, sort_keys=True).encode("utf-8")).hexdigest()
        path = self.root / f"{key}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            data["tool_calls"] = [ToolCall(**c) for c in data["tool_calls"]]
            return LLMReply(**{**data, "cached": True})
        if self.offline or self.inner is None:
            raise ReplayMiss("Offline and no recorded model reply for this request.")
        reply = self.inner.create(
            system=system,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(reply)), encoding="utf-8")
        return reply
