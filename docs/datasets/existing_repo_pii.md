# existing_repo_pii (safety_v0 source)

First `safety_v0` source (see `DATA_PLAN.md`). It is not a new `BaseDataset`; it
reuses the repo's existing Vietnamese PII datasets and converts their rows into
the canonical `safety_v0` schema (`src/pipeline/Datasets/safety_v0_schema.py`).

- Slug: `existing_repo_pii`
- Underlying datasets (via the dataset registry): `pii_masking_95k`,
  `hoangha_vie_pii`
- Converter: `scripts/safety_v0/convert/convert_existing_repo_pii.py`
- Output: `data/safety_v0/converted/existing_repo_pii/source_canonical.jsonl`

## Why straight-convert

These are PII-only Vietnamese text corpora: no prompt injection, no
sensitive-topic content. So they are converted directly with no LLM verifier and
no weak-label review pass. The gold PII spans are authoritative, so they are
written as `detections.pii_spans` and used to anonymize the text deterministically.

## Source → canonical mapping

| Source field | Canonical field |
|---|---|
| `source_text` | `content.input_text` |
| `privacy_mask[*]` (start/end/label) | `detections.pii_spans[*]` after `label_to_presidio` |
| dataset `name` | `source.name` |
| dataset `input_id` | `source.source_sample_id` |
| row `split` | `source.split` |

- Each dataset's own `label_to_presidio` is used. PII-masking-95k now maps every
  personal-data label to one of **21 target types** (8 original + 13 added);
  only 6 genuinely non-identifying tokens are dropped (~1.8% of spans, down from
  46.5%), so `sanitized_text` is genuinely PII-free and `pii_visible: False` is
  honest. HoangHa maps all 7 of its labels. See
  `docs/datasets/pii-masking-95k.md` for the full mapping and the dropped set.
- `pii_spans[*].detector = "source_gold"`, `score = 1.0`, span `text` sliced
  from `input_text` so offsets stay authoritative.
- `content.sanitized_text` replaces each PII span with `<ENTITY_TYPE>`
  (deterministic anonymization from gold spans, not a detector pass).
- These rows are text-only: `modality.has_text = true`, `has_image = false`,
  `has_ocr = false`. No OCR boxes or redaction metadata.

## Label policy (`pii_only_text_labels`)

The DATA_PLAN rule "null means unknown, not false" is preserved for everything we
genuinely cannot judge. These are ordinary Vietnamese PII texts, so every content
risk axis is known to be absent and asserted `false`. `null` is reserved for
image sources whose visual axes have not been inspected — not used here.

| Label | Value | `label_source` | Reason |
|---|---|---|---|
| `action` | `safe` | `source_assumption` | PII removed, no other risk present |
| `pii_visible` | `false` | `source_gold` | gold PII is anonymized in `sanitized_text` |
| `prompt_injection` | `false` | `source_assumption` | corpus has no injection |
| `sexual` | `false` | `source_assumption` | ordinary text, no sexual content |
| `violence` | `false` | `source_assumption` | ordinary text, no violent content |
| `blood_gore` | `false` | `source_assumption` | ordinary text, no gore content |
| `political` | `false` | `source_assumption` | corpus has no topic content |
| `religious` | `false` | `source_assumption` | corpus has no topic content |

`derive_label_mask` therefore supervises every head on these rows (mask = 1
across the board); nothing is masked out, because the content is known on all
axes.

## Entity-type coverage

Driven by each dataset's `label_to_presidio` (see
`docs/datasets/pii-masking-95k.md` and `docs/datasets/hoangha-vie-pii.md`). With
the expanded 21-type taxonomy, almost all gold PII now maps and is redacted;
only genuinely non-identifying tokens (currency type, exchange rate, language,
timezone, airport/station codes — `VI_PII_DROPPED_LABELS`) are dropped from
`pii_spans`. Note that the detection recognizers still emit only the original 8
types, so detection recall on the 13 new types is 0 until detectors are added;
this does not affect these converted gold spans.

## Run

```bash
# Gated sources need HF_TOKEN in the environment / .env.
python scripts/safety_v0/convert/convert_existing_repo_pii.py --limit 500
python scripts/safety_v0/validate_safety_v0.py \
  data/safety_v0/converted/existing_repo_pii/source_canonical.jsonl
```

Converter logic is unit-tested without any download in
`tests/test_convert_existing_repo_pii.py`.
