# AGENTS.md: reference-resolver-agent

Instructions for coding agents (and people) changing this repository. Read this first.

Turns messy bibliographic references into verified DOIs from Crossref and OpenAlex. Code
decides what code can decide; a model only chooses among retrieved candidates, and anything
uncertain goes to a human review queue. Precision of automatic links is the headline metric.

## Commands

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest                                                   # offline, no key
refresolver eval evals/gold_references.jsonl --cache-dir evals/recordings --offline --min-precision 0.95
refresolver run examples/aurora_working_paper.md --no-llm --out out/   # deterministic path, free
```

The evaluation replays recorded HTTP and model responses; a missing recording fails the run.
Re-recording needs network access and a key or a local model, so ask before doing it.

## Layout

- `src/refresolver/resolver.py`: the pipeline, prompts and guardrails
- `src/refresolver/scoring.py`: deterministic match scoring (title, year, authors)
- `src/refresolver/sources.py`, `fetch.py`: registry clients, cache, politeness, replay
- `src/refresolver/llm.py`: model interface, adapters, record/replay, cost meter
- `src/refresolver/evaluation.py`: gold-set metrics, including the calibration table
- `src/refresolver/mcp_server.py`: the two read-only MCP tools
- `skills/reference-resolver/SKILL.md`: how an assistant should use those tools
- `evals/gold_references.jsonl`, `evals/recordings/`, `evals/results*/`: gold set, recordings, results

## Invariants: never weaken these

1. **The model never writes an identifier.** Adjudication returns a candidate number (a schema
   enum); the search agent may only submit an identifier it retrieved (design decisions 3).
2. **A model-assisted link needs deterministic corroboration** (score floor) **and at least one
   cited author on the candidate** (decision 4 and `model_link`). Anything else goes to review.
3. **Auto-links need a clear lead over the runner-up** (the margin rule).
4. **The search agent has a hard step budget** (`REFRESOLVER_MAX_AGENT_STEPS`).
5. **CI fails below 0.95 precision, on any false link, or on any source error.** Never lower the
   gate, delete a gold case or edit a recording to make a run pass.
6. **A failed model call is recorded and replayed as a failure**, so degraded runs replay exactly.

## Working rules

- A wrong link found anywhere becomes a gold case before the fix.
- A change to a prompt, a model or the scoring makes recordings stale: re-record, then update
  the results tables in the README from `evals/results*/eval.md`, never by hand.
- Thresholds are policy (`config.py`): change them only with an evaluation run that shows the
  trade-off.
- Record every change in `CHANGELOG.md`; a design change goes in `docs/design-decisions.md`.
- Examples are fictional or public. Commits carry no AI co-author trailers.
