# Regex and Underthesea Session Report

Date: 2026-06-10

This report summarizes the work done in the session around per-entity metrics,
regex-only evaluation, recall-oriented regex rules, and the first Underthesea NER
integration. The goal was to understand whether deterministic rules are enough
for the Vietnamese PII pipeline, then test whether a lightweight Vietnamese NER
backend can improve the weak entities without exhausting local machine resources.

## Starting Point

The repository already had a Presidio-based Vietnamese PII pipeline with:

- `PIIEvaluator.evaluate_presidio(...)` for overall metrics.
- Optional per-entity metrics via `return_per_entity=True`.
- A `regex_only` pipeline using `CustomPatternRecognizer`.
- JSONL prediction logging through the pipeline wrapper.
- Dataset label mapping from the Vietnamese `pii-masking-95k` taxonomy to
  Presidio entity types.

The first check after pulling latest `master` confirmed that per-entity metrics
are emitted by the evaluator and by the CLI runner.

## Important Evaluation Discipline Change

Early in the session, a 50-row `test` sample was inspected for regex misses.
After that, we agreed to treat `test` as reserved again and avoid further
inspection/tuning against it.

To support that, we added deterministic train-derived inspection splits:

- `train_val`: 10% deterministic holdout from train, `random_state=42`.
- `train_main`: the remaining 90%.

This gives us a repeatable place to inspect errors without touching `test`.
Both the CLI loader and the dataset class loader now understand these split
names.

## Regex-Only Baseline

The first full-set regex-only check showed that `regex_only` was very
precision-heavy.

| split | rows | precision | recall | F1 |
|---|---:|---:|---:|---:|
| validation | 9,512 | 0.9834 | 0.6894 | 0.8105 |
| test | 9,513 | 0.9828 | 0.6984 | 0.8166 |

The broad pattern was stable across validation and test:

- Strong: `EMAIL_ADDRESS`, `PHONE_NUMBER`, `LOCATION`.
- Weak recall: `PERSON`, `ORGANIZATION`, `BANK_ACCOUNT`, `DATE_TIME`.

This confirmed that regex rules were reliable but incomplete.

## First Regex Fixes

On the small inspected sample, the dominant false negatives were:

- `PERSON`: split `HO` / `TEN` labels, honorific narrative names, missing labeled
  roles.
- `DATE_TIME`: many context variants like `Ngày sao kê`, `Ngày ghi nhận`,
  `Ngày/Date`, durations like `05 tháng`.
- `LOCATION`: `Thôn`, trailing country names, broader province lookaheads.
- `ORGANIZATION`: labels like `Tên cửa hàng`, `Tên đơn vị vận tải`, `Tại Ngân hàng / At Bank`.
- `ID`: transaction subtypes, hyphenated employee IDs, loose CCCD labels.
- `BANK_ACCOUNT`: bilingual `A/C No` patterns.

We added targeted high-precision regex support for those cases. This improved
the small sample substantially, but it also showed the limit of continuously
tuning `regex_only`: we were starting to encode many context phrases one by one.

## Recall-Oriented Regex Variant

Instead of weakening `regex_only`, we introduced a separate pipeline:

- `regex_recall`

This uses `CustomPatternRecognizer(recall_mode=True)` and leaves `regex_only`
as the precision baseline.

The recall mode adds broader but still context-aware patterns for:

- PERSON names under more labels and role contexts.
- broader date labels, years, and month durations.
- organization labels and some party/recipient labels.
- employee IDs, transaction IDs, business tax IDs, document numbers.
- bank account variants.
- country/address variants.

### Full Non-Test Comparison

| split | pipeline | precision | recall | F1 |
|---|---|---:|---:|---:|
| train_val | regex_only | 0.9815 | 0.6992 | 0.8166 |
| train_val | regex_recall | 0.9662 | 0.8503 | 0.9045 |
| validation | regex_only | 0.9834 | 0.6894 | 0.8105 |
| validation | regex_recall | 0.9658 | 0.8420 | 0.8996 |

This paid off well. The validation F1 improved by about 0.089 while precision
remained acceptable. The main downside was more `DATE_TIME` false positives
because broader date/year/month rules are inherently less precise.

### Validation Per Entity for `regex_recall`

| entity | precision | recall | F1 |
|---|---:|---:|---:|
| EMAIL_ADDRESS | 0.9988 | 1.0000 | 0.9994 |
| PHONE_NUMBER | 0.9517 | 1.0000 | 0.9753 |
| LOCATION | 0.9780 | 0.9681 | 0.9730 |
| ID | 0.9974 | 0.8961 | 0.9441 |
| DATE_TIME | 0.9033 | 0.9338 | 0.9183 |
| BANK_ACCOUNT | 0.9697 | 0.7952 | 0.8739 |
| ORGANIZATION | 0.9336 | 0.6853 | 0.7904 |
| PERSON | 0.9971 | 0.5402 | 0.7008 |

The remaining obvious weakness was `PERSON`: very high precision, but recall
only around 0.54.

## Why Try NER

At that point, continuing regex tuning had diminishing returns:

- `PERSON` and `ORGANIZATION` are inherently variable.
- Regex can catch labeled/contextual cases, but broad name matching risks many
  false positives.
- A Vietnamese NER backend might recover names in contexts that are hard to
  enumerate.

We chose Underthesea first because it was already installed and lightweight
relative to transformer models. The machine constraint was noted: Mac mini M4
with 16 GB RAM, while the repo may also be developed on a ThinkBook.

## Underthesea Integration

Added:

- `UndertheseaNER` wrapper implementing the existing `BaseNERWrapper` interface.
- `underthesea_ner`: raw Underthesea NER only.
- `underthesea_regex`: regex plus filtered Underthesea PERSON spans.
- `underthesea_regex_recall`: recall regex plus filtered Underthesea PERSON spans.

The wrapper integrates through the existing Presidio path:

1. Underthesea emits NER spans.
2. `DeepLearningRecognizer` converts them into Presidio `RecognizerResult`s.
3. The recognizer is registered in Presidio's analyzer registry.
4. The normal `AnalyzerEngine.analyze(...)` call performs aggregation/conflict
   resolution.
5. The evaluator sees final Presidio analyzer results.

So this is not an ad hoc post-processing path.

## Raw Underthesea Was Too Noisy

Raw Underthesea had very poor precision on PII evaluation:

| pipeline | sample | precision | recall | F1 |
|---|---:|---:|---:|---:|
| underthesea_ner | train_val 100 | 0.2536 | 0.3365 | 0.2892 |

Common false positives included:

- airport codes tagged as person,
- employee IDs and customer IDs tagged as person,
- address chunks tagged as person or location,
- drug names tagged as person,
- money/currency fragments tagged as location.

This made it clear that raw Underthesea cannot be dropped into Presidio with a
single fixed score.

## Score Calibration

Underthesea does not provide meaningful confidence scores in this interface, so
we added adapter-local calibration rather than modifying Presidio internals.

The wrapper now:

- starts PERSON spans from a lower base score,
- boosts spans near strong person context:
  - `Họ và tên`
  - `Tên bệnh nhân`
  - `Tên ứng viên`
  - `Đại diện`
  - `Bác sĩ`
  - `Người nhận`
  - `Chủ thẻ`
  - signature/cash receiver contexts
- boosts plausible 2-4 token Vietnamese names,
- penalizes spans with digits, code-like/admin contexts, address terms, drug
  terms, money/currency cues,
- drops spans below `min_score`.

For the combined Underthesea+regex pipelines, we currently use Underthesea only
as a filtered PERSON source with `min_score=0.70`.

## Calibration Payoff

On validation 500, calibration improved the precision/recall balance.

Before calibration:

| pipeline | precision | recall | F1 |
|---|---:|---:|---:|
| underthesea_regex | 0.9271 | 0.7566 | 0.8332 |
| underthesea_regex_recall | 0.9198 | 0.9059 | 0.9128 |

After calibration:

| pipeline | precision | recall | F1 |
|---|---:|---:|---:|
| underthesea_regex | 0.9646 | 0.7439 | 0.8400 |
| underthesea_regex_recall | 0.9502 | 0.8941 | 0.9213 |

PERSON after calibration:

| pipeline | PERSON precision | PERSON recall | PERSON F1 |
|---|---:|---:|---:|
| underthesea_regex | 0.9025 | 0.6769 | 0.7736 |
| underthesea_regex_recall | 0.8892 | 0.7193 | 0.7953 |

The calibration did what we wanted: recover much of the recall benefit while
reducing the worst false positive behavior.

## Full Validation: Regex Recall vs Underthesea Recall

We then ran full official validation for the two strongest non-test candidates.

| pipeline | precision | recall | F1 | runtime | peak footprint |
|---|---:|---:|---:|---:|---:|
| regex_recall | 0.9658 | 0.8420 | 0.8996 | 7.22s | ~405 MB |
| underthesea_regex_recall | 0.9481 | 0.8817 | 0.9137 | 153.99s | ~482 MB |

Counts:

| pipeline | TP | FP | FN |
|---|---:|---:|---:|
| regex_recall | 36,151 | 1,282 | 6,783 |
| underthesea_regex_recall | 37,854 | 2,074 | 5,080 |

PERSON:

| pipeline | precision | recall | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| regex_recall | 0.9971 | 0.5402 | 0.7008 | 4,534 | 13 | 3,859 |
| underthesea_regex_recall | 0.8857 | 0.7431 | 0.8082 | 6,237 | 805 | 2,156 |

Underthesea made a real quality improvement on validation F1, driven almost
entirely by PERSON recall. But the cost is significant:

- many more PERSON false positives,
- about 21x slower runtime,
- modest memory increase but still within this machine's RAM.

## Runtime and RAM Notes

Observed with `/usr/bin/time -l`:

- `regex_recall` full validation:
  - runtime: 7.22s
  - max RSS: ~1.21 GB
  - peak footprint: ~405 MB
- `underthesea_regex_recall` full validation:
  - runtime: 153.99s
  - max RSS: ~1.21 GB
  - peak footprint: ~482 MB

Earlier cold Underthesea 100-row runs showed higher max RSS, around 2.96 GB, but
full validation after the environment was warm stayed around 1.21 GB max RSS.
The practical issue is runtime, not RAM.

## Current Recommendation

Keep both:

- `regex_recall`: fast, strong, high precision. Best default candidate right now.
- `underthesea_regex_recall`: slower, higher recall. Useful when PERSON recall is
  more important than speed/precision.

Do not replace the regex baseline with Underthesea by default yet.

## Suggested Next Steps

1. Inspect PERSON false positives from `underthesea_regex_recall` on validation.
   The key question is whether we can cut the 805 PERSON FPs without losing too
   much of the recovered recall.

2. Add a JSONL run for full validation with `underthesea_regex_recall` and inspect:
   - frequent false-positive span text,
   - surrounding context,
   - whether Presidio overlap resolution is choosing Underthesea over regex in
     unexpected ways.

3. Consider a stricter Underthesea mode:
   - higher `min_score`, maybe 0.75,
   - require left-side person labels for some contexts,
   - block more organization/address/drug/code shapes.

4. If Underthesea cannot keep PERSON precision above roughly 0.92 while keeping
   recall meaningfully above regex-only, move to a stronger Vietnamese NER model.

5. Keep `test` reserved for final reporting. Selection should continue on
   `train_val` and official `validation`.

## Bottom Line

Regex tuning paid off more than expected: `regex_recall` reached validation F1
0.8996 with high precision and excellent speed.

Underthesea also paid off, but in a different way: it proved that NER can recover
many PERSON spans regex misses, raising validation F1 to 0.9137. However, it is
slow and adds many PERSON false positives, so it should remain an experimental
high-recall candidate until its false positives are better controlled.
