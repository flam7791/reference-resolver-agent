# Design decisions

## 1. A workflow with one bounded agent step, not a free agent

**Context.** A fully autonomous agent (the model decides every step) is flexible but hard to
predict, test and cost.
**Decision.** A fixed pipeline where most references are settled by code. Model calls happen at
two defined points (adjudication, then search) with explicit entry conditions and a step budget.
**Consequences.** Predictable cost and behaviour, testable decision paths, an audit trail per
reference. Less flexible on very unusual citations, which go to review.

## 2. Deterministic first, model where it adds value

**Context.** Most citations are easy once the right record is retrieved. Paying a model to
confirm them adds cost and non-determinism.
**Decision.** Score candidates with transparent rules (title, year, authors). Auto-link only
high, unambiguous scores. Call the model only for the ambiguous middle.
**Consequences.** The pipeline runs with no key at all, and the evaluation can measure exactly
what the model steps add (with and without `--no-llm`).

## 3. The model chooses; it never writes an identifier

**Context.** Language models produce plausible but non-existent DOIs.
**Decision.** Adjudication answers with a candidate number constrained by the tool schema. The
search agent's submission is checked against the set of identifiers it actually retrieved.
**Consequences.** Hallucinated identifiers cannot reach the output. A model can still choose the
wrong real record, which is what decision 4 addresses.

## 4. Model-assisted links need deterministic corroboration

**Context.** A model's stated confidence is not calibrated evidence.
**Decision.** A model-assisted link requires both model confidence ≥ 0.80 and a deterministic
score ≥ 0.55. Otherwise the proposal goes to review.
**Consequences.** Some correct cross-language matches go to review (for example a French citation
of an English work). That is the intended trade: precision over automation.

## 5. Precision over recall; review is part of the product

**Context.** A wrong link is worse than no link, because nobody checks linked items.
**Decision.** The margin rule, conservative thresholds, and a review queue carrying the best
candidates, their scores and the reasons. The headline metric is precision of automatic links;
CI fails on any false link.
**Consequences.** The review rate is the cost of safety. The evaluation reports whether the
queue's suggestions contain the answer, so reviewing stays fast.

## 6. Two open sources, merged

**Context.** Crossref registers most DOIs. OpenAlex covers more items and ranks differently.
**Decision.** Query both, merge by identifier, score the union.
**Consequences.** Higher recall and a second ranking opinion, at twice the requests (cached).

## 7. Record once, replay exactly

**Context.** Evaluations that call live APIs and models are slow, costly and not reproducible.
**Decision.** Every HTTP and model response is recorded, keyed by the full request. Offline mode
replays them, and any gap fails the run.
**Consequences.** CI evaluates quality with no network and no key. Changing a prompt requires
re-recording, which is correct: it is a different system.

## 8. A vendor-neutral model interface; forced tool calls for structure

**Context.** Organisations change model providers, and tests must not need a key.
**Decision.** The resolver depends on a three-method interface. The Anthropic adapter is one
implementation, the test fake is another. Structured output uses a forced tool call, which works
on every current Claude model. A test runs the real SDK against a local stand-in API.
**Consequences.** Swapping providers means one new adapter. All decision paths are tested
offline.

## 9. Respect public infrastructure

**Context.** Crossref and OpenAlex are free public services.
**Decision.** Responses are cached, requests per host are spaced out, retries are bounded, only
the needed fields are requested, and a contact email can be sent for the polite pool.
**Consequences.** Slightly slower first runs; repeat runs are instant.
