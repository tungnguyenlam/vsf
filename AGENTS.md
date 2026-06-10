Do not use icons when coding.

## Project

This repository (`vsf`) is the user's work for a 6-week internship at VinSmartFuture (VSF), the later part of the "Vin AI in Action" program. It builds Vietnamese-language safety tooling on top of Microsoft Presidio (Analyzer -> Recognizers -> Anonymizer).

Roadmap, in order:
1. PII pipeline (current) — Vietnamese PII detection / anonymization. Modular NER wrappers (spaCy, HuggingFace Transformers, Ensemble), pipeline variants in a registry, evaluation tooling, JSONL prediction logging, and a PII dataset on HuggingFace.
2. Prompt injection pipeline (next) — possibly customized inside the same Presidio pipeline.
3. Safe tooling — user permission gating and related guardrails.

Language: Vietnamese-only by default. English is a stretch goal and may not be reached; do not add English support unless explicitly asked.

## Collaboration

This repository is developed through continuous agent collaboration.

The user will bring hypotheses, experiment ideas, and direction. The agent should execute the work end to end: inspect the existing code, make the smallest useful implementation, run relevant tests or checks, and report the outcome clearly.

Default workflow:
- Treat user ideas as implementation requests unless the user explicitly asks only to discuss.
- Prefer reusable Python modules and tests over notebook-only changes.
- Preserve existing user changes and avoid broad rewrites.
- Design for swappability. The user wants to try different things (models, providers, NER backends, prompts) with the least pain. Build components behind narrow interfaces, hide vendor specifics behind a thin adapter, and expose choices (model, provider, base URL, backend) as configuration with a single source of truth — never hardcode them deep in call sites. Prefer flipping one config value over editing logic. Do not add automatic runtime switching between options; keep selection explicit and reproducible.
- Run focused tests after each meaningful change; run the broader test suite when the blast radius warrants it.
- Report what changed, what was verified, and any blocker or residual risk.
- Keep heavyweight model downloads, dataset downloads, and integration tests optional unless the user asks to run them.
- For this project, default to Vietnamese-only behavior unless the user explicitly asks to add English support.

## Datasets

Each evaluation dataset is a `BaseDataset` subclass under `src/pipeline/Datasets/` (registered in `registry.py`) that owns its source location, column schema, and its own `label_to_presidio` mapping — every dataset has a different label taxonomy, so the mapping lives with the dataset, not in a global dict. Combining datasets later is just instantiating several and concatenating their loaded frames.

For every dataset, also write `docs/datasets/<name>.md` documenting: what it is, columns/format, the span format, the full label taxonomy, and the mismatch vs our Presidio entity types (which labels map, which are dropped). Add it to the index in `docs/datasets/README.md`.

## WORKLOG.md

After finishing a task, append a short entry to `WORKLOG.md` at the repo root (date, what changed, what was verified, any residual risk).

This file grows large and must never be loaded into context:
- Write to it only with the `bash` tool, by appending (e.g. `printf '...' >> WORKLOG.md` or `cat >> WORKLOG.md <<'EOF' ... EOF`). Never open it with the Read/Edit/Write file tools.
- To read it, use `bash` with `tail`/`grep`/`head` to pull only the few lines you need. Never `cat` the whole file.
