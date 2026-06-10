# PII Checkpoint Summary

This is the short presentation summary for the current Vietnamese PII milestone.
The detailed checkpoint is in `docs/pii-checkpoint.md`; Vietnam-specific
research notes are in `docs/vietnamese-pii-research.md`.

## Goal

Build a Vietnamese-only PII detection and anonymization pipeline on top of
Microsoft Presidio.

Current flow:

```text
Vietnamese text
  -> Presidio AnalyzerEngine
  -> Vietnamese recognizers
  -> optional deterministic resolver
  -> optional LLM verifier
  -> final PII spans
  -> Presidio anonymizer
  -> JSONL prediction log and evaluation metrics
```

## Current Entity Scope

The current mapped evaluation targets:

| Entity | Examples |
|---|---|
| `PERSON` | Ho ten, ho, ten |
| `LOCATION` | Tinh, thanh pho, quan, huyen, phuong, xa, duong, so nha |
| `ORGANIZATION` | Cong ty, ngan hang, benh vien, truong hoc |
| `PHONE_NUMBER` | Vietnamese-like phone numbers |
| `EMAIL_ADDRESS` | Email addresses |
| `BANK_ACCOUNT` | So tai khoan, STK |
| `ID` | CCCD/CMND, passport, tax code, employee ID, transaction ID |
| `DATE_TIME` | Ngay sinh, thang sinh, nam sinh, selected date contexts |

The dataset has more labels than this scope. Payment cards, medical information,
credentials, IP/device identifiers, vehicle identifiers, salary, demographics,
and several other labels are currently documented as out of scope for mapped
evaluation.

## Dataset

Default dataset: `pii_masking_95k`

| Split | Rows |
|---|---:|
| train | 76,097 |
| validation | 9,512 |
| test | 9,513 |
| total | 95,122 |

The routine iteration split is `train_val`, a deterministic 10 percent holdout
from train. The official `test` split should stay reserved for final reporting.

## Methods Tried

| Method | Registry key | Summary |
|---|---|---|
| Precision regex | `regex_only` | High-precision deterministic regex baseline |
| Recall regex | `regex_recall` | Broader context-aware regex mode |
| Underthesea NER | `underthesea_ner` | NER-only experiment, too noisy alone |
| Regex + Underthesea | `underthesea_regex` | Regex plus filtered Underthesea PERSON spans |
| Recall regex + Underthesea | `underthesea_regex_recall` | Higher recall, slower, more PERSON false positives |
| Resolver variant | `underthesea_regex_recall_resolved` | Adds deterministic post-analysis false-positive suppression |
| LLM verifier | `--verify` | Optional paid adjudication pass for sampled experiments |

## Current Results

Full validation:

| Pipeline | Precision | Recall | F1 | Interpretation |
|---|---:|---:|---:|---|
| `regex_recall` | 0.9658 | 0.8420 | 0.8996 | Fast default candidate |
| `underthesea_regex_recall` before cleanup | 0.9481 | 0.8817 | 0.9137 | Higher recall, many PERSON false positives |
| `underthesea_regex_recall` after cleanup | 0.9659 | 0.8714 | 0.9162 | Best full-validation F1 so far, but slow |

Small-sample resolver A/B:

| Split/sample | Pipeline | Precision | Recall | F1 |
|---|---|---:|---:|---:|
| validation 500 | `underthesea_regex_recall` | 0.9679 | 0.8839 | 0.9240 |
| validation 500 | `underthesea_regex_recall_resolved` | 0.9690 | 0.8834 | 0.9242 |
| train_val 500 | `underthesea_regex_recall` | 0.9648 | 0.8993 | 0.9309 |
| train_val 500 | `underthesea_regex_recall_resolved` | 0.9667 | 0.8993 | 0.9317 |

## Recommendation

Use `regex_recall` as the current default for demo and routine reporting:

- fast,
- deterministic,
- explainable,
- high precision,
- no heavy model dependency.

Keep `underthesea_regex_recall` and `underthesea_regex_recall_resolved` as
experimental higher-recall candidates. They are useful for showing the PERSON
recall tradeoff, but should not replace the regex default yet.

## Demo Commands

Run a local detection/anonymization demo:

```bash
PYTHONPATH=. .venv/bin/python scripts/demo_pii_checkpoint.py
```

Run a small evaluation sample:

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_pipeline.py --pipeline regex_recall --split train_val --limit 50
```

Run the experimental resolver variant on a small sample:

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_pipeline.py --pipeline underthesea_regex_recall_resolved --split train_val --limit 50
```

## Open Project Questions

These are project decisions and research items, not mentor-only questions:

1. Whether to keep the current 8 evaluable entity types or expand into payment
   cards, credentials, medical data, digital identifiers, and vehicle IDs.
2. Which Vietnam-specific identifiers have stable official validation rules that
   are worth implementing as checksum/format helpers.
3. Whether the demo should prioritize speed and precision (`regex_recall`) or
   higher recall with slower runtime (`underthesea_regex_recall`).
4. Whether the next technical milestone should be resolver decision logging or
   the first prompt-injection detection prototype.

## Next Step

Use this summary for the PII checkpoint discussion. After the checkpoint is
accepted, move to prompt injection detection. If PII work continues first, the
highest-value engineering task is resolver decision logging.
