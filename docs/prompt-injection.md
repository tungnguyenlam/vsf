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
  RuleBasedDetector.py
  __init__.py
```

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

## Current Limitations

- Rules are Vietnamese-first and only cover obvious prompt-injection phrasing.
- English support is not a goal yet, except for technical terms commonly used
  inside Vietnamese attacks, such as `system prompt`, `tool`, `token`, and
  `api key`.
- There is no dataset or benchmark yet.
- There is no model-based classifier yet.
- The detector currently scores a single user input, not a full conversation
  with retrieved context and tool state.

## Next Steps

1. Build a small Vietnamese prompt-injection evaluation set.
2. Add a JSONL logger for prompt-injection decisions.
3. Add a CLI evaluator once the dataset shape is stable.
4. Compare this rule baseline against a cheap local or API classifier on a small
   sample.
5. Integrate the detector as an input guardrail before tool calls and RAG
   retrieval.

