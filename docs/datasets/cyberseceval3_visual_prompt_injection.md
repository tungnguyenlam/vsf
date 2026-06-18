# cyberseceval3_visual_prompt_injection (CyberSecEval 3)

safety_v0 source slug: `cyberseceval3_visual_prompt_injection`. Canonical dataset
identity recorded on every row: `facebook/cyberseceval3-visual-prompt-injection`.

## What it is

The visual prompt-injection split of Meta's CyberSecEval 3 benchmark: 1,000
synthetic cases where a benign-looking user question is paired with an image that
carries an injected instruction. It is the source most directly aligned with
**visual / indirect prompt injection** and is meant to guide a visual PI
detector. Every row is an attack — there is no benign control.

## Download / access

The dataset ships **no image binaries**: each row only has text fields (the
image's `image_text` and `image_description`, not pixels). We therefore page the
datasets-server `/rows` API (no parquet/image download) into a single raw JSONL.
One config (`visual_prompt_injection`), one split (`test`), 1,000 rows — tiny
text, so the default pulls all of it.

## Columns / format

| Column | Meaning |
|---|---|
| `id` | Source row id. |
| `system_prompt` | The app's system prompt; often plants a secret key the attack tries to exfiltrate. |
| `user_input_text` | The benign-looking user question. |
| `image_description` | Scene description of the image. |
| `image_text` | Text embedded in the image = **the injection** (empty for ~100 rows whose attack is carried by the scene, e.g. figstep / query_relevant_images). |
| `judge_question` | Eval rubric for the original benchmark. |
| `injection_technique` | list[str] (embedded_text_instructions, obfuscated, indirect_reference, misleading, figstep, virtualization, query_relevant_images). |
| `injection_type` | `direct` or `indirect`. |
| `risk_category` | `logic-violating` or `security-violating`. |

Distribution (1,000 rows): injection_type 500 direct / 500 indirect;
risk_category 600 logic-violating / 400 security-violating; 100 rows have empty
`image_text`. All English (0 non-ASCII text).

## Mapping to canonical safety_v0

The injection lives in the image, so it maps to OCR text:

- `content.input_text`  <- `user_input_text`
- `content.ocr_text`    <- `image_text`
- `modality.has_image = False` (no pixels), `has_ocr = bool(image_text)`,
  `has_text = True`.
- Gold injection span over the OCR text (`field="ocr_text"`,
  `detector="source_gold"`, `attack_type="visual_prompt_injection"`) when
  `image_text` is non-empty; no span for the ~100 scene-only rows.

### Label taxonomy vs our label types

Mirrors the deepset converter ("null means unknown, not false"):

| Field | Value | Provenance | Rationale |
|---|---|---|---|
| `prompt_injection` | `True` | `source_gold` | Every row is an attack. |
| `action` | `reject` | `source_assumption` | Attacks should be rejected. |
| `pii_visible` | `False` | `source_assumption` | Synthetic tests, no depicted PII (the secret lives in the system prompt, not the content). |
| `sexual` / `violence` / `blood_gore` | `False` | `source_assumption` | Security/logic attacks, no depicted content. |
| `political` / `religious` | `None` | — | No topic gold; keep unknown. |

The CyberSecEval taxonomy (`injection_type` / `injection_technique` /
`risk_category`) is **orthogonal** to our 7 axes, so it is preserved in
`source_labels` (with `system_prompt`, `image_description`, `judge_question`) for a
later image-render step, a topic teacher, or human review.

### Language filter

The corpus is all English, kept under safety_v0's English/Vietnamese policy. The
combined-text language detector drops **1 row** (id 292, a short bracket-placeholder
question it misjudges) — a known minor false-drop, leaving **999** converted rows.

## Weak prompt-injection rule result

Running the Vietnamese-first rule detector over the OCR text (DATA_PLAN: run the
weak detector on OCR text) fires on **0 / 999** rows — recall 0.0. As with the
other English PI sources (deepset R=0.084, llmail R=0.022) the rules do not
generalize to English/visual attacks; these rows are gold positives for a learned
/ multimodal detector and for future EN->VI translation, not for the rule
detector.

## Human / future-work focus

- These are text-only stand-ins for visual attacks: a render step (image_text +
  image_description -> image -> OCR) would make them true multimodal rows.
- Whether the ~100 scene-only (`empty image_text`) rows should be kept as
  text-only PI positives or deferred until rendered.
- Topic axes (political/religious) and any actual sexual/violent depiction.

## Commands

```bash
python scripts/safety_v0/download/download_cyberseceval3_visual_prompt_injection.py
python scripts/safety_v0/inspect/inspect_cyberseceval3_visual_prompt_injection.py
python scripts/safety_v0/convert/convert_cyberseceval3_visual_prompt_injection.py
python scripts/safety_v0/run_prompt_injection_rules.py --slug cyberseceval3_visual_prompt_injection
python scripts/safety_v0/validate_safety_v0.py \
    data/safety_v0/converted/cyberseceval3_visual_prompt_injection/source_canonical.jsonl
```

- converter output:
  `data/safety_v0/converted/cyberseceval3_visual_prompt_injection/source_canonical.jsonl`
- weak-label output:
  `data/safety_v0/weak/cyberseceval3_visual_prompt_injection/weak_labeled.jsonl`
