"""Build a Resolver from settings: the one place where real services are wired together."""

from __future__ import annotations

import logging
import os

from .config import Settings
from .fetch import JsonFetcher
from .llm import AnthropicClient, OpenAICompatibleClient, RecordingClient
from .resolver import Resolver
from .sources import CrossrefSource, OpenAlexSource

log = logging.getLogger(__name__)


def build_resolver(settings: Settings, use_llm: bool | None = None, use_agent: bool = True):
    if settings.provider not in {"anthropic", "openai_compatible"}:
        raise ValueError("REFRESOLVER_PROVIDER must be 'anthropic' or 'openai_compatible'")
    fetcher = JsonFetcher(settings)
    crossref = CrossrefSource(fetcher)
    sources = [crossref, OpenAlexSource(fetcher)]

    llm = None
    wants_llm = settings.use_llm if use_llm is None else use_llm
    if wants_llm and settings.provider == "openai_compatible":
        # A local model (Ollama, vLLM, llama.cpp) needs no key; a gateway or cloud may.
        inner = (
            None
            if settings.offline
            else OpenAICompatibleClient(settings.base_url, settings.model, settings.api_key)
        )
        llm = RecordingClient(
            inner, settings.cache_dir / "llm", settings.model, offline=settings.offline
        )
    elif wants_llm:
        has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
        if has_key or settings.offline:
            inner = AnthropicClient(settings.model) if has_key else None
            llm = RecordingClient(
                inner, settings.cache_dir / "llm", settings.model, offline=settings.offline
            )
        else:
            log.warning("ANTHROPIC_API_KEY not set: running without the model steps.")
    return Resolver(settings, crossref, sources, llm=llm, use_agent=use_agent)
