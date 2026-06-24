# VLM Safety Router

This document defines the shared safety model that every input should pass
through after deterministic preprocessing. The model is responsible for the
final routing decision:

```text
safe | reject | unsure
```

It must support:

- image-only samples
- text-only samples
- image plus OCR text samples
- redacted document images
- OCR and Presidio metadata when available

## Role In The Pipeline

The VLM safety router is not the primary PII redactor. Localized PII redaction
still comes from OCR, span detection, and span-to-box mapping. The router checks
whether the artifact is safe after preprocessing.

The router should catch risks that OCR and Presidio cannot fully cover:

- visible PII left after redaction
- prompt injection in visible text or OCR text
- sexual visual content
- violence, weapons, injury, blood, or gore
- political or religious topic content
- low-quality or ambiguous cases that should not be auto-approved

## Recommended Model Path

Near-term target:

```text
Qwen2.5-VL-3B-Instruct with LoRA or QLoRA
```

Fallback prototype if compute is tight:

```text
Qwen3-0.6B text-only classifier over OCR text
```

Do not design the system around a Vietnamese text-only encoder if image support
is a core requirement. A text-only model can be useful for an ablation, but it
creates a later fusion redesign.

## Input Contract

Each sample should use one unified schema:

```json
{
  "input_id": "safety_v0_000001",
  "original_image_path": "data/raw/000001.png",
  "redacted_image_path": "data/redacted/000001.png",
  "ocr_text": "OCR text if available",
  "presidio_spans": [
    {
      "start": 10,
      "end": 22,
      "entity_type": "PHONE_NUMBER"
    }
  ],
  "redaction_metadata": [
    {
      "entity_type": "PHONE_NUMBER",
      "box": [120, 80, 260, 112],
      "method": "solid_fill"
    }
  ],
  "input_modalities": {
    "image": true,
    "ocr_text": true,
    "presidio_metadata": true
  }
}
```

For image-only rows:

```json
{
  "redacted_image_path": "data/images/sample.png",
  "ocr_text": "",
  "input_modalities": {
    "image": true,
    "ocr_text": false,
    "presidio_metadata": false
  }
}
```

For text-only rows:

```json
{
  "redacted_image_path": null,
  "ocr_text": "Text sample here",
  "input_modalities": {
    "image": false,
    "ocr_text": true,
    "presidio_metadata": false
  }
}
```

## Output Contract

The first implementation should force a compact flat JSON object:

```json
{
  "action": "safe",
  "pii_visible": false,
  "prompt_injection": false,
  "sexual": false,
  "violence": false,
  "blood_gore": false,
  "political": false,
  "religious": false
}
```

Allowed `action` values:

```text
safe
reject
unsure
```

The model must return only valid JSON. If parsing fails, the router must treat
the result as:

```json
{
  "action": "unsure"
}
```

## Generative JSON Approach

This is the fastest implementation path for a VLM.

The model keeps its normal next-token output layer. Training examples are:

```text
input prompt plus optional image -> target JSON tokens
```

At inference:

```python
generated = model.generate(...)
text = tokenizer.decode(generated)
decision = json.loads(text)
```

The runtime must validate:

- JSON parses successfully
- all required keys are present
- `action` is one of `safe`, `reject`, `unsure`
- risk fields are booleans

Invalid or incomplete output routes to `unsure`.

## Classifier-Head Approach

This is the cleaner long-term classifier design.

Instead of using the final next-token distribution directly, take a pooled
hidden state before the language-model head and add task heads:

```text
VLM hidden state
  -> pii_visible head
  -> prompt_injection head
  -> visual risk heads
  -> topic heads
  -> action head
```

Conceptually:

```python
outputs = model(
    input_ids=input_ids,
    pixel_values=pixel_values,
    output_hidden_states=True,
)

hidden = outputs.hidden_states[-1]
pooled = hidden[:, -1, :]

pii_visible_logit = pii_visible_head(pooled)
prompt_logit = prompt_head(pooled)
visual_logits = visual_head(pooled)
topic_logits = topic_head(pooled)
action_logits = action_head(pooled)
```

Training uses masked multi-task loss:

```text
loss =
  mask_pii * BCE(pii_visible_logit, pii_visible_label)
+ mask_prompt * BCE(prompt_logit, prompt_label)
+ mask_visual * BCE(visual_logits, visual_labels)
+ mask_topic * BCE(topic_logits, topic_labels)
+ mask_action * CE(action_logits, action_label)
```

This allows one dataset to mix samples with partial labels. Unknown labels must
be masked out, not treated as negative.

## Labels

Use these risk labels first:

```text
pii_visible
prompt_injection
sexual
violence
blood_gore
political
religious
```

Use these actions:

```text
safe
reject
unsure
```

Action policy can be rule-composed from risk heads:

```text
if pii_visible: reject or unsure
if prompt_injection: reject
if sexual or violence or blood_gore: reject
if OCR quality is low or signals conflict: unsure
else safe
```

## Dataset Mixing

The router dataset may contain different subset types:

- PII redacted correctly
- PII redaction failed
- prompt injection documents or screenshots
- prompt injection hard negatives
- sexual visual content
- violence, blood, gore, weapons, or injury visual content
- political or religious topic content
- ordinary safe documents and screenshots
- low-quality or ambiguous samples

Rows can supervise different heads:

```json
{
  "labels": {
    "prompt_injection": true,
    "sexual": null,
    "violence": null
  },
  "label_mask": {
    "prompt_injection": 1,
    "visual_safety": 0
  }
}
```

Never convert unknown labels to `false`.

## Implementation Status

The generative-JSON router (the first path above) is built behind a narrow
interface in `src/pipeline/Router/`:

- `router.py` — `SafetyRouter` interface; `GeminiVlmRouter` default backend
  (Gemini Flash vision over an OpenAI-compatible Chat Completions endpoint),
  selected by name via `get_router` (config flip). `model`/`base_url` swap the
  engine; the `openai` client and API key are resolved lazily, so importing the
  module and the test suite need neither. Any call failure (auth, network, SDK)
  routes to `unsure`, audited in `RouterResult.error`.
- `input.py` — `build_router_input(row)` is the "merge before model" step: it
  maps a canonical row to the compact input contract (prefers the redacted
  image, sanitized OCR/text, span/redaction summaries, modality flags).
- `output.py` — `parse_router_output` validates the flat JSON; missing/invalid
  `action` or non-boolean risk flags route to `unsure` (`valid=False`) while
  keeping any present boolean flags for audit. Unknown flags stay `None`, never
  coerced to `false`. `RouterResult.to_labels()` yields the 8-field label dict.
- Config (single source of truth, `router.py`): `DEFAULT_MODEL =
  "gemini-flash-latest"`, `DEFAULT_BASE_URL` = Gemini's OpenAI-compatible
  endpoint, key from `GEMINI_API_KEY` / `GOOGLE_API_KEY`.
- Key loading: both entrypoints (`scripts/safety_v0/run_router.py` and
  `webdemo/app.py`) call `src.pipeline.Utils.load_env()` at startup, which loads
  the repo-root `.env` into the environment. So dropping `GEMINI_API_KEY` in
  `.env` is enough — no manual `export`. An explicit shell export still wins
  (`.env` does not override an already-set variable).

The router is fired EXPLICITLY from the webdemo "Run router" button
(`POST /api/review/run-router`) — never on load — because it spends paid budget.
It returns the decision for inspection and never writes labels; the reviewer
chooses whether to copy it into the form.

### Batch stage + fallback queue

`scripts/safety_v0/run_router.py` routes a JSONL of canonical rows (default
`redacted/<slug>/redacted.jsonl`) and writes two artifacts:

- `review/api_labels/<slug>.jsonl` — one record per row with the router decision
  as an API-label layer (`label_source="api"`; unknown flags stay `None`).
- `review/queue/<slug>.jsonl` — the fallback queue: rows whose action is
  `unsure` or whose output failed validation, with a reason.

Cost discipline (CLAUDE.md): the CLI refuses to run without `--limit N` (or an
explicit `--all`), since it spends one paid model call per row.

The Annotate tab applies the API-label layer as the **base** layer beneath any
human override: routed rows show the router's labels with `label_source="api"`
and `review.status="needs_review"`, and a human edit saved on top wins and
becomes `label_source="human"`. This closes the loop preprocessing -> router ->
human review.

The classifier-head approach and a second-pass/auto fallback (beyond queuing for
human review) are not built yet.

### OpenRouter fallback (opt-in)

When the Gemini call exhausts its retries on a transient error (free-tier daily
cap, 429, 5xx), the router can call an OpenRouter model as a one-shot fallback.
This is **opt-in** and **text-only**:

- Wire it by passing `fallback_client=` (a pre-built `OpenAI` client whose
  `base_url` points at `https://openrouter.ai/api/v1`) when constructing
  `GeminiVlmRouter`. The key is read from `OPENROUTER_API_KEY` (or
  `OPENAI_API_KEY`).
- Default fallback model: `xiaomi/mimo-v2.5`. Override via `fallback_model=`.
- Triggered only after the primary call raises a retryable error; the same
  retryability rules as the translator (HTTP 429 / 5xx + overload markers).
- **Text-only** — the default fallback model is not a VLM, so the router skips
  the fallback for rows that carry an image. Image rows continue to land in the
  `unsure` fallback queue as before.
- No `response_format` constraint is sent on the fallback call; the existing
  `parse_router_output` handles malformed/chatty responses by routing to
  `unsure`. A fallback that raises also ends up as `unsure` (with the original
  Gemini error in `RouterResult.error`).

No automatic runtime switching: a script must construct the router with the
fallback client explicitly. Selection stays configuration, reproducible.

