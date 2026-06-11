# Local Vietnamese Prompt Injection App Seed

## Source

- Local file: `data/prompt_injection/vietnamese_app_seed.jsonl`
- Local registry key: `local_vietnamese_app_seed`
- Access: checked into the repository
- Split: `test`

This is a repo-owned Vietnamese prompt-injection smoke benchmark with prompts
shaped like application traffic: customer support, account workflows, tool
permission checks, retrieved documents, payment/refund APIs, logs, and policy
summaries.

It complements `local_vietnamese_seed`. The original seed is the compact
rule-regression set; this app seed is for product-shaped scenarios and should be
expanded with mentor or application examples when available.

Current size: 30 rows.

## Columns And Format

Each JSONL record has:

| Field | Meaning |
|---|---|
| `input_id` | Stable row id |
| `text` | Vietnamese application-shaped input prompt |
| `label` | `0` benign, `1` prompt injection |
| `language` | `vi` |
| `category` | Coarse local category |
| `source` | `local_vietnamese_app_seed` |
| `expected_action` | Expected detector action: `allow`, `review`, or `block` |

There are no spans. Evaluation is binary classification plus optional
expected-action accuracy.

## Label Taxonomy

| Label | Meaning |
|---|---|
| `0` | Benign application request |
| `1` | Prompt-injection attempt against an application or tool workflow |

Current seed categories include:

- `app_benign_account_support`
- `app_benign_customer_support`
- `app_benign_data_handling`
- `app_benign_tool_permission`
- `app_benign_policy_summary`
- `app_benign_indirect_analysis`
- `app_benign_tooling`
- `app_benign_retrieval_review`
- `app_benign_testing`
- `app_instruction_override`
- `app_mixed_language_jailbreak`
- `app_indirect_tool_abuse`
- `app_indirect_data_exfiltration`
- `app_tool_permission_bypass`
- `app_mixed_language_tool_abuse`
- `app_secret_extraction`
- `app_mixed_language_secret_extraction`
- `app_data_exfiltration`
- `app_mixed_language_data_exfiltration`
- `app_obfuscation`
- `app_jailbreak`
- `app_indirect_injection`

## Mismatch Vs Current Project

This is still hand-written and should not be treated as a production benchmark.
It is closer to likely VSF application workflows than the compact rule seed, but
it still needs real mentor/application examples and real traffic-shaped prompts.
