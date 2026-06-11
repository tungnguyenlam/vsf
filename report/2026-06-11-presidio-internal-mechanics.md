# Presidio Internal Mechanics Report

Date: 2026-06-11

This report explains how Presidio produces final PII spans and confidence
scores in this repository. It is based on:

- `src/notebooks/04_presidio_pipeline_checksum_context_confidence.ipynb`
- the installed `presidio-analyzer==2.2.362`
- this repo's Vietnamese pipeline wrapper under `src/pipeline/`

The important correction: Presidio does not learn or solve confidence scores at
runtime. Scores are mostly recognizer-provided heuristic values, optionally
modified by validation and context boosting, then filtered by duplicate removal
and score thresholds.

## End-To-End Analyzer Flow

For one input text, `AnalyzerEngine.analyze(...)` runs this sequence:

```text
text
  -> choose recognizers from registry
  -> create NLP artifacts
  -> run each recognizer
  -> add recognizer metadata
  -> recognizer-level context enhancement
  -> analyzer-level context enhancement
  -> duplicate / contained-span removal
  -> score threshold filtering
  -> allow-list filtering
  -> optionally strip decision process fields
  -> final RecognizerResult list
```

In code, the key upstream methods are:

- `AnalyzerEngine.analyze`
- `AnalyzerEngine._enhance_using_context`
- `EntityRecognizer.remove_duplicates`
- `AnalyzerEngine.__remove_low_scores`
- `AnalyzerEngine._remove_allow_list`

## Where Scores Come From

### Pattern recognizers

For `PatternRecognizer`, every regex `Pattern` has a fixed base score:

```python
Pattern("email_pattern", r"...", 0.9)
```

When the regex matches, Presidio creates a `RecognizerResult` with:

```text
result.score = pattern.score
analysis_explanation.original_score = pattern.score
```

So the initial score is not probabilistic calibration. It is the confidence the
recognizer author assigned to that pattern.

In this repo, `CustomPatternRecognizer` follows the same idea through
`ContextRegexPattern`:

```python
ContextRegexPattern(
    name="vn_cccd_cmnd",
    entity_type="ID",
    regex="...",
    score=0.9,
)
```

Our custom recognizer emits value-only spans with that fixed score and stores
the recognizer, pattern name, original score, regex, and metadata in
`AnalysisExplanation`.

### ML or NER recognizers

NER recognizers can provide their own model scores. Presidio treats those scores
as just another `RecognizerResult.score`. Later Presidio stages do not know
whether a score came from regex, spaCy, Underthesea, HuggingFace, or a custom
wrapper.

## Validation And Invalidation

`PatternRecognizer.validate_result(pattern_text)` is a hook for deterministic
validation such as checksums.

Default behavior:

```text
validate_result(...) -> None
```

If a recognizer overrides it:

```text
True  -> result.score = EntityRecognizer.MAX_SCORE = 1.0
False -> result.score = EntityRecognizer.MIN_SCORE = 0.0
None  -> keep the original pattern score
```

There is also `invalidate_result(...)`; if it returns `True`, Presidio sets the
score to `0.0`.

The old notebook demonstrates this with a toy Vietnamese checksum recognizer:

```text
123456786 -> valid checksum -> score promoted to 1.0
123456789 -> invalid checksum -> score set to 0.0 and removed
```

That checksum was intentionally a demo rule, not a real Vietnamese ID rule.
The useful lesson is the mechanism: validation is a deterministic post-regex
gate that can promote or drop a match.

## Context Score Boosting

Presidio has two context stages.

### Recognizer-level context

Each recognizer can override:

```python
EntityRecognizer.enhance_using_context(...)
```

By default this does nothing and returns the recognizer's raw results.

### Analyzer-level context

The default upstream enhancer is `LemmaContextAwareEnhancer`. In the installed
version, its constructor defaults are:

```text
context_similarity_factor = 0.35
min_score_with_context_similarity = 0.4
context_prefix_count = 5
context_suffix_count = 0
context_matching_mode = "substring"
```

Mechanically:

```text
if a supportive context word is found:
    result.score += 0.35
    result.score = max(result.score, 0.4)
    result.score = min(result.score, 1.0)
```

The supportive context word comes from:

- nearby lemmatized tokens around the detected span
- explicit `context=[...]` passed to `analyze(...)`
- the recognizer's own `context=[...]` list

The analyzer stores this in the explanation:

```text
score_context_improvement
supportive_context_word
analysis_explanation.score
```

### Important repo-specific behavior

The Vietnamese regex-first analyzer built by
`src/pipeline/Pipelines/analyzer_utils.py` uses:

```text
NoOpNlpEngine
NoContextAwareEnhancer
```

That means the default repository Vietnamese analyzer disables analyzer-level
context boosting:

```text
context_similarity_factor = 0.0
min_score_with_context_similarity = 0.0
context_prefix_count = 0
context_suffix_count = 0
```

Why this matters: for the main regex-only Vietnamese runs, most "context" is
encoded directly in our regex patterns, not added later by Presidio's default
context enhancer.

The old notebook used a local analyzer setup to demonstrate Presidio's context
boosting. That is still useful conceptually, but not always the same as the
current production path for `regex_only`.

## Duplicate And Contained-Span Filtering

After context enhancement, Presidio calls:

```python
EntityRecognizer.remove_duplicates(results)
```

The installed implementation does this:

```text
1. Convert to set(results)
2. Sort by:
   - score descending
   - start offset ascending
   - span length descending
3. Drop score == 0 results
4. Keep a result unless it is contained inside an already kept result
   with the same entity type
```

The containment rule only removes same-type contained spans. It does not fully
resolve cross-entity ambiguity like:

```text
same digits -> ID and BANK_ACCOUNT
```

That kind of ambiguity is why this repo has additional deterministic resolver
logic for specific pipeline variants.

## Score Threshold Filtering

After duplicate removal, Presidio applies the score threshold:

```text
keep result if result.score >= score_threshold
```

If no threshold is provided, Presidio uses the analyzer's
`default_score_threshold`, which is `0` in the upstream default configuration.

In this repo:

- `PIIPipeline.predict(..., score_threshold=...)` passes the threshold to
  `AnalyzerEngine.analyze(...)`.
- Evaluation defaults to `score_threshold=0.0`.
- CLI users can pass `--score-threshold`.

The notebook demonstrates this with a low-score 9-digit ID:

```text
score_threshold omitted -> weak match remains
score_threshold = 0.5 -> weak match is removed
```

## Allow List Filtering

Allow lists run after threshold filtering.

Two modes exist:

```text
exact -> remove result if detected text exactly equals an allow-list value
regex -> remove result if detected text matches any allow-list regex
```

This is useful for known safe tokens but should be used carefully because it can
hide real PII if the allow list is too broad.

## Decision Process Fields

When `return_decision_process=True`, final results retain
`analysis_explanation` and metadata fields such as:

```text
recognizer
pattern_name
pattern
original_score
score
score_context_improvement
supportive_context_word
validation_result
recognition_metadata
```

This repo enables decision process output when prediction logging is enabled or
when the LLM verifier is enabled. `PredictionJsonlLogger` serializes the key
fields into the JSONL audit log:

```text
score
recognizer
pattern
original_score
explanation_score
score_context_improvement
supportive_context
validation
```

That is the best place to inspect why one span got a specific confidence score
during evaluation.

## This Repo's Current PII Flow

For the current Vietnamese PII pipelines, the practical flow is:

```text
PIIPipeline.predict
  -> create/load Vietnamese AnalyzerEngine
  -> register custom recognizers
  -> AnalyzerEngine.analyze(return_decision_process=True when logging/verifier)
  -> optional DeterministicResolver
  -> optional LLMVerifier
  -> optional AnonymizerEngine
  -> PredictionJsonlLogger
```

Key repo files:

- `src/pipeline/BasePipeline.py`
- `src/pipeline/Pipelines/analyzer_utils.py`
- `src/pipeline/Recognizers/CustomPatternRecognizer.py`
- `src/pipeline/PredictionJsonlLogger.py`

## Practical Interpretation For Demos

Use this framing in a demo:

1. A recognizer proposes candidate spans and assigns an initial score.
2. Validation can promote a match to `1.0` or suppress it to `0.0`.
3. Context boosting can add confidence in analyzers that enable it.
4. Presidio removes duplicates and same-type contained spans.
5. Presidio applies the score threshold.
6. The repo logs the final spans plus explanation fields for auditability.

The most honest sentence:

> Presidio confidence is an explainable heuristic score, not a calibrated
> probability. In our Vietnamese pipeline, score quality depends mostly on the
> recognizer rules, validation hooks, optional context handling, and resolver
> logic.

## Recommended Next Step

Add a short CLI or notebook cell that runs one text through `regex_only` with
`include_source_text=True`, opens the generated `predictions.readable.json`, and
points to `original_score`, `score`, `pattern`, and `validation`. That will make
the score mechanics visible without relying on the older long notebook.
