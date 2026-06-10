# Vietnamese PII Checkpoint

This document packages the current PII work into a mentor-review checkpoint.
It is meant to answer: what we detect, what data we evaluate on, how we measure
quality, what methods were tried, and what should happen before moving to prompt
injection detection.

## Executive Summary

Current phase: Vietnamese PII detection and anonymization on top of Microsoft
Presidio.

Current recommendation:

- Use `regex_recall` as the best default candidate right now. It is fast,
  deterministic, high precision, and has strong validation F1.
- Keep `underthesea_regex_recall` and `underthesea_regex_recall_resolved` as
  experimental higher-recall variants, mainly for improving `PERSON` recall.
- Do not move to prompt injection detection until this PII checkpoint has been
  reviewed and accepted.

The current work is useful enough to demo, but it is not production-ready. The
main remaining risks are taxonomy mismatch, synthetic-data bias, PERSON and
ORGANIZATION boundary errors, and lack of broad Vietnam-specific validation
rules for some identifiers.

## Current Flow

```text
Vietnamese text
  -> Presidio AnalyzerEngine
      -> registered recognizers
          -> regex recognizers
          -> optional Underthesea NER recognizer
          -> later spaCy / HF / ensemble recognizers
      -> Presidio overlap resolution
      -> candidate PII spans
  -> optional deterministic resolver
      -> drop repeated false-positive patterns
  -> optional LLMVerifier
      -> keep / drop / relabel each candidate
  -> final RecognizerResult spans
  -> optional Presidio AnonymizerEngine
  -> prediction log + evaluation metrics
```

The system is Vietnamese-only by default. English support is out of scope unless
explicitly requested.

## Vietnamese PII Scope

The current evaluator targets these Presidio entity types:

| Presidio type | Current meaning in this project | Vietnam-specific examples |
|---|---|---|
| `PERSON` | Person names and name parts | Ho ten, ho, ten, ten dem |
| `LOCATION` | Address components and country/province/district/ward/street fields | Tinh/thanh pho, quan/huyen, phuong/xa, duong pho, so nha |
| `ORGANIZATION` | Organization or bank names | Cong ty, ngan hang, benh vien, truong hoc |
| `PHONE_NUMBER` | Vietnamese phone numbers | Mobile/landline-like phone strings with context |
| `EMAIL_ADDRESS` | Email addresses | Email field values |
| `BANK_ACCOUNT` | Bank account numbers | So tai khoan, STK context |
| `ID` | Personal, employee, transaction, tax, passport-like identifiers | CCCD/CMND, ho chieu, ma so thue, ma nhan vien, ma giao dich |
| `DATE_TIME` | Dates, years, months relevant to PII | Ngay sinh, ngay/thang/nam fields |
| `MISC` | Reserved catch-all | Not mapped in the current dataset |

Important mismatch: the dataset contains many more fine-grained labels than our
current target types. Examples such as payment cards, medical information,
credentials, IP/MAC addresses, vehicle identifiers, salary, demographics, and
education fields are annotated by the dataset but currently dropped from mapped
evaluation. This means the headline F1 only measures the selected 8 evaluable
types, not the full possible PII surface.

## Vietnam-Specific Research Items

These should be reviewed before a final seminar or production-style demo:

| Area | Current implementation status | Research question |
|---|---|---|
| CCCD/CMND | Regex/context support under `ID` | Confirm current 12-digit personal identification structure and whether any checksum exists or only structured digits/context. |
| Passport | Regex/context support under `ID` | Confirm valid Vietnamese passport formats and old/new variants. |
| Tax code | Regex/context support under `ID` | Confirm 10-digit and 13-digit formats, branch suffix behavior, and whether checksum validation is practical. |
| Bank account | Contextual regex under `BANK_ACCOUNT` | Bank account lengths and validation are bank-specific; avoid claiming universal checksum unless verified per bank. |
| Phone number | Regex/context support under `PHONE_NUMBER` | Confirm currently active Vietnam numbering ranges and landline/mobile edge cases. |
| Address | Regex/context support under `LOCATION` | Continue expanding province/district/ward context, but avoid overmatching form labels. |
| Health/medical data | Mostly unmapped | Decide whether to add medical-specific entity types later, because health data can be sensitive PII. |
| Credentials/digital identifiers | Mostly unmapped | Decide whether to add password, OTP, API key, IP, MAC, URL, wallet address, and device identifiers. |

Practical interpretation: checksum and strict validation should be added only
where the identifier has stable public rules. Otherwise, context-aware detection
is safer than hardcoding weak validation logic.

## Dataset

Default dataset: `pii_masking_95k`

- Hugging Face repo: `nguyenlamtung/pii-masking-95k-preencoded`
- Access: private, requires `HF_TOKEN`
- Language: Vietnamese (`vi`), Vietnam region (`VN`), Latin script (`Latn`)
- Nature: synthetic documents covering banking, healthcare, HR, government, and
  identity-like forms

Size:

| Split | Rows |
|---|---:|
| train | 76,097 |
| validation | 9,512 |
| test | 9,513 |
| total | 95,122 |

Routine iteration should use `train_val`, a deterministic 10 percent holdout
derived from train with `random_state=42`. The official `test` split should stay
reserved for final reporting.

Ground truth lives in `privacy_mask`, a list of character spans:

```json
{"start": 121, "end": 131, "value": "7204684910", "label": "SO_TAI_KHOAN", "label_index": 1}
```

Full dataset details are documented in `docs/datasets/pii-masking-95k.md`.

## Metrics

The evaluator compares predicted Presidio spans against mapped ground-truth
spans.

| Metric | Meaning | PII interpretation |
|---|---|---|
| Precision | Of predicted PII spans, how many were correct | Low precision means unnecessary masking or false alarms |
| Recall | Of true PII spans, how many were found | Low recall means leaked PII |
| F1 | Harmonic mean of precision and recall | Single summary for comparing variants |

For PII, the tradeoff is use-case dependent:

- For anonymization before sharing logs or documents, recall is usually more
  important because missed PII is a privacy leak.
- For user-facing review tools, precision also matters because too many false
  positives reduce trust and usability.
- For this checkpoint, `regex_recall` is recommended as the default because it
  balances quality, speed, and explainability.

Per-entity metrics matter more than only overall F1. Current weak areas are
mainly `PERSON` and `ORGANIZATION`.

## Method Summary

| Method | Registry key | Role | Strength | Weakness |
|---|---|---|---|---|
| Presidio shell | `baseline_presidio` | Minimal Vietnamese analyzer shell | Establishes infrastructure | Not enough Vietnamese coverage alone |
| Precision regex | `regex_only` | Context-aware deterministic baseline | Very high precision, fast | Lower recall |
| Recall regex | `regex_recall` | Broader deterministic regex mode | Strong validation F1, fast, explainable | Still weak on some names/orgs |
| Underthesea NER only | `underthesea_ner` | Vietnamese NER experiment | Finds some names regex misses | Too noisy alone |
| Regex + Underthesea | `underthesea_regex` | Precision regex plus filtered PERSON NER | Better PERSON recall | Slower and adds false positives |
| Recall regex + Underthesea | `underthesea_regex_recall` | High-recall combined candidate | Best full-validation F1 so far after cleanup | Much slower; PERSON FP risk |
| Resolver variant | `underthesea_regex_recall_resolved` | Adds deterministic post-analysis resolver | Directionally reduces some Underthesea PERSON FPs | Small effect so far; needs decision logging |
| LLM verifier | CLI `--verify` | Optional adjudication pass | Can keep/drop/relabel candidates | Paid calls; must be sampled sparingly |

## Current Results

Full validation comparison before the resolver experiment:

| Pipeline | Precision | Recall | F1 | Notes |
|---|---:|---:|---:|---|
| `regex_recall` | 0.9658 | 0.8420 | 0.8996 | Fast default candidate |
| `underthesea_regex_recall` before cleanup | 0.9481 | 0.8817 | 0.9137 | Higher recall, many PERSON FPs |
| `underthesea_regex_recall` after cleanup | 0.9659 | 0.8714 | 0.9162 | Better precision/F1, slower |

Resolver A/B on smaller slices:

| Split/sample | Pipeline | Precision | Recall | F1 | TP | FP | FN |
|---|---|---:|---:|---:|---:|---:|---:|
| validation 500 | `underthesea_regex_recall` | 0.9679 | 0.8839 | 0.9240 | 1,812 | 60 | 238 |
| validation 500 | `underthesea_regex_recall_resolved` | 0.9690 | 0.8834 | 0.9242 | 1,811 | 58 | 239 |
| train_val 500 | `underthesea_regex_recall` | 0.9648 | 0.8993 | 0.9309 | 2,000 | 73 | 224 |
| train_val 500 | `underthesea_regex_recall_resolved` | 0.9667 | 0.8993 | 0.9317 | 2,000 | 69 | 224 |

Interpretation:

- `regex_recall` is still the best default because it is fast, stable, and
  explainable.
- Underthesea improves PERSON recall, but the runtime and false-positive tradeoff
  are significant.
- The resolver is worth keeping for further experiments, but it is not strong
  enough yet to promote as the default.

## Current TODO Before Prompt Injection

Required before moving on:

1. Review this checkpoint with mentor.
2. Confirm whether the current entity taxonomy is enough for the PII milestone.
3. Confirm whether the synthetic dataset is acceptable for current evaluation.
4. Decide whether the demo should prioritize `regex_recall` or the slower
   Underthesea variant.
5. Keep the official `test` split for final reporting only.

Useful engineering follow-ups:

1. Add resolver decision logging so dropped candidates are auditable.
2. Add or document validated Vietnam-specific checksum/format rules where
   reliable public rules exist.
3. Mine remaining `PERSON` and `ORGANIZATION` errors on targeted validation
   samples.
4. Run LLM verifier only on small targeted samples when it answers a specific
   question.
5. Prepare a short demo script showing detection, anonymization, JSONL logging,
   and evaluation metrics.

Move to prompt injection detection after the PII checkpoint is accepted or after
the user explicitly reprioritizes.

## Suggested Mentor Questions

Use these to confirm direction one by one:

1. Is this Vietnamese PII entity set sufficient for the first PII milestone?
2. Is the current synthetic dataset acceptable for reporting progress?
3. Should the demo optimize for speed/precision (`regex_recall`) or higher recall
   with slower runtime (`underthesea_regex_recall`)?
4. Should we add more Vietnam-specific identifier validation before moving on?
5. After this checkpoint, can we start the prompt injection detection pipeline?

