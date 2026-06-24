# llmail_vi (second held-out Vietnamese prompt-injection source)

A second, **independent** held-out Vietnamese prompt-injection set, built by
translating a sample of the `llmail-inject` challenge EN->VI. Where `deepset_vi`
gives the first non-circular generalization number, `llmail_vi` answers the
follow-up question: does growing and diversifying the Vietnamese training pool
actually improve transfer to a *new* attack distribution? It does.

llmail-inject is **attack-only** (email-borne indirect injection), so this is a
**recall-only** source: it has no benigns, so precision is not meaningful here.
It measures how many genuinely novel attacks a detector recovers.

## How it is built

```bash
PYTHONPATH=. python scripts/safety_v0/run_translation_augmentation.py \
    --slug llmail_inject_challenge \
    --backend openrouter --model openai/gpt-4o-mini --limit 500 --sleep 0.1
# data/safety_v0/converted/llmail_inject_challenge/source_canonical.jsonl
#   -> data/safety_v0/augmented/llmail_inject_challenge/augmented.jsonl
```

The full challenge is 2,000 rows but only ~741 unique text prefixes (heavy
duplication) and all attacks, so a bounded 500-row sample is translated rather
than the whole set. Same `openrouter` / `gpt-4o-mini` choice and rationale as
[deepset_vi.md](deepset_vi.md). `LlmailViDataset` (registered `llmail_vi`) reads
only the translated twins and exposes them as `PromptInjectionExample`; the
500-row sample is 500 attacks, all Vietnamese.

## Measured (transfer to a novel source)

Recall is the only meaningful metric (attack-only). "Train" is the data the
detector learned from; every row of `llmail_vi` is the held-out test.

| Detector | Train | Recall | tp / 500 |
|---|---|---|---|
| Rule-based | authored | 0.026 | 13 |
| Char n-gram NB | pi_vi_eval | 0.262 | 131 |
| Char n-gram NB | deepset_vi | 0.364 | 182 |
| Char n-gram NB | pi_vi_eval + local seeds + deepset_vi (pool) | 0.386 | 193 |

Reproduce (each line is one run):

```bash
PYTHONPATH=. python scripts/evaluate_prompt_injection.py \
    --dataset llmail_vi --split all \
    --detector rule_based_prompt_injection --no-log
PYTHONPATH=. python scripts/evaluate_prompt_injection.py \
    --dataset llmail_vi --split all --detector char_ngram_prompt_injection \
    --train-strategy external --train-dataset deepset_vi --no-log
PYTHONPATH=. python scripts/evaluate_prompt_injection.py \
    --dataset llmail_vi --split all --detector char_ngram_prompt_injection \
    --train-strategy external \
    --train-dataset "pi_vi_eval,local_vietnamese_seed,local_vietnamese_app_seed,local_vietnamese_mentor_seed,deepset_vi" \
    --no-log
```

## Reading the result

- The **rules collapse even harder** here than on `deepset_vi`: recall 0.026
  (13 of 500). They do not generalize to an unseen attack distribution at all.
- The **learned model beats the rules 10–15×** even across domains.
- **Recall climbs monotonically as the training pool grows and diversifies**:
  `pi_vi_eval` alone 0.262 -> `deepset_vi` 0.364 -> full pool 0.386. This is the
  positive confirmation the `deepset_vi` analysis pointed to: on a genuinely
  novel source, more diverse in-domain Vietnamese training data directly buys
  recall. (Note the contrast: on `deepset_vi` itself, pooling *diluted* the
  single best in-domain source; on a truly held-out source, diversity helps.)
- This validates translation augmentation as the central lever for the next
  phase: keep growing the Vietnamese attack pool from labelled English sources.

## Caveats / next

- Recall-only: no benign rows, so this set cannot detect over-firing. Pair it
  with a benign-bearing set (e.g. `deepset_vi`, `pi_vi_eval`) when judging
  precision.
- Only the first 500 of 2,000 rows are translated; the remainder (and the
  duplicate-heavy tail) are not. Raising `--limit` extends coverage at linear
  cost.
- Labels inherited via faithful translation (provenance `*_translated`), not
  re-verified per row.
