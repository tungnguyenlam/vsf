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
- `GET /api/review/files` — canonical `safety_v0` JSONL files found under `data/safety_v0/`.
- `GET /api/review/rows?file=<rel path>` — rows for one file with human overrides applied, plus stats.
- `POST /api/review/save` — `{file, input_id, labels, review, span_edits?}` → appends a human override. `span_edits` (optional) adds/deletes human detections: `{pii_spans:{added,deleted}, prompt_injection_spans:{added,deleted}, boxes:{added,deleted}}`.
- `GET /api/review/image?path=<rel path>` — serves a row's image (constrained to the data root).
- `POST /api/review/recompute` — `{file, input_id, span_edits?}` → re-maps the row's current PII spans (incl. unsaved human edits) to OCR boxes, redacts human image boxes, renders a throwaway redacted **preview** under `data/safety_v0/review/preview/<input_id>.png`, and returns `{regions, pii_spans, redacted_image_path}`. Writes no labels/overrides. Free (no LLM/OCR — deterministic Pillow render).
- `POST /api/review/run-router` — `{file, input_id, router?}` → runs the shared VLM safety router on one row (PAID; fired only by the button) and returns `{result, labels, modalities}`. Writes no labels.

## Annotate view (safety_v0 review)

The **Annotate** tab is the human-review step from `DATA_PLAN.md`. It is a
**top-down stepper**: the **left column** scrolls through the evidence one step
at a time (source & modality → input text → PII spans → prompt-injection spans →
image → OCR text), and the **right sticky sidebar** holds the row verdict and
actions (nav, action, risk flags, status/notes, Save, router). It loads
canonical `safety_v0` rows (the converter / weak-pipeline output) from a chosen
JSONL file and lets you correct the labels:

- `action` (safe / reject / unsure / unknown),
- the 7 risk flags as tri-state (unknown / true / false) — `unknown` (`null`) is
  masked out of training, never treated as a negative,
- `review.status` and free-text notes.

### Manual annotation (add a missed detection)

The steps are not read-only — you can fix detections the pipeline missed:

- **Text spans:** select any substring in the **Input text** or **OCR text**
  step; a popover lets you add it as a **PII span** (entity type from the
  canonical 21-type taxonomy) or a **prompt-injection span** (attack type).
  Each span row has a `×` to delete it. On the OCR text, selecting only part of
  an OCR line box (e.g. 2-3 words) redacts just that slice: the matched box is
  clipped horizontally to the selected characters (proportional, single-line
  assumption) rather than masking the whole line.
- **Image boxes:** in the **Image** step, drag a rectangle over a missed PII
  region and pick a type; the box is stored in `geometry.source_pii_boxes`
  (coords normalized to the image's natural size) and can be deleted.

The image steps derive from a single source of truth — the row's `pii_spans`
mapped to OCR boxes plus human image boxes — so the "Image — detection boxes"
overlay and the "Boxes ↔ OCR text" table always reflect what actually gets
redacted (source-aligned spans render blue, your additions dashed-green). When a
span changes, the box overlay updates instantly client-side and the **Redacted
image** step refreshes from a live `/api/review/recompute` preview (debounced
~0.4 s; a **Re-run redaction** button in the sidebar forces it). The preview is
throwaway and writes nothing — on **Save** the edits persist as a span override
and baking still happens offline via `run_pii_redaction.py`.

Human-added items carry `detector="human"` (distinct from `source_gold` / the
pipeline) and render with a dashed green outline. Adding or removing a **PII**
span re-derives the sanitized-text preview live, so `pii_visible: false` stays
honest. Unsaved edits are flagged in the sidebar (`unsaved spans`) and are
persisted in the same override line as the labels on **Save**, then re-merged
from the server (assigning stable ids). The schema validator accepts both
`ocr_boxes` and `source_pii_boxes` as span box references, so baked overrides
stay valid.

Each label shows a colored **provenance chip** so you can tell at a glance where
its current value came from, derived from `label_source`:

- `source` (blue) — the sample's own annotation from the converter
  (`source_gold`, `source_assumption`, `source`, …),
- `weak/auto` (amber) — the weak-label / router pipeline (`pipeline`, `rule`,
  `api`, …),
- `you` (green) — a value you saved as a human override (`human`).

The sidebar's nav card shows a one-line summary of
which layers contributed to the row. Once you review and save, those fields
become `you` (green) — the final corrected value.

Edits are pre-filled from the row's existing labels and appended as overrides to
`data/safety_v0/review/human_overrides/<source>.jsonl` (latest line per
`input_id` wins). Paths are constrained to `data/safety_v0/` to prevent
traversal.

The file picker includes converter, OCR, redacted, weak, and demo sample JSONL
outputs. For image PII rows such as WebPII, the **Image** step overlays the
existing `source_pii_boxes` on the original image (and shows the redacted image
when present), so you can see what was boxed and add any that were missed.

The sidebar also has a **Run router** button: it sends the row through the
shared VLM safety router (Gemini Flash vision) and shows the returned action +
risk flags. This is a **paid** call and runs only on click — never on load.
"Apply to form" copies the router's decision into the editable fields (it does
not save), so a human still confirms before writing an override. Set
`GEMINI_API_KEY` (or `GOOGLE_API_KEY`) for the router to reach the API; without
a key it returns `unsure` with the error shown inline. The key is read from the
repo-root `.env` automatically — `webdemo/app.py` calls `Utils.load_env()` at
startup, so no manual `export` is needed (an explicit export still wins).

Batch routing happens offline via `scripts/safety_v0/run_router.py`, which writes
an **API-label layer** to `data/safety_v0/review/api_labels/<source>.jsonl` and a
fallback queue to `review/queue/<source>.jsonl`. The Annotate tab applies that
layer as the base (router labels with `label_source="api"`, shown as
`needs_review`); a human override saved on top wins. The stats line shows how
many rows in the current file carry router labels (`N routed`).

To try it without the gated source datasets, generate a small varied demo
sample (text PII, prompt injection, image+OCR with redaction, visual safety):

```bash
python scripts/safety_v0/make_demo_review_sample.py
```

## Log view

Every `/api/analyze` call is appended as one JSON line to
`webdemo/logs/demo_requests.jsonl` (git-ignored). The **Log** tab in the UI
shows these records — verdict, score, matched rules, detected PII types, and the
anonymized output — newest first, with refresh and clear controls.
