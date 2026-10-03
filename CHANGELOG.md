# Changelog

## 0.2.0 (2026-10)

- Any OpenAI-compatible endpoint for the model steps (`REFRESOLVER_PROVIDER=openai_compatible`):
  a local open-weight model through Ollama, vLLM or llama.cpp, or an LLM gateway. Requests keep
  their tool-use shape; a model that ignores a forced tool call yields "no decision", never a link.
- System card, operating notes, dependency scan in CI, Dependabot.

## 0.1.0 (2026-10)

- Deterministic scoring, bounded Claude agent, review queue, gold-set evaluation replayed in CI,
  MCP server.
