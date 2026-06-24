# local_vi_prompt_injection (safety_v0 source)

First prompt-injection `safety_v0` source (see `DATA_PLAN.md`). It is not a new
`BaseDataset`; it reuses the repo's hand-authored Vietnamese prompt-injection
seed files and converts their rows into the canonical `safety_v0` schema
(`src/pipeline/Datasets/safety_v0_schema.py`).

- Slug: `local_vi_prompt_injection`
- Underlying seed files (local, no download/token):
  - `data/prompt_injection/vietnamese_seed.jsonl` (`vietnamese_seed`)
  - `data/prompt_injection/vietnamese_app_seed.jsonl` (`vietnamese_app_seed`)
  - `data/prompt_injection/vietnamese_mentor_seed.jsonl` (`vietnamese_mentor_seed`)
- Converter: `scripts/safety_v0/convert/convert_local_vi_prompt_injection.py`
- Output: `data/safety_v0/converted/local_vi_prompt_injection/source_canonical.jsonl`
- Per-seed docs: `docs/datasets/local-vietnamese-prompt-injection-seed.md`,
  `…-app-seed.md`, `…-mentor-seed.md`.

## Why straight-convert

These are hand-authored Vietnamese instruction prompts labelled at the row level
with a gold prompt-injection flag. They are text-only and synthetic: no PII, no
images, no sensitive-topic content. So they are converted directly with no OCR,
no redaction, and no LLM verifier. The gold flag is authoritative and becomes the
`prompt_injection` label.

## Source format

Each line is a JSON object:

| Source field | Meaning |
|---|---|
| `input_id` | upstream sample id (e.g. `vi-seed-009`) |
| `text` | the Vietnamese prompt |
| `label` | gold flag: `1` = prompt injection, `0` = benign |
| `category` | attack/benign category (e.g. `instruction_override`) |
| `source` | originating seed (`local_vietnamese_seed`, …) |
| `expected_action` | optional (`allow`/`block`) in the app/mentor seeds |
| `language` | always `vi` |

Counts (full conversion): 120 rows — 74 attack (`label=1`), 46 benign
(`label=0`).

## Source → canonical mapping

| Source field | Canonical field |
|---|---|
| `text` | `content.input_text` and `content.sanitized_text` (no PII to remove) |
| `label==1` | one whole-text `detections.prompt_injection_spans[*]` |
| `category` | `prompt_injection_spans[*].attack_type` |
| `source` | `source.name` |
| `input_id` | `source.source_sample_id` |
| `label`, `category`, `expected_action`, `language` | `source_labels` (kept for audit) |

- For attack rows only, a single span `[0, len(text))` is written with
  `detector = "source_gold"`, `score = 1.0`, `attack_type = category`. The seeds
  carry no character offsets, so the whole-text span is the honest provenance.
- These rows are text-only: `modality.has_text = true`, `has_image = false`,
  `has_ocr = false`. No OCR boxes or redaction metadata.

## Label policy (`prompt_injection_text_labels`)

The DATA_PLAN rule "null means unknown, not false" is preserved for everything we
genuinely cannot judge. The gold `label` is the only *annotated* axis; the rest
are content axes judged from the text, and these are ordinary instruction prompts
with no sensitive content, so they are asserted `false`. `null` is reserved for
image sources whose visual axes have not been inspected — not used here.

| Label | Value | `label_source` | Reason |
|---|---|---|---|
| `prompt_injection` | `bool(label)` | `source_gold` | gold row-level flag |
| `action` | `reject` if attack else `safe` | `source_assumption` | composed from the gold flag; no other risk axis present |
| `pii_visible` | `false` | `source_assumption` | hand-authored prompts with no personal data |
| `sexual` | `false` | `source_assumption` | ordinary prompts, no sexual content |
| `violence` | `false` | `source_assumption` | ordinary prompts, no violent content |
| `blood_gore` | `false` | `source_assumption` | ordinary prompts, no gore content |
| `political` | `false` | `source_assumption` | no topic content |
| `religious` | `false` | `source_assumption` | no topic content |

`derive_label_mask` therefore supervises every head on these rows (mask = 1
across the board); nothing is masked out, because the content is known on all
axes. In the Annotate tab these rows show the blue `source` provenance chip until
a human reviews them.

## Run

```bash
# No token or network required (local seed files).
python scripts/safety_v0/convert/convert_local_vi_prompt_injection.py
python scripts/safety_v0/validate_safety_v0.py \
  data/safety_v0/converted/local_vi_prompt_injection/source_canonical.jsonl
# One sub-source / a row cap:
python scripts/safety_v0/convert/convert_local_vi_prompt_injection.py \
  --sources vietnamese_seed --limit 20
```

Converter logic is unit-tested without any download in
`tests/test_convert_local_vi_prompt_injection.py`.
