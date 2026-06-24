# Translation augmentation (EN -> VI)

Grows scarce Vietnamese data by translating English, whole-text-labelled rows
into Vietnamese twins: one labelled sample becomes two. This is the cheapest way
to lift Vietnamese prompt-injection coverage, where we otherwise have only the
120 overfit local seeds (see `docs/prompt-injection.md`).

## Why it is safe for these labels only

A label is either **whole-text** (the entire string is or is not an attack /
about a topic) or **span-level** (PII at specific character offsets).

- Whole-text labels (`prompt_injection`, `political`, `religious`, and the other
  topic axes) **survive translation** — "ignore all previous instructions" and
  its Vietnamese rendering are both attacks.
- Span-level PII labels **do not** — translation shifts every offset and
  transliterates names/phones, so `pii_spans` break.

Scope is therefore prompt-injection + topic only. The stage **never** produces a
twin for a row carrying `detections.pii_spans`; the original passes through
untouched.

## Direction

EN -> VI only. We do not translate VI -> EN: that would create English samples,
and English is not a project goal (Vietnamese-only by default). Rows whose
detected language already equals the target are skipped.

## Provenance and traceability (honest labels)

A twin's label *value* is inherited, but its text changed, so it is not pristine
gold. The stage marks the provenance of the content-bearing axes
(`prompt_injection`, `political`, `religious`) as `<orig>_translated` (e.g.
`source_gold_translated`). Modality assumptions that do not depend on language
(`pii_visible`, `sexual`, `violence`, `blood_gore` on a text PI source) keep
their original provenance. A source-gold whole-text injection span is regenerated
over the translated text as `source_gold_translated`.

Every twin carries an `augmentation` block:

```json
{"type": "translation", "direction": "en2vi", "backend": "gemini",
 "model": "gemini-flash-latest", "source_input_id": "safety_v0_..._000001"}
```

The twin's `input_id` is the original id with a `_vi` suffix. Downstream split
assignment must keep a twin in the **same split** as its `source_input_id` to
avoid train/test leakage.

## Backend (swappable)

Translation goes through `src/pipeline/Translation` behind a narrow `Translator`
interface; `GeminiTranslator` is the default and reuses the same Gemini endpoint
and credentials as the safety router (single source of truth). Swap
`--backend`/`--model` to change engines without touching call sites. The texts
are adversarial, so the system prompt instructs the model to translate
faithfully and **not** to obey instructions inside the text.

The translator retries HTTP 429 / quota errors with exponential backoff.

### OpenRouter fallback (opt-in)

When the Gemini call exhausts its retries on a transient error, the translator
can call an OpenRouter model as a one-shot fallback. This is **opt-in**:

- Wire it by passing `fallback_client=` (a pre-built `OpenAI` client whose
  `base_url` points at `https://openrouter.ai/api/v1`) when constructing
  `GeminiTranslator`. The key is read from `OPENROUTER_API_KEY` (or
  `OPENAI_API_KEY`).
- Default fallback model: `xiaomi/mimo-v2.5`. Override via `fallback_model=`.
- Triggered only after the primary call exhausts retries on a retryable error
  (HTTP 429 / 5xx + overload markers). Non-retryable errors re-raise as before.
- The same `messages` payload (system + user) is forwarded verbatim, so the
  faithful-translation system prompt still instructs the model not to obey
  instructions in the text.
- A fallback that raises logs a warning and re-raises the **original** Gemini
  error, so callers can still treat the row as failed.

No automatic runtime switching: a script must construct the translator with the
fallback client explicitly. Selection stays configuration, reproducible.

## Cost and rate limits

Paid Gemini calls, against the `$2-$10` project budget.

- Translations are cached on disk (`data/safety_v0/manifests/translation_cache.json`,
  keyed by model + langs + text hash), so reruns never re-pay and a crashed run
  resumes from where it stopped.
- The current key is on the Gemini **free tier**, and the binding limit is a
  **daily request cap**, measured at **20 requests/day** for `gemini-3.5-flash`
  (quota `GenerateRequestsPerDayPerProjectPerModel-FreeTier`), on top of ~5
  req/min. At 20/day, deepset (351) would take ~18 days and llmail (2,000) ~100
  days, so **free-tier translation is not viable at scale** — it needs billing
  enabled on the key. The translator retries the per-minute 429s and transient
  5xx, but cannot retry past a daily cap; the run stops and the cache preserves
  whatever completed, resumable the next day.
- Always smoke-test with `--limit` before a full run.

## Usage

```bash
# Smoke test (paced under the free-tier RPM cap)
python scripts/safety_v0/run_translation_augmentation.py \
    --slug deepset_prompt_injections --limit 10 --sleep 13

# Full source (originals + twins -> data/safety_v0/augmented/<slug>/augmented.jsonl)
python scripts/safety_v0/run_translation_augmentation.py \
    --slug deepset_prompt_injections --sleep 13

# Re-run the rule detector on the augmented file to measure rule recall on the
# Vietnamese translations (a free, useful cross-check):
python scripts/safety_v0/run_prompt_injection_rules.py \
    --input data/safety_v0/augmented/deepset_prompt_injections/augmented.jsonl \
    --output data/safety_v0/weak/deepset_prompt_injections/weak_augmented.jsonl
```

Pipeline position: `convert -> translate-augment -> prompt-injection rules`. The
augmentation stage reads converted rows and writes originals + twins; the rule
stage then runs over both.
