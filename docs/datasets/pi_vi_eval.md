# pi_vi_eval (balanced Vietnamese prompt-injection eval set)

A curated **evaluation** set (not a build source) that lets a prompt-injection
detector be scored on **precision and recall together** on Vietnamese text. The
attack-only seeds could show recall and per-attack precision, but never precision
against realistic non-attack Vietnamese; this set adds real negatives so a single
run yields P / R / F1 and a false-positive count.

It is an aggregate, so it lives under the shared `eval` location
(`data/safety_v0/eval/pi_vi/eval.jsonl`) rather than per-source.

## How it is built

`scripts/safety_v0/build_pi_vi_eval.py` combines two already-converted sources:

| Bucket | From | Ground truth | `gold` |
|---|---|---|---|
| `attack` | `local_vi_prompt_injection` gold attacks | `prompt_injection = True` | `True` (source_gold) |
| `benign_seed` | `local_vi_prompt_injection` gold benigns | `prompt_injection = False` | `True` (source_gold) |
| `benign_vihsd` | `vihsd_topic_safety` negatives | `prompt_injection = False` | `False` (source_assumption) |

The `benign_seed` rows are *hard* negatives: Vietnamese prompts that discuss
security / jailbreaks / prompt injection without performing an attack. The
`benign_vihsd` rows are real Vietnamese social-media comments (not a PI dataset,
so trustworthy negatives, but not hand-verified per row — hence `gold: False`).

Each row is a valid canonical `safety_v0` row plus a top-level `eval` block:

```json
"eval": {"label": true, "bucket": "attack", "gold": true}
```

By default the set is **balanced**: all local attacks, all local benigns, and
just enough vihsd negatives to match the positive count. Sampling is deterministic
(`--seed`, default 42). For a realistic (negative-heavy) false-positive estimate,
raise `--vihsd-negatives` — a single flag, no code change.

Default balanced composition: **148 rows** = 74 positives + 74 negatives
(46 `benign_seed` + 28 `benign_vihsd`).

## Evaluation

`scripts/safety_v0/evaluate_pi_vi.py` runs a registry detector over each row's
text and reports accuracy / precision / recall / F1, the confusion matrix, and a
per-bucket breakdown against `eval.label`. Misclassified rows are printed and can
be saved with `--errors`. The detector (`--detector`) and thresholds are config
flips.

```bash
python scripts/safety_v0/build_pi_vi_eval.py
python scripts/safety_v0/evaluate_pi_vi.py \
    --metrics output/safety_v0/pi_vi_eval/rule_based.json \
    --errors  output/safety_v0/pi_vi_eval/rule_based_errors.json
```

### Measured (rule_based_prompt_injection, after the 2026-06-17 rule fix)

| Set | n | P | R | F1 | FP | Note |
|---|---|---|---|---|---|---|
| balanced (default) | 148 | 1.0 | 1.0 | 1.0 | 0 | recall is overfit; rules were authored against these seeds |
| all vihsd negatives (`--vihsd-negatives 5000`) | 3,620 | 1.0 | 1.0 | 1.0 | 0 | realistic precision on Vietnamese |

The recall of 1.0 is **not** production recall: the positives are the same seeds
the rules were tuned on. The value of the set is the **precision** side — over all
3,500 vihsd negatives the detector now fires **0** times. Before the fix it fired
once (the `secret_or_data_exfiltration` false positive on `..._002461`, P ~0.987);
this eval set is what confirmed the tightening removed that FP without any new
attack-bucket false negatives.

## Caveats / next

- Positives are overfit; a meaningful recall number needs Vietnamese attack data
  the rules were *not* authored against (e.g. translated deepset/llmail twins once
  translation is unblocked, or new held-out seeds).
- This set was the validation harness for the `secret_or_data_exfiltration` rule
  tightening (done 2026-06-17): `evaluate_pi_vi.py --vihsd-negatives 5000`
  confirmed the FP dropped to 0 with no new attack-bucket false negatives. Reuse
  the same command to guard future rule changes.
- This eval set is also registered as the `pi_vi_eval` prompt-injection dataset
  (`PiViEvalDataset`), exposing its 148 rows as labelled `PromptInjectionExample`
  objects so a trainable detector can be scored leave-one-out on the identical
  rows as the rule baseline. The char-ngram Naive Bayes baseline reaches
  leave-one-out F1 `0.875` (P `0.814`, R `0.946`) here — a non-circular
  generalization estimate, unlike the rules' coverage-by-construction `1.0`.
- A decision-threshold sweep over the same leave-one-out scores
  (`scripts/safety_v0/sweep_pi_vi_nb_threshold.py`, also run by
  `scripts/safety_v0/run_heldout_evaluation.py`) shows the NB posteriors are
  saturated near 0/1: the default 0.5 cut-off sits in a flat region, and raising
  it to `0.999` removes only 6 false positives (16 -> 10), lifting F1 to at most
  `0.909` while recall stays hard-capped at `0.946` (4 attacks score ~0). That
  best-F1 threshold is selected on the eval set itself, so `0.909` is an
  optimistic ceiling, not a deployable gain — threshold tuning cannot close the
  gap to the rules; more diverse Vietnamese attack data is the real lever.
