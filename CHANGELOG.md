# Changelog

## Unreleased

- Live run with `REFRESOLVER_EXTRACT_BATCH=1`, Qwen 2.5 7B on a laptop CPU: 22 of 22
  references parsed by the model (2 of 22 in batches of 20); precision and recall 1.00, no
  wrong or false link; 3 to review, 1 unresolved; 44 minutes against about 16. Results in
  `evals/results-qwen2.5-7b-ctx8k-batch1`; local recordings are now git-ignored.

## 0.4.0 (2026-10)

- `REFRESOLVER_EXTRACT_BATCH` (default 20, unchanged) sets how many references go into one
  extraction call. Both 8B local models parsed 2 of 22 references in batches of 20; `1` sends
  one reference per call for them. The recorded Claude run keeps the default and replays
  unchanged. Not measured yet; the command is in the README.

## 0.3.0 (2026-10)

- Calibration tables in every evaluation: accuracy of the top candidate per band of
  deterministic score, and of the model's choices per band of its stated confidence (including
  choices sent to review). `refresolver calibrate` computes them from any saved run; the four
  committed result folders include them. Findings in the README.
- `AGENTS.md` for coding agents (`CLAUDE.md` imports it), and `skills/reference-resolver/SKILL.md`
  for assistants that call the MCP tools.

## 0.2.2 (2026-10)

- A model's choice (adjudication or search agent) is not linked automatically when none of the
  candidate's authors appears in the citation; a person confirms it. Found in the live run with
  Qwen 2.5 7B, which linked a web page without a DOI to an unrelated record with confidence 0.95.
- Failed model calls (timeouts, server errors) are recorded and replayed as failures, so a run
  that degraded to heuristic parsing replays exactly.
- Results of Qwen 2.5 7B on the gold set, next to Claude and Llama 3.1 8B.

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
