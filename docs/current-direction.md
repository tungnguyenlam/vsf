# Current Direction

This note captures the working interpretation of the current internship direction
so future sessions can recover the plan quickly.

## Current Phase

We are still in the Vietnamese PII detection/anonymization phase.

Do not move to prompt injection detection yet unless the user explicitly asks.
First, package the PII work into a clear research/demo checkpoint that can be
reported to mentors.

## Immediate Goal

Turn the current PII pipeline into a defensible checkpoint:

- clear Vietnamese PII entity taxonomy,
- dataset overview,
- metric explanation,
- method-by-method solution explanation,
- current pipeline comparison,
- residual risks and TODO list.

The goal is not endless tuning. The goal is to make the current work easy to
explain, evaluate, and demo before starting the next pipeline.

## Mentor Notes Interpreted As Tasks

1. Review Vietnamese PII entities.
   - Identify which Vietnam-specific identifiers matter: CCCD/CMND, passport,
     tax code, health insurance, phone, email, bank account, address, name,
     date of birth, organization, and related fields.
   - Compare those against current Presidio entity types.
   - Document what is supported, what is dropped, and why.

2. Research checksum, context, and validation rules.
   - Distinguish identifiers with real checksum/format validation from those
     that only have useful context or pattern heuristics.
   - Keep this Vietnamese-first. Do not add English support unless requested.

3. Introduce the dataset.
   - Source/name.
   - Number of samples.
   - Splits.
   - Columns and span format.
   - Full label taxonomy.
   - Mapping mismatch between dataset labels and our Presidio entity types.

4. Introduce evaluation metrics.
   - Precision, recall, F1.
   - Entity-level metrics.
   - Explain why precision/recall tradeoffs matter for PII.

5. Explain each method in detail.
   - Regex baseline.
   - Recall regex.
   - Underthesea NER wrapper.
   - Regex plus Underthesea.
   - Deterministic resolver.
   - Optional LLM verifier.

6. Keep "bonus" knowledge in the main content when it is conceptually central.
   - LLM verifier, guardrails, safety design, and privacy architecture are part
     of the core project story, not just extra material.

7. Maintain a clear TODO list for mentor updates.
   - What is implemented.
   - What is experimental.
   - What still needs research.
   - What should happen before moving to prompt injection detection.

## Current Recommended Pipeline Position

Keep both main candidates:

- `regex_recall`: fast, strong, high precision. Best default candidate for now.
- `underthesea_regex_recall` and `underthesea_regex_recall_resolved`: slower,
  higher-recall experimental variants, mainly useful for PERSON recall research.

Do not replace the regex baseline with Underthesea by default yet.

## Last Completed Task

The last implementation task added a conservative deterministic resolver:

- pipeline key: `underthesea_regex_recall_resolved`,
- resolver: `DeterministicResolver`,
- purpose: drop some Underthesea `PERSON` false positives using recognizer
  provenance and local Vietnamese context,
- result: small but directionally useful gain on small validation/train_val
  slices,
- audit: resolver-enabled prediction logs now include `resolver_audit`, plus a
  generated `predictions.audit.md` for manual keep/drop review.

## Suggested Next Task

Before prompt injection detection:

1. Commit or otherwise stabilize the current resolver work.
2. Write a PII checkpoint report or expand the existing session report with:
   - Vietnamese PII taxonomy,
   - dataset summary,
   - metric explanation,
   - method comparison table,
   - current recommendation,
   - TODO list.
3. Optionally add a dedicated Vietnamese PII research note covering checksum,
   context, and validation rules.

After that checkpoint is presentable, move to prompt injection detection as the
next pipeline.
