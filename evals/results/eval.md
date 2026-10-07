# Evaluation: gold_references.jsonl

Model: claude-sonnet-5; agent: on.

| Metric | Value |
|---|---|
| References | 22 |
| Precision of automatic links | 1.00 |
| Recall (resolvable, linked correctly) | 1.00 |
| Wrong links | 0 |
| False links on unresolvable items | 0 |
| Sent to review | 2 (9%) |
| Review items with the answer among suggestions | 0 |
| Unresolved | 2 |
| Source errors (searches that failed) | 0 |
| Model cost | $0.0851 ($0.00387/ref) |

## Calibration

Thresholds in this run: auto-link at score >= 0.85 with a lead of >= 0.05; model-assisted link at confidence >= 0.8 and score >= 0.55.

Top candidate's deterministic score: is the top candidate the expected work?

| Score band | References | Top candidate correct | Accuracy |
|---|---|---|---|
| [0.00, 0.55) | 2 | 0 | 0.00 |
| [0.55, 0.70) | 1 | 0 | 0.00 |
| [0.70, 0.85) | 1 | 0 | 0.00 |
| [0.85, 0.95) | 4 | 4 | 1.00 |
| [0.95, 1.00] | 13 | 13 | 1.00 |

Model's stated confidence on the candidate it chose (adjudication or search agent),
whether or not the choice was linked: is the chosen record the expected work?

| Confidence band | Model choices | Correct | Accuracy |
|---|---|---|---|
| [0.00, 0.50) | 0 | 0 | no data |
| [0.50, 0.80) | 0 | 0 | no data |
| [0.80, 0.90) | 0 | 0 | no data |
| [0.90, 1.00] | 5 | 5 | 1.00 |

## Errors

