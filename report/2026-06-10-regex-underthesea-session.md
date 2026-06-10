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

## Addendum: Validation Cleanup After Underthesea Error Inspection

After the initial Underthesea comparison, we inspected false predictions from the
validation run and made a narrow deterministic cleanup pass. The goal was not to
optimize on the leaked test split. We treated the earlier test look as already
known leakage, then continued selection and inspection on validation only.

The high-value false-positive classes were mostly from recall-oriented regex
rules, not from Underthesea itself:

- `recall_date_labeled` was matching `ngày cấp`, `ngày cấp đơn`, and
  `ngày hết hạn` contexts as `DATE_TIME`.
- `recall_context_year` was too broad and matched generic bare `năm 2015` style
  references.
- `vn_street_like_location` sometimes treated field names such as `Mã`, `Ngày`,
  `Số`, `Tên`, and `Địa` as location starts.
- `vn_district_location` could consume police issuance contexts such as
  `Công an Huyện...` and spans containing `ngày cấp`.
- `recall_bank_account` used `Khách hàng` as a trigger, which could turn nearby
  income-like numeric text into `BANK_ACCOUNT`.

We tightened those rules in
`src/pipeline/Recognizers/CustomPatternRecognizer.py`.

### 500-row Validation Check

Before cleanup, the calibrated 500-row validation sample had:

| metric | value |
|---|---:|
| precision | 0.9502 |
| recall | 0.8941 |
| F1 | 0.9213 |
| TP | 1,833 |
| FP | 96 |
| FN | 217 |

After cleanup:

| metric | value |
|---|---:|
| precision | 0.9679 |
| recall | 0.8839 |
| F1 | 0.9240 |
| TP | 1,812 |
| FP | 60 |
| FN | 238 |

This confirmed the direction: fewer false positives and slightly better F1, with
a measurable recall tradeoff.

### Full Validation Rerun After Cleanup

Full validation after cleanup:

| metric | value |
|---|---:|
| precision | 0.9659 |
| recall | 0.8714 |
| F1 | 0.9162 |
| TP | 37,412 |
| FP | 1,320 |
| FN | 5,522 |

Compared with the previous full validation run:

| metric | before | after |
|---|---:|---:|
| precision | 0.9481 | 0.9659 |
| recall | 0.8817 | 0.8714 |
| F1 | 0.9137 | 0.9162 |
| TP | 37,854 | 37,412 |
| FP | 2,074 | 1,320 |
| FN | 5,080 | 5,522 |

Per-entity full validation after cleanup:

| entity | precision | recall | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| BANK_ACCOUNT | 1.0000 | 0.7921 | 0.8840 | 766 | 0 | 201 |
| ID | 0.9974 | 0.8961 | 0.9441 | 4,269 | 11 | 495 |
| PERSON | 0.8857 | 0.7431 | 0.8082 | 6,237 | 805 | 2,156 |
| LOCATION | 0.9897 | 0.9681 | 0.9788 | 15,962 | 166 | 526 |
| DATE_TIME | 0.9870 | 0.8614 | 0.9199 | 5,221 | 69 | 840 |
| PHONE_NUMBER | 0.9517 | 1.0000 | 0.9753 | 1,301 | 66 | 0 |
| ORGANIZATION | 0.9336 | 0.6853 | 0.7904 | 2,839 | 202 | 1,304 |
| EMAIL_ADDRESS | 0.9988 | 1.0000 | 0.9994 | 817 | 1 | 0 |

The cleanup reduced false positives by 754 on full validation, but increased
false negatives by 442. This is a precision-leaning improvement, not a recall
optimization.

### Updated Runtime and RAM Observation

The later full validation rerun with `underthesea_regex_recall` was much slower
than the earlier measured run:

- runtime: about 3,292.69s real time, or roughly 54m53s
- max RSS: about 1.97 GB
- peak memory footprint: about 609 MB

RAM is still acceptable for a 16 GB development machine, but runtime is now the
main operational concern. Underthesea should stay optional, with routine
iteration done on smaller validation samples.

### Updated Interpretation

The deterministic cleanup paid off, but the remaining error distribution is now
less attractive for hand-written regex work. The easy false positives from
DATE_TIME, BANK_ACCOUNT, and generic location patterns are mostly gone. The
remaining failures are dominated by PERSON and ORGANIZATION, where many examples
look like NER boundary issues, entity-type disagreement, or dataset annotation
mismatch.

That means the next meaningful improvement probably should not be another broad
regex-tuning pass. Better next steps are:

1. Add a resolver/verifier layer that can use features from Presidio candidates,
   recognizer source, score, entity type, and local context.
2. Tune that resolver on small targeted validation slices, not full train and
   not test.
3. Use LLM checks sparingly to explain ambiguous validation errors and turn those
   explanations into deterministic resolver features.

Presidio itself does not learn from examples automatically in the way we need
here. It gives us recognizers, scores, and conflict resolution hooks. The
self-improving part has to be built around it: mine errors, convert repeated
failure modes into recognizer or resolver changes, rerun on validation, and keep
test untouched for final reporting.

## Addendum: Deterministic Resolver v1

We then implemented the first resolver experiment as a separate pipeline variant:

- registry key: `underthesea_regex_recall_resolved`
- class: `UndertheseaRegexRecallResolvedPipeline`
- resolver: `DeterministicResolver`

The resolver runs after Presidio's AnalyzerEngine and before the optional LLM
verifier. It receives the already-resolved Presidio candidates and can drop
repeated false-positive patterns using:

- entity type,
- recognizer provenance,
- local Vietnamese context.

Version 1 is deliberately narrow. It only suppresses `PERSON` spans from
`DeepLearning_UndertheseaNER` when the left-side context strongly suggests an
organization, document/code/product field, or similar non-person context. It also
protects person-role contexts such as `Họ và tên`, `Khách hàng`, `Bác sĩ`,
`Người nhận`, `Chủ sở hữu`, and `Đại diện pháp lý`.

An initial broader version also dropped candidates based on address context
around the span, but that over-dropped real people who were followed by an
address field. We removed that broad address rule.

### Resolver A/B Results

Validation 500, after narrowing the resolver:

| pipeline | precision | recall | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| `underthesea_regex_recall` | 0.9679 | 0.8839 | 0.9240 | 1,812 | 60 | 238 |
| `underthesea_regex_recall_resolved` | 0.9690 | 0.8834 | 0.9242 | 1,811 | 58 | 239 |

Train-val 500:

| pipeline | precision | recall | F1 | TP | FP | FN |
|---|---:|---:|---:|---:|---:|---:|
| `underthesea_regex_recall` | 0.9648 | 0.8993 | 0.9309 | 2,000 | 73 | 224 |
| `underthesea_regex_recall_resolved` | 0.9667 | 0.8993 | 0.9317 | 2,000 | 69 | 224 |

The result is directionally useful but small. On validation 500 it removed two
false positives at the cost of one true positive. On train-val 500 it removed
four false positives with no recall loss.

This is enough to keep the resolver variant for continued experiments, but not
enough to promote it as the default pipeline. The next useful resolver work
should focus on logging resolver decisions and comparing dropped candidates
directly, because the current prediction log only contains the final kept spans.
