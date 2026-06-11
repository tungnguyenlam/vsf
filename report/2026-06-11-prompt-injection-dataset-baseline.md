# Prompt Injection Dataset Baseline

Date: 2026-06-11

## What Changed

Added the first reproducible evaluation path for the prompt-injection checkpoint:

- local Vietnamese seed benchmark: `data/prompt_injection/vietnamese_seed.jsonl`
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
| `local_vietnamese_seed` | 40 | 1.0000 | 1.0000 | 1.0000 | 24 | 0 | 16 | 0 |

This is a seed/regression result, not a production estimate. The examples were
chosen to cover current rule categories plus harder mixed-language,
retrieved-context, and benign security-education cases. Among rows with
`expected_action`, action accuracy is 1.0000 on 18 rows.

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

Next, add a prompt-injection error miner for decision logs so future misses can
be summarized by category, expected action, score, and matched rules.
