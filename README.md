# vsf — Vietnamese safety tooling

Vietnamese-language safety tooling built on top of
[Microsoft Presidio](https://github.com/microsoft/presidio)
(Analyzer → Recognizers → Anonymizer). This repository is the work for a 6-week
internship at VinSmartFuture (VSF).

The project is Vietnamese-first by default. Three pipelines have landed and are
demoable end to end:

1. **PII detection / anonymization** — modular NER wrappers (spaCy, HuggingFace
   Transformers, Ensemble), pipeline variants in a registry, a deterministic
   resolver, evaluation tooling, JSONL prediction logging, and an optional LLM
   verifier. Recommended default pipeline: `regex_recall`.
2. **Prompt injection detection** — a Vietnamese-first rule-based detector with
   allow/flag/block verdicts and held-out VI evaluation (`deepset_vi`,
   `llmail_vi`).
3. **Safe tooling** — a role-based permission gate plus an append-only audit
   log, wired into every demo endpoint.

Around these sit an image safety path (OCR → PII redaction → VLM safety router),
a `safety_v0` human review workflow, and a reproducible typst writeup.

## Layout

| Path | What |
|------|------|
| `src/pipeline/` | All pipeline code: `Pipelines/`, `Recognizers/`, `NERWrappers/`, `Resolvers/`, `Verifiers/`, `PromptInjection/`, `Image/`, `Router/`, `SafeTooling/`, `Datasets/`, `Evaluator.py` |
| `webdemo/` | Flask demo app (Analyze / Annotate / Log tabs) |
| `docs/` | Component docs — start at [`docs/README.md`](docs/README.md) |
| `writeup/` | Typst report (`report.typ` EN, `report-vi.typ` VI) with reproducible numbers |
| `report/` | Presentation summaries |
| `tests/` | Test suite (`pytest`) |
| `scripts/` | Reproducers, sample-manifest builders, figure renderers |
| `Makefile` | One-command reproducers and tests (`make help`) |

## Run the demo

From the repo root (Flask + Presidio must be importable — see
`requirements.txt`):

```bash
python -m webdemo.app   # open http://127.0.0.1:5000 ; set PORT to change
```

See [`webdemo/README.md`](webdemo/README.md) for the HTTP API, the access-control
headers, and the Annotate workflow.

## Reproduce and test

`make help` lists the targets. These run with **no LLM spend** (they read
on-disk data and the translation cache):

```bash
make all            # reproduce-pi + test-pi + reproduce-pii + test-pii + smoke-pii
make reproduce-pi   # re-run every prompt-injection number cited in the writeup
make reproduce-pii  # re-run regex_recall on the pinned 500-row val manifest
make test           # full test suite
```

Routine iteration uses a fixed 5,000-row deterministic sample
(`random_state=42`). The total paid LLM budget for the project is small
($2–$10), so LLM-verifier runs stay small and targeted — see `CLAUDE.md` for the
cost discipline.

## Where to look next

- Current status and plan: [`docs/current-direction.md`](docs/current-direction.md)
- Mentor-ready PII checkpoint: [`docs/pii-checkpoint.md`](docs/pii-checkpoint.md)
- Combined text + image safety flow: [`docs/full-safety-pipeline.md`](docs/full-safety-pipeline.md)
- Task-by-task history: `WORKLOG.md`
