# Local Vietnamese Prompt Injection Seed

## Source

- Local file: `data/prompt_injection/vietnamese_seed.jsonl`
- Local registry key: `local_vietnamese_seed`
- Access: checked into the repository
- Split: `test`

This is a small repo-owned seed benchmark for the first Vietnamese
prompt-injection detector checkpoint. It exists to make rule changes measurable
before spending LLM calls or adapting larger public datasets.

Current size: 65 rows.

## Columns And Format

Each JSONL record has:

| Field | Meaning |
|---|---|
| `input_id` | Stable row id |
| `text` | Vietnamese input prompt |
| `label` | `0` benign, `1` prompt injection |
| `language` | `vi` |
| `category` | Coarse local category |
| `source` | `local_vietnamese_seed` |
| `expected_action` | Optional expected detector action: `allow`, `review`, or `block` |

There are no spans. Evaluation is binary classification.

## Label Taxonomy

| Label | Meaning |
|---|---|
| `0` | Benign user request |
| `1` | Prompt-injection attempt |

Current seed categories include:

- `benign`
- `benign_security_education`
- `benign_guardrail`
- `benign_tooling`
- `benign_obfuscation_context`
- `benign_roleplay`
- `benign_retrieved_context_analysis`
- `benign_data_handling`
- `instruction_override`
- `secret_extraction`
- `jailbreak`
- `tool_abuse`
- `data_exfiltration`
- `obfuscation`
- `mixed_language_instruction_override`
- `mixed_language_secret_extraction`
- `mixed_language_tool_abuse`
- `mixed_language_data_exfiltration`
- `mixed_language_jailbreak`
- `mixed_language_indirect_injection`
- `indirect_injection`
- `indirect_data_exfiltration`

## Mismatch Vs Current Project

This is not a production benchmark. It is intentionally small and hand-written,
so it can catch obvious regressions but cannot estimate real-world prevalence.
It now includes ambiguous benign prompts, mixed Vietnamese/English attacks,
retrieved-context attacks, and tool-call bypass scenarios, but still needs
mentor-provided examples and real application traffic patterns.
