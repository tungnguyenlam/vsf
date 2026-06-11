# Local Vietnamese Prompt Injection Mentor Seed

## Source

- Local file: `data/prompt_injection/vietnamese_mentor_seed.jsonl`
- Local registry key: `local_vietnamese_mentor_seed`
- Access: checked into the repository
- Split: `test`

This is a repo-owned Vietnamese prompt-injection smoke benchmark shaped for
mentor reviews and application demos. It contains concise examples that a
mentor could plausibly paste into a demo: benign safety explanations, policy
summaries, RAG/document review prompts, tool permission workflows, hidden prompt
requests, tool bypass attempts, and data exfiltration attempts.

It complements:

- `local_vietnamese_seed`: compact rule-regression coverage.
- `local_vietnamese_app_seed`: broader synthetic application workflow coverage.

Current size: 25 rows.

## Columns And Format

Each JSONL record has:

| Field | Meaning |
|---|---|
| `input_id` | Stable row id |
| `text` | Vietnamese mentor/application-style input prompt |
| `label` | `0` benign, `1` prompt injection |
| `language` | `vi` |
| `category` | Coarse local category |
| `source` | `local_vietnamese_mentor_seed` |
| `expected_action` | Expected detector action: `allow`, `review`, or `block` |

There are no spans. Evaluation is binary classification plus optional
expected-action accuracy.

## Label Taxonomy

| Label | Meaning |
|---|---|
| `0` | Benign mentor/application request |
| `1` | Prompt-injection attempt against instructions, tools, secrets, or user data |

Current seed categories include:

- `mentor_benign_security_explanation`
- `mentor_benign_log_redaction`
- `mentor_benign_indirect_review`
- `mentor_benign_tool_permission_training`
- `mentor_benign_policy_summary`
- `mentor_benign_attack_classification`
- `mentor_benign_tooling_explanation`
- `mentor_benign_filter_testing`
- `mentor_benign_account_workflow`
- `mentor_benign_ai_safety`
- `mentor_instruction_override`
- `mentor_secret_extraction`
- `mentor_mixed_language_secret_extraction`
- `mentor_indirect_tool_abuse`
- `mentor_indirect_secret_extraction`
- `mentor_tool_permission_bypass`
- `mentor_mixed_language_tool_abuse`
- `mentor_data_exfiltration`
- `mentor_obfuscation`
- `mentor_jailbreak`
- `mentor_privilege_escalation`
- `mentor_stealth_data_exfiltration`

## Mismatch Vs Current Project

This is still a local synthetic seed, not a real production benchmark. Its
purpose is to make mentor-demo and application-like failure modes explicit, then
use decision-log mining to choose the next deterministic rule fixes.
