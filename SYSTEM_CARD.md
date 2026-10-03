# System card: reference-resolver-agent

| | |
|---|---|
| Pattern | P4 deterministic first, model chooses among retrieved candidates ([ai-engineering-framework](https://github.com/flam7791/ai-engineering-framework)) |
| Models | Claude by default; any OpenAI-compatible endpoint, including a local open-weight model (`REFRESOLVER_PROVIDER=openai_compatible`); runs without a model in deterministic mode |
| Sources | Crossref and OpenAlex (public registries) |

## Intended use

Resolve the references in a document's bibliography to DOIs, link the clear cases automatically,
and send uncertain ones to a person with suggestions.

## Out of scope

Judging whether a citation supports the claim it is attached to; works without a registry record.

## Data

Reference strings are sent to the public registries as search queries and, when a model is used,
to the model endpoint (nothing leaves the machine with a local model). HTTP and model responses
are cached locally for replay.

## How it can fail

- A wrong automatic link: guarded by a deterministic score threshold, a margin over the runner-up,
  a model that may only choose among retrieved records, and a review queue for the rest.
- A registry outage that silently lowers recall: the evaluation counts source errors and fails on
  any.
- A small local model that ignores the forced tool call: its answer counts as no decision, so the
  reference goes to review rather than to a link.

## Evaluation

Gold set of 22 references with precision, recall, wrong links, review rate and cost per
reference; CI replays the recorded run and fails below 0.95 precision or on any false link.

## Human oversight

`review_queue.csv` lists every uncertain item with the suggestion, the alternatives and an empty
decision column for the reviewer.
