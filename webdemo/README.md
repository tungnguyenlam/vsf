# Guardrail demo website

A small Flask app for demoing the pipeline end to end: paste Vietnamese text and
see (1) prompt-injection screening with an allow/flag/block verdict and matched
rules, and (2) PII detection with highlighted spans plus the anonymized output.

## Run

From the repo root (uses the same Python env as the pipeline — Flask + Presidio
must be importable):

```bash
python -m webdemo.app
```

Then open <http://127.0.0.1:5000>. Set `PORT=8080` to change the port.

The PII pipeline and prompt-injection detector are picked from the dropdowns
(populated from `list_pipeline_names()` / `list_prompt_injection_detector_names()`),
loaded lazily, and cached after first use.

## HTTP API

- `POST /api/analyze` — `{text, pipeline?, detector?}` → both results (injection first, then PII).
- `POST /api/prompt-injection` — `{text, detector?}` → `PromptInjectionResult`.
- `POST /api/pii` — `{text, pipeline?}` → `{pipeline, spans, anonymized}`.
- `GET /api/log` — recent analyze requests (most recent first).
- `DELETE /api/log` — clear the log.

## Log view

Every `/api/analyze` call is appended as one JSON line to
`webdemo/logs/demo_requests.jsonl` (git-ignored). The **Log** tab in the UI
shows these records — verdict, score, matched rules, detected PII types, and the
anonymized output — newest first, with refresh and clear controls.
