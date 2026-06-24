# Prompt Injection Detection

This is the first checkpoint for the prompt-injection pipeline. It is deliberately
small: a deterministic Vietnamese-first detector that can run locally without
LLM calls, model downloads, or paid APIs.

## Goal

Detect user inputs that try to:

- override previous or system instructions,
- reveal hidden prompts or internal rules,
- bypass safety policies or guardrails,
- abuse tools while skipping permission checks,
- extract secrets or user data,
- execute encoded or obfuscated instructions.

This is an input guardrail. It does not replace PII detection; it sits before an
agent or chat model decides how to respond.

## Current Implementation

Module:

```text
src/pipeline/PromptInjection/
  Detectors/
    BasePromptInjectionDetector.py
    RuleBasedPromptInjectionDetector.py
  Models/
    PromptInjectionResult.py
    PromptInjectionRule.py
  Datasets/
    PromptInjectionDataset.py
    LocalJsonlPromptInjectionDataset.py
    LocalVietnamesePromptInjectionSeed.py
    HuggingFacePromptInjectionDataset.py
    HfPromptInjectionMultilingualDataset.py
    registry.py
  Evaluation/
    PromptInjectionEvaluationConfig.py
    PromptInjectionEvaluationRunner.py
    cli.py
  Logging/
    PromptInjectionDecisionJsonlLogger.py
```

Class definitions are intentionally one-class-per-file. Top-level modules such
as `RuleBasedDetector.py`, `Datasets.py`, `Evaluation.py`, and
`DecisionJsonlLogger.py` are compatibility shims only.

Main detector classes:

```python
RuleBasedPromptInjectionDetector
CharNgramPromptInjectionDetector
```

Result object:

```python
PromptInjectionResult(
    is_injection=bool,
    score=float,
    action="allow" | "review" | "block",
    matched_rules=[...],
    categories=[...],
    evidence=[...],
)
```

The detector uses explicit regex rules with weights. Default thresholds:

| Threshold | Action |
|---|---|
| score < 0.45 | `allow` |
| 0.45 <= score < 0.75 | `review` |
| score >= 0.75 | `block` |

The interface is intentionally narrow so a later model-based classifier can
replace the rule engine without changing callers. Evaluation now supports
explicit detector selection:

- `rule_based_prompt_injection`
- `char_ngram_prompt_injection`

## Demo

```bash
PYTHONPATH=. .venv/bin/python scripts/demo_prompt_injection.py
```

Example output includes benign summarization, instruction override, hidden prompt
extraction, tool permission bypass, encoded instruction, and secret-exfiltration
examples.

## Evaluation

Current datasets:

| Dataset | Source | Role |
|---|---|---|
| `local_vietnamese_seed` | `data/prompt_injection/vietnamese_seed.jsonl` | Main small Vietnamese regression set with optional expected-action labels |
| `local_vietnamese_app_seed` | `data/prompt_injection/vietnamese_app_seed.jsonl` | Application-shaped Vietnamese smoke set for support/tool/RAG scenarios |
| `local_vietnamese_mentor_seed` | `data/prompt_injection/vietnamese_mentor_seed.jsonl` | Mentor/application-style Vietnamese smoke set for demo and review prompts |
| `hf_prompt_injection_multilingual` | `rikka-snow/prompt-injection-multilingual` | Optional public HF cross-language smoke benchmark |
| `pi_vi_eval` | `data/safety_v0/eval/pi_vi/eval.jsonl` | Balanced Vietnamese eval set (74 gold attacks + 46 benign seeds + 28 ViHSD negatives); ground truth from the `eval.label` block. Same 148 rows the rule detector is scored on |
| `deepset_vi` | `data/safety_v0/augmented/deepset_prompt_injections/augmented.jsonl` | Held-out Vietnamese set: 351 translated `deepset` twins (154 attacks + 197 benigns) the rules were NOT authored against — the non-circular generalization estimate |
| `llmail_vi` | `data/safety_v0/augmented/llmail_inject_challenge/augmented.jsonl` | Second held-out source: 500 translated `llmail-inject` twins, attack-only (recall-only); used to show transfer improves as the training pool grows |

Run the local Vietnamese seed benchmark:

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_prompt_injection.py \
  --dataset local_vietnamese_seed \
  --detector rule_based_prompt_injection \
  --run-id prompt-injection-local-seed
```

Run the experimental trainable baseline with leave-one-out evaluation on the
same dataset:

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_prompt_injection.py \
  --dataset local_vietnamese_seed \
  --detector char_ngram_prompt_injection \
  --train-strategy leave_one_out \
  --run-id prompt-injection-char-ngram-loo
```

Run a small sample from the HuggingFace multilingual benchmark:

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_prompt_injection.py \
  --dataset hf_prompt_injection_multilingual \
  --split test \
  --limit 100 \
  --run-id prompt-injection-hf-smoke
```

Run the application-shaped Vietnamese smoke benchmark:

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_prompt_injection.py \
  --dataset local_vietnamese_app_seed \
  --run-id prompt-injection-app-seed \
  --include-source-text
```

Run the mentor/application-style Vietnamese smoke benchmark:

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_prompt_injection.py \
  --dataset local_vietnamese_mentor_seed \
  --run-id prompt-injection-mentor-seed \
  --include-source-text
```

The evaluator writes JSONL decision logs under
`output/prompt_injection/<run-id>/decisions.jsonl` unless `--no-log` is used.
Rerunning the evaluator with the same `run-id` replaces that run's decision log
instead of appending duplicate records.
Use `--include-source-text` for local debugging logs; omit it for lighter logs.

Mine false positives, false negatives, and action mismatches from a decision log:

```bash
PYTHONPATH=. .venv/bin/python scripts/mine_prompt_injection_errors.py \
  output/prompt_injection/<run-id>/decisions.jsonl \
  --out-dir output/prompt_injection_error_analysis/<run-id>
```

For useful text examples in the mined report, run the evaluator with
`--include-source-text`.

## Manual Tuning Loop

Use this command when you want to check the local Vietnamese seed and keep
source text in the decision log for debugging:

```bash
RUN_ID=prompt-injection-local-seed-manual

PYTHONPATH=. .venv/bin/python scripts/evaluate_prompt_injection.py \
  --dataset local_vietnamese_seed \
  --run-id "$RUN_ID" \
  --include-source-text
```

Then mine the generated decision log:

```bash
PYTHONPATH=. .venv/bin/python scripts/mine_prompt_injection_errors.py \
  "output/prompt_injection/$RUN_ID/decisions.jsonl" \
  --out-dir "output/prompt_injection_error_analysis/$RUN_ID"
```

Read the mined Markdown report:

```bash
sed -n '1,220p' "output/prompt_injection_error_analysis/$RUN_ID/summary.md"
```

Run the focused regression tests after changing seed examples or rules:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/test_prompt_injection_detector.py \
  tests/test_prompt_injection_evaluation.py
```

Run the broader focused suite before committing prompt-injection changes:

```bash
PYTHONPATH=. .venv/bin/pytest -q \
  tests/test_prompt_injection_detector.py \
  tests/test_prompt_injection_evaluation.py \
  tests/test_pipeline_registry_and_evaluation.py \
  tests/test_prediction_jsonl_logging.py
```

When expanding `data/prompt_injection/vietnamese_seed.jsonl`, prioritize:

- ambiguous benign prompts that discuss security, jailbreaks, or prompt
  injection without asking the model to perform the attack;
- indirect injections inside retrieved-context or document text;
- tool-state and permission examples, especially shell/API/tool-call requests
  that try to skip confirmation;
- mixed Vietnamese/English attacks using terms such as `system prompt`,
  `developer message`, `tool`, `shell`, `token`, or `api key`;
- expected-action boundary cases where the right output is `review` rather than
  `block`.

## safety_v0 batch stage

`scripts/safety_v0/run_prompt_injection_rules.py` runs the rule detector as a
weak-label stage over canonical `safety_v0` rows. For each row it scans
`content.input_text` and `content.ocr_text`, appends the matched evidence to
`detections.prompt_injection_spans` (`detector="rule"`, ids `pi_rule_*`, each
span tagged with the `field` it indexes and the `rule` that fired), and fills
the `prompt_injection` weak label **only where it is currently unknown**
(`label_source="rule"`). It never overrides a stronger provenance such as
`source_gold`, and never touches `action` or the topic axes ("null means
unknown"). The detector and thresholds are config flips; default input is the
converted JSONL and output is `data/safety_v0/weak/<slug>/weak_labeled.jsonl`.
For image sources pass the redacted-stage JSONL via `--input` so OCR text is
present.

When `source_gold` flags exist the stage prints (and `--metrics` persists)
precision/recall/F1 of the rules against them — a free measurement. Measured on
the converted PI sources:

| Source | n (gold) | Precision | Recall | F1 | Note |
|---|---|---|---|---|---|
| `local_vi_prompt_injection` | 120 | 1.0 | 1.0 | 1.0 | Vietnamese seeds the rules were authored against (overfit) |
| `deepset_prompt_injections` | 351 | 1.0 | 0.084 | 0.156 | English attacks; rules barely fire |
| `llmail_inject_challenge` | 2000 | 1.0 | 0.022 | 0.043 | Adversarial/obfuscated English; all positives |

Takeaway: the rules are a **high-precision** signal but have **near-zero recall
on English and adversarial text**. They are usable as a cheap, trustworthy
positive signal — a rule hit is almost certainly a real attack — but recall on
non-Vietnamese sources needs a learned detector or the LLM teacher. The perfect
score on `local_vi_prompt_injection` is overfit (rules tuned on those seeds) and
should not be read as production recall.

Precision on real Vietnamese non-attack text (the check the attack-only seeds
could not give): over the 3,500 `vihsd_topic_safety` comments (Vietnamese
hate/offensive/clean, none of them prompt injections) the detector now fires on
**0 rows**. It previously fired once — a benign CLEAN comment discussing app
privacy ("Đọc báo thấy bảo xài app này nguy hiểm đến thông tin cá nhân"), where
`secret_or_data_exfiltration` matched bare "đọc … thông tin cá nhân". That rule
was tightened (2026-06-17): it now uses two branches — hard secrets
(password/token/api key/secret/credentials/hidden info) fire on any read/extract
verb including bare `đọc`/`read`, but soft personal-data targets (user data /
personal info / chat history) require a stronger exfiltration verb
(`lấy`/`trích xuất`/`gửi`/`liệt kê`/`xuất`/`đọc toàn bộ`/`dump`/…) and no longer
match bare `đọc`/`read`. Validated on the balanced Vietnamese eval set: the FP
dropped to 0 with no new attack-bucket false negatives.

## Balanced Vietnamese eval set

The seeds above measure recall on attacks, but precision/recall *together* on
realistic Vietnamese needs negatives. `scripts/safety_v0/build_pi_vi_eval.py`
assembles a curated benchmark — `local_vi` gold attacks (positives) + `local_vi`
gold benigns + `vihsd_topic_safety` negatives — and
`scripts/safety_v0/evaluate_pi_vi.py` scores any registry detector on it (P / R /
F1, confusion, per-bucket, FP/FN dump). See
[docs/datasets/pi_vi_eval.md](datasets/pi_vi_eval.md).

```bash
python scripts/safety_v0/build_pi_vi_eval.py
python scripts/safety_v0/evaluate_pi_vi.py --metrics output/safety_v0/pi_vi_eval/rule_based.json
```

Measured for `rule_based_prompt_injection` (after the 2026-06-17
`secret_or_data_exfiltration` fix): balanced (148) = P/R/F1 1.0 (recall is
overfit — same seeds the rules were tuned on); over all 3,500 vihsd negatives
(`--vihsd-negatives 5000`) = P/R/F1 1.0 with **0 false positives** (was 1 before
the fix). This set was the validation harness that confirmed the rule tightening
removed the FP without introducing attack-bucket false negatives.

## Current Limitations

- Rules are Vietnamese-first and only cover obvious prompt-injection phrasing.
- English support is not a goal yet, except for technical terms commonly used
  inside Vietnamese attacks, such as `system prompt`, `tool`, `token`, and
  `api key`, and mixed Vietnamese/English attacks in the local seed.
- There is no model-based classifier yet.
- There is now only a very small experimental model baseline: a local
  character-ngram Naive Bayes detector. It is useful for plumbing and quick
  comparisons, not as the intended final detector.
- The detector currently scores a single user input, not a full conversation
  with retrieved context and tool state.

## Current Comparison

On the current repo-owned Vietnamese seed set, the rule detector still wins:

- `rule_based_prompt_injection` on `local_vietnamese_seed`: accuracy/precision/recall/F1 = `1.0`
- `char_ngram_prompt_injection` with leave-one-out on `local_vietnamese_seed`:
  accuracy `0.707692`, precision `0.8125`, recall `0.666667`, F1 `0.732394`
- `char_ngram_prompt_injection` with leave-one-out on
  `local_vietnamese_mentor_seed`: accuracy `0.28`, recall `0.133333`
- On the balanced `pi_vi_eval` set (148 rows), the leave-one-out Naive Bayes
  baseline reaches precision `0.8140`, recall `0.9459`, F1 `0.8750`
  (tp=70 fp=16 fn=4 tn=58), while the rule detector scores `1.0` — but the
  rule `1.0` is coverage by construction (the rules were authored against these
  same gold attacks), so the leave-one-out `0.875` is the more honest
  generalization estimate. Reproduce with:

```bash
PYTHONPATH=. python scripts/evaluate_prompt_injection.py \
  --dataset pi_vi_eval --detector char_ngram_prompt_injection \
  --train-strategy leave_one_out --no-log
```

- A decision-threshold sweep over those same leave-one-out scores
  (`scripts/safety_v0/sweep_pi_vi_nb_threshold.py`) shows the NB posteriors are
  saturated near 0/1: the default `0.5` cut-off is in a flat region, and raising
  it to `0.999` only removes 6 false positives (16 -> 10), lifting F1 to at most
  `0.909` while recall stays hard-capped at `0.946` (4 attacks score ~0). That
  best-F1 threshold is fit on the eval set, so `0.909` is an optimistic ceiling,
  not a deployable gain. Threshold tuning cannot close the gap to the rules;
  more diverse Vietnamese attack data is the real lever. Reproduce with:

```bash
PYTHONPATH=. python scripts/safety_v0/sweep_pi_vi_nb_threshold.py
```

- **Held-out generalization on `deepset_vi`** (351 Vietnamese rows the rules were
  NOT authored against; translated EN->VI via openrouter/gpt-4o-mini). This is
  the non-circular number the `pi_vi_eval` overfit warning was waiting for:

  | Detector | Train -> Test | P | R | F1 |
  |---|---|---|---|---|
  | Rule-based | authored -> deepset_vi | 1.000 | 0.065 | 0.122 |
  | Char n-gram NB | pi_vi_eval -> deepset_vi | 0.542 | 0.292 | 0.380 |
  | Char n-gram NB | local_vi_seed -> deepset_vi | 0.646 | 0.201 | 0.307 |
  | Char n-gram NB | deepset_vi leave-one-out (in-domain) | 0.783 | 0.799 | 0.791 |

  The rules catch only 10 of 154 unseen attacks (recall 0.065) at perfect
  precision; cross-source NB transfer is weak (F1 0.31–0.38); but NB trained
  in-domain reaches F1 0.791, so the data is learnable and the gap is a **data**
  problem (diverse in-domain Vietnamese attacks), not a model ceiling. Reproduce
  with the commands in [datasets/deepset_vi.md](datasets/deepset_vi.md).

- **Transfer to a second, independent source `llmail_vi`** (500 translated
  `llmail-inject` attacks, recall-only) confirms growing the training pool is the
  lever. Recall climbs monotonically with pool size/diversity:

  | Detector | Train | Recall (of 500) |
  |---|---|---|
  | Rule-based | authored | 0.026 (13) |
  | Char n-gram NB | pi_vi_eval | 0.262 (131) |
  | Char n-gram NB | deepset_vi | 0.364 (182) |
  | Char n-gram NB | pi_vi_eval + local seeds + deepset_vi | 0.386 (193) |

  The rules collapse to 0.026 on this novel source; NB beats them 10–15x and
  improves as more diverse in-domain Vietnamese data is pooled in. The
  `--train-strategy external --train-dataset a,b,c` flag trains on a pool of
  sources and scores a held-out one. See
  [datasets/llmail_vi.md](datasets/llmail_vi.md).

That does not mean regex is sufficient in production. The `deepset_vi` held-out
numbers make this concrete: the seed datasets are small and heavily aligned with
the hand-written rules, so the rules' 1.0 is coverage-by-construction and
collapses to 0.065 recall on unseen attacks. A real learned detector needs a
broader, in-domain Vietnamese training set before it can be judged fairly.

## Next Steps

1. Run the decision-log miner after each seed or rule change and use the mined
   FP/FN/action-mismatch groups to choose the next examples.
2. Build a larger Vietnamese prompt-injection dataset with explicit train/dev/test
   splits instead of only smoke/regression seeds.
3. Compare the rule baseline against a stronger Vietnamese classifier
   (for example PhoBERT/viBERT fine-tuning or a cheap embedding+linear model)
   on that held-out split.
4. Keep topic filtering separate from prompt injection unless both tasks share a
   labeled taxonomy and evaluation plan.
5. Integrate the chosen detector as an input guardrail before tool calls and RAG
   retrieval.
