# HoangHa vie-pii Cross-Dataset Evaluation

Date: 2026-06-11

## Goal

Add `HoangHa/vie-pii` as a second PII benchmark, split it deterministically
because the source only has one `train` split, tune on the dev split, and report
metrics on both:

- original `pii_masking_95k`,
- new `hoangha_vie_pii`.

## Dataset Integration

`HoangHa/vie-pii` is a gated Hugging Face dataset with 10,000 rows and one source
split, `train`.

Observed columns:

| column | meaning |
|---|---|
| `input` | source/prompt text with original inline labels |
| `output` | Vietnamese translated text with `[value]<label>` annotations |
| `total_tokens` | source token metadata |
| `text` | JSON string summarizing label values |

The loader reconstructs:

- `source_text`: `output` with inline markup removed,
- `privacy_mask`: character spans from `[value]<label>`,
- `input_id`: stable row id,
- deterministic local splits.

Local split policy:

| split | rows |
|---|---:|
| `train_main` | 8,000 |
| `train_val` / `validation` | 1,000 |
| `test` | 1,000 |

All splits use `random_state=42`.

## Label Mapping

| HoangHa label | Presidio type |
|---|---|
| `human_name` | `PERSON` |
| `address` | `LOCATION` |
| `company_name` | `ORGANIZATION` |
| `phone_number` | `PHONE_NUMBER` |
| `email_address` | `EMAIL_ADDRESS` |
| `id_number` | `ID` |
| `date` | `DATE_TIME` |

Important mismatch: this dataset is noisier than `pii_masking_95k`. For example,
`address` can include URLs, coordinates, countries, and cities; `id_number` can
include broad document/license-like values and occasional non-ID text. Treat
metrics as cross-dataset robustness, not as a clean Vietnamese production
estimate.

## Tuning

Baseline pipeline:

- `regex_recall`

New opt-in tuned pipeline:

- `regex_recall_vie_pii`

The tuned variant adds broad HoangHa-specific recall patterns for:

- labeled company names,
- company/organization trigger words,
- medical/customer/biometric/license/id contexts,
- date/time contexts,
- international phone/fax contexts,
- some labeled person contexts.

These rules are intentionally isolated in a separate pipeline because applying
them directly to `regex_recall` reduced precision on the original dataset.

## HoangHa Dev Metrics

Split: `hoangha_vie_pii` `train_val`, 1,000 rows.

| pipeline | precision | recall | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| `regex_recall` | 0.9449 | 0.1596 | 0.2731 | 1,320 | 77 | 6,949 |
| `regex_recall_vie_pii` | 0.9477 | 0.2848 | 0.4380 | 2,355 | 130 | 5,914 |

The tuned rules improved dev F1 by about 0.165 while keeping precision roughly
flat.

## Held-Out Test Metrics

Split: `hoangha_vie_pii` `test`, 1,000 rows.

| pipeline | precision | recall | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| `regex_recall` | 0.9240 | 0.1865 | 0.3104 | 1,337 | 110 | 5,831 |
| `regex_recall_vie_pii` | 0.9334 | 0.3422 | 0.5008 | 2,453 | 175 | 4,715 |

Per-entity held-out test metrics for `regex_recall_vie_pii`:

| entity | precision | recall | F1 |
|---|---:|---:|---:|
| `EMAIL_ADDRESS` | 0.9883 | 0.9768 | 0.9825 |
| `DATE_TIME` | 0.9791 | 0.4440 | 0.6109 |
| `ORGANIZATION` | 0.9013 | 0.4169 | 0.5701 |
| `PHONE_NUMBER` | 0.9750 | 0.3814 | 0.5483 |
| `ID` | 0.9754 | 0.2693 | 0.4221 |
| `LOCATION` | 0.6508 | 0.2169 | 0.3254 |
| `PERSON` | 0.9189 | 0.0333 | 0.0642 |

Remaining weaknesses are `PERSON` and broad/noisy `LOCATION`.

## Original Dataset Regression Check

Split: `pii_masking_95k` official `validation`, 9,512 rows.

| pipeline | precision | recall | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| `regex_recall` | 0.9854 | 0.8317 | 0.9021 | 35,709 | 528 | 7,225 |
| `regex_recall_vie_pii` | 0.9285 | 0.8448 | 0.8847 | 36,270 | 2,792 | 6,664 |

The tuned variant improves recall but causes too many false positives on the
original dataset, especially `ORGANIZATION`, `ID`, and `DATE_TIME`. Therefore it
should not replace `regex_recall`.

## Recommendation

Keep both:

- `regex_recall`: current default for `pii_masking_95k` and general demo use.
- `regex_recall_vie_pii`: opt-in tuned baseline for `HoangHa/vie-pii`.

Do not merge HoangHa-specific broad rules into the default regex pipeline.

## Commands

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_pipeline.py \
  --dataset hoangha_vie_pii \
  --pipeline regex_recall_vie_pii \
  --split test \
  --no-log \
  --per-label
```

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_pipeline.py \
  --dataset pii_masking_95k \
  --pipeline regex_recall \
  --split validation \
  --no-log
```

