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

Main class:

```python
RuleBasedPromptInjectionDetector
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
replace the rule engine without changing callers.

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
| `hf_prompt_injection_multilingual` | `rikka-snow/prompt-injection-multilingual` | Optional public HF cross-language smoke benchmark |

Run the local Vietnamese seed benchmark:

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_prompt_injection.py \
  --dataset local_vietnamese_seed \
  --run-id prompt-injection-local-seed
```

Run a small sample from the HuggingFace multilingual benchmark:

```bash
PYTHONPATH=. .venv/bin/python scripts/evaluate_prompt_injection.py \
  --dataset hf_prompt_injection_multilingual \
  --split test \
  --limit 100 \
  --run-id prompt-injection-hf-smoke
```

The evaluator writes JSONL decision logs under
`output/prompt_injection/<run-id>/decisions.jsonl` unless `--no-log` is used.
Use `--include-source-text` for local debugging logs; omit it for lighter logs.

Mine false positives, false negatives, and action mismatches from a decision log:

```bash
PYTHONPATH=. .venv/bin/python scripts/mine_prompt_injection_errors.py \
  output/prompt_injection/<run-id>/decisions.jsonl \
  --out-dir output/prompt_injection_error_analysis/<run-id>
```

For useful text examples in the mined report, run the evaluator with
`--include-source-text`.

## Current Limitations

- Rules are Vietnamese-first and only cover obvious prompt-injection phrasing.
- English support is not a goal yet, except for technical terms commonly used
  inside Vietnamese attacks, such as `system prompt`, `tool`, `token`, and
  `api key`, and mixed Vietnamese/English attacks in the local seed.
- There is no model-based classifier yet.
- The detector currently scores a single user input, not a full conversation
  with retrieved context and tool state.

## Next Steps

1. Run the decision-log miner after each seed or rule change and use the mined
   FP/FN/action-mismatch groups to choose the next examples.
2. Compare this rule baseline against a cheap local or API classifier on a small
   sample.
3. Integrate the detector as an input guardrail before tool calls and RAG
   retrieval.
