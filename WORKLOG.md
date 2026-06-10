## 2026-06-10 — AGENTS.md: swappability guidance + WORKLOG protocol
- Added "Design for swappability" rule to Default workflow (narrow interfaces, vendor behind thin adapters, choices as config with single source of truth, no automatic runtime switching).
- Added "## WORKLOG.md" section: append-only via bash, read only via tail/grep/head, never load into context tools.
- Decision (LLM provider for PII pipeline): use flash-tier on OpenRouter (Claude/Opus too expensive). Provider = config knob, not auto-switched. Small-prefix prompt today -> Alibaba on base price; switch to DeepSeek only if a large few-shot/guideline prefix or per-document fan-out is adopted. Rely on OpenRouter built-in sticky routing.
- Verified: AGENTS.md edits applied; no code changed yet.

## 2026-06-10 — LLMVerifier: migrate to OpenAI-compatible API, drop Anthropic
- Rewrote src/pipeline/Verifiers/LLMVerifier.py to use the OpenAI SDK (chat.completions) against an OpenAI-compatible endpoint. Removed all anthropic usage.
- Provider as config seam (single source of truth): DEFAULT_BASE_URL=OpenRouter, DEFAULT_MODEL=deepseek/deepseek-v4-flash, API key from OPENROUTER_API_KEY|OPENAI_API_KEY. Swap model/base_url to move between DeepSeek/Qwen/OpenAI with no code change.
- effort is now optional reasoning effort (low/medium/high), default None (off, suits non-reasoning flash); forwarded via OpenRouter extra_body reasoning when set. Dropped Anthropic cache_control (DeepSeek caches automatically).
- Structured output via response_format json_schema (strict). Kept verify() no-op fallback on error.
- CLI (scripts/evaluate_pipeline.py): --verify-model default deepseek/deepseek-v4-flash, --verify-effort default None choices low/medium/high, --verify help now says OPENROUTER_API_KEY.
- requirements.txt: anthropic -> openai.
- Verified: import OK; injected-fake-client test passes (keep/drop applied, reasoning only sent when effort set, empty-results short-circuits). No live API call made.

## 2026-06-10 — LLMVerifier: live OpenRouter smoke test (DeepSeek V4 Flash)
- Ran a real call via OpenRouter (key from .env). Model deepseek/deepseek-v4-flash.
- Input: 2 candidates. '0901234567' (upstream PHONE_NUMBER, STK context) -> correctly kept + relabeled BANK_ACCOUNT. '778899' (upstream ID, order number) -> correctly dropped.
- Structured json_schema output parsed cleanly; no fallback. Wiring confirmed end-to-end.

## 2026-06-10 — Full eval run via OpenRouter (regex_only + verify, 20 rows)
- Command: python scripts/evaluate_pipeline.py --pipeline regex_only --verify --limit 20
- Ran end-to-end, no verifier fallbacks/errors. Overall P=0.75 R=0.082 F1=0.148 (tp6 fp2 fn67).
- Per-entity: PHONE 1.0/1.0, EMAIL 1.0/1.0, BANK_ACCOUNT 1.0P/0.67R good. LOCATION/ORG/PERSON/DATE_TIME 0 recall.
- Low recall is expected: regex_only has no recognizers for those types, so candidates never reach the verifier (it cannot invent spans). This run validates plumbing, not detection quality.
- TODO: A/B verify on-vs-off on hybrid_regex / baseline_presidio to measure DeepSeek Flash's actual precision contribution.

## 2026-06-10 — Dataset abstraction (BaseDataset) + pii_masking_95k doc
- New package src/pipeline/Datasets/: BaseDataset (base.py), PiiMasking95kDataset + VI_PII_LABEL_TO_PRESIDIO (variants.py), registry.py (get_dataset/list_dataset_names), __init__.py. Mirrors the Pipelines package shape.
- Each dataset owns its label_to_presidio mapping (single source of truth). Evaluator.DEFAULT_LABEL_TO_PRESIDIO now imports VI_PII_LABEL_TO_PRESIDIO from the dataset (no cycle: base imports Utils lazily inside load()).
- BaseDataset.load() returns normalized df (source_text, privacy_mask, split, input_id); honors requires_token/text_column/mask_column. unmapped_labels(df) helper.
- Docs: docs/datasets/pii-masking-95k.md (full schema, span format, 23 mapped / 88 unmapped label taxonomy, MISC has no GT, eval implications) + docs/datasets/README.md (convention + index). AGENTS.md: added Datasets convention section.
- Dataset facts: nguyenlamtung/pii-masking-95k-preencoded, PRIVATE (HF_TOKEN). 95,122 rows (train 76,097 / test 9,513 / val 9,512). vi/VN/Latn. ~111 distinct labels; 23 map to 8 Presidio types (no MISC GT); 88 unmapped (money/health/credentials/vehicle/etc). Pre-encoded BIO columns use a baked-in tokenizer.
- Verified: package imports clean, no cycles, Evaluator constructs, ds.load(limit=5) returns required cols.

## 2026-06-10 — Verify-pass cost analysis (budget check)
- Measured real token usage on 25 live test-split calls (DeepSeek V4 Flash via OpenRouter).
- Only 44% of rows trigger an LLM call (regex finds no candidates in 56% -> verifier short-circuits). Docs tiny: src mean 126 tokens.
- Per call: ~714 input (105 cached), ~350 output -> ~$0.00013/call (prices in/cache/out = 0.0983/0.0028/0.1966 per 1M).
- Cost: test 9,513 rows ~$0.54 | val ~$0.54 | test+val ~$1.08 | full 95k ~$5.40. A/B run so far <2 cents total.
- Conclusion: full-test eval is cheap (~$0.54); do NOT run verify on train (76k, ~$4.30, it's for NER training). Caching ~irrelevant at this prefix size (confirms provider should be chosen on base price). Output (reason field) is the cost driver. Adding a NER recognizer pushes call rate toward 100% (~2x cost, still ~$1 on test).

## 2026-06-10 — OPEN PROBLEM: provider pinning breaks structured output (needs resolution)
Context: user saw OpenRouter rotating across providers for deepseek/deepseek-v4-flash. Root cause = our prompt prefix is tiny so caching barely engages, so OpenRouter's sticky routing never kicks in -> it load-balances across all providers. For reproducible eval we want to pin one provider.

What was added (code is in place, working):
- LLMVerifier: new `provider` param + `pin_provider(name, allow_fallbacks=False)` staticmethod. Passed through as extra_body.provider. Merges with reasoning extra_body.
- DEFAULT_PROVIDER="deepseek" constant; provider defaults (via _PROVIDER_UNSET sentinel) to pin_provider("deepseek") i.e. {"order":["deepseek"],"allow_fallbacks":False}. Pass provider=None to opt out (load-balance).
- CLI scripts/evaluate_pipeline.py: --verify-provider (default "deepseek"; "none"/"any"/"off" disables).

THE BUG (live-tested, reproducible):
- LLMVerifier() default (pinned deepseek, allow_fallbacks=False) -> API returns 404 {"message":"No endpoints found for deepseek/deepseek-v4-flash"}.
- Because verify() swallows errors -> it NO-OPS that row and keeps ALL regex candidates (kept the false positive). In an eval this SILENTLY CORRUPTS results. This is the allow_fallbacks=False risk realized.
- Note "deepseek" IS a valid online endpoint (see list below, status=0), so it's NOT a bad slug.

Hypothesis (was about to confirm when interrupted): our request forces response_format = json_schema strict. OpenRouter filters out endpoints that don't support structured outputs; with allow_fallbacks=False and a single pinned provider that lacks json_schema support, zero endpoints match -> 404. i.e. DeepSeek first-party endpoint likely doesn't support strict structured outputs.

Endpoints for deepseek/deepseek-v4-flash (from GET /api/v1/models/deepseek/deepseek-v4-flash/endpoints): 15 total. tag/slug | quant | ctx | status(0=ok):
  baidu/fp8 fp8 1048576 0 | deepinfra/fp4 fp4 0 | cloudflare unknown 0 | digitalocean unknown 0 | gmicloud/fp8 -2 | siliconflow/fp8 -2 | streamlake unknown 0 | alibaba unknown 0 | morph -5 | deepseek unknown 0 | parasail/fp8 0 | atlas-cloud/fp8 0 | akashml/fp8 0 | novita/fp8 0 | venice 0
  (Note: quant varies fp4/fp8/unknown across providers -> another reason to pin for consistent eval. Alibaba is present here too.)

NEXT STEPS to resolve (pick one):
1. CONFIRM hypothesis: run the diagnostic that was interrupted — call deepseek-pinned WITH vs WITHOUT response_format json_schema, and a no-pin call, and a {"provider":{"require_parameters":true}} call; read response.provider to see who actually serves structured output. (Test was written, user interrupted before running.)
2. If strict schema is the filter, options:
   (a) Pin a provider that DOES support structured outputs (likely an fp8 provider, e.g. novita/parasail/atlas-cloud/akashml). Trade-off: not first-party, fp8 quant.
   (b) Use provider={"require_parameters":true} (no hard pin) so OpenRouter only routes to structured-output-capable providers but still load-balances among them — fixes 404 but not full reproducibility.
   (c) Drop strict structured output: switch response_format to {"type":"json_object"} (looser) or plain prompt+json.loads, which more providers (incl. deepseek first-party) support. Verifier already tolerates parse errors via no-op.
   (d) Pin deepseek AND set allow_fallbacks=True so it prefers deepseek but won't 404.
3. SAFETY FIX regardless: the silent no-op on 404 is dangerous for eval integrity. Consider making LLMVerifier surface/raise routing/auth errors (4xx) instead of silently no-oping, OR have eval report the no-op count so corrupted runs are visible. Currently a misconfigured provider yields plausible-but-wrong metrics with no signal.

Decision still owned by user: which provider/quant to pin to (they can see prices+providers in dashboard). User chose "pin DeepSeek first-party" but that endpoint appears incompatible with strict structured output — so this needs revisiting.
