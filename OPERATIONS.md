# Operations: Reference resolver

Owner: _name_ · Backup: _name_ · Review: every three months

## Monitoring

| Signal | Source | Frequency | Act when |
|---|---|---|---|
| Precision of automatic links | `resolutions.json` of each run; the gold-set evaluation | each release; monthly sample of 20 links | any wrong link: lower automation (raise `REFRESOLVER_AUTO_ACCEPT`) |
| Review rate | `review_queue.csv` rows / references | each run | above 25%: look at the review reasons |
| Source errors | run report | each run | any: rerun later; the gate fails on them |
| Model cost per reference | run report (zero with a local model) | monthly | above budget |

## Runbook

- Model provider down: run with `--no-llm` (deterministic steps only) or switch `REFRESOLVER_PROVIDER` to a local model.
- Registry rate-limited: set `REFRESOLVER_CONTACT_EMAIL` (polite pool), rerun from the cache.
- A wrong link found by a reader: add the reference to `evals/gold_references.jsonl` before fixing, then rerun the evaluation.

## Change and release

- Every change runs the tests and the evaluation in CI; a recorded model run is re-recorded when the prompt or the model changes.
- Versions and changes are listed in CHANGELOG.md; the previous release tag is the rollback.
