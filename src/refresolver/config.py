"""Settings, read from environment variables (prefix REFRESOLVER_) with safe defaults.

The decision thresholds live here because they are policy, not code: they set the balance
between automation (fewer references for people to check) and precision (fewer wrong links).
Change them, re-run the evaluation, and compare.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    # Model. "anthropic": Claude through the SDK, key from ANTHROPIC_API_KEY.
    # "openai_compatible": any OpenAI-compatible endpoint, e.g. a local open-weight model through
    # Ollama (base URL http://localhost:11434/v1, no key), vLLM, or an LLM gateway.
    provider: str = "anthropic"
    model: str = "claude-sonnet-5"
    base_url: str = "http://localhost:11434/v1"
    api_key: str = ""
    use_llm: bool = True
    # Prices in USD per million tokens, for the cost report. Check current prices.
    price_input_per_mtok: float = 2.0
    price_output_per_mtok: float = 10.0

    # Decision policy.
    auto_accept: float = 0.85  # deterministic score needed to link without a model or a person
    min_margin: float = 0.05  # ...and the lead over the runner-up (ambiguity guard)
    review_floor: float = 0.55  # below this, a candidate is not worth a person's time
    llm_accept: float = 0.80  # model confidence needed for a model-assisted link
    max_agent_steps: int = 6  # hard budget for the search agent, per reference
    # References per extraction call. 20 suits a frontier model; small local models mostly
    # failed batches of 20 (2 of 22 parsed), so measure 1 for them.
    extract_batch: int = 20

    # Scholarly APIs. A contact email puts requests in Crossref's and OpenAlex's "polite pool".
    contact_email: str | None = None
    openalex_api_key: str | None = None
    http_timeout: float = 20.0
    cache_dir: Path = Path.home() / ".cache" / "refresolver"
    offline: bool = False  # replay cached HTTP and model responses only; never call out

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        d = cls()

        def flag(name: str, default: bool) -> bool:
            return env.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")

        return cls(
            provider=env.get("REFRESOLVER_PROVIDER", d.provider).strip().lower(),
            model=env.get("REFRESOLVER_MODEL", d.model),
            base_url=env.get("REFRESOLVER_BASE_URL", d.base_url),
            api_key=env.get("REFRESOLVER_API_KEY", d.api_key),
            use_llm=flag("REFRESOLVER_USE_LLM", d.use_llm),
            price_input_per_mtok=float(env.get("REFRESOLVER_PRICE_INPUT", d.price_input_per_mtok)),
            price_output_per_mtok=float(
                env.get("REFRESOLVER_PRICE_OUTPUT", d.price_output_per_mtok)
            ),
            auto_accept=float(env.get("REFRESOLVER_AUTO_ACCEPT", d.auto_accept)),
            min_margin=float(env.get("REFRESOLVER_MIN_MARGIN", d.min_margin)),
            review_floor=float(env.get("REFRESOLVER_REVIEW_FLOOR", d.review_floor)),
            llm_accept=float(env.get("REFRESOLVER_LLM_ACCEPT", d.llm_accept)),
            max_agent_steps=int(env.get("REFRESOLVER_MAX_AGENT_STEPS", d.max_agent_steps)),
            extract_batch=int(env.get("REFRESOLVER_EXTRACT_BATCH", d.extract_batch)),
            contact_email=env.get("REFRESOLVER_CONTACT_EMAIL") or None,
            openalex_api_key=env.get("OPENALEX_API_KEY") or None,
            http_timeout=float(env.get("REFRESOLVER_HTTP_TIMEOUT", d.http_timeout)),
            cache_dir=Path(env.get("REFRESOLVER_CACHE_DIR", str(d.cache_dir))),
            offline=flag("REFRESOLVER_OFFLINE", d.offline),
        )
