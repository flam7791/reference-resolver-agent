"""A thin, testable layer over the model API.

The resolver talks to a small `LLMClient` interface, not to a vendor SDK directly:
- `AnthropicClient` calls Claude through the official SDK;
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
