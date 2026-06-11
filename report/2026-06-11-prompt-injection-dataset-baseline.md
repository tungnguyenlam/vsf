# Prompt Injection Dataset Baseline

Date: 2026-06-11

## What Changed

Added the first reproducible evaluation path for the prompt-injection checkpoint:

- local Vietnamese seed benchmark: `data/prompt_injection/vietnamese_seed.jsonl`
- local Vietnamese app-shaped smoke benchmark:
  `data/prompt_injection/vietnamese_app_seed.jsonl`
- HuggingFace dataset adapter: `rikka-snow/prompt-injection-multilingual`
- binary evaluator CLI: `scripts/evaluate_prompt_injection.py`
- JSONL decision logs under `output/prompt_injection/<run-id>/decisions.jsonl`
- one-class-per-file prompt-injection packages for detectors, models, datasets,
  evaluation, and logging

## Dataset Choice

The main project target remains Vietnamese-only by default, so the local seed set
is the main regression benchmark for now.

The selected public HF dataset is `rikka-snow/prompt-injection-multilingual`
because it is public, binary-labeled, and directly about prompt injection.

Other candidates inspected:

| Dataset | Decision |
|---|---|
| `neuralchemy/Prompt-injection-dataset` | Defer. Rich schema, but positive labels include broader unsafe/crescendo examples, not only prompt injection. |
| `rogue-security/prompt-injections-benchmark` | Defer. Gated. |
| `Necent/llm-jailbreak-prompt-injection-dataset` | Defer. Gated and broader than prompt injection. |

## Baseline Results

Command:

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_prompt_injection.py \
  --dataset local_vietnamese_seed \
  --run-id prompt-injection-local-seed \
  --include-source-text
```

Result:

| Dataset | Rows | Precision | Recall | F1 | TP | FP | TN | FN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `local_vietnamese_seed` | 65 | 1.0000 | 1.0000 | 1.0000 | 39 | 0 | 26 | 0 |

This is a seed/regression result, not a production estimate. The examples were
chosen to cover current rule categories plus harder mixed-language,
retrieved-context, and benign security-education cases. Among rows with
`expected_action`, action accuracy is 1.0000 on 43 rows.

The expanded 65-row checkpoint added harder benign security-analysis prompts,
retrieved-context/document injections, tool permission/state bypasses,
Vietnamese/English mixed attacks, and review-vs-block boundary cases. An
intermediate run before rule tuning surfaced 8 FP, 4 FN, and 17 action
mismatches, which drove the targeted rule updates.

Application-shaped smoke command:

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_prompt_injection.py \
  --dataset local_vietnamese_app_seed \
  --run-id prompt-injection-app-seed \
  --include-source-text
```

Result:

| Dataset | Rows | Precision | Recall | F1 | TP | FP | TN | FN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `local_vietnamese_app_seed` | 30 | 1.0000 | 1.0000 | 1.0000 | 20 | 0 | 10 | 0 |

The first app-seed run before rule tuning found precision 0.9412, recall
0.8000, F1 0.8649, with 1 FP, 4 FN, and 9 action mismatches. The mined errors
covered benign policy summaries, app-shaped tool permission bypasses,
retrieved-document attacks, and credential/user-data exfiltration phrasing.
After targeted rule updates, action accuracy is 1.0000 on all 30 rows.

Command:

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_prompt_injection.py \
  --dataset hf_prompt_injection_multilingual \
  --split test \
  --limit 100 \
  --run-id prompt-injection-hf-smoke
```

Result:

| Dataset | Rows | Precision | Recall | F1 | TP | FP | TN | FN |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `hf_prompt_injection_multilingual` sample | 100 | 0.0000 | 0.0000 | 0.0000 | 0 | 0 | 45 | 55 |

This failure is expected: the detector is Vietnamese-first, while the sampled HF
examples are mostly non-Vietnamese. Treat this as evidence that the HF dataset is
cross-language smoke coverage, not the current target metric.

## Recommendation

Next, supplement the hand-written seed with mentor/application examples and use
the decision-log miner after each rule change so future misses are summarized by
category, expected action, score, and matched rules.
