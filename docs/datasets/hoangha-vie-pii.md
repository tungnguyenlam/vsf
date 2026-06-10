# Dataset: `hoangha_vie_pii`

Vietnamese PII dataset hosted on Hugging Face as `HoangHa/vie-pii`.

- **Registry key:** `hoangha_vie_pii`
- **HF repo:** `HoangHa/vie-pii` (gated; requires an accepted Hugging Face account/token)
- **Rows:** 10,000
- **Source splits:** only `train`
- **Language:** mostly Vietnamese translated text, with some English source/domain text and
  technical terms preserved

## Split Handling

The source dataset only has one `train` split, so the loader creates deterministic
local partitions from it:

| Split | Meaning | Size |
|---|---|---:|
| `train_main` | routine tuning pool | 80% |
| `train_val` / `validation` | deterministic dev split | 10% |
| `test` | deterministic held-out split | 10% |
| `train` | full original source split | 100% |

All partitions use `random_state=42` by default.

## Columns

Original columns:

| Column | Meaning |
|---|---|
| `input` | Prompt/source text with original inline labels, often English or mixed-language |
| `output` | Vietnamese translated text with inline `[value]<label>` annotations |
| `total_tokens` | Token-count metadata from the source |
| `text` | JSON string summarizing labels and values |

Normalized columns added by our loader:

| Column | Meaning |
|---|---|
| `source_text` | Clean text after removing inline label markup from `output` |
| `privacy_mask` | Character spans reconstructed from `[value]<label>` annotations |
| `split` | Requested normalized split |
| `input_id` | Stable id: `hoangha_vie_pii:<split>:<source_index>` |
| `inline_label_count` | Count of inline annotations found in `output` |

## Span Format

The source marks spans like:

```text
[Nguyễn Văn An]<human_name>
```

The loader converts this to:

```json
{"start": 0, "end": 13, "value": "Nguyễn Văn An", "label": "human_name"}
```

Offsets are character offsets into normalized `source_text`, not the original
marked-up `output`.

## Label Taxonomy & Mapping

Observed native labels:

| Native label | Presidio type | Notes |
|---|---|---|
| `human_name` | `PERSON` | Can include partial names or occasional noisy role text |
| `address` | `LOCATION` | Broad; can include coordinates, URLs, countries, cities, and addresses |
| `company_name` | `ORGANIZATION` | Company/organization names |
| `phone_number` | `PHONE_NUMBER` | Includes Vietnamese and international-looking numbers |
| `email_address` | `EMAIL_ADDRESS` | Email addresses |
| `id_number` | `ID` | Broad; includes employee/license/document ids and some noisy non-id values |
| `date` | `DATE_TIME` | Dates and times |

This dataset does **not** have a separate `BANK_ACCOUNT` label in the observed
taxonomy. Therefore `BANK_ACCOUNT` predictions count as false positives unless
they overlap a mapped label of another type, which usually means they will hurt
mapped evaluation.

## Mismatch vs Current Pipeline

This corpus is useful as a second benchmark because it is different from
`pii_masking_95k`, but the label taxonomy is noisy and broader in places:

- `address` can label URLs and coordinates, not only postal addresses.
- `id_number` can label education-level text in some rows.
- `phone_number` includes non-Vietnamese phone formats.
- Several rows contain English or mixed-language content after translation.

These mismatches mean metrics on this dataset should be interpreted as
cross-dataset robustness, not a pure Vietnamese production estimate.

## Usage

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_pipeline.py \
  --dataset hoangha_vie_pii \
  --pipeline regex_recall \
  --split train_val \
  --limit 50
```

