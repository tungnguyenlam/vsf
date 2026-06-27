# Current Direction

This note captures the working interpretation of the current internship
direction so future sessions can recover the plan quickly. It is the
authoritative status snapshot; the per-task history lives in `WORKLOG.md`.

## Status (2026-06-27)

All three roadmap pipelines from `CLAUDE.md` have landed and are demoable
end to end:

1. **PII pipeline — done (maintained).** Vietnamese PII detection and
   anonymization on Presidio (Analyzer → Recognizers → Anonymizer). Modular NER
   wrappers (spaCy, HuggingFace, Ensemble), pipeline variants in a registry,
   evaluation tooling, JSONL prediction logging, a deterministic resolver, and
   an optional LLM verifier. Recommended default is `regex_recall`;
   `underthesea_regex_recall[_resolved]` are the higher-recall PERSON-research
   variants. Pinned by `make reproduce-pii` / `make test-pii`.
2. **Prompt injection pipeline — done.** Vietnamese-first rule-based detector
   with allow/flag/block verdicts, held-out VI evaluation (`deepset_vi`,
   `llmail_vi`), and a no-LLM reproducer. Pinned by `make reproduce-pi` /
   `make test-pi`. See `docs/prompt-injection.md`.
3. **Safe tooling — done.** Role-based permission gate + append-only audit log
   (`src/pipeline/SafeTooling/`), wired into every webdemo JSON endpoint and
   surfaced read-only in the demo's Log tab. See `docs/full-safety-pipeline.md`.

Surrounding these: an image safety path (OCR → PII redaction → VLM safety
router), a `safety_v0` review-queue workflow with a human annotation tab, and a
typst writeup (`writeup/report.typ`, `report-vi.typ`) whose every cited number
is reproduced by `make all`.

## Mentor-Facing Checkpoint

The mentor-ready artifacts are in place and should be kept current:

- `docs/pii-checkpoint.md` — Vietnamese PII taxonomy, dataset, metrics, method
  comparison, recommendation, TODO list.
- `docs/vietnamese-pii-research.md` — checksum / context / validation rules.
- `docs/full-safety-pipeline.md` — the combined text + image safety flow and
  the tool-access gate.
- `writeup/` — the typst report (EN + VI) with reproducible numbers.
- `report/pii-checkpoint-summary.md` — presentation summary.

The goal remains: keep the work easy to explain, evaluate, and demo. Avoid
endless tuning; prefer closing documented gaps and tightening the demo.

## Reproducibility (single source of truth)

`make help` lists the targets. `make all` chains `reproduce-pi` + `test-pi` +
`reproduce-pii` + `test-pii` + `smoke-pii` — no LLM spend. Use these instead of
hand-rolling commands. Routine iteration uses a fixed 5,000-row deterministic
sample (`random_state=42`); LLM-verifier runs stay small and targeted per the
cost discipline in `CLAUDE.md`.

## Suggested Next Tasks

With all three pipelines landed, the highest-value work is consolidation rather
than new pipelines:

1. Keep this note and `docs/README.md` honest as the demo and docs evolve.
2. Tighten the demo and writeup story (the safety gate is now visible in the
   Log tab; the writeup could gain a short SafeTooling section if mentors want
   it).
3. Only start a genuinely new capability (e.g. extending the prompt-injection
   detector with a learned classifier, or broadening the PII taxonomy) when the
   user explicitly asks — the existing pipelines are the deliverable.

If the user asks "what's next" with no other steer, propose closing a concrete
documented gap (a stale doc, an unverified writeup number, a missing test)
rather than opening a new research thread.
