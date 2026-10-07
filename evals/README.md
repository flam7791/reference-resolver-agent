# Evaluation

`gold_references.jsonl` holds 22 citations with known answers, chosen to cover the hard cases
seen in real bibliographies:

| Case | Examples |
|---|---|
| Edition traps in report series | Employment Outlook 2005 versus 2023 |
| Other languages | the French edition of a report, which is a different work with its own DOI |
| Formatting noise | all capitals, title-first style, abbreviated journal names |
| Partial or wrong data | truncated titles, a year off by one, a mistyped DOI, a DOI-only citation |
| Nothing to find | an unpublished note, a personal communication, a web page, a working paper that does not exist |

Each expected DOI was checked against the Crossref registry when the set was built.

## Record once, replay anywhere

```bash
# Live run: calls Crossref, OpenAlex and Claude, and records every response.
refresolver eval evals/gold_references.jsonl --cache-dir evals/recordings --out evals/results

# The same run without the model, for comparison (the "ablation").
refresolver eval evals/gold_references.jsonl --cache-dir evals/recordings --no-llm

# Replay: no network, no API key, identical results. CI runs this when recordings exist.
refresolver eval evals/gold_references.jsonl --cache-dir evals/recordings --offline
```

Commit `evals/recordings/` and `evals/results/` after a live run: the recordings contain only
public bibliographic metadata and the model's answers about it.

## Reading the results

- **Precision of automatic links** is the headline number: a wrong link is worse than no link,
  because nobody checks it. CI fails below 0.95, or on any false link.
- **Recall** is the share of resolvable citations linked with no human involved.
- **Review items with the answer among suggestions** shows whether the review queue saves the
  reviewer time.
- **Cost per reference** turns token usage into money, for the business case.
- **Calibration** shows, per band of deterministic score and of the model's stated confidence,
  how often the choice was the right work. Use it before changing `REFRESOLVER_AUTO_ACCEPT` or
  `REFRESOLVER_LLM_ACCEPT`; `refresolver calibrate evals/gold_references.jsonl
  <folder>/eval_resolutions.json` recomputes it for any saved run.
