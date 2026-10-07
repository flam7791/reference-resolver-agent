# Evaluation: gold_references.jsonl

Model: none (deterministic only); agent: off.

| Metric | Value |
|---|---|
| References | 22 |
| Precision of automatic links | 1.00 |
| Recall (resolvable, linked correctly) | 0.83 |
| Wrong links | 0 |
| False links on unresolvable items | 0 |
| Sent to review | 4 (18%) |
| Review items with the answer among suggestions | 3 |
| Unresolved | 3 |
| Source errors (searches that failed) | 0 |
| Model cost | $0.0000 ($0.00000/ref) |

## Calibration

Thresholds in this run: auto-link at score >= 0.85 with a lead of >= 0.05; model-assisted link at confidence >= 0.8 and score >= 0.55.

Top candidate's deterministic score: is the top candidate the expected work?

| Score band | References | Top candidate correct | Accuracy |
|---|---|---|---|
| [0.00, 0.55) | 3 | 0 | 0.00 |
| [0.55, 0.70) | 0 | 0 | no data |
| [0.70, 0.85) | 1 | 0 | 0.00 |
| [0.85, 0.95) | 4 | 3 | 0.75 |
| [0.95, 1.00] | 13 | 13 | 1.00 |

Model's stated confidence on the candidate it chose (adjudication or search agent),
whether or not the choice was linked: is the chosen record the expected work?

| Confidence band | Model choices | Correct | Accuracy |
|---|---|---|---|
| [0.00, 0.50) | 0 | 0 | no data |
| [0.50, 0.80) | 0 | 0 | no data |
| [0.80, 0.90) | 0 | 0 | no data |
| [0.90, 1.00] | 0 | 0 | no data |

## Errors

