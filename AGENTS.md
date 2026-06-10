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
- Run focused tests after each meaningful change; run the broader test suite when the blast radius warrants it.
- Report what changed, what was verified, and any blocker or residual risk.
- Keep heavyweight model downloads, dataset downloads, and integration tests optional unless the user asks to run them.
- For this project, default to Vietnamese-only behavior unless the user explicitly asks to add English support.
