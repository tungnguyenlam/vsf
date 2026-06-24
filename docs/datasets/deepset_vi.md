# deepset_vi (held-out Vietnamese prompt-injection set)

A **held-out** Vietnamese prompt-injection evaluation set built by translating
the English `deepset/prompt-injections` dataset EN->VI. Its whole point is that
the hand-written rules were **not** authored against it, so it yields the first
non-circular generalization estimate for the prompt-injection detectors — unlike
the local seeds and `pi_vi_eval`, whose attacks the rules were tuned on.

## How it is built

`scripts/safety_v0/run_translation_augmentation.py` translates each English row
to a Vietnamese twin (whole-text label preserved; translation would destroy PII
spans, so PII rows are never translated — not an issue here, deepset has none):

```bash
PYTHONPATH=. python scripts/safety_v0/run_translation_augmentation.py \
    --slug deepset_prompt_injections \
    --backend openrouter --model openai/gpt-4o-mini --sleep 0.1
# data/safety_v0/converted/deepset_prompt_injections/source_canonical.jsonl
#   -> data/safety_v0/augmented/deepset_prompt_injections/augmented.jsonl
```

The Gemini free tier is rate-limited so hard that even a single call cannot
land, so translation uses the `openrouter` backend. `openai/gpt-4o-mini` was
chosen over the default `xiaomi/mimo-v2.5` (a reasoning model at ~19 s/call) for
speed (~0.9 s/call) and because it faithfully translates the adversarial text
*without obeying* the injection — Mistral-small, by contrast, followed the
injection and refused to translate, so it was rejected.

## Format and taxonomy

`DeepsetViDataset` (`src/pipeline/PromptInjection/Datasets/DeepsetViDataset.py`,
registered as `deepset_vi`) reads only the translated twins (rows with an
`augmentation` block) and exposes them as `PromptInjectionExample`:

| Field | Source |
|---|---|
| `text` | `content.input_text` (Vietnamese translation) |
| `label` | `labels.prompt_injection` (1 attack / 0 benign) |
| `category` | `attack` / `benign` (derived from the label) |
| `language` | always `vi` |

Composition: **351 rows = 154 attacks + 197 benigns**. Only `test`/`all` splits.

The deepset taxonomy is binary (`prompt_injection` true/false), so it maps
cleanly onto our whole-text label with no dropped classes.

## Measured (held-out generalization)

This is the key result: the earlier `1.0` scores on the local seeds were
coverage-by-construction. On attacks the detectors were not built for:

| Detector | Train -> Test | P | R | F1 | tp | fp | fn | tn |
|---|---|---|---|---|---|---|---|---|
| Rule-based | authored -> deepset_vi | 1.000 | 0.065 | 0.122 | 10 | 0 | 144 | 197 |
| Char n-gram NB | pi_vi_eval -> deepset_vi | 0.542 | 0.292 | 0.380 | 45 | 38 | 109 | 159 |
| Char n-gram NB | local_vi_seed -> deepset_vi | 0.646 | 0.201 | 0.307 | 31 | 17 | 123 | 180 |
| Char n-gram NB | deepset_vi leave-one-out | 0.783 | 0.799 | 0.791 | 123 | 34 | 31 | 163 |

Reproduce:

```bash
PYTHONPATH=. python scripts/evaluate_prompt_injection.py \
    --dataset deepset_vi --split all \
    --detector rule_based_prompt_injection --no-log
PYTHONPATH=. python scripts/evaluate_prompt_injection.py \
    --dataset deepset_vi --split all \
    --detector char_ngram_prompt_injection \
    --train-strategy external --train-dataset pi_vi_eval --no-log
PYTHONPATH=. python scripts/evaluate_prompt_injection.py \
    --dataset deepset_vi --split all \
    --detector char_ngram_prompt_injection \
    --train-strategy leave_one_out --no-log
```

## Reading the result

- The **rules generalize almost not at all** to unseen phrasings: recall 0.065
  (10 of 154 attacks). Precision stays perfect (0 false positives on 197 real
  Vietnamese benigns) — they are high-precision keyword matchers locked to the
  exact wordings they were written for.
- **Cross-source NB transfer is weak** (F1 0.31–0.38): a model trained on the
  local Vietnamese seeds or `pi_vi_eval` and tested on translated deepset
  recovers only 20–29% of attacks.
- **But the data is learnable**: NB trained in-domain (leave-one-out on
  deepset_vi) reaches F1 0.791. So the production gap is a **data problem**
  (need diverse in-domain Vietnamese attack data spanning many phrasings), not a
  model ceiling.

## Caveats / next

- Labels are inherited from the English source via faithful translation; a
  whole-text injection label survives translation, but per-row gold was not
  re-verified in Vietnamese (provenance is marked `*_translated`).
- Translation quality depends on `gpt-4o-mini`; spot-checks look faithful, but
  the set is not hand-corrected.
- Next: fold deepset_vi (and further translated sources such as llmail) into the
  training pool and re-measure transfer; the in-domain 0.79 suggests a combined,
  diverse Vietnamese corpus is the path to a deployable learned detector.
