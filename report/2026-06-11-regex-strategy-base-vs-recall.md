# Regex Strategy: Base (Precision) vs Recall-Optimized

Date: 2026-06-11

This report compares the two deterministic regex strategies in the Vietnamese
PII pipeline: the **base / precision** strategy (`regex_only`) and the
**recall-optimized** strategy (`regex_recall`). It explains the idea behind
each, the measured trade-off, and which one to use for which job. A third,
corpus-tuned extension (`regex_recall_vie_pii`) is covered briefly because it is
the same recall idea pushed one step further.

Both strategies are implemented in a single recognizer
(`src/pipeline/Recognizers/CustomPatternRecognizer.py`) and selected by a flag:

| Pipeline | Constructor | Pattern set |
|---|---|---|
| `regex_only` | `CustomPatternRecognizer()` | core patterns only |
| `regex_recall` | `CustomPatternRecognizer(recall_mode=True)` | core + `build_recall_patterns()` |
| `regex_recall_vie_pii` | `CustomPatternRecognizer(recall_mode=True, vie_pii_mode=True)` | core + recall + `build_vie_pii_patterns()` |

So the strategies are strictly additive: recall mode does not change the base
patterns, it only **adds** broader ones on top.

---

## 1. The Base Strategy (`regex_only`)

### Idea

Match PII only when the surrounding text leaves almost no doubt. Every pattern
is *context-anchored*: it requires an explicit Vietnamese label or trigger word
right next to the value, and it captures only the value via a named group
(`(?P<value>...)`), never the label. The recognizer drops empty spans, so a
label with no following value produces nothing.

Concrete tactics used to keep precision high:

- **Label-anchored values.** A bank account only matches after
  `số tài khoản`, `stk`, `a/c no`, etc. A tax ID only after `mã số thuế`. A
  birth year only after `năm sinh`. Bare numbers are never grabbed.
- **Tight value shapes.** CCCD is exactly `\d{12}|\d{9}`; VN mobile is
  `(?:\+?84|0)` + a `[35789]` head + 8 digits, with `(?<!\d)`/`(?!\d)` guards so
  it cannot bite into a longer number.
- **Boundary lookaheads for free-text entities.** Names, locations, and
  organizations stop at the next field label (`(?=\s+(?:Mã|Ngày|Số|Địa|...))`)
  or punctuation, so a `PERSON` span does not swallow the rest of the line.
- **Negative lookarounds to exclude near-misses.** e.g. the district pattern has
  `(?<!Công an )` so "Công an Quận X" (an organization) is not read as a
  location; `ngày` date contexts exclude `ngày cấp` (issue date).
- **High per-pattern scores (0.7–0.95).** These spans are trusted.

### Profile

High precision, lower recall. It fires confidently on the obvious, labeled
cases and stays silent on everything ambiguous — unlabeled names, free-narrative
mentions, organization names without a trigger word.

### Measured results (`pii_masking_95k`)

| Split | Precision | Recall | F1 |
|---|---:|---:|---:|
| train_val | 0.9815 | 0.6992 | 0.8166 |
| validation | 0.9834 | 0.6894 | 0.8105 |

The pattern is clear: ~98% precision, but recall stuck near 0.69 — roughly a
third of true PII is missed because it appears without the strict label/shape
the base patterns demand.

---

## 2. The Recall-Optimized Strategy (`regex_recall`)

### Idea

Keep every base pattern as-is, then layer on **looser sibling patterns** that
accept the same entity types in more phrasings — at a lower confidence score.
The design rule is: *broaden the trigger and the value shape, but never remove
the anchor entirely.* The recall patterns live in `build_recall_patterns()` and
are only appended when `recall_mode=True`.

How the recall patterns relax each base pattern:

- **More trigger phrases.** `recall_person_labeled_roles` adds `Người phụ
  trách`, `Bác sĩ kê đơn`, `Cash receiver`, `Delivered by`, `Signature & full
  name`, etc. — roles the base `PERSON` rule never covered.
- **Looser value shapes.** `recall_employee_id` accepts `XXX-EMP-1234`,
  `2024-12345`, ampersand-prefixed codes; `recall_transaction_id` allows longer
  mixed alphanumerics; `recall_document_number` covers `CMND/CCCD Số`,
  `Số GTTT`, passport-number phrasings the base ID rules skip.
- **Wider context windows.** `recall_date_labeled` matches `ngày <up to 45
  chars> : dd/mm/yyyy` instead of requiring a fixed sub-label, while still
  excluding `ngày cấp`/`hết hạn`.
- **New sub-entities.** `recall_country_labeled`, `recall_country_after_address`,
  `recall_special_ward` (`Đặc khu …`), `recall_business_tax_id`
  (`mã số doanh nghiệp`), linked-account variants in `recall_bank_account`.
- **Lower scores (0.58–0.70).** These spans are weaker evidence and score below
  the base ones, which keeps a downstream verifier/threshold able to tell strong
  from speculative hits.

The key engineering discipline: recall patterns are *additive and isolated*. A
risky pattern can be added or removed without touching the high-precision core,
so a recall experiment can never silently degrade the base behaviour.

### Profile

Strong recall gain for a small precision cost. It still anchors on labels — it
does not guess at bare names in free prose — so precision stays high.

### Measured results (`pii_masking_95k`)

| Split / sample | Precision | Recall | F1 |
|---|---:|---:|---:|
| validation (500 sample) | 0.9658 | 0.8420 | 0.8996 |
| validation (full, 9,512) | 0.9854 | 0.8317 | 0.9021 |

Versus the base `regex_only` on the same data: recall jumps from **~0.69 to
~0.83** (about +14 points), F1 from **~0.81 to ~0.90** (about +9 points), with
precision essentially unchanged (~0.98 on the full validation split). This is
the headline result — the recall patterns recovered a large share of the misses
almost for free.

---

## 3. The Corpus-Tuned Extension (`regex_recall_vie_pii`)

`regex_recall_vie_pii` = recall mode **plus** `build_vie_pii_patterns()`, a set
of broad patterns written specifically for the `HoangHa/vie-pii` corpus (labeled
company names, biometric/medical/license ID contexts, international phone/fax,
markdown-`**Tên**`-style labels).

It exists as a *separate* pipeline on purpose. The same patterns, if merged into
`regex_recall`, helped HoangHa but hurt the main dataset:

| Pipeline | Dataset | Precision | Recall | F1 |
|---|---|---:|---:|---:|
| `regex_recall` | HoangHa test | 0.9240 | 0.1865 | 0.3104 |
| `regex_recall_vie_pii` | HoangHa test | 0.9334 | 0.3422 | 0.5008 |
| `regex_recall` | pii_masking_95k val | 0.9854 | 0.8317 | 0.9021 |
| `regex_recall_vie_pii` | pii_masking_95k val | 0.9285 | 0.8448 | 0.8847 |

On HoangHa it nearly doubles recall (+0.16 F1). On the original dataset it
*lowers* F1 (precision drops from 0.985 to 0.929 from `ORGANIZATION`/`ID`/
`DATE_TIME` over-matching). The lesson: corpus-specific recall rules should stay
opt-in, not in the default.

---

## 4. Which Is Better?

There is no single winner; the strategies sit on a precision/recall curve and
the right pick depends on the cost of a miss versus the cost of a false hit.

| If you care most about… | Use | Why |
|---|---|---|
| Not leaking PII (recall) | `regex_recall` | +14 pts recall over base, precision barely moves |
| Zero false positives, max speed | `regex_only` | ~0.98 precision, smallest pattern set |
| Best overall F1, fast, explainable | `regex_recall` | Highest deterministic F1 (~0.90), current default |
| The HoangHa/vie-pii corpus specifically | `regex_recall_vie_pii` | Recall there nearly doubles |

**Overall recommendation (matches the PII checkpoint):** `regex_recall` is the
default. It dominates `regex_only` on F1 and recall at negligible precision
cost, while keeping the things that make regex attractive — fast, deterministic,
explainable, no model dependency. `regex_only` is not deprecated: it is the
precision anchor and the regression baseline that recall mode is measured
against.

---

## 5. Use-Case Guidance

**Pick `regex_only` when:**

- A false positive is expensive (e.g. auto-redacting content where over-masking
  breaks meaning, or a hard block/alert with no human review).
- You need the tightest, most auditable rule set to explain *why* each span
  matched.
- You are establishing a precision ceiling / regression baseline to evaluate new
  recall patterns against.

**Pick `regex_recall` when:** (the default for demo and routine reporting)

- A miss is worse than a false alarm — anonymization, compliance scanning, any
  guardrail where leaked PII is the real risk.
- You want the best deterministic F1 without paying for an NER model or LLM.
- You feed spans into a downstream verifier or score threshold that can use the
  lower recall-pattern scores to triage strong vs speculative hits.

**Pick `regex_recall_vie_pii` when:**

- You are running on the `HoangHa/vie-pii` corpus (or similarly
  labeled/markdown-structured documents) and accept extra false positives for a
  large recall gain.
- Do **not** use it as the general default — it lowers precision on
  `pii_masking_95k`.

**When even `regex_recall` is not enough:** for hard PERSON recall (bare names in
free narrative, which no label-anchored regex catches), step up to the
Underthesea variants (`underthesea_regex_recall` /
`underthesea_regex_recall_resolved`). They add a few recall points on PERSON but
are much slower and carry PERSON false-positive risk — experimental, not the
default.

---

## 6. Summary

- The base strategy trusts only **labeled, tightly-shaped** values → high
  precision, ~0.69 recall.
- The recall strategy **adds looser, lower-scored siblings** on top of the base,
  never replacing it → ~0.83 recall at the same precision, best deterministic
  F1 (~0.90).
- Recall rules are kept **additive and isolated** so they cannot silently
  regress the precision core; corpus-specific recall (`regex_recall_vie_pii`)
  stays a separate opt-in pipeline for exactly that reason.
- Default to `regex_recall`; keep `regex_only` as the precision/regression
  anchor; reserve `regex_recall_vie_pii` for the HoangHa corpus.
