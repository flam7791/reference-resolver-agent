# Changelog

## 0.2.1 (2026-10)

- Tool arguments are repaired to the tool's schema before use: small open-weight models return
  lists as JSON-encoded strings, numbers as strings and null as "null". Found in the first live
  run with Llama 3.1 8B, where every model extraction was lost this way.

## 0.2.0 (2026-10)

- Any OpenAI-compatible endpoint for the model steps (`REFRESOLVER_PROVIDER=openai_compatible`):
  a local open-weight model through Ollama, vLLM or llama.cpp, or an LLM gateway. Requests keep
  their tool-use shape; a model that ignores a forced tool call yields "no decision", never a link.
- System card, operating notes, dependency scan in CI, Dependabot.

## 0.1.0 (2026-10)

- Deterministic scoring, bounded Claude agent, review queue, gold-set evaluation replayed in CI,
  MCP server.
