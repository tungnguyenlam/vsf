# Prompt Injection Multilingual

## Source

- HuggingFace dataset: `rikka-snow/prompt-injection-multilingual`
- Local registry key: `hf_prompt_injection_multilingual`
- Access: public, no token required
- Splits: `train`, `test`

This is the first external dataset wired into the prompt-injection checkpoint.
It is useful as a cheap public smoke benchmark, not as the main Vietnamese
project benchmark.

## Columns And Format

The source schema is binary classification:

| Column | Meaning |
|---|---|
| `text` | Input prompt text |
| `label` | `0` for benign, `1` for prompt injection |

There are no character spans. This dataset is evaluated with the
prompt-injection evaluator, not the Presidio PII span evaluator.

## Label Taxonomy

| Source label | Meaning | Local target |
|---|---|---|
| `0` | Benign prompt | `is_injection=False` |
| `1` | Prompt-injection prompt | `is_injection=True` |

The source does not provide fine-grained attack categories.

## Mismatch Vs Current Project

The project is Vietnamese-first. This dataset is multilingual but not
Vietnamese-specific, and many examples are English. It should not replace the
repo-owned Vietnamese seed set.

Expected mismatch:

- English and non-Vietnamese attacks are mostly out of scope for the current
  detector.
- The labels are binary, while our detector emits categories such as
  `instruction_override`, `secret_extraction`, `tool_abuse`, and
  `data_exfiltration`.
- Scores on this dataset should be reported as cross-language robustness, not
  as the main Vietnamese target metric.

Other HuggingFace candidates inspected:

- `neuralchemy/Prompt-injection-dataset`: richer schema, but the positive class
  includes broader unsafe and crescendo-style safety examples, not only prompt
  injection.
- `rogue-security/prompt-injections-benchmark`: gated at the time of review.
- `Necent/llm-jailbreak-prompt-injection-dataset`: gated and aggregates broader
  safety tasks beyond prompt injection.
