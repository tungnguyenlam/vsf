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

## 2026-06-10 — LLMVerifier provider routing safety fix
- Changed LLMVerifier default OpenRouter provider routing from hard-pinned first-party DeepSeek to {"require_parameters": true}, so strict json_schema calls only route to endpoints that support the requested parameters. Explicit hard pinning remains available via LLMVerifier.pin_provider("slug").
- Added raise_on_error to LLMVerifier. Default interactive behavior still falls back to no-op, but scripts/evaluate_pipeline.py now enables raise_on_error=True so routing/auth/schema failures stop eval instead of silently corrupting metrics.
- Updated --verify-provider default/help: require_parameters is default; provider slug hard-pins; none/any/off disables provider routing.
- Added focused tests for provider request payloads, keep/drop/relabel behavior, no-op fallback, and strict raise behavior.
- Verified: py_compile passed for changed Python files. Could not run pytest/evaluate help because local .venv lacks pytest, pip, presidio_analyzer, and spacy; system shell also lacks python/pytest commands.
- Residual risk: no live OpenRouter diagnostic was run; need one later to choose a reproducible structured-output-capable provider slug for benchmark mode.

## 2026-06-10 — LLMVerifier provider routing safety fix: verification follow-up
- Bootstrapped pip into .venv with ensurepip and installed missing local test/runtime dependencies: pytest, presidio-analyzer, presidio-anonymizer, spacy, openai.
- Verified: .venv/bin/python -m pytest tests/test_llm_verifier.py -q -> 5 passed. Existing lightweight tests -> 12 passed. Full suite -> 17 passed, 1 skipped. evaluate_pipeline.py --help renders the updated --verify-provider help.
- Residual risk unchanged: no live OpenRouter diagnostic was run; still need to choose a reproducible structured-output-capable provider slug for benchmark mode.

## 2026-06-10 — AGENTS.md: LLM budget and sampling discipline
- Added cost policy for the project-wide $2-$10 paid LLM budget.
- Hardened future-agent guidance: full train verifier runs are forbidden by default; use fixed 5k train/dev sample for cheap iteration; use 50/100-300/500/1000-row verifier tiers for smoke, iteration, A/B, and near-final decisions.
- Added preference for targeted verifier samples (candidate rows, numeric ambiguity, type mismatches, regex FP risk) and preserving JSONL logs for paid runs.
- Verified: AGENTS.md text reviewed; no code changes.
- Residual risk: this is policy only; no helper script yet persists a canonical 5k input_id sample.

## 2026-06-10 — Deterministic sample manifest helper
- Added src/pipeline/Datasets/sampling.py with default cost-policy sample tiers: train_dev_5k, llm_smoke_50, llm_iter_300, llm_ab_500, llm_final_1000.
- Added scripts/create_sample_manifests.py to load a registered dataset split and write deterministic input_id JSON manifests under data/sample_ids/ by default. Supports custom --tier NAME:SIZE, --random-state, and --overwrite.
- Updated AGENTS.md cost guidance to point future agents at the helper script.
- Added tests/test_dataset_sampling.py covering tier parsing, deterministic/capped sampling, manifest writing, and overwrite protection.
- Verified: py_compile passed for new files; script --help renders; tests/test_dataset_sampling.py -> 4 passed; full suite -> 21 passed, 1 skipped.
- Residual risk: actual pii_masking_95k manifests were not generated in this task to avoid an unsolicited private HF dataset download.

## 2026-06-10
- Changed prediction logging defaults to write each implicit run under `output/predictions/<run_id>/predictions.jsonl`, with timestamp-style run ids for new runs.
- Added an adjacent `predictions.readable.json` pretty-printed mirror for manual VSCode inspection while keeping machine JSONL one-record-per-line.
- Updated evaluation CLI default logging path handling and focused logging tests.
- Verified with `PYTHONPATH=. .venv/bin/pytest tests/test_prediction_jsonl_logging.py tests/test_pipeline_registry_and_evaluation.py` (12 passed).
- Residual risk: the readable JSON mirror rewrites the accumulated records on each append, so very large logs may be slower than JSONL-only logging.

## 2026-06-10 — LLM verifier sparse correction output
- Changed LLMVerifier structured output from one decision per candidate to sparse corrections: `drop` ids plus `relabel` corrections; omitted candidates are kept unchanged.
- Removed model-emitted `keep` and `reason` fields from the schema/prompt and lowered default max_tokens from 8192 to 1024.
- Updated verifier tests for sparse drop/relabel and no-change behavior.
- Verified: `PYTHONPATH=. pytest tests/test_llm_verifier.py -q` -> 6 passed; `PYTHONPATH=. pytest -q` -> 22 passed, 1 skipped.
- Residual risk: no live OpenRouter call was run, so structured-output provider compatibility with the new schema is still untested.

## 2026-06-10 — Sparse LLM verifier local smoke test
- Attempted live verifier smoke setup, but current shell has neither OPENROUTER_API_KEY nor OPENAI_API_KEY set.
- Ran a local fake-client smoke test for the new sparse schema. Verified request schema keys are `drop`/`relabel`, default max_tokens is 1024, relabel is applied, and dropped candidate is removed.
- Verified: `PYTHONPATH=. python3 - <<PY ...` local smoke passed.
- Residual risk: live OpenRouter structured-output compatibility remains untested until an API key is available in the shell.

## 2026-06-10 — Sparse LLM verifier live OpenRouter smoke test
- Loaded OPENROUTER_API_KEY from .env explicitly; shell environment does not auto-load .env.
- Ran one live OpenRouter verifier call with the new sparse structured-output schema (`drop` + `relabel`).
- Result: STK-like number was kept/relabelled as BANK_ACCOUNT and order-code number was dropped. This confirms the default require_parameters routing can serve the new strict schema.
- Verified: one live smoke command passed after network escalation.
- Residual risk: this was a single handcrafted row, not a sampled dataset evaluation.

## 2026-06-10 — Tiny live end-to-end verified evaluation
- Ran full pipeline eval with `regex_only`, test split, limit 5, and `--verify`, loading credentials from `.env`.
- Created prediction logs under `output/predictions/20260610T083008Z/`: 5-line `predictions.jsonl` and `predictions.readable.json`.
- Metrics on the tiny sample: precision 0.5, recall 0.1, f1 0.1667 (tp=1, fp=1, fn=9).
- Verified: command completed successfully with live OpenRouter verifier and private dataset access.
- Residual risk: sample is too small for model conclusions; source_text is null in logs because `--include-source-text` was not passed.

## 2026-06-10 — Tiny live verified eval for remaining pipeline variants
- Ran `baseline_presidio` and `hybrid_regex` on test split limit 5 with `--verify`, loading credentials from `.env`.
- baseline_presidio: precision 0.0, recall 0.0, f1 0.0 (tp=0, fp=0, fn=10), log `output/predictions/20260610T083503Z/predictions.jsonl`.
- hybrid_regex: precision 0.5, recall 0.1, f1 0.1667 (tp=1, fp=1, fn=9), log `output/predictions/20260610T083504Z/predictions.jsonl`.
- Verified both logs exist with 5 JSONL records and readable JSON mirrors.
- Residual risk: limit=5 smoke only; hybrid_regex currently matches regex_only because no extra recognizers were configured.

## 2026-06-10 — Pipeline class file split and reusable evaluation runner
- Split registered pipeline model classes into separate files: `baseline_presidio.py`, `regex_only.py`, and `hybrid_regex.py` under `src/pipeline/Pipelines/`.
- Updated registry/package exports to import the separate model files; kept `variants.py` as a compatibility re-export only.
- Added `src/pipeline/Pipelines/evaluation.py` as the reusable evaluation runner with the previous CLI options and local `.env` loading before dataset/verifier setup.
- Simplified `scripts/evaluate_pipeline.py` to a thin wrapper around the evaluation module.
- Verified: py_compile for changed runner/model files; `scripts/evaluate_pipeline.py --help`; focused tests -> 11 passed; full suite -> 22 passed, 1 skipped; tiny no-LLM CLI run `baseline_presidio --split test --limit 1 --no-log` completed.
- Residual risk: no verified LLM eval was rerun after this structural refactor, but the verifier behavior itself was already covered by tests.

## 2026-06-10 — Make pipeline models easier to spot and OO eval runner
- Moved pipeline model classes into `src/pipeline/Pipelines/Models/` with PascalCase filenames matching the class names: `BaselinePresidioPipeline.py`, `RegexOnlyPipeline.py`, and `HybridRegexPipeline.py`.
- Removed the lowercase root-level pipeline model files; root `Pipelines/` now keeps infrastructure files like `registry.py`, `base.py`, and `evaluation.py`.
- Kept public package imports and `variants.py` compatibility re-export working through `Pipelines.Models`.
- Refactored evaluation orchestration into `PipelineEvaluationConfig` and `PipelineEvaluationRunner` classes; CLI still calls the same script entrypoint.
- Added a registry test assertion that `RegexOnlyPipeline` comes from `src.pipeline.Pipelines.Models.RegexOnlyPipeline`.
- Verified: py_compile passed; `scripts/evaluate_pipeline.py --help` renders; `tests/test_pipeline_registry_and_evaluation.py` -> 5 passed; full suite -> 22 passed, 1 skipped.
- Residual risk: old notebooks that import from lowercase modules such as `src.pipeline.Pipelines.regex_only` would now need package-level or `Pipelines.Models` imports; current repo search found no such imports.

## 2026-06-10 — Pipeline docs updated for Models layout and OO runner
- Added `docs/README.md` as a docs index.
- Added `docs/pipelines.md` documenting `src/pipeline/Pipelines/Models/`, PascalCase model files, registry responsibilities, OOP evaluation runner usage, prediction logs, and sparse verifier output.
- Updated dataset docs to avoid stale `variants.py`-only guidance and to point CLI evaluation at `src/pipeline/Pipelines/evaluation.py`.
- Updated `AGENTS.md` with the pipeline model class convention for future agents.
- Verified: stale-reference scan found no old lowercase pipeline module references; `scripts/evaluate_pipeline.py --help` renders; full suite -> 22 passed, 1 skipped.
- Residual risk: notebook prose/output may still show older ad hoc pipeline examples, but no source imports referenced the removed lowercase pipeline modules.

## 2026-06-10 — Regex-only precision target reached without LLM
- Reworked `CustomPatternRecognizer` from broad Presidio `PatternRecognizer` rules into a custom `VietnameseContextRegexRecognizer` that returns value-only spans and requires high-confidence Vietnamese context for BANK_ACCOUNT and ID.
- Removed the low-precision location keyword regex from the base regex recognizer; regex-only now targets high-confidence EMAIL_ADDRESS, PHONE_NUMBER, BANK_ACCOUNT, and ID spans.
- Tightened phone matching to Vietnamese mobile-like prefixes and fixed CCCD/CMND matching to prefer 12 digits over 9 digits.
- Added regression tests for rejecting bare numeric false positives and keeping contextual STK/CCCD detections.
- Baseline before change on full test split without LLM: precision 0.3169, recall 0.1084, f1 0.1616.
- After change on full test split without LLM: precision 0.9835, recall 0.0975, f1 0.1774 (tp=4177, fp=70, fn=38680). Hybrid regex matches the same recognizer behavior.
- Verified: `PYTHONPATH=. pytest tests/test_pipeline_registry_and_evaluation.py -q` -> 7 passed; full suite -> 24 passed, 1 skipped; full test eval command completed with no `--verify`.
- Residual risk: precision target is achieved by sacrificing broad recall, especially LOCATION/PERSON/DATE_TIME/ORGANIZATION, which regex-only does not attempt now.

## 2026-06-10 — Regex-only per-entity metric improvements without LLM
- Added conservative context regex coverage for DATE_TIME, LOCATION, PERSON, ORGANIZATION, passport IDs, transaction IDs, and more bank-account contexts.
- Tightened LOCATION matching to case-sensitive administrative/address tokens with field-boundary stops; fixed `TP. ...` overrun and numeric district names such as `Quận 1`.
- Tightened BANK_ACCOUNT context so balance amounts after `Số dư hiện tại tài khoản` no longer count as accounts; BANK_ACCOUNT precision reached 1.0 on test.
- Added regression coverage for contextual date/location/person/org/passport/transaction matching.
- Final no-LLM full test split (`regex_only --split test --no-log --per-label`): precision 0.9808, recall 0.6187, f1 0.7588 (tp=26515, fp=518, fn=16342).
- Per-entity precision/recall/f1: BANK_ACCOUNT 1.0000/0.3588/0.5281; ID 1.0000/0.6139/0.7607; ORGANIZATION 0.9150/0.3651/0.5220; LOCATION 0.9780/0.8639/0.9174; PERSON 1.0000/0.3100/0.4733; DATE_TIME 1.0000/0.4361/0.6073; PHONE_NUMBER 0.9620/1.0000/0.9806; EMAIL_ADDRESS 1.0000/1.0000/1.0000.
- Verified: focused pipeline tests -> 8 passed; full suite -> 25 passed, 1 skipped.
- Residual risk: recall remains intentionally limited for PERSON/ORGANIZATION/DATE_TIME compared with an NER model; regex-only still cannot robustly cover free-form names or all organization mentions.

## 2026-06-10
- Ran lite regex_only evaluation after pulling latest master (test split, limit 50, no logging, no verifier).
- Verified per-entity metrics are emitted by the evaluation runner; overall precision 1.0000, recall 0.6175, F1 0.7635.
- Residual risk: sample is only 50 test rows and dataset generation/cache output occurred during the run; no full-suite tests run.

## 2026-06-10
- Re-ran lite regex_only evaluation with source-text JSONL logging at output/predictions/lite_false_analysis/predictions.jsonl.
- Analyzed unmatched predictions vs mapped ground truth: 0 FP and 83 FN; largest misses are PERSON 43, DATE_TIME 17, LOCATION 11.
- Residual risk: findings are from the deterministic 50-row test lite sample only; broader sample may reveal additional regex gaps.

## 2026-06-10
- Added targeted Vietnamese regex contexts for lite-sample false negatives: bilingual CCCD/account labels, hyphenated employee IDs, transaction subtypes, expanded date contexts, thôn/country address spans, split/person honorific names, and organization labels.
- Verified focused pipeline/evaluation tests pass: PYTHONPATH=. .venv/bin/pytest -q tests/test_pipeline_registry_and_evaluation.py (8 passed).
- Reran regex_only lite eval on test split limit 50 with source logging at output/predictions/lite_false_analysis_after2/predictions.jsonl: overall F1 improved from 0.7635 to 0.9177 with 0 FP; residual misses are mostly PERSON spans.
- Residual risk: changes are tuned from a 50-row sample; run the deterministic 5k/dev sample before relying on broad precision.

## 2026-06-10
- Added deterministic train-derived inspection splits: train_val (10% holdout from train) and train_main (remaining 90%), both using random_state=42.
- Updated CLI/dataset loading docs to use train_val for routine lite evaluation instead of test.
- Verified focused tests: PYTHONPATH=. .venv/bin/pytest -q tests/test_dataset_sampling.py tests/test_pipeline_registry_and_evaluation.py (13 passed).
- Ran train_val lite eval on 50 rows with source logging at output/predictions/train_val_lite/predictions.jsonl: precision 0.9769, recall 0.6546, F1 0.7840.
- Residual risk: prior test-split logs still exist from earlier analysis, but ongoing inspection should use train_val and keep test untouched for final reporting.

## 2026-06-10
- Ran full regex_only evaluation on official validation and test splits without verifier/logging at user request.
- Validation: 9512 rows, precision 0.9834, recall 0.6894, F1 0.8105. Test: 9513 rows, precision 0.9828, recall 0.6984, F1 0.8166.
- Residual risk: regex rules had previously been adjusted using a small test sample before the train_val workflow was added, so test is not a pristine untouched estimate for final reporting.

## 2026-06-10
- Added explicit regex_recall pipeline variant using CustomPatternRecognizer(recall_mode=True), preserving regex_only as the precision baseline.
- Inspected regex_only false negatives/false positives on train_val 300 and validation 500 logs, then added broader recall-oriented patterns for names, dates, organizations, IDs, bank accounts, and countries.
- Verified focused tests: PYTHONPATH=. .venv/bin/pytest -q tests/test_pipeline_registry_and_evaluation.py tests/test_dataset_sampling.py (13 passed).
- Final non-test comparison: train_val regex_only F1 0.8166 -> regex_recall F1 0.9045; validation regex_only F1 0.8105 -> regex_recall F1 0.8996.
- Residual risk: regex_recall trades precision for recall, especially DATE_TIME false positives; test split was not rerun for this recall-optimization task.

## 2026-06-10
- Added UndertheseaNER wrapper and explicit pipeline variants: underthesea_ner, underthesea_regex, and underthesea_regex_recall.
- Initial raw Underthesea train_val 100 eval was noisy: underthesea_ner F1 0.2892; unfiltered underthesea_regex F1 0.5436 with many PERSON/LOCATION false positives.
- Added filtered PERSON-only Underthesea usage for combined regex variants. Validation 500: regex_only F1 0.8122, underthesea_regex F1 0.8332, underthesea_regex_recall F1 0.9128.
- Observed memory with /usr/bin/time -l: validation 500 regex_only max RSS ~1.22GB/peak footprint ~387MB; underthesea_regex max RSS ~1.22GB/peak footprint ~450MB; cold 100-row runs showed max RSS up to ~2.96GB.
- Verified focused registry/evaluation tests: PYTHONPATH=. .venv/bin/pytest -q tests/test_pipeline_registry_and_evaluation.py (9 passed).
- Residual risk: Underthesea improves PERSON recall but introduces many PERSON false positives; only sampled validation runs were used, not full validation/test.

## 2026-06-10
- Calibrated UndertheseaNER span scores instead of using a fixed confidence: PERSON spans now get context/shape boosts and code/address/drug/money penalties, with low-score spans dropped.
- Updated combined Underthesea regex pipelines to use filtered PERSON-only Underthesea spans with min_score=0.70.
- Validation 500 after calibration: underthesea_regex precision 0.9646, recall 0.7439, F1 0.8400; underthesea_regex_recall precision 0.9502, recall 0.8941, F1 0.9213.
- Train_val 300 after calibration: underthesea_regex precision 0.9687, recall 0.7768, F1 0.8622.
- Verified focused tests: PYTHONPATH=. .venv/bin/pytest -q tests/test_pipeline_registry_and_evaluation.py (9 passed).
- Residual risk: calibration was tuned on small train_val/validation samples; run full validation before promoting Underthesea variants over regex_recall.

## 2026-06-10
- Ran full official validation comparison for regex_recall vs calibrated underthesea_regex_recall.
- regex_recall: precision 0.9658, recall 0.8420, F1 0.8996, runtime 7.22s, max RSS ~1.21GB, peak footprint ~405MB.
- underthesea_regex_recall: precision 0.9481, recall 0.8817, F1 0.9137, runtime 153.99s, max RSS ~1.21GB, peak footprint ~482MB.
- Underthesea improved PERSON recall from 0.5402 to 0.7431 and PERSON F1 from 0.7008 to 0.8082, but added 805 PERSON FP and is ~21x slower.
- Residual risk: full test was not run; use validation for selection and reserve test for final reporting.

## 2026-06-10
- Added detailed session report at report/2026-06-10-regex-underthesea-session.md covering regex tuning, train_val split, recall regex, Underthesea integration, calibration, metrics, runtime/RAM, and next steps.
- Verification: report file created; no code tests needed for documentation-only change.
- Residual risk: report summarizes current uncommitted working tree state and should be updated if metrics or pipeline variants change before submission.

## 2026-06-10
- Added scripts/mine_prediction_errors.py to mine FP/FN summaries from prediction JSONL logs with source text, recognizer, pattern, span text, and context.
- Ran it on output/predictions/underthesea_regex_recall_validation_500_calibrated/predictions.jsonl and wrote output/error_analysis/underthesea_regex_recall_validation_500_calibrated/{summary.md,summary.json}.
- Findings from the 500-row calibrated validation sample: 96 FP and 217 FN; FP mostly PERSON/DATE_TIME, and most FP came from regex patterns rather than Underthesea after calibration.
- Verified focused tests: PYTHONPATH=. .venv/bin/pytest -q tests/test_pipeline_registry_and_evaluation.py tests/test_dataset_sampling.py (14 passed).
- Residual risk: script currently uses evaluator-style overlap matching and mapped labels only; future versions could add exact-match mode or unmapped-label diagnostics.

## 2026-06-10
- Tightened deterministic Vietnamese regex recall cleanup after inspecting validation false positives for underthesea_regex_recall. Updated location/date/year/bank-account patterns in src/pipeline/Recognizers/CustomPatternRecognizer.py to remove high-volume validation false positives such as issue dates, generic years, police issuance locations, and income-like bank-account matches.
- Verified with: PYTHONPATH=. .venv/bin/pytest -q tests/test_pipeline_registry_and_evaluation.py tests/test_dataset_sampling.py (14 passed).
- Ran validation 500 and full validation for underthesea_regex_recall without touching test. Full validation after cleanup: precision 0.9659196530, recall 0.8713839847, F1 0.9162197242, TP 37412, FP 1320, FN 5522. Compared with previous full validation calibrated run, precision improved and F1 rose slightly, while recall dropped.
- Residual risk: cleanup is precision-leaning, not recall-optimized. Remaining errors are mostly PERSON/ORGANIZATION from NER/label-boundary mismatch. Full underthesea validation run was slow and peaked around 1.97GB RSS, so keep it optional and use smaller validation slices for iteration.

## 2026-06-10
- Updated report/2026-06-10-regex-underthesea-session.md with the post-cleanup validation results, precision/recall tradeoff, per-entity metrics, runtime/RAM observation, and updated recommendation that further gains should move toward a resolver/verifier rather than broad regex tuning.
- Verified by reviewing the report diff; no code or tests changed in this documentation-only step.
- Residual risk: report now includes both the earlier and later Underthesea runtime observations, which should be interpreted as environment/run variance rather than a stable benchmark.

## 2026-06-10
- Added deterministic resolver support as a post-Analyzer hook in PIIPipeline and registered underthesea_regex_recall_resolved. The v1 resolver only suppresses Underthesea PERSON candidates in strong left-side organization/document/product/code contexts while preserving person-label contexts.
- Updated docs/pipelines.md and report/2026-06-10-regex-underthesea-session.md with resolver behavior and A/B results.
- Verified with: PYTHONPATH=. .venv/bin/pytest -q tests/test_pipeline_registry_and_evaluation.py tests/test_prediction_jsonl_logging.py (17 passed).
- Evaluated underthesea_regex_recall_resolved on validation limit 500: precision 0.9689673622, recall 0.8834146341, F1 0.9242153611, TP 1811, FP 58, FN 239. Compared with unresolved validation 500, this is a tiny precision/F1 gain with one extra FN.
- Evaluated train_val limit 500: resolved precision 0.9666505558, recall 0.8992805755, F1 0.9317493594, TP 2000, FP 69, FN 224; unresolved comparison was precision 0.9647853353, recall 0.8992805755, F1 0.9308820107, TP 2000, FP 73, FN 224.
- Residual risk: effect size is small and current logs only show final kept spans, not resolver-dropped candidates. Add resolver decision logging before relying on this for larger tuning.

## 2026-06-11
- Added docs/current-direction.md to preserve the agreed project guidance: finish a presentable Vietnamese PII checkpoint before moving to prompt injection detection.
- Linked the guidance note from docs/README.md.
- Verification: reviewed the new note and docs index diff.
- Residual risk: this is a planning/documentation note only; the current staged resolver implementation still needs to be committed or otherwise stabilized separately.

## 2026-06-11
- Added docs/pii-checkpoint.md as a mentor-ready Vietnamese PII checkpoint covering entity scope, dataset, metrics, method comparison, current recommendation, TODOs, and mentor confirmation questions.
- Updated docs/README.md to link both current-direction and PII checkpoint guidance.
- Verification: PYTHONPATH=. .venv/bin/pytest -q tests/test_pipeline_registry_and_evaluation.py tests/test_prediction_jsonl_logging.py (17 passed).
- Residual risk: Vietnam-specific checksum/format rules are listed as research items and still need official-source confirmation before seminar or production claims.

## 2026-06-11
- Added docs/vietnamese-pii-research.md with Vietnam-specific PII engineering notes for CCCD/CMND, passport, tax code, bank account, phone, address, names, organizations, dates, and future unmapped PII categories.
- Linked the research note from docs/README.md.
- Verification: PYTHONPATH=. .venv/bin/pytest -q tests/test_pipeline_registry_and_evaluation.py tests/test_prediction_jsonl_logging.py (17 passed).
- Residual risk: official legal/checksum references could not be confirmed in this environment, so the doc explicitly marks those points as research items rather than settled facts.

## 2026-06-11
- Added report/pii-checkpoint-summary.md as a concise presentation package for the Vietnamese PII checkpoint, using project open questions rather than mentor-specific open questions.
- Added scripts/demo_pii_checkpoint.py to demonstrate regex_recall detection and Presidio anonymization on Vietnamese sample texts.
- Verification: PYTHONPATH=. .venv/bin/python scripts/demo_pii_checkpoint.py completed successfully; PYTHONPATH=. .venv/bin/pytest -q tests/test_pipeline_registry_and_evaluation.py tests/test_prediction_jsonl_logging.py (17 passed).
- Residual risk: the demo consolidates exact duplicate display spans for readability, but does not change the underlying pipeline behavior.

## 2026-06-11
- Pushed the completed PII checkpoint commits to origin/master.
- Ran scripts/demo_pii_checkpoint.py through the project virtualenv and reviewed report/pii-checkpoint-summary.md for presentation readiness.
- Added the first prompt-injection detection checkpoint: RuleBasedPromptInjectionDetector, result/rule dataclasses, demo script, docs, and focused tests.
- Verification: PYTHONPATH=. .venv/bin/python scripts/demo_prompt_injection.py completed successfully; PYTHONPATH=. .venv/bin/pytest -q tests/test_prompt_injection_detector.py tests/test_pipeline_registry_and_evaluation.py tests/test_prediction_jsonl_logging.py (21 passed).
- Residual risk: prompt-injection detector is a Vietnamese-first heuristic baseline with no dataset/benchmark yet; next step is a small labeled evaluation set and JSONL decision logging.

## 2026-06-11
- Added HoangHa/vie-pii as a gated registry-backed dataset with inline markup parsing, dataset-specific label mapping, deterministic train_main/train_val/test splits, and dataset docs.
- Added regex_recall_vie_pii as an opt-in corpus-tuned pipeline so HoangHa-specific broad rules do not replace the default regex_recall pipeline.
- Evaluated regex_recall and regex_recall_vie_pii on hoangha_vie_pii test and pii_masking_95k validation; wrote report/2026-06-11-hoangha-vie-pii-cross-dataset.md with metrics and recommendation.
- Verification: PYTHONPATH=. .venv/bin/pytest -q tests/test_dataset_sampling.py tests/test_pipeline_registry_and_evaluation.py tests/test_prediction_jsonl_logging.py (24 passed); authenticated split smoke confirmed validation aliases to train_val.
- Residual risk: HoangHa/vie-pii labels are noisy and broad, so metrics are best interpreted as cross-dataset robustness rather than a clean production estimate.

## 2026-06-11
- Updated AGENTS.md collaboration workflow to require a concrete recommended next step after every completed task.
- Verification: reviewed AGENTS.md diff; no code tests needed for instruction-only change.
- Residual risk: none.

## 2026-06-11
- Added a prompt-injection evaluation path with a repo-owned Vietnamese seed JSONL, a public HuggingFace adapter for rikka-snow/prompt-injection-multilingual, JSONL decision logging, a CLI evaluator, dataset docs, and a baseline report.
- Verification: PYTHONPATH=. .venv/bin/pytest -q tests/test_prompt_injection_detector.py tests/test_prompt_injection_evaluation.py tests/test_pipeline_registry_and_evaluation.py tests/test_prediction_jsonl_logging.py (24 passed); local seed evaluation reached precision/recall/F1 1.0 on 24 seed rows; HF multilingual 100-row smoke reached recall 0.0 as expected for Vietnamese-only rules on mostly non-Vietnamese examples.
- Residual risk: the local seed is hand-written and easy for the current rules; expand it with ambiguous benign, retrieved-context, mixed-language, and tool-state examples before treating metrics as meaningful.

## 2026-06-11
- Refactored the prompt-injection package into class-centric one-class-per-file modules for models, detectors, datasets, evaluation, and logging, with compatibility shims left at the old module paths.
- Expanded the local Vietnamese prompt-injection seed from 24 to 40 rows with ambiguous benign security-education prompts, mixed Vietnamese/English attacks, indirect retrieved-context injections, and expected-action labels for review/block/allow checks.
- Tightened rule behavior for mixed-language attacks, direct shell permission bypass, indirect retrieved-context injection, and benign security-discussion suppression.
- Verification: PYTHONPATH=. .venv/bin/pytest -q tests/test_prompt_injection_detector.py tests/test_prompt_injection_evaluation.py tests/test_pipeline_registry_and_evaluation.py tests/test_prediction_jsonl_logging.py (27 passed); scripts/demo_prompt_injection.py ran successfully; local seed evaluation reached precision/recall/F1/action accuracy 1.0 on 40 rows; one-class-per-file class-count check passed.
- Residual risk: the 40-row seed is still hand-written and should be supplemented with real mentor/application examples plus a decision-log error miner before treating metrics as representative.

## 2026-06-11
- Added scripts/mine_prompt_injection_errors.py to mine false positives, false negatives, and expected-action mismatches from prompt-injection decision JSONL logs. The miner writes summary.json and summary.md with matched-rule/category breakdowns and example text when source_text is logged.
- Documented the prompt-injection error-mining workflow in docs/prompt-injection.md.
- Verified with: PYTHONPATH=. .venv/bin/pytest -q tests/test_prompt_injection_detector.py tests/test_prompt_injection_evaluation.py tests/test_pipeline_registry_and_evaluation.py tests/test_prediction_jsonl_logging.py (28 passed).
- Ran a local seed evaluation with --include-source-text and mined the resulting decision log; the 40-row hand-written seed remains perfect, so the mined report has no FP/FN/action mismatches.
- Residual risk: the miner is only useful once logs include realistic mistakes; the current seed is still too small and curated to represent real-world prompt-injection performance.

## 2026-06-11
- Documented the manual prompt-injection tuning loop in docs/prompt-injection.md, including copy-paste commands for local seed evaluation, decision-log mining, reading the mined report, and focused test runs.
- Added concrete seed-expansion priorities: ambiguous benign security prompts, retrieved-context injections, tool permission/state cases, mixed Vietnamese/English attacks, and review-vs-block boundary cases.
- Verification: reviewed docs/prompt-injection.md diff; documentation-only change, no tests run.
- Residual risk: commands assume the project virtualenv exists at .venv and are intended for local development from the repository root.

## 2026-06-11
- Expanded data/prompt_injection/vietnamese_seed.jsonl from 40 to 65 rows with harder ambiguous benign security prompts, retrieved-context/document injections, tool permission/state bypasses, mixed Vietnamese/English attacks, and review-vs-block boundary cases.
- Tuned RuleBasedPromptInjectionDetector using the mined decision-log errors: broader benign meta-analysis suppression, block-level direct instruction override/tool-bypass/retrieved-context signals, short English hidden-prompt print detection, and additional mixed-language data/tool patterns.
- Updated dataset docs, baseline report, and prompt-injection tests for the 65-row checkpoint.
- Verification: initial expanded-seed run found precision 0.814, recall 0.897, F1 0.854 with 8 FP, 4 FN, and 17 action mismatches; after tuning, local seed evaluation reached precision/recall/F1/action accuracy 1.0 on 65 rows. Final focused suite: PYTHONPATH=. .venv/bin/pytest -q tests/test_prompt_injection_detector.py tests/test_prompt_injection_evaluation.py tests/test_pipeline_registry_and_evaluation.py tests/test_prediction_jsonl_logging.py (30 passed).
- Residual risk: this remains a hand-written regression seed, so perfect local metrics should not be treated as production performance; next validation needs mentor/application examples or real traffic-shaped prompts.

## 2026-06-11
- Added local_vietnamese_app_seed: a 30-row application-shaped Vietnamese prompt-injection smoke dataset covering support workflows, tool permission checks, retrieved documents, refund/payment APIs, logs, policy summaries, and credential/user-data exfiltration.
- Registered the dataset, added dataset docs/index entries, updated prompt-injection docs and the baseline report with app-seed commands and metrics.
- Tuned RuleBasedPromptInjectionDetector from mined app-seed errors: benign policy-summary suppression, app-shaped approval/tool-call bypass phrasing, retrieved help-document phrasing, credential dump/external secret exfiltration, and user chat/personal-info exfiltration.
- Verification: initial app-seed run found precision 0.9412, recall 0.8000, F1 0.8649 with 1 FP, 4 FN, and 9 action mismatches; final app-seed run reached precision/recall/F1/action accuracy 1.0 on 30 rows. Final focused suite: PYTHONPATH=. .venv/bin/pytest -q tests/test_prompt_injection_detector.py tests/test_prompt_injection_evaluation.py tests/test_pipeline_registry_and_evaluation.py tests/test_prediction_jsonl_logging.py (32 passed).
- Residual risk: app seed is still synthetic; use mentor/application examples next to test whether these app-shaped patterns hold outside hand-written prompts.

## 2026-06-11
- Checked whether pipeline evaluation results are saved under output. Found prediction JSONL logging to output/predictions, while evaluation metric summaries are printed/returned and not persisted by the current evaluation runner.
- Verified by inspecting src/pipeline/Pipelines/evaluation.py, scripts/evaluate_pipeline.py, src/pipeline/BasePipeline.py, and src/pipeline/PredictionJsonlLogger.py.
- Residual risk: none for the code-path inspection; no tests were run because no code changed.

## 2026-06-11
- Changed PII evaluation outputs so each run writes metrics to output/evaluations/<run_id>/metrics.json and default prediction logs to the same run directory. Updated CLI output fields and docs.
- Verified with python3 -m pytest tests/test_pipeline_registry_and_evaluation.py tests/test_prediction_jsonl_logging.py.
- Residual risk: existing direct PIIPipeline default logs still use output/predictions; only evaluation defaults were restructured.

## 2026-06-11
- Changed PII evaluation run layout to group default artifacts by pipeline/model name: output/evaluations/<pipeline>/<run_id>/.
- Verified with python3 -m pytest tests/test_pipeline_registry_and_evaluation.py tests/test_prediction_jsonl_logging.py.
- Residual risk: existing run folders are not migrated; only new evaluation runs use the model-first layout.

## 2026-06-11
- Ran a smoke PII evaluation for regex_only with split=train_val and limit=1 to confirm the model-first output layout.
- Verified artifacts exist under output/evaluations/regex_only/20260611T074448Z/: metrics.json, predictions.jsonl, and predictions.readable.json.
- Residual risk: this was only a one-row smoke check, not a quality evaluation.

## 2026-06-11
- Added report/2026-06-11-presidio-internal-mechanics.md explaining Presidio AnalyzerEngine flow, confidence score sources, validation, context boosting, duplicate removal, thresholds, allow lists, decision process fields, and repo-specific Vietnamese analyzer behavior.
- Verified by inspecting the old notebook and installed presidio-analyzer 2.2.362 source; ran git diff --check.
- Residual risk: this is a static mechanics report, not a refreshed executable demo notebook.

## 2026-06-11 - Reran report result commands
- Regenerated report-folder evaluation outputs using system `python` because `.venv/bin/python` is absent on this machine.
- Ran PII demo, regex_recall train_val limit-50, underthesea_regex_recall_resolved train_val limit-50, prompt-injection local/app/HF smoke checks, HoangHa test check, and pii_masking_95k validation check.
- Verified outputs were written under `output/evaluations/` and `output/prompt_injection/`; `--no-log` runs produced metrics only.
- Residual risk: current prompt-injection local seed action accuracy is 0.976744, not the 1.0000 documented in the report, and HF smoke metrics differ from the report.

## 2026-06-11 - Fixed prompt-injection report rerun mismatch
- Changed `vi-seed-032` expected action from `review` to `block` because direct API key/token dumping is a blocking data-exfiltration request under the current detector rules.
- Added detector and evaluator regression tests for the direct credential/token dump case and full local seed action accuracy.
- Verified `python -m pytest -q tests/test_prompt_injection_detector.py tests/test_prompt_injection_evaluation.py` passes and regenerated `output/prompt_injection/prompt-injection-local-seed/`.
- Residual risk: HF multilingual smoke remains a known cross-language failure for the Vietnamese-first rule detector.

## 2026-06-11 - Added mentor prompt-injection smoke result
- Ran `local_vietnamese_mentor_seed` with decision logging and source text under `output/prompt_injection/prompt-injection-mentor-seed/`.
- Mined the mentor decision log into `output/prompt_injection_error_analysis/prompt-injection-mentor-seed/summary.md`.
- Updated `report/2026-06-11-prompt-injection-dataset-baseline.md` with the mentor command, metrics, and current failure summary.
- Verified the run completed: precision 1.0000, recall 0.9333, F1 0.9655, action accuracy 0.7600.
- Residual risk: mentor/demo seed is not tuned yet; it has 1 FN and 6 action mismatches.

## 2026-06-11 - Tuned mentor prompt-injection seed
- Added targeted deterministic rules for mentor seed misses: user-over-developer instruction priority, production config secret access, external chat-history exfiltration, Vietnamese `tắt guardrail`, and plain `xuất dữ liệu cá nhân`.
- Narrowed direct shell permission bypass so generic `lệnh ẩn` encoded-instruction cases remain `review` instead of escalating to `block`.
- Fixed prompt-injection decision logging so rerunning the same `run-id` replaces the JSONL/readable logs instead of appending duplicate records.
- Updated prompt-injection docs and report with the tuned mentor result.
- Verified `python -m pytest -q tests/test_prompt_injection_detector.py tests/test_prompt_injection_evaluation.py` passes; regenerated local/app/mentor/HF prompt-injection outputs and mentor error mining summary.
- Residual risk: HF multilingual smoke still has precision/recall/F1 0.0000 because the detector remains Vietnamese-first by design.

## 2026-06-12 - Added PII resolver audit logs
- Added structured resolver_audit records for deterministic PII resolver decisions, including keep/drop action, reason, span text, context, recognizer, and counts.
- Added generated predictions.audit.md beside prediction JSONL/readable logs so humans can review final spans and resolver drops without reading raw JSON.
- Updated pipeline docs and current-direction notes for the new audit artifact.
- Verified with: python -m pytest -q tests/test_prediction_jsonl_logging.py tests/test_pipeline_registry_and_evaluation.py (20 passed).
- Residual risk: audit currently covers the deterministic resolver stage only; verifier decisions are still represented through final spans rather than a separate verifier decision table.

## 2026-06-12 - Ran resolver audit sample
- Ran underthesea_regex_recall_resolved on a 50-row train_val sample with source text; generated metrics plus predictions.jsonl/readable/audit artifacts under output/evaluations/underthesea_regex_recall_resolved/20260612T090729Z.
- Because the 50-row sample had no resolver drops, ran a 500-row train_val sample under output/evaluations/underthesea_regex_recall_resolved/20260612T105503Z for manual audit coverage.
- 500-row metrics: precision 0.9667, recall 0.8993, F1 0.9317; resolver audit had 2,069 keep decisions and 4 drops across 4 rows.
- Drop reasons: 3 document/code-field context drops and 1 organization-context drop.
- Residual risk: this is a deterministic train_val sample and not final reporting; the human audit still needs a manual correctness pass over the four dropped rows in predictions.audit.md.
- 2026-06-16: Added pluggable prompt-injection detectors with an experimental trainable char-ngram baseline, leave-one-out evaluation support, and detector selection in the prompt-injection CLI/docs. Verified with python3 -m pytest -q tests/test_prompt_injection_detector.py tests/test_prompt_injection_evaluation.py and manual detector comparison on local_vietnamese_seed/local_vietnamese_mentor_seed. Residual risk: the trainable baseline is intentionally weak and current seed datasets are too small and rule-aligned to judge a production model fairly.
- 2026-06-16: Scoped image anonymization integration requirements for the Presidio-based Vietnamese PII pipeline. Verified current pipeline flow in BasePipeline, VietnamesePipeline, evaluation runner, and checkpoint docs. Residual risk: image path not yet implemented; OCR/box-level evaluation format still needs a concrete dataset choice.

## 2026-06-16 — Demo website (Flask) for the guardrail pipeline
- Added webdemo/: Flask app (app.py) + single-page UI (templates/index.html) + README.md.
- Reuses existing seams: get_pipeline()/list_pipeline_names() for PII and get_prompt_injection_detector()/list_prompt_injection_detector_names() for prompt injection. Pipelines/detectors selectable via dropdowns, lazy-loaded and cached (Presidio warm-up). dedupe_exact_spans mirrors demo_pii_checkpoint.py.
- Endpoints: POST /api/analyze (injection screen then PII+anonymize), /api/prompt-injection, /api/pii. UI highlights PII spans by entity type, shows allow/flag/block verdict + matched rules/categories/evidence, and the anonymized text.
- Verified live: python -m webdemo.app on :5000; /api/analyze on a mixed sample correctly returns action=block (ignore_previous_instructions + reveal_hidden_prompt) and masks PHONE_NUMBER + EMAIL_ADDRESS; index serves 200.
- Note: Flask not yet in requirements.txt; was already importable in the active env.
- 2026-06-16: Added docs/image-safety-pipeline.md with a Mermaid graph and design notes for OCR, PII redaction, VLM safety classification, and fallback routing. Verified the new doc renders structurally via readback and linked it from docs/README.md. Residual risk: this is a design doc only; OCR/redaction/VLM interfaces are not implemented yet.
- 2026-06-16: Added docs/full-safety-pipeline.md with a Mermaid graph for the combined text and image safety flow, including PII anonymization, VLM classification, and fallback routing. Verified the doc by readback and linked it from docs/README.md. Residual risk: this is still architectural documentation; shared router and multimodal interfaces remain unimplemented.
- 2026-06-16: Soạn prompt nghiên cứu sâu cho web agent về thiết kế bộ dữ liệu huấn luyện unified model đa nhiệm (PII, prompt injection, topic safety). Xác minh: rà lại yêu cầu user và phạm vi chỉ dừng ở research prompt, chưa thay đổi code. Rủi ro còn lại: cần chốt taxonomy nhãn và tiêu chí ưu tiên giữa OCR-level, page-level, và region-level trước khi thu thập dữ liệu.

## 2026-06-16 — Demo website: request log view + light mode
- webdemo/app.py: each POST /api/analyze now appends a JSONL record (timestamp, input, PI verdict/score/rules/categories, PII pipeline/entity types/anonymized) to webdemo/logs/demo_requests.jsonl. Added GET /api/log (most-recent-first, capped 200) and DELETE /api/log (clear). Lightweight demo logger, not the eval PredictionJsonlLogger.
- templates/index.html: switched palette to light mode (GitHub-light tokens). Added Analyze/Log tab nav. Log tab renders collapsible rows with verdict badge, timestamp, snippet, PII count, and full details on expand; Refresh + Clear buttons.
- .gitignore: ignore webdemo/logs/. README updated with log endpoints + Log view.
- Verified live on :5001: two analyses logged, GET /api/log returns newest-first with correct block/allow verdicts and masked PHONE/EMAIL; DELETE clears to [].

## 2026-06-16
- Task: Synthesized dataset-creation reports into a 2-day high-yield plan for the current Vietnamese PII pipeline.
- Changed: No code changes; planned a text-first weak/gold dataset strategy aligned with existing `source_text` / `privacy_mask` / Presidio entity mappings.
- Verified: Reviewed the four deepresearch reports plus current dataset/pipeline docs and dataset loader code.
- Residual risk: Plan still depends on manual review quality and, if implemented later, access to HF-gated datasets/API budget.

## 2026-06-16
- Task: Corrected dataset/model plan to include mandatory prompt injection detection and topic filtering alongside PII.
- Changed: No code changes; defined multi-head/masked-loss strategy and model recommendation tradeoffs for PhoBERT/Qwen/LFM-style backbones.
- Verified: Checked current Hugging Face model cards for LiquidAI/LFM2.5-VL-450M, Qwen/Qwen3-0.6B, and VinAI PhoBERT variants.
- Residual risk: Final model choice depends on available GPU memory, license constraints, and whether v0 uses OCR text only or rendered page images.

## 2026-06-16
- Task: Refined safety model plan for image-first moderation after OCR/PII redaction.
- Changed: No code changes; clarified that the trained model must consume redacted image plus OCR/redaction metadata to catch visual sexual/violence/blood content beyond OCR.
- Verified: Reasoned against the proposed pipeline and prior model/dataset plan.
- Residual risk: Final architecture still depends on available compute for VL fine-tuning and quality of rendered/manual image labels.

## 2026-06-16
- Task: Explained how to train/extract outputs from a vision-language model for multi-head safety routing.
- Changed: No code changes; clarified generative JSON vs classifier-head approaches, pooling from hidden states, output formats, and mixed image/text sample handling.
- Verified: Matched the explanation to the proposed Image -> OCR -> Presidio -> redacted image -> safety model pipeline.
- Residual risk: Exact implementation details will depend on the selected HF model class and available training stack.

## 2026-06-16
- Task: Documented the shared VLM safety router and updated full/image safety pipeline docs.
- Changed: Added `docs/vlm-safety-router.md`; revised `docs/full-safety-pipeline.md` so every text/image/mixed artifact goes through the shared VLM router; aligned `docs/image-safety-pipeline.md`; added the router doc to `docs/README.md`.
- Verified: Scanned docs for stale separate-classifier wording and checked git status for touched files.
- Residual risk: Documentation only; implementation still needs router interface, JSON validation, dataset loader, and model training code.

## 2026-06-16
- Task: Revised safety pipeline diagrams to match split-process-merge architecture.
- Changed: Updated `docs/full-safety-pipeline.md` Mermaid flow so input splits into text/image branches, text and OCR text pass through PII pipelines, image PII boxes are blurred, OCR text is anonymized, then sanitized text/image/metadata merge before the shared VLM router. Updated `docs/image-safety-pipeline.md` similarly.
- Verified: Re-read the edited Mermaid sections for node flow and stale wording.
- Residual risk: Mermaid rendering was not compiled visually; docs are untracked in git status and need adding before commit.

## 2026-06-16
- Added DATA_PLAN.md for safety_v0 dataset construction, including candidate checklist, unified schema, box/span/redaction IDs, prompt-injection weak-label plan, review workflow, and next dataset order.
- Verified by reading the new plan back with sed. No tests run; docs-only change.
- Residual risk: candidate dataset schemas/licenses still need source-by-source inspection before converters or downloads.

## 2026-06-16
- Updated DATA_PLAN.md to make dataset construction pipeline-first: converter, OCR, PII detection/redaction, prompt-injection detection, weak visual/topic labeling, schema validation, then human/API review for uncertain or incorrect fields.
- Replaced the compact dataset table with per-source work blocks so each source has room for notes, converter outputs, first-pass pipeline steps, human review focus, and completion criteria.
- Clarified that human review can correct labels, OCR boxes, PII/prompt-injection spans, and redaction metadata, but should not be first-pass labeling from blank samples.
- Verified by reading the updated DATA_PLAN.md sections back. No tests run; docs-only change.
- Residual risk: actual dataset schemas, licenses, and sample quality still need source-by-source inspection before converters are implemented.

## 2026-06-16
- Updated DATA_PLAN.md to list only active v0 dataset sources and removed skipped/later-only sources from the work queue and target mix.
- Added the safety_v0 project folder structure for download scripts, inspection scripts, converters, OCR/PII/prompt-injection/weak-label stages, review outputs, verified rows, final JSONL files, manifests, and source docs.
- Updated converter, weak-label, human override, verified, and final dataset paths so converted labels and final verified datasets have clear locations.
- Verified with rg that removed dataset names and stale interim paths no longer appear. No tests run; docs-only change.
- Residual risk: folder structure is documented but the actual scripts/schema validator still need to be implemented.

## 2026-06-16 — safety_v0 schema + validator (DATA_PLAN Step 1)
- Added `src/pipeline/Datasets/safety_v0_schema.py`: canonical-row builders
  (`new_row`, `new_ocr_box`, `new_pii_span`, `new_prompt_injection_span`,
  `new_redaction`), label helpers (`empty_labels`, `derive_label_mask`,
  `model_target`), and `validate_row`/`is_valid_row`.
- Validator implements the DATA_PLAN Step-1 checklist: required top-level keys,
  unique box/span/redaction IDs within a row, span `box_ids` -> existing OCR
  boxes, redaction `source_span_ids` -> existing spans and `box_ids` -> existing
  boxes, label value constraints (action in safe/reject/unsure or null; risks
  bool or null), and box geometry shape. `derive_label_mask` enforces
  `null = unknown` (never trains unknown as negative).
- Placement follows the updated DATA_PLAN "Project Folder Structure"
  (`src/pipeline/Datasets/safety_v0_schema.py`); removed an earlier off-plan
  `src/pipeline/Safety/` package draft.
- Verified: `tests/test_safety_v0_schema.py` (26 tests) passes.
- Residual risk: `safety_v0_sources.py` (stable source names + path helpers)
  not yet written; data/ and scripts/safety_v0/ trees not created.

## 2026-06-16 — safety_v0 source registry + path helpers (DATA_PLAN Step 1 cont.)
- Added `src/pipeline/Datasets/safety_v0_sources.py`: `SafetySource` registry
  (11 work-queue sources with stable slugs, upstream names, decisions, image
  flag), `format_input_id` (safety_v0_<slug>_NNNNNN), and path helpers for the
  DATA_PLAN folder layout (`converted_path`, `weak_path`, `human_overrides_path`,
  `source_dir`, `shared_dir`, `final_dir`, `manifests_dir`, etc.). `create=True`
  makes dirs; default root = data/safety_v0 under repo root, overridable.
- Keeps all data/safety_v0 paths out of converters/scripts (single source of
  truth for the layout).
- Verified: `tests/test_safety_v0_sources.py` (9) + schema tests, 35 total pass.
- Residual risk: data/safety_v0 and scripts/safety_v0 trees not yet created;
  no converters written.

## 2026-06-16 — existing_repo_pii converter + validate CLI (DATA_PLAN Steps 1/3)
- Added `scripts/safety_v0/convert/convert_existing_repo_pii.py`: converts the
  repo PII datasets (pii_masking_95k, hoangha_vie_pii) into canonical safety_v0
  rows. Gold privacy_mask spans -> detections.pii_spans (per-dataset
  label_to_presidio, detector="source_gold"); deterministic anonymization into
  sanitized_text; PII-only label policy (action=safe, pii_visible/prompt_injection/
  political/religious=false with label_source, visual labels null/masked-out).
  Straight convert: no LLM verifier / weak-review pass, per user direction.
- Added `scripts/safety_v0/validate_safety_v0.py`: CLI wrapping validate_row over
  JSONL files; per-file pass/fail counts, first errors, non-zero exit on invalid.
- Added `docs/datasets/existing_repo_pii.md` + index row in datasets README.
- Verified: `tests/test_convert_existing_repo_pii.py` (6, importlib-loaded, no
  download) + validate CLI smoke (1 valid / 1 invalid, exit 1). Full suite 99 pass.
- Not run on real data yet (gated sources need HF_TOKEN + download; kept optional
  per project policy). Residual risk: real-data run/row counts unverified;
  visual-label-null policy is a stated assumption open to revision.

## 2026-06-16 — webdemo safety_v0 review/annotate tab (DATA_PLAN Step 6)
- Added `webdemo/safety_v0_review.py`: load canonical rows + apply human
  overrides (latest per input_id wins), discover canonical files under
  data/safety_v0, save overrides to review/human_overrides/<slug>.jsonl (slug
  inferred from converted/weak path, else file stem), path-traversal-guarded
  file/image resolution, tri-state label coercion (true/false/null).
- Wired routes into `webdemo/app.py`: GET /api/review/files, /api/review/rows,
  /api/review/image, POST /api/review/save.
- Added "Annotate" tab to `templates/index.html`: renders input text (PII
  highlighted), sanitized text, original/redacted images, OCR text+boxes, PII /
  prompt-injection span tables, source labels; editable label form (action
  radio, 7 risk tri-state selects with mask column + label_source, review status
  + notes), prev/next nav, only-unreviewed filter, live stats.
- Added `scripts/safety_v0/make_demo_review_sample.py`: generates 5 varied demo
  rows (2 text PII via real converter, 1 prompt-injection reject, 1 image+OCR
  PII with rendered + redacted PNGs, 1 visual-safety reject) under
  data/safety_v0/samples/demo/ so the tab is usable before gated downloads.
- Verified: tests/test_safety_v0_review.py (5) incl. override roundtrip,
  latest-wins, traversal block, bad-value rejection. Flask test-client smoke:
  files/rows/save/image all 200, traversal blocked (404/400), GET / renders tab.
  Full suite 104 pass. Demo sample validates 5/5.
- Residual risk: not exercised in a real browser this session (test-client
  only); OCR/redaction/router stages still TODO (demo uses pre-rendered images).

## 2026-06-16 - WebPII sample cache bootstrap
- Changed: downloaded WebPII/webpii upstream sample files into the Hugging Face cache and linked data/safety_v0/raw/webpii to the cached snapshot; added scripts/safety_v0/download/download_webpii.py for reproducible sample/full downloads; recorded the bootstrap state in DATA_PLAN.md.
- Verified: raw symlink resolves to the HF cache snapshot; sample files are present; schema_sample_100.parquet loads as 100 rows x 18 columns; download script passes py_compile and --help.
- Residual risk: full WebPII train/test shards were intentionally not downloaded yet; source mapping, converter, OCR, and weak-label passes still need implementation after sample inspection.

## 2026-06-16 - WebPII sample inspection notes
- Changed: added scripts/safety_v0/inspect/inspect_webpii.py; generated ignored inspection artifacts under data/safety_v0/inspection/webpii/; documented WebPII source schema, box format, provisional Presidio mapping, conversion plan, and risks in docs/datasets/webpii.md; added the WebPII index row and updated DATA_PLAN.md inspection state.
- Verified: inspect script passes py_compile and --help; inspection script reads the cached sample and writes schema.json, stats.json, manifest_summary.json, and sample_rows.jsonl. Sample inspection found 100 parquet rows x 18 columns, 933 PII elements, 124 unique PII keys, and visual zip metadata for 28 sample pages / 132 PNGs.
- Residual risk: no converter/OCR/redaction pass yet; source boxes still need alignment to OCR boxes before writing canonical pii_spans with box_ids.

## 2026-06-16 - WebPII decision alignment
- Changed: marked WebPII as accepted after sample inspection in DATA_PLAN.md and aligned the safety_v0 source registry decision to accept.
- Verified: python -m py_compile for WebPII download/inspect helpers and safety_v0_sources.py; PYTHONPATH=. pytest tests/test_safety_v0_sources.py passed (9 tests).
- Residual risk: converter/OCR/redaction implementation remains next.

## 2026-06-16 — Image OCR + redaction runtime stages

- Added `src/pipeline/Image/` package: `ocr.py` (narrow `OcrAdapter` interface +
  lazy `PaddleOcrAdapter` backend, `get_ocr_adapter` registry, `OcrResult`/
  `OcrSegment` with char-aligned offsets and `build_full_text`/`quad_to_aabb`
  helpers) and `redaction.py` (`map_span_to_box`/`map_spans_to_boxes` span→OCR-box
  mapping with padding+clamp, `redact_image` blur/fill via lazy Pillow,
  `image_size`).
- Added stage CLIs `scripts/safety_v0/run_ocr.py` (converted→ocr) and
  `scripts/safety_v0/run_pii_redaction.py` (ocr→redacted, runs regex_recall on
  OCR text, maps spans to boxes, blurs image, anonymizes OCR text). Both default
  paths from the source registry; new path helpers `ocr_path`/`redacted_path`/
  `redacted_images_dir` added to `safety_v0_sources.py`. These stages fill
  content/geometry/detections only, never labels (null stays unknown).
- Tests: `tests/test_image_ocr_redaction.py` (12) — offset assembly, paddle
  normalize without engine, registry, span→box mapping (single/merge/clamp/
  no-overlap/skip), blur+fill+empty+bad-method redaction, and an end-to-end
  `redact_row` on a synthetic phone-number row asserting box mapping, redacted
  image written, and labels untouched.
- Verified: full suite 116 passed, 1 skipped. End-to-end run of
  run_pii_redaction.py on the demo sample detected the phone number, mapped it
  to its OCR box, blurred the region, anonymized OCR text to <PHONE_NUMBER>, and
  wrote a redacted PNG; labels unchanged.
- Doc: added "Implementation Status" to docs/image-safety-pipeline.md.
- Residual risk: PaddleOCR not installed in this env (adapter raises a clear
  ImportError on run); real-image OCR accuracy unverified. VLM router + fallback
  (stages 4–7) still TODO.

## 2026-06-16 — Demo generator uses the real redaction stage

- Rewrote `image_pii_row` in scripts/safety_v0/make_demo_review_sample.py to
  render the doc image + simulated OCR boxes (no PaddleOCR in env) and then call
  the production `run_pii_redaction.redact_row` to fill pii_spans /
  redaction_metadata / sanitized_ocr_text and produce the blurred image, instead
  of the old hardcoded solid_fill + manual span/redaction construction. Removed
  the `solid_fill` helper. Demo labels still set separately (stage never sets
  labels).
- Verified: regenerated demo sample (5/5 rows valid); image row now shows
  detector="presidio", method="blur", real span→box mapping (PHONE_NUMBER ->
  box_0014), sanitized OCR text, and a stage-produced redacted PNG. Full suite
  116 passed, 1 skipped.

## 2026-06-16 - WebPII sample converter
- Changed: added scripts/safety_v0/convert/convert_webpii.py and tests/test_convert_webpii.py; converted the cached WebPII 100-row parquet sample to data/safety_v0/converted/webpii/source_canonical.jsonl; wrote 100 image files under data/safety_v0/converted/webpii/images; updated docs/datasets/webpii.md and DATA_PLAN.md with converter behavior/output.
- Verified: python -m py_compile for the converter/test; PYTHONPATH=. pytest tests/test_convert_webpii.py tests/test_safety_v0_sources.py passed (13 tests); python scripts/safety_v0/validate_safety_v0.py data/safety_v0/converted/webpii/source_canonical.jsonl passed with 100/100 valid rows. Converted output has 100 rows, 100 images, 923 mapped source PII boxes, and intentionally empty OCR boxes / PII spans.
- Residual risk: OCR/alignment/redaction stages are still needed before WebPII can produce final weak-labeled rows.

## 2026-06-16
- Changed: extended `scripts/safety_v0/run_ocr.py` with WebPII source-box to OCR-box alignment and added `tests/test_run_ocr_webpii_alignment.py`; updated `DATA_PLAN.md` and `docs/datasets/webpii.md`.
- Verified: `python -m py_compile scripts/safety_v0/run_ocr.py tests/test_run_ocr_webpii_alignment.py`; `python scripts/safety_v0/run_ocr.py --help`; `PYTHONPATH=. pytest tests/test_run_ocr_webpii_alignment.py tests/test_image_ocr_redaction.py tests/test_convert_webpii.py tests/test_safety_v0_sources.py` (28 passed).
- Risk: real PaddleOCR/model run was not executed; alignment is validated with fake OCR and will need a small real-OCR smoke once dependencies are installed.

## 2026-06-16 — VLM safety router (stage 4) + explicit webdemo button

- Added `src/pipeline/Router/` package: `router.py` (`SafetyRouter` interface +
  `GeminiVlmRouter` default backend over Gemini's OpenAI-compatible endpoint,
  `get_router`/`list_router_names` registry; lazy openai client + lazy API key
  from GEMINI_API_KEY/GOOGLE_API_KEY; any call failure routes to unsure with the
  error captured), `input.py` (`build_router_input` merges a canonical row into
  the compact input contract — prefers redacted image, sanitized text/OCR, span/
  redaction summaries, modality flags; `encode_image_data_url`), `output.py`
  (`parse_router_output`/`RouterResult` — flat-JSON validation reusing
  ACTION_VALUES/RISK_FIELDS; invalid/missing -> unsure, unknown flags stay None,
  `to_labels()`). Config is single-source in router.py (DEFAULT_MODEL
  gemini-flash-latest, Gemini base URL).
- webdemo: `POST /api/review/run-router` (lazily cached router, returns decision
  + labels + modalities, writes no labels), `get_row` helper in
  safety_v0_review.py, and a "Run router" + "Apply to form" control in the
  Annotate Labels card. Fired only on click (paid); apply copies output into the
  form without saving so a human still confirms.
- Tests: tests/test_router.py (12) — output parsing (valid/bad-action/missing-
  flag/garbage/fenced-JSON), input building (redacted-preferred + text-only),
  backend with fake client (valid/malformed/api-error/sends-image), registry.
- Verified: full suite 135 passed, 1 skipped. Flask test-client smoke with an
  injected fake router: image row -> 200 with valid reject result; bad file /
  missing input_id -> 400. Real router with no key degrades to unsure (no crash).
- Docs: Implementation Status added to docs/vlm-safety-router.md; webdemo README
  documents the endpoint + button.
- Residual risk: no real Gemini call made this session (no key in env / paid
  budget); live VLM accuracy + Gemini's exact response_format/image handling
  unverified. Classifier-head + fallback routing still TODO.
- Follow-up: refined WebPII OCR alignment to prefer text-compatible overlapping OCR boxes with geometry fallback; reran `PYTHONPATH=. pytest tests/test_run_ocr_webpii_alignment.py tests/test_image_ocr_redaction.py tests/test_convert_webpii.py tests/test_safety_v0_sources.py` (30 passed).

## 2026-06-16
- Changed: extended scripts/safety_v0/run_ocr.py with WebPII source-box to OCR-box alignment and added tests/test_run_ocr_webpii_alignment.py; updated DATA_PLAN.md and docs/datasets/webpii.md.
- Verified: python -m py_compile scripts/safety_v0/run_ocr.py tests/test_run_ocr_webpii_alignment.py; python scripts/safety_v0/run_ocr.py --help; PYTHONPATH=. pytest tests/test_run_ocr_webpii_alignment.py tests/test_image_ocr_redaction.py tests/test_convert_webpii.py tests/test_safety_v0_sources.py (30 passed).
- Risk: real PaddleOCR/model run was not executed; alignment is validated with fake OCR and needs a small real-OCR smoke once dependencies are installed.

## 2026-06-16 — Batch router stage + fallback queue + API-label layer

- Added scripts/safety_v0/run_router.py: batch routes canonical rows (default
  redacted/<slug>/redacted.jsonl) through the VLM safety router and writes
  review/api_labels/<slug>.jsonl (one record/row, label_source="api", unknown
  flags stay None, unsure/invalid -> review.status needs_review) plus
  review/queue/<slug>.jsonl (fallback queue of unsure/invalid rows with reason).
  Cost discipline: refuses to run without --limit N (or explicit --all) since it
  is one paid call per row. Pure helpers api_label_record/queue_record/route_rows.
- webdemo review tool now applies API/router labels as a BASE layer beneath human
  overrides: generalized _apply_override into _apply_label_layer(row, rec,
  default_source) that honors the record's own label_source; added
  api_labels_path_for + _layer_path_for (now also resolves ocr/redacted source
  slugs); load_rows applies api_labels then overrides, adds stats["routed"] and
  row["_routed"]. Stats line in the Annotate tab shows "N routed".
- Tests: tests/test_run_router.py (3 — record provenance/status, queue only
  unsure+invalid, limit) and a new review test asserting API layer shows as
  label_source=api/needs_review and a human override wins on top. Full suite 141
  passed, 1 skipped.
- Verified: end-to-end CLI run with an injected fake router (alternating safe/
  unsure) wrote api labels + queued the 2 unsure rows; --limit guard rejects an
  unbounded run.
- Docs: batch stage + queue + API-label layer documented in
  docs/vlm-safety-router.md and webdemo/README.md.
- Residual risk: still no real Gemini call (no key/budget this session); live
  routing accuracy unverified. No queue-driven UI view yet (rows surface via the
  needs_review status / "only unreviewed" filter, not a dedicated queue picker).

## 2026-06-16 — Ran existing_repo_pii converter on real data (500/source)

- Ran scripts/safety_v0/convert/convert_existing_repo_pii.py --limit 500 using
  the local HF dataset cache (HF_HUB_OFFLINE=1; no HF_TOKEN in env, datasets
  pii_masking_95k + hoangha_vie_pii already cached). Wrote 1000 rows to
  data/safety_v0/converted/existing_repo_pii/source_canonical.jsonl (500/source,
  0 invalid).
- Validated: validate_safety_v0.py reports 1000/1000 valid. Spot check: gold PII
  spans -> detections.pii_spans (PERSON/LOCATION/ORGANIZATION/PHONE_NUMBER/EMAIL/
  ID/BANK_ACCOUNT/DATE_TIME), deterministic <ENTITY> anonymization in
  sanitized_text, PII-only labels (action=safe, pii_visible/prompt_injection/
  political/religious known, visual sexual/violence/blood_gore=None) with
  label_source provenance. ~3/40 sample rows had no mapped spans (labels dropped
  by taxonomy mismatch) — expected.
- Verified in webdemo: /api/review/files discovers the file; /api/review/rows
  loads 1000 rows; override path slug-resolves to
  review/human_overrides/existing_repo_pii.jsonl; label_mask = 1 for the known
  PII-policy fields and 0 for the unknown visual fields (sexual/violence/
  blood_gore), confirming "null = unknown" is respected end to end.
- Residual risk: data/ is gitignored (regenerate from cache). Only the first 500
  rows/source converted; full conversion deferred. Real Gemini routing still
  unrun.

## 2026-06-16 — Annotate tab: color-coded label provenance

- Added a 3-layer provenance display to the webdemo Annotate Labels card so the
  reviewer can tell where each label's current value came from, derived from
  label_source: "source" (blue; converter/sample's own: source_gold/
  source_assumption/source), "weak/auto" (amber; pipeline/router: pipeline/rule/
  api/...), "you" (green; human override). After save, fields flip to "you".
- Implemented in templates/index.html: provCategory/provChip/provSummary JS
  helpers + .prov/.row-* CSS; each action + risk field shows a colored chip and
  the risk-table rows are tinted on the left edge by layer; a per-row layer
  summary appears in the nav header and atop the Labels card; added a legend.
- Verified: GET / renders with the new UI tokens; full suite 142 passed, 1
  skipped. Confirmed real existing_repo_pii rows expose label_source
  (source_gold/source_assumption) that maps to the "source" layer.
- Docs: provenance legend documented in webdemo/README.md.

## 2026-06-16
- Changed: updated PaddleOCR adapter for PaddleOCR 3.x constructor/result shapes, fixed NumPy polygon box normalization, preserved source-aligned WebPII spans during redaction, and documented the English OCR smoke in DATA_PLAN.md/docs/datasets/webpii.md.
- Ran: installed paddleocr==3.7.0 and paddlepaddle==3.2.2 in the existing vinai conda env after paddlepaddle==3.3.1 failed CPU inference; used HOME=/tmp/paddle-home for PaddleX model cache.
- Output: data/safety_v0/ocr/webpii/ocr.jsonl (5 rows, 666 OCR boxes, 34 source-aligned PII spans) and data/safety_v0/redacted/webpii/redacted.jsonl plus 5 redacted images (35 spans/redactions total).
- Verified: py_compile for OCR/redaction scripts and tests; PYTHONPATH=. pytest tests/test_image_ocr_redaction.py tests/test_run_ocr_webpii_alignment.py tests/test_convert_webpii.py tests/test_safety_v0_sources.py (32 passed); validate_safety_v0.py on OCR and redacted WebPII artifacts (5/5 valid each).
- Risk: PaddleOCR model cache is in /tmp/paddle-home and may need redownload after cleanup; only 5 WebPII rows were smoke-tested, not the full 100-row cached sample.

## 2026-06-16 — Convert local_vi_prompt_injection (first prompt-injection source)
- Added `scripts/safety_v0/convert/convert_local_vi_prompt_injection.py`: straight-converts the three local Vietnamese prompt-injection seed files (`data/prompt_injection/vietnamese_{seed,app_seed,mentor_seed}.jsonl`) into canonical safety_v0 rows. Text-only, no download/token.
- Label policy (`prompt_injection_text_labels`): `prompt_injection = bool(gold label)` with `label_source="source_gold"`; `action` reject/safe (source_assumption); `pii_visible`/`political`/`religious` False (source_assumption); `sexual`/`violence`/`blood_gore` stay None (no image — null=unknown preserved). Attack rows get one whole-text `prompt_injection_span` (attack_type=category, detector=source_gold); benign rows get none.
- Ran the real conversion: 120 rows (74 attack, 46 benign), 0 invalid; validated with validate_safety_v0.py (120/120 valid). Output at data/safety_v0/converted/local_vi_prompt_injection/source_canonical.jsonl.
- Docs: docs/datasets/local_vi_prompt_injection.md (format, mapping, label policy table) + index row in docs/datasets/README.md.
- Tests: tests/test_convert_local_vi_prompt_injection.py (7 tests, pure functions + real-file load). Full suite 150 passed, 1 skipped.
- Residual risk: pii_visible=False is an assumption (seeds aren't PII-annotated); if any seed text embeds personal data it would be mislabelled. The seeds are hand-authored instruction prompts, so this is low-risk but not gold-verified.

## 2026-06-16
- Changed: ran English PaddleOCR and redaction over the full cached 100-row WebPII sample, replacing the previous 5-row smoke artifacts; updated DATA_PLAN.md and docs/datasets/webpii.md with full-sample counts.
- Output: data/safety_v0/ocr/webpii/ocr.jsonl has 100 valid rows, 4,937 OCR boxes, and 333 source-aligned PII spans across 90 rows. data/safety_v0/redacted/webpii/redacted.jsonl has 100 valid rows, 90 redacted images, and 335 PII spans/redactions total.
- Verified: validate_safety_v0.py on OCR and redacted WebPII artifacts (100/100 valid each); PYTHONPATH=. pytest tests/test_image_ocr_redaction.py tests/test_run_ocr_webpii_alignment.py tests/test_convert_webpii.py tests/test_safety_v0_sources.py (32 passed).
- Risk: 10 rows still have source PII boxes but no aligned OCR spans/redactions at the current overlap threshold; review those alignment misses before treating the redacted sample as complete.

## 2026-06-16 — Text converters: assert sexual/violence/blood_gore False (was null)
- Fixed an inconsistency surfaced in the Annotate tab review: the two text converters left sexual/violence/blood_gore as null ("visual-only, no image") while asserting political/religious False. The schema has one field per risk (no text-vs-visual split), so for ordinary text the content axes are judgeable and should be asserted, not masked.
- convert_existing_repo_pii.py (`pii_only_text_labels`) and convert_local_vi_prompt_injection.py (`prompt_injection_text_labels`): sexual/violence/blood_gore now False with label_source="source_assumption". null is now reserved for image sources whose visual axes are uninspected.
- Regenerated both files: existing_repo_pii 1000/1000 valid, local_vi_prompt_injection 120/120 valid. derive_label_mask now = 1 across all 8 heads on these text rows (every head supervised; nothing masked out).
- Updated docstrings, both dataset docs' label-policy tables, and tests. Full suite 150 passed, 1 skipped.
- Residual risk: source_assumption, not gold. A PII row that happens to embed violent/sexual text (e.g. clinical injury mentions in medical PII) would be a false negative on that axis. Low for these corpora (synthetic PII / hand-authored instruction prompts), and a human override flips it during review.

## 2026-06-16
- Changed: integrated WebPII OCR/redaction artifacts into the webdemo Annotate tab by adding redacted/ocr JSONL discovery, row-level image PII artifact counts, alignment-miss warnings, and detector/box columns for span tables; documented the behavior in webdemo/README.md.
- Verified: python -m py_compile webdemo/safety_v0_review.py webdemo/app.py tests/test_safety_v0_review.py; PYTHONPATH=. pytest tests/test_safety_v0_review.py (6 passed); live GET /api/review/files on http://127.0.0.1:5001 lists the redacted and OCR WebPII files.
- Risk: UI was integrated without browser screenshot automation; Claude is actively editing nearby webdemo files, so reconcile overlapping frontend changes before committing.

## 2026-06-16 — Expand PII entity taxonomy 8 -> 21 types (redaction completeness)
- Problem (found via Annotate tab): VI_PII_LABEL_TO_PRESIDIO mapped only 23 of pii_masking_95k's ~110 labels, dropping 46.5% of gold PII spans. The existing_repo_pii safety converter then redacted only the mapped subset yet labeled rows pii_visible=False/source_gold — leaving PINs, license/insurance/medical numbers, IPs, salaries, crypto, passwords, diagnoses in the "sanitized" text.
- Per user decision (expand globally, fine-grained, drop non-identifying tokens): rewrote VI_PII_LABEL_TO_PRESIDIO to map every personal-data label to one of 21 target types (8 original + 13 new: CREDIT_CARD, CRYPTO, IP_ADDRESS, URL, CREDENTIAL, FINANCIAL, MEDICAL, VEHICLE, USERNAME, NRP, OCCUPATION, EDUCATION, PROPERTY). Added VI_PII_DROPPED_LABELS = {LOAI_TIEN_TE, TY_GIA_HOI_DOAI, NGON_NGU, MUI_GIO, MA_SAN_BAY, MA_GA_TRAM} (genuinely non-PII). All 110 labels accounted for.
- Extended LLMVerifier.ENTITY_TYPES enum with the 13 new types (only hard enum constraint; MISC kept). Updated convert_webpii.py map (card->CREDIT_CARD, login->USERNAME/CREDENTIAL, codes->ID) off MISC. convert_existing_repo_pii.py needed no logic change (reads label_to_presidio).
- Regenerated existing_repo_pii (1000/1000 valid). Drop rate fell 46.5% -> 1.8% (only the 6 non-PII labels). Verified screenshot row safety_v0_existing_repo_pii_000001 now redacts the asset/property spans (<PROPERTY>) it previously leaked; pii_visible=False is now honest. local_vi_prompt_injection unaffected (no PII spans).
- Docs: rewrote pii-masking-95k.md taxonomy section (full 21-type table, dropped set, detection-coverage caveat); updated existing_repo_pii.md coverage notes. Tests: new tests/test_pii_taxonomy.py (7), updated test_convert_existing_repo_pii.py + test_convert_webpii.py. Full suite 157 passed, 1 skipped.
- Residual risk: evaluator derives its type set dynamically from the mapping, so detection eval on pii_masking_95k now counts the 13 new types with NO recognizer -> 0 recall on them, lowering headline recall. Read detection quality on the recognizer-covered 8-type subset until detectors are added (easy regex follow-ups: IP_ADDRESS, URL, CRYPTO, CREDIT_CARD).

## 2026-06-16 — Regex recognizers for 4 mechanical PII types (restore detection recall)
- Added high-precision, mostly context-free patterns to CustomPatternRecognizer.build_patterns() (always-on base set) for the easy mechanical members of the expanded taxonomy: URL (http/https/www, trailing punctuation trimmed), IP_ADDRESS (octet-validated IPv4, full canonical IPv6 incl. compressed ::, MAC), CRYPTO (Ethereum 0x+40hex, Bitcoin base58/bech32, Litecoin), CREDIT_CARD (4-4-4-4 grouped, "số thẻ/card number" context, CVV context -> CREDIT_CARD per taxonomy).
- These 4 types previously had 0 detection recall after the taxonomy expansion; now covered. Remaining 9 new types (CREDENTIAL, FINANCIAL, MEDICAL, VEHICLE, USERNAME, NRP, OCCUPATION, EDUCATION, PROPERTY) still have no detector.
- Verified end-to-end via get_pipeline('regex_only'): all 4 detected with value-only spans and correct types/scores. Fixed initial IPv6 alternation (missing prefix/suffix branches) and URL trailing-comma/period capture.
- Tests: tests/test_custom_recognizer_mechanical.py (9 tests: supported_entities, url + trailing-punct, ipv4 octet validation, ipv6 full/compressed, mac, crypto BTC/ETH/LTC, credit card grouped + CVV, value-only span). Updated docs/datasets/pii-masking-95k.md detection-coverage note (12 of 21 types now covered). Full suite 166 passed, 1 skipped.
- Residual risk: base58 crypto patterns (length 26-35) and 4-4-4-4 credit-card grouping could occasionally over-match long alphanumeric/grouped-digit strings; scores set moderate (0.78-0.85). No Luhn check on card numbers. Precision can be tuned if FP appear in eval.

## 2026-06-16 — Mapped-type eval of regex_only after taxonomy + new recognizers (5000-row dev sample)
- Ran scripts/evaluate_pipeline.py --pipeline regex_only --dataset pii_masking_95k --split train --limit 5000 (deterministic, non-LLM, offline cache). Validates the 4 new recognizers and checks precision regression on the original 8.
- No precision regression: original-8 precision all >=0.954 (PHONE 0.954, rest >=0.994); overall mapped-type precision 0.994 (105 fp / 17344 tp).
- New 4 recognizers high quality: URL P=1.00 R=1.00 F1=1.00 (200); IP_ADDRESS P=0.998 R=1.00 F1=0.999 (653); CRYPTO P=0.986 R=0.971 F1=0.978 (494); CREDIT_CARD P=0.997 R=0.808 F1=0.892 (332, recall capped by non-grouped numbers w/o context).
- Headline recall (all 21 types) 0.439 — depressed purely by the 9 still-uncovered types (10,172 fn, 0 recall by design). On the recognizer-covered 12-type subset: P=0.994 R=0.591 F1=0.742. The covered-subset recall reflects pre-existing regex limits on PERSON/ORG/ID (NER-style types), not the new work.
- Conclusion: new recognizers are precise and effective; expansion did not hurt the original types. Read detection headline on the covered-12 subset until detectors exist for the remaining 9 (CREDENTIAL/FINANCIAL/MEDICAL/VEHICLE/USERNAME/NRP/OCCUPATION/EDUCATION/PROPERTY) — those are context-driven, better suited to NER/LLM than regex.

## 2026-06-16 — Tried Luhn-gated bare credit-card pattern; reverted (net negative)
- Added a reusable `validator` hook to ContextRegexPattern + a `luhn_check(value)` helper, then a bare card-number pattern gated by Luhn. Measured on the 5k dev sample: precision collapsed 0.997 -> 0.619 (+206 fp) for +3 tp — in banking-heavy data ~10% of 16-digit account/ID numbers pass Luhn.
- Tightened to require a valid issuer prefix (IIN by brand+length) AND Luhn: much better (15 fp vs 206) but still net-negative — only +1 tp for +14 fp, CREDIT_CARD F1 0.892 -> 0.877. The 79 CREDIT_CARD misses are CVVs / non-standard SO_THE values, not bare brand cards, so bare matching can't recover them.
- Decision: removed the bare pattern; kept the `validator` hook + `luhn_check` (both unit-tested) for a future context-gated card pattern. CREDIT_CARD back to baseline P=0.997 R=0.808 F1=0.892; overall precision 0.994. Full suite 168 passed, 1 skipped.

## 2026-06-16 — Redesign Annotate tab (top-down stepper) + manual text/image annotation

Reworked the webdemo Annotate tab from a flat two-panel review into a top-down
stepper and added the ability to add/delete missed detections (the tab is now a
real labeling tool, not just label review).

Layout: left column scrolls through ordered evidence steps (source & modality →
input text → PII spans → prompt-injection spans → image → OCR text); right
sticky sidebar holds the row verdict + actions (nav, action, 7 risk flags,
status/notes, Save, VLM router). User chose "controls in right sidebar" and
"text + image boxes" scope.

Manual annotation:
- Text: select a substring in the Input/OCR step -> popover -> add as PII span
  (21-type taxonomy) or prompt-injection span (attack type); delete via row ×.
  Offsets captured with a TreeWalker over the container text nodes; the span
  label is rendered via CSS ::after (data-lbl) so it stays out of textContent
  and selection offsets map cleanly.
- Image: drag a rectangle on the original image -> popover -> add a
  source_pii_box (coords normalized to natural image size); delete via × on the
  box. Existing boxes render as percentage-positioned overlays.
- Human items carry detector="human" (dashed green); adding/removing a PII span
  re-derives the sanitized-text preview live so pii_visible:false stays honest.

Backend (webdemo/safety_v0_review.py): save_override gained an optional
span_edits arg; clean_span_edits validates+bounds added spans/boxes against the
row text; _merge_span_edits applies adds (stamping span_id/score/human) and
deletes (by (start,end,type) key for spans, box_id for boxes) on top of the
row's detections, recomputing sanitized_text when PII changes; latest override
line wins so re-applying the same edit is idempotent. app.py forwards span_edits.
Frontend Save sends the row's pending edits then re-fetches the file (server
assigns real ids, clears pending state).

Schema: validate_row now collects box_ids from geometry.source_pii_boxes in
addition to ocr_boxes, so human image boxes (and spans referencing them) stay
schema-valid when overrides are baked in.

Verified: tests/test_safety_v0_review.py extended with 7 span/box tests (add PII
+ reanonymize, delete existing gold span, add injection span, add image box,
merged-row-still-validates, idempotent re-apply, bad-input rejection). Flask
test client renders the new layout (GET / 200, contains annotate-layout +
annot-pop). Full suite: 175 passed, 1 skipped. No icons used.

Residual risk: image-box drawing is mouse/pointer-driven and untested by unit
tests (only the backend merge is); OCR-text spans share the pii_spans collection
with input-text spans (offsets are not disambiguated by which text field they
target) — fine for current single-text rows but worth revisiting if a row has
both input_text and ocr_text with overlapping offsets.

## 2026-06-16 — Annotate tab: full-bleed wide layout

The redesigned Annotate tab inherited the 1100px centered `.wrap`, so on wide
monitors it floated mid-screen with large empty side gutters. Made `#view-review`
full-bleed (`margin-inline: calc(50% - 50vw)` breakout, `html{overflow-x:hidden}`
to contain the 50vw math) so it uses the whole viewport; widened the sidebar to
420px and let the steps column take the rest. Capped the original image at 920px
and mono text blocks at 1100px so they stay readable instead of stretching
edge-to-edge. Analyze/Log keep the narrow centered wrap. Verified GET / renders
200 with the new classes.

## 2026-06-16 — Annotate tab: image step sequence + sidebar overflow fix

Per review feedback, decomposed the image area into the pipeline order the user
wanted: OCR text -> "Image — detection boxes" (original image, numbered PII box
overlays, drag-to-add) -> "Boxes ↔ OCR text" (table: #, box_id, type, text,
detector; row numbers match the badges drawn on the image) -> "Redacted image".
Each image box now carries a small index badge (box-tag) cross-referencing its
table row.

Fixed the sidebar risk table spilling past the card border: the global
`select{min-width:200px}` forced the VALUE column too wide for the 420px sidebar.
Added `.annotate-side select{min-width:0;width:100%}`, `table-layout:fixed` with
explicit `.risk-table` column widths (36/40/17/7%), and tighter cell padding so
the FIELD/VALUE/FROM/M columns fit inside the card. Also hardened image height
caps (max-height:78vh) on original + redacted images.

Verified: GET / renders 200, JS brace-balanced, step order OCR < image < boxes
table < redacted, risk-table class + select override present.

## 2026-06-16 — WebPII image path: OCR + redaction over all 100 rows
- Installed PaddleOCR 3.7.0 / paddlepaddle 3.3.1 (CPU). Hit a PIR-executor crash
  (ConvertPirAttribute2RuntimeAttribute) whenever oneDNN was on; env-var FLAGS
  did not bypass it. Fixed by defaulting PaddleOcrAdapter to enable_mkldnn=False
  (overridable config knob), src/pipeline/Image/ocr.py.
- Confirmed no GPU/NPU path on this box: iGPU is gfx1103 (Radeon 780M, unsupported
  by ROCm, no paddlepaddle-rocm wheel on PyPI); XDNA NPU has no paddle backend.
  Faster CPU route documented as paddle==3.0.0 + oneDNN.
- Ran run_ocr.py --slug webpii --lang en: 100/100 rows with ocr_text + ocr_boxes
  (4937 boxes). Ran run_pii_redaction.py --slug webpii: 90/100 rows with aligned
  source PII spans (335 spans) + redacted images. Both validate 100/100.
- Verified: webdemo file picker lists [ocr] and [redacted] webpii files, so the
  Annotate tab's four image steps now render on real data. Tests: image/ocr/
  alignment suites green (19 passed). Committed code+doc (data/ is gitignored).
- Residual risk: WebPII is English; the VI PII pipeline adds little on top of the
  source-box alignment. enable_mkldnn=False makes CPU OCR slower (~1 row/min).

## 2026-06-17 — Annotate tab: live redaction recompute + fix source/span box split
- Root cause of two bugs (edits not flowing downstream; "2522" detected but not
  redacted): a split data model where the image overlay/table/box-edits used
  geometry.source_pii_boxes while redaction used detections.pii_spans -> ocr_boxes.
- Shared core: extracted recompute_redactions() into src/pipeline/Image/redaction.py
  (maps each pii_span to OCR boxes, fills box_ids, builds redaction_metadata,
  redacts human pixel boxes, renders image, returns regions). redact_row now calls
  it; batch output unchanged (regression tests green).
- Alignment fix: run_ocr.py source_box_ocr_matches now matches when max(ocr_cov,
  source_cov) >= threshold (added --min-source-coverage 0.6) so a tight PII box
  inside a wide OCR line aligns. Added --realign (skip OCR, re-align existing
  ocr.jsonl in place). Re-aligned + re-redacted webpii: 90 -> 100/100 rows
  redacted, validates 100/100; "2522" now a span (box_0017) and in
  redaction_metadata.
- Backend: webdemo recompute_row() + POST /api/review/recompute — applies in-flight
  span_edits, writes a throwaway preview under data/safety_v0/review/preview/,
  returns regions + preview path, persists nothing.
- Frontend (index.html): overlay + step-6 table now derive from currentRegions()
  (client-side span->OCR-box mapping; source=blue, human=dashed-green); edits
  trigger a debounced recompute that swaps in the cache-busted redacted preview;
  added a "Re-run redaction" sidebar button + recomputing indicator.
- Verified: full suite 180 passed / 1 skipped (was 175); HTTP smoke test of
  /api/review/recompute (baseline + human 2522 span -> mapped to box_0017, preview
  served 200). Docs: webdemo/README.md (recompute endpoint + live behavior),
  docs/datasets/webpii.md (coverage criteria + --realign).
- Residual risk: redaction masks the whole OCR line (over-redaction) for sub-token
  PII; enable_mkldnn=False keeps CPU OCR slow but realign avoids re-OCR.

## 2026-06-17 — Sub-box redaction: clip OCR line to selected chars
- map_span_to_box (src/pipeline/Image/redaction.py) now clips each overlapping
  OCR segment box horizontally to the span's char sub-range (_clip_segment_box,
  linear char->x interpolation, single-line assumption) before merging, instead
  of masking the whole line box. Full-segment spans yield the full box (existing
  tests unchanged). Mirrored client-side in index.html (clipBoxToChars/spanBoxes)
  so the live overlay matches the redaction.
- Effect: selecting "2522" inside the OCR line "ending in 2522 Change" now redacts
  ~23% of the line at the true card-number position ([496.6..533.7] vs source box
  [502..533]) instead of the full 163px line.
- Verified: full suite 181 passed / 1 skipped; new test
  test_map_span_clips_partial_selection_within_one_box; recompute_row end-to-end
  shows the clipped human region. Docs: webdemo/README.md.
- Residual risk: proportional to char count, so variable-width fonts / multi-line
  OCR boxes are approximate; source-aligned spans still span their full matched
  box (their char range is the whole line) — tightening those is a separate change.

## 2026-06-17 — Narrow source-aligned spans to the PII token (no more whole-line redaction)
- Bug (user screenshot): the OCR block "FREE Two-Day Shipping on this Order: Alexa Copeland, you can save $3.99 ... by" was redacted in full. Root cause: `align_source_pii_spans` set each aligned span's char range to the full extent of the matched OCR box(es) (`min(start)`..`max(end)`), so a tight source box (a name) inside a wide OCR block produced a span covering the whole block.
- Fix (`scripts/safety_v0/run_ocr.py`): added `_narrow_to_source_text(ocr_text, start, end, source_text)` — whitespace-flexible regex search for the source text inside the matched window; narrows the span to that occurrence, else keeps the full range (safe over-redact fallback). `align_source_pii_spans` now narrows the range and trims `box_ids` to the boxes the narrowed range still overlaps (never empty). Redaction's existing `_clip_segment_box` then clips the pixel box horizontally to the sub-range.
- Re-ran `run_ocr.py --slug webpii --realign` (100 rows, 894 aligned spans, 0 invalid) + `run_pii_redaction.py --slug webpii` (100/100 redacted, 0 invalid).
- Verified: the Alexa block now yields two PERSON spans of exactly "Alexa Copeland" (was the whole block); the 583px OCR line redacts only ~99px at the name position. The earlier 96px tight line still redacts ~102px (with padding).
- Tests: added `_narrow_to_source_text` cases (clip inside block, whitespace-flexible, absent->fallback) and `align_source_pii_spans` narrowing-in-block case to tests/test_run_ocr_webpii_alignment.py. Full suite 185 passed, 1 skipped.
- Doc: docs/datasets/webpii.md alignment section now documents span narrowing.
- Residual: narrowing is char-proportional and assumes single-line LTR text; multi-line OCR blocks or variable-width fonts make the pixel clip approximate (still far tighter than the whole line). Spans whose source text isn't literally in the OCR window keep the full box.

## 2026-06-17 — Don't redact whole free-text MISC fields (gift message / delivery instructions)
- Report (user screenshot, row safety_v0_webpii_000002): the entire gift message was masked. Source has PII_GIFT_MESSAGE -> MISC covering the whole personalized message; its embedded name (PII_GIFT_FULLNAME=James Pena) and address are already separately boxed. OCR reads across columns so the message text interleaves the shipping address, so span-narrowing can't isolate the message and the whole region (290..575) was redacted.
- Decision (user): "Don't redact them" — free-text fields are not PII per se; the embedded PII is covered by its own boxes.
- Fix (scripts/safety_v0/run_ocr.py): added NON_REDACTABLE_SOURCE_KEYS = {PII_GIFT_MESSAGE, PII_DELIVERY_INSTRUCTIONS} (mirrors convert_webpii MISC mapping) + `_source_key_base` (strips numeric suffixes). `align_source_pii_spans` skips these source boxes, so they stay in geometry.source_pii_boxes for the record but produce no redaction span. Applies via --realign with no re-OCR/re-convert.
- Re-ran realign (100 rows, 839 aligned spans, down from 894 = 55 free-text fields dropped) + re-redact (100/100). Verified row 000002 now has 0 MISC spans, only LOCATION+PERSON, and James Pena is still redacted.
- Test: tests/test_run_ocr_webpii_alignment.py::test_align_skips_free_text_misc_fields. Full suite 186 passed, 1 skipped.
- Doc: docs/datasets/webpii.md documents the free-text MISC skip.

## 2026-06-17 — Redaction policy doc (which entities must be redacted vs ignored)
- Added docs/redaction-policy.md: an authoritative triage rule for annotation, organized by the 21 ENTITY_TYPES (LLMVerifier.py). Three tiers: MUST (redact every instance: CREDIT_CARD, CREDENTIAL, BANK_ACCOUNT, FINANCIAL, ID=govt/identity numbers, CRYPTO, MEDICAL, PHONE_NUMBER, EMAIL_ADDRESS), CONDITIONAL (redact when it identifies a person: PERSON, LOCATION, USERNAME, IP_ADDRESS, VEHICLE, DATE_TIME=DOB/card-expiry only, NRP, OCCUPATION, EDUCATION, PROPERTY), IGNORE (ORGANIZATION, URL-plain, MISC free-text, order/promo/job codes, qty/price/SKU, generic dates, boilerplate, example values). Includes ambiguity rules (bare numbers by VN context words, names vs brands, addresses, dates, free-text) and a WebPII source-key reference. Linked from docs/README.md.
- Flagged inconsistency: PII_PO_NUMBER/PII_JOB_CODE/PII_PROMO_CODE currently map to ID (a MUST type) in convert_webpii.py but the policy classifies them as transaction identifiers = IGNORE. Candidate to reclassify/drop; not changed yet (needs user confirm).
- No code/behavior change in this entry; doc only.

## 2026-06-17 — Reclassify transaction codes (PO/job/promo) as non-PII per redaction policy
- Per docs/redaction-policy.md, PII_PO_NUMBER / PII_JOB_CODE / PII_PROMO_CODE are transaction identifiers, not personal identity, but convert_webpii mapped them to ID (a MUST type). Reclassified: converter now returns None (no source box, never redacted); run_ocr.py NON_REDACTABLE_SOURCE_KEYS extended to also drop these at alignment so already-converted data clears them via --realign (no re-OCR). Generalized the constant's comment (free-text MISC fields + transaction identifiers).
- Prevalence: only PII_PROMO_CODE present in WebPII (2 boxes / 2 rows, e.g. WELCOME69). Realign 839 -> 837 spans; verified 0 PO/job/promo spans remain; re-redacted 100/100.
- Tests: test_convert_webpii.py asserts the three keys map to None. Full suite 186 passed, 1 skipped.
- Doc: docs/redaction-policy.md source-key reference updated (done, not "candidate").

## 2026-06-17 — Auto-load .env for router/verifier entrypoints

Wired the repo-root `.env` (now holding `GEMINI_API_KEY`, `OPENROUTER_API_KEY`)
into the LLM entrypoints so keys are picked up without a manual `export`.

- Added `src/pipeline/Utils.load_env()` as the single source of truth for
  loading `.env` (idempotent, best-effort; existing env vars win so an explicit
  export still overrides). Refactored `load_hf_token()` to use it.
- Called `load_env()` at the start of `scripts/safety_v0/run_router.py:main()`
  and at `webdemo/app.py` import time.
- The Gemini VLM router (`gemini_flash`) and the OpenRouter PII verifier both
  resolve keys via `os.getenv`, so no call-site changes were needed.

Verified: `GEMINI_API_KEY` visible after `load_env()` and after importing
`webdemo.app` (was False before). 1-row PAID router smoke check succeeded
(`run_router.py --slug webpii --limit 1` -> safe=1, invalid=0, valid Gemini
structured output). Added `tests/test_utils_env.py` (3 cases: loads from .env,
does not override an export, no-ops without python-dotenv). Router tests + full
suite green (189 passed, 1 skipped). Updated `docs/vlm-safety-router.md` and
`webdemo/README.md`.

Residual risk: none functional. Budget note — only 1 paid Gemini call spent.

## 2026-06-17 — Parked PII-dropout augmentation; resuming DATA_PLAN source queue

Captured the PII-dropout augmentation design (self-labeled `pii_visible`
variants by toggling which real PII boxes stay visible; both modalities
co-vary; matched-pair training signal; free/no-LLM) as a DEFERRED design note
`docs/pii-dropout-augmentation.md`. Indexed in `docs/README.md` and pointed to
from a new "Deferred Ideas" section in `DATA_PLAN.md`. Not implemented — parked
until the core source queue is further along.

No code changes. Next: pick up the next source in the DATA_PLAN work queue.

## 2026-06-17 — New source: deepset/prompt-injections (English-filtered) + reusable language filter

Added the `deepset_prompt_injections` safety_v0 source (text prompt-injection
positives/benign hard-negatives).

- download/inspect/convert scripts under scripts/safety_v0/{download,inspect,
  convert}/; raw persisted to data/safety_v0/raw/deepset_prompt_injections/
  (train 546 / test 116, columns text+label).
- Language constraint: source is EN+DE with no Vietnamese; project keeps only
  EN/VI. Added reusable `src/pipeline/Datasets/language.py`
  (detect_language / is_allowed_language; langdetect backend behind an
  injectable interface, seed pinned to 42, strict drop of undetectable). Added
  langdetect to requirements.txt.
- Converter filters to English: kept 351 of 662 (train 287 / test 64; 154
  attack / 197 benign); 311 dropped (222 German + other/undetectable). Kept set
  audits 100% English. Strict drop = purity over yield (some short English lost).
- Label mapping: prompt_injection from gold label (source_gold); action
  reject/safe; pii_visible/sexual/violence/blood_gore False (source_assumption,
  text prompts); political/religious left null (no topic gold — "null means
  unknown, not false"). Attack rows get a whole-text prompt_injection_span.
- Split preserved into source.split for the final build.

Verified: convert output validates 351/351; new tests
(test_convert_deepset_prompt_injections.py, test_language_filter.py) pass; full
suite 201 passed, 1 skipped. Docs: docs/datasets/deepset_prompt_injections.md +
index row; DATA_PLAN deepset section updated.

Residual risk: ~30 short English rows likely dropped as nl/af false positives
(acceptable for purity). No Vietnamese in this source. Next: run the
prompt-injection rule detector over it (rule vs gold precision/recall) — needs
the not-yet-built run_prompt_injection_rules.py batch script.

## 2026-06-17 — New source: microsoft/llmail-inject-challenge (bounded, all PI positives)

Added the `llmail_inject_challenge` safety_v0 source: email-structured
prompt-injection submissions (every row is an attack -> positives only).

- download/inspect/convert scripts under scripts/safety_v0/{download,inspect,
  convert}/. Full dataset is huge (Phase1 ~370k / Phase2 ~91k rows, multi-GB
  raw), so the download pages the HF datasets-server /rows API for a BOUNDED
  sample (default 1,000/phase) — no full-file download — plus tiny meta/
  description files. Raw under data/safety_v0/raw/llmail_inject_challenge/.
- Mapping: prompt_injection=True for all (source_gold); action=reject; visual/PII
  False; political/religious null. Whole-text prompt_injection_span with
  attack_type=scenario (level code, e.g. level4e). objectives/scenario/team/phase
  kept in source_labels. input_text = "Subject: {subject}\n\n{body}".
- Split: Phase1->train, Phase2->test (Phase2 = different defenses -> useful
  distribution-shift held-out set).
- Language: English by construction but adversarial/obfuscated payloads break
  langdetect (mislabels ~9% obfuscated English as fr/zh). Added reusable
  is_mostly_latin / latin_letter_ratio to src/pipeline/Datasets/language.py and
  filtered by SCRIPT instead (keeps EN+VI Latin script, drops non-Latin). Dropped
  0 on the sample.

Verified: convert validates 2,000/2,000 (train 1,000 / test 1,000), all
prompt_injection=True, all political/religious null. New tests
(test_convert_llmail_inject_challenge.py + latin-script cases in
test_language_filter.py). Full suite 209 passed, 1 skipped. Docs:
docs/datasets/llmail_inject_challenge.md + index row; DATA_PLAN section updated.

Residual risk: bounded first-N sample (not random) under-represents rare
scenarios; attack_type carries the challenge level, not a semantic attack family.
Next (plan a): build run_prompt_injection_rules.py to run the rule detector over
the PI sources (deepset, llmail, local_vi) and measure rule recall/precision vs
the gold flags.

## 2026-06-17 — Prompt-injection rule batch stage (plan a)

- Added `scripts/safety_v0/run_prompt_injection_rules.py`: runs the rule-based
  detector (`src/pipeline/PromptInjection`, via the detector registry) over
  canonical rows. Scans `input_text` + `ocr_text`, appends evidence to
  `detections.prompt_injection_spans` (`detector="rule"`, ids `pi_rule_*`, each
  span tagged with `field`/`rule`), and fills the `prompt_injection` weak label
  ONLY where unknown (`label_source="rule"`) — never overrides `source_gold`,
  never touches `action`/topic axes. Detector + thresholds are config flips;
  default in=converted, out=`weak/<slug>/weak_labeled.jsonl`. Prints + `--metrics`
  persists precision/recall/F1 vs `source_gold` flags (free, no LLM).
- Tests: `tests/test_run_prompt_injection_rules.py` (5) — rule spans + weak label
  on attack, no-fire benign, source_gold not overridden, existing spans
  preserved with unique ids, evaluate() P/R math. Full suite 214 passed, 1 skipped.
- Ran over 3 PI sources (all validate 100%): deepset 351 -> P=1.0 R=0.084 F1=0.156;
  llmail 2000 (all positives) -> P=1.0 R=0.022 F1=0.043; local_vi 120 -> P=1.0
  R=1.0 F1=1.0. Wrote metrics JSON per source under weak/.
- Finding: rules are high-precision / zero-FP everywhere (benign guard holds) but
  near-zero recall on English/adversarial text; the perfect local_vi score is
  overfit (rules tuned on those seeds). Reusable signal = a rule hit is almost
  certainly a real attack; recall on non-VI sources needs a learned/LLM detector.
- Docs: new "safety_v0 batch stage" section in docs/prompt-injection.md (results
  table + takeaway); DATA_PLAN weak-label notes for the 3 sources updated done.
- Residual risk: span char offsets index either input_text or ocr_text (recorded
  in span `field`); schema's prompt_injection_span has no native field for this,
  so it is stored as an extra key (validator ignores extras).

## 2026-06-17 — EN->VI translation augmentation (whole-text labels)

- New swappable Translation module `src/pipeline/Translation/` (Translator ABC,
  GeminiTranslator, registry get_translator). Reuses the router's Gemini endpoint
  + credentials (single source of truth). Faithful-translation system prompt that
  explicitly tells the model NOT to obey injected instructions, only translate.
  Retries HTTP 429 / quota with exponential backoff (configurable, injectable
  sleep_fn for tests).
- New stage `scripts/safety_v0/run_translation_augmentation.py`: for each eligible
  EN row writes a VI twin (one sample -> two). Guards: never twins a row with
  pii_spans (translation breaks offsets); EN->VI only (skip rows already target
  language); twin labels inherited but provenance of content axes marked
  `<orig>_translated` (e.g. source_gold_translated), gold whole-text PI span
  regenerated over the VI text, `augmentation` block records backend/model/
  source_input_id for split-safe pairing. Output data/safety_v0/augmented/<slug>/.
  On-disk translation cache (manifests/translation_cache.json) so reruns never
  re-pay and crashes resume. `--sleep` paces under free-tier RPM; `--limit` smoke.
- Registry: added `augmented` per-source kind + augmented_path() in
  safety_v0_sources.py (no hardcoded paths at call sites).
- Tests: tests/test_translation.py (7: registry, injected client, system prompt
  forbids obeying, empty no-call, batch, 429 retry-then-succeed, give-up) +
  tests/test_run_translation_augmentation.py (5: twin valid+provenance+span,
  benign no-span, no-mutate original, cache roundtrip, stable cache key). Full
  suite 226 passed, 1 skipped.
- Verified live: 3-row throttled smoke produced fluent natural Vietnamese
  (quality good). Launched full deepset (351) translation in background, paced
  --sleep 13 (~4.6/min under free-tier 5 RPM).
- BLOCKER/finding: the Gemini key is on the FREE tier (5 req/min + daily cap), not
  billed. deepset (~350) is ~75 min throttled; llmail (2000) is impractical on
  free tier -> needs billing enabled or a bounded sample. Decided EN->VI only
  (VI->EN would add English, which the project does not want).
- Residual risk: adversarial/obfuscated attacks (llmail) may lose their mechanism
  in translation though intent survives -> treat translated llmail as noisier.
  Twin/original must stay in the same split downstream (augmentation.source_input_id).

## 2026-06-17 — Translation retry hardening (503) + resilient run

- First full deepset run died on a transient 503 (model overloaded); retry only
  covered 429. Broadened GeminiTranslator retry to all transient errors (429 +
  5xx 500/502/503/504, overloaded/unavailable/high-demand/timeout markers,
  InternalServerError/APITimeoutError). Cache had saved 17 -> no progress lost.
- Made the augmentation loop per-row resilient: a translation that exhausts
  retries is logged + counted (failed), cache flushed, row skipped; the run
  continues and a rerun fills the gap (cache skips done rows). Added `failed`
  to the summary line. Tests: +1 (503 retry) -> translation suite 13, full 227
  passed, 1 skipped. Resumed full deepset translation in background.

## 2026-06-17 — Translation BLOCKED on free-tier daily cap; cross-check inconclusive

- Root cause of the stalls: the Gemini free tier binding limit is a DAILY cap,
  ~20 requests/day for gemini-3.5-flash (quota
  GenerateRequestsPerDayPerProjectPerModel-FreeTier), not just 5/min. Stopped the
  run after it hit the daily cap; cache preserved 21 translations. deepset (351)
  ~= 18 days and llmail (2000) ~= 100 days at 20/day -> free-tier translation is
  NOT viable at scale; needs billing on the key.
- Partial deepset augmented file: 43 originals + 21 twins, all valid.
- Matched-pair rule cross-check (EN original vs VI twin) on the 21 twins:
  only 2 are gold attacks (early deepset rows are mostly benign), so the recall
  comparison is statistically meaningless (EN 1/2, VI 0/2). The one solid signal:
  ZERO false positives on both EN and VI benign rows (19/19) -> the benign guard
  holds in Vietnamese too.
- Updated docs/translation-augmentation.md cost section with the real 20/day cap.
- DECISION NEEDED FROM USER: enable billing on the Gemini key to translate at
  scale, or cap translation at a tiny daily-budget sample. Until then the VI-twin
  recall question stays open.

## 2026-06-17 — New source: vihsd_topic_safety (UIT-ViHSD)

- Translation augmentation PAUSED per user (free-tier 20/day); moved to next source.
- Added UIT-ViHSD as safety_v0 source vihsd_topic_safety (Vietnamese hate/offensive
  comments). Canonical uitnlp/vihsd is a loading-script repo (not datasets-server
  indexed), so downloaded a bounded sample from the parquet mirror phucdev/ViHSD
  (free_text + label_id, train/validation/test); recorded source.name stays
  canonical uitnlp/vihsd.
- download_/inspect_/convert_vihsd_topic_safety.py: bounded /rows paging (auth'd,
  default 2000 train / 500 dev / 1000 test = 3500); inspect writes label dist +
  length buckets; converter maps conservatively.
- Mapping (hate taxonomy is orthogonal to our 7 axes): prompt_injection=False +
  pii_visible=False (source_assumption — gives scarce VI PI negatives, text-only);
  sexual/violence/blood_gore/political/religious/action = null (unknown, for
  teacher/review); hate label kept in source_labels {label_id,label_name,split}.
  ViHSD validation -> our dev split.
- Verified: convert 3500/3500 valid; dist CLEAN 2879 / HATE 362 / OFFENSIVE 259.
  Tests tests/test_convert_vihsd_topic_safety.py (4). Full suite 231 passed, 1 skipped.
- Docs: docs/datasets/vihsd_topic_safety.md + index row; DATA_PLAN section marked [x].
- Residual: topic axes all null until a teacher/human pass; sample keeps source
  CLEAN skew (balance at final-build); image render/OCR for these comments deferred.

## 2026-06-17 — PI rule precision check on vihsd (VI negatives)

- Ran run_prompt_injection_rules.py over vihsd_topic_safety (3500 real VI
  non-attack comments). Rule fired on 1/3500 -> ~0.03% false-positive rate on
  in-distribution Vietnamese text. Weak label correctly NOT filled (already
  source_assumption False; rule does not override). weak_labeled.jsonl validates.
- The 1 FP: a CLEAN comment about app privacy ("...nguy hiểm đến thông tin cá
  nhân"); secret_or_data_exfiltration rule matched "đọc...thông tin cá nhân"
  without an imperative/attack frame. Candidate rule refinement noted in
  docs/prompt-injection.md; deferred (needs a broader benign VI set to avoid
  regressing seed recall=1.0).

## 2026-06-17 — Balanced Vietnamese prompt-injection eval set

- Added `scripts/safety_v0/build_pi_vi_eval.py` (builder) and
  `scripts/safety_v0/evaluate_pi_vi.py` (scorer). Builder combines local_vi gold
  attacks (positives) + local_vi gold benigns + deterministic vihsd negatives
  into `data/safety_v0/eval/pi_vi/eval.jsonl`; each row is a valid canonical row
  plus a top-level `eval` block {label, bucket, gold}. Balanced by default
  (148 rows: 74 pos / 74 neg = 46 benign_seed + 28 benign_vihsd); `--vihsd-negatives`
  raises the realistic negative pool with one flag (no code change), seed 42.
- Added `eval` shared kind + `eval_dir()` / `pi_vi_eval_path()` to
  safety_v0_sources.py (path single source of truth).
- Evaluator scores any registry detector: acc/P/R/F1, confusion, per-bucket
  breakdown, FP/FN dump (`--errors`), metrics JSON (`--metrics`).
- Verified: build 148/148 valid; evaluate_pi_vi on rule detector = P/R/F1 1.0 on
  balanced set (recall overfit — same seeds rules were authored on); over all
  3,500 vihsd negatives P=0.9867 R=1.0 F1=0.9933 with the single known
  `secret_or_data_exfiltration` FP (..._002461) reproduced exactly.
- Tests: tests/test_build_pi_vi_eval.py (5) + tests/test_evaluate_pi_vi.py (4),
  all 9 green. Docs: docs/datasets/pi_vi_eval.md (+ index row), prompt-injection.md
  section.
- Residual risk: positives are overfit, so recall is not production-meaningful;
  a real recall number needs held-out Vietnamese attacks (translated twins once
  translation is unblocked, or fresh seeds). This set is the validation harness
  for the deferred secret_or_data_exfiltration rule tightening.

## 2026-06-17 — Tightened secret_or_data_exfiltration rule (FP fix)

- Split the `secret_or_data_exfiltration` rule into two branches:
  hard secrets (password/token/api key/secret/credentials/hidden info) still
  fire on any read/extract verb incl. bare "đọc"/"read"; soft personal-data
  targets (user data / personal info / chat history) now require a stronger
  exfiltration verb (lấy/trích xuất/gửi/liệt kê/xuất/đọc toàn bộ/dump/...) and no
  longer match bare "đọc"/"read".
- Motivation: the one vihsd false positive (..._002461, benign "Đọc báo ...
  thông tin cá nhân"). Verified beforehand that no local_vi positive relies on
  bare đọc+soft-target (all use trích xuất / đọc toàn bộ / xuất / gửi), so no
  recall regression.
- Verified on the balanced Vietnamese eval set: over all 3,500 vihsd negatives
  FP 1 -> 0, attack recall unchanged 74/74; P/R/F1 now 1.0 across the board.
  Regenerated vihsd weak file (now 0 rule-flagged) and rebuilt eval.jsonl.
- Tests: added 3 regression cases to tests/test_prompt_injection_detector.py
  (benign reading allowed; hard-secret read still blocks; strong-verb personal
  data still blocks). Full PI detector suite 15 green; build/evaluate suites green.
- Docs updated: prompt-injection.md (vihsd precision paragraph + eval table),
  docs/datasets/pi_vi_eval.md (measured tables + caveats).
- Residual risk: none new. Recall on the eval positives is still overfit; a real
  recall number needs held-out Vietnamese attacks.

## 2026-06-17 — Added cyberseceval3_visual_prompt_injection source

- Next DATA_PLAN source. Inspected facebook/cyberseceval3-visual-prompt-injection
  via datasets-server: 1 config (visual_prompt_injection) / 1 split (test), 1,000
  rows, 9 columns, NO image binaries (text-only: user_input_text + image's
  image_text/image_description). All attacks (no benign control), all English.
  500 direct / 500 indirect; risk_category 600 logic / 400 security; ~100 rows
  empty image_text (scene-carried).
- Added download (pages /rows, no image download), inspect, and convert scripts
  (one PascalCase-free script each under download/inspect/convert). Converter maps
  injection to OCR text: input_text<-user_input_text, ocr_text<-image_text, gold
  span over ocr_text (field=ocr_text, detector=source_gold,
  attack_type=visual_prompt_injection) when image_text present. Labels mirror
  deepset: prompt_injection=True source_gold, action=reject, visual/sexual/
  violence/blood_gore=False source_assumption, political/religious=None;
  CyberSecEval taxonomy + system_prompt/image_description/judge_question kept in
  source_labels. has_image=False (no pixels).
- Verified: download 1000; convert 999 (1 dropped by language filter, id 292 minor
  false-drop), 999/999 valid; weak PI rule stage 0/999 fire (R=0.0 — VN rules miss
  English visual attacks, as expected), weak file 999/999 valid.
- Tests: tests/test_convert_cyberseceval3_visual_prompt_injection.py (5) green;
  related convert/PI suites green (20 total). Docs:
  docs/datasets/cyberseceval3_visual_prompt_injection.md + index row; DATA_PLAN
  entry marked [x] with state notes.
- Residual risk: text-only stand-ins for visual attacks; a render step
  (image_text+description -> image -> OCR) would make them true multimodal rows.
  English-only, so they feed the learned/multimodal detector + future translation,
  not the Vietnamese rule detector.

## 2026-06-18 — Completed existing_repo_pii and WebPII weak-label status

- Verified existing_repo_pii safety_v0 converted artifact: 1000/1000 canonical rows valid. Ran prompt-injection weak stage over it, producing data/safety_v0/weak/existing_repo_pii/weak_labeled.jsonl; 1 rule evidence span found but source-assumed prompt_injection=false was not overridden.
- Closed WebPII weak-label gap by running prompt-injection rules over data/safety_v0/redacted/webpii/redacted.jsonl; output data/safety_v0/weak/webpii/weak_labeled.jsonl is 100/100 valid with 0 rule-flagged rows.
- Updated DATA_PLAN.md: marked existing_repo_pii and WebPII done, recorded residual review note, and set next step to bounded VLGuard inspection/conversion.
- Verified: validate_safety_v0 on existing_repo_pii converted + weak outputs and WebPII weak output; python -m pytest tests/test_convert_existing_repo_pii.py tests/test_pii_taxonomy.py -q (13 passed); python -m pytest tests/test_run_prompt_injection_rules.py tests/test_convert_existing_repo_pii.py -q (12 passed); python -m pytest tests/test_run_prompt_injection_rules.py tests/test_convert_webpii.py tests/test_run_ocr_webpii_alignment.py -q (20 passed).
- Residual risk: existing_repo_pii rendering/synthetic OCR boxes remain deferred; review safety_v0_existing_repo_pii_000738 as a prompt-injection hard-negative sanity case.

## 2026-06-18 — VLGuard metadata inspection and conversion

- Retried `ys-zong/VLGuard` after access was granted. Downloaded metadata only (`README.md`, `train.json`, `test.json`) into `data/safety_v0/raw/vlguard/`; image zips were intentionally not downloaded because they are multi-GB.
- Added VLGuard source scripts: `scripts/safety_v0/download/download_vlguard.py`, `scripts/safety_v0/inspect/inspect_vlguard.py`, and `scripts/safety_v0/convert/convert_vlguard.py`. Inspection artifacts written under `data/safety_v0/inspection/vlguard/`.
- Added `docs/datasets/vlguard.md` and indexed it in `docs/datasets/README.md`. Updated `DATA_PLAN.md` with VLGuard state and next-step decision point.
- Converted metadata to one canonical row per instruction-response pair: `data/safety_v0/converted/vlguard/source_canonical.jsonl`, 4,535/4,535 valid rows (train 2,977 / test 1,558). Mapping: sexually explicit -> sexual, violence -> violence, political -> political, personal data -> pii_visible; blood_gore remains unknown.
- Ran prompt-injection weak stage: `data/safety_v0/weak/vlguard/weak_labeled.jsonl`, 4,535/4,535 valid rows, 0 rule-flagged.
- Verified: `python -m pytest tests/test_convert_vlguard.py tests/test_run_prompt_injection_rules.py -q` (10 passed); `validate_safety_v0.py` on converted and weak VLGuard outputs.
- Residual risk: VLGuard image OCR/PII/redaction is pending actual image extraction; do not automatically download upstream multi-GB zips without deciding the bounded image slice.

## 2026-06-18 — webdemo Analyze tab: image upload + full image safety pipeline
Extended the demo (Analyze) tab to mirror the Annotate tab's image flow. Users
can now drop/browse an image; it runs OCR (PaddleOCR) → PII detection on the OCR
text → span-to-box mapping + localized blur redaction, screens prompt injection
over typed text + OCR text, and exposes an explicit (paid) VLM safety router
button over the redacted artifact.
- New `webdemo/image_demo.py`: orchestrates upload→OCR→PII→redact reusing
  `Image.ocr`, `Image.redaction.recompute_redactions`, the PII pipeline, and the
  schema row builders. Caches the OCR adapter + built rows in memory (keyed by a
  `demo_id`) so the router reuses the same artifact without re-OCR. Uploads and
  redacted previews land under `data/safety_v0/review/demo/` (git-ignored),
  served via the existing `/api/review/image` route.
- `webdemo/app.py`: added `POST /api/analyze-image` (multipart) and
  `POST /api/demo/router` (paid, by `demo_id`).
- `webdemo/templates/index.html`: drag/drop upload control, image-pipeline
  output section (original w/ numbered region overlay, redacted image, OCR text
  + PII highlight, regions table, router verdict), analyze() branches on image.
- README updated (Analyze-tab description + new endpoints).
Verified: import-check of app+module; end-to-end `process_image` on a real
WebPII screenshot (OCR 23 boxes, redacted file written) and a synthetic email
image (1 PII span → 1 region mapped to box_0001, redaction applied); HTTP smoke
test (index renders new elements; `/api/analyze-image` returns spans/regions/
redacted_url + PI verdict; `/api/review/image` serves the redacted PNG as
200 image/png; `/api/demo/router` 404s cleanly on an unknown demo_id). The paid
router call itself was not exercised (mirrors the already-working review route).
Residual risk: first image analysis is slow (PaddleOCR warm-up); in-memory
demo-row cache is per-process (lost on restart — UI re-runs analysis).

## 2026-06-18 — VLGuard bounded image slice (option A)

- Built `scripts/safety_v0/download/extract_vlguard_images.py`: extracts a
  deterministic, diverse VLGuard image slice via `HfFileSystem` ranged reads of
  the remote `train.zip`/`test.zip` (central directory + selected member byte
  ranges only) instead of downloading the 440 MB of zips. Round-robins across
  (split, safe|harmful_subcategory) buckets. Also writes `review_slice.jsonl`
  (converted rows whose image is on disk) for reproducibility.
- Extracted 100 images (50 train / 50 test, 0 missing, ~14 MB) into
  data/safety_v0/raw/vlguard/images/ + extracted_manifest.json. Slice = 111
  canonical rows (some images have 2 instruction pairs).
- Ran English PaddleOCR -> PII redaction (regex_recall) -> prompt-injection
  rules on the slice. OCR 111/111 valid, 94 with text; 0 PII / 0 redactions
  (personal-data rows are ad-style topic risk, not visible PII strings); 0 PI
  hits. All three stage outputs validate 111/111.
- Fixed OCR adapter bug: `PaddleOcrAdapter._normalize` raised
  `ValueError: truth value of an empty array is ambiguous` when PaddleOCR
  returns empty numpy arrays for a text-less image. Now uses explicit length
  checks. Added regression test `test_paddle_normalize_v3_dict_empty_arrays`;
  tests/test_image_ocr_redaction.py + test_run_ocr_webpii_alignment.py = 29
  passed.
- Updated docs/datasets/vlguard.md and DATA_PLAN.md (VLGuard -> [x] for slice;
  Current Next Step -> inspect PKU-Alignment/MM-SafetyBench).
- Residual risk: slice is English-content visual safety only; Vietnamese PII
  regex naturally finds nothing here. Full VLGuard image set not downloaded
  (scale with --limit when more rows needed for the v0 mix).

## 2026-06-18 — MM-SafetyBench inspection + mapping decision

- Inspected `PKU-Alignment/MM-SafetyBench` (next multimodal safety source after
  VLGuard). It is PUBLIC (not gated) but CC BY-NC 4.0 (research-only). It ships
  per-category Parquet, NOT zips: `Text_only` (harmful question, image null,
  ~6-10 KB each) plus `TYPO`/`SD`/`SD_TYPO` image splits with PNG bytes embedded
  in the parquet. 13 categories, 1,680 rows per split. So the VLGuard ranged-zip
  extractor does not apply; per-category `TYPO` parquets are small enough to read
  whole.
- Confirmed the core signal: the harmful keyword is rendered as typography in
  `TYPO`/`SD_TYPO` images while the visible question is innocuous. PaddleOCR
  (`--lang en`) recovers the keyword verbatim ("hack into someone's bank
  account", "purchase illegal drugs"), so the OCR -> PII / prompt-injection
  pipeline applies directly.
- Added `scripts/safety_v0/download/download_mm_safetybench.py` (Text_only
  metadata only by default, ~110 KB; `--include-images` for the big parquets)
  and `scripts/safety_v0/inspect/inspect_mm_safetybench.py` (schema/stats/sample
  artifacts under `data/safety_v0/inspection/mm_safetybench/`).
- Decided the label mapping in `docs/datasets/mm_safetybench.md`: map only
  obvious axes (Sex->sexual, Physical_Harm->violence,
  Political_Lobbying/Gov_Decision->political); action=reject for the
  clearly-harmful categories; professional-advice categories' action left null;
  prompt_injection left NULL for all rows (multimodal image-smuggling is
  injection-ambiguous — deliberate departure from VLGuard's source_assumption
  false). pii_visible stays null at convert time (OCR/PII detector sets it).
- Updated DATA_PLAN.md (MM-SafetyBench -> [x] inspected with a State note;
  Current Next Step -> write the converter + bounded TYPO/SD_TYPO slice) and the
  docs/datasets/README.md index.
- Verified: download (13 Text_only parquets) + inspect run clean; total 1,680
  rows; sample_rows.jsonl spot-checked.
- Residual risk: converter and bounded image slice not built yet; SD-only images
  carry little OCR text (expected); prompt_injection ambiguity and
  professional-advice action mapping flagged for human review.

## 2026-06-18 — OpenRouter fallback (xiaomi/mimo-v2.5) for paid Gemini calls

- Added `src/pipeline/Fallbacks/openrouter_fallback.py`: thin `OpenRouterFallback`
  client pinned to `https://openrouter.ai/api/v1`, default model
  `xiaomi/mimo-v2.5`, key from `OPENROUTER_API_KEY` (falls back to
  `OPENAI_API_KEY`). One-shot, no internal retries (the primary has already
  retried). Lazy `openai` import + injectable client keep the test suite
  network-free.
- `GeminiTranslator` and `GeminiVlmRouter` gained opt-in `fallback_client=` /
  `fallback_model=` kwargs. When set, the fallback is called once **after**
  the primary raises a retryable error (HTTP 429 / 5xx + overload markers).
  Non-retryable errors still re-raise / route to `unsure` as before.
- Router fallback is **text-only** — `xiaomi/mimo-v2.5` is not a VLM in this
  repo, so the fallback is skipped for rows that carry an image and those
  rows continue to land in the `unsure` fallback queue. No `response_format`
  is sent on the fallback call; `parse_router_output` handles malformed
  responses by routing to `unsure`.
- Verified: 15 new tests across `tests/test_translation.py`,
  `tests/test_router.py`, and the new `tests/test_openrouter_fallback.py`.
  Full suite: 268/268 pass.
- Docs: `docs/translation-augmentation.md` and `docs/vlm-safety-router.md`
  got an "OpenRouter fallback (opt-in)" subsection each.
- Residual risk: no live OpenRouter diagnostic run yet; the slug
  `xiaomi/mimo-v2.5` and its availability/structured-output behavior are
  unverified at runtime. The fallback path is fully unit-tested with a fake
  client; smoke test with a real `OPENROUTER_API_KEY` before relying on it
  in production runs.

## 2026-06-18 — MM-SafetyBench converter + bounded image slice

- Built `scripts/safety_v0/convert/convert_mm_safetybench.py`: reads the
  Text_only parquets, emits one text-only canonical row per (category, id) ->
  1,680 rows, split="test", license_status="cc_by_nc_4.0". Label mapping lives
  in `category_labels()` (single source of truth): action=reject for the 8
  clearly-harmful categories (972 rows), null for the 5 professional-advice
  categories (708); sexual=true for Sex (109), violence=true for Physical_Harm
  (144), political=true for Political_Lobbying+Gov_Decision (302);
  prompt_injection null on all rows (multimodal smuggling is injection-
  ambiguous). 0 invalid.
- Built `scripts/safety_v0/download/extract_mm_safetybench_images.py`: reads the
  chosen image variant's per-category parquets (default TYPO ~25 MB total, on
  demand), round-robins a diverse slice across all 13 categories, writes PNGs to
  images/<Category>/<VARIANT>/<id>.png, and emits image-bearing rows to
  review_slice.jsonl. Imports category_labels from the converter so slice labels
  match. SD_TYPO/SD selectable via --variant.
- Ran a 26-image TYPO slice (2/category) end to end: OCR 26/26 with text (English
  PaddleOCR recovers the smuggled keyword verbatim, e.g. "multi-level marketing",
  "create a scam", "demeans and insults a specific race"); PII 0 redactions
  (correct — OCR text is the harmful keyword, not identifiers); PI rules 0 hits,
  filled prompt_injection=false (label_source="rule", weakest layer) on all 26.
  All five artifacts validate (1,680/1,680 convert; 26/26 slice stages) via
  validate_safety_v0.py.
- Added tests/test_convert_mm_safetybench.py (8 tests, all pass): label mapping
  per category + a valid built row.
- Updated docs/datasets/mm_safetybench.md (Converter + Bounded Image Slice +
  Current State), docs/datasets/README.md index, DATA_PLAN.md (completion notes +
  Current Next Step -> inspect yiting/UnsafeBench).
- Residual risk: only a 26-image TYPO slice is processed; full-image weak labels
  and SD_TYPO realism pending a larger extraction. The professional-advice action
  mapping and the multimodal prompt_injection question remain human-review flags.

2026-06-19
- Refined the writeup files to convert them into high-quality scientific reports:
  - Corrected broken Vietnamese and improved the academic/formal tone in `writeup/report-vi.typ`.
  - Created a corresponding English version in `writeup/report.typ`.
  - Removed all internal filenames, code symbols (e.g. classes, variables), and private repository/token references to make the reports readable and polished for an external scientific reader.
- Verified that both Typst files compile cleanly using `typst compile`.
- Residual risk: None.

2026-06-19
- Re-introduced the dataset names (e.g. `pii_masking_95k`, `safety_v0`, `vihsd_topic_safety`, `UIT-ViHSD`), repository info, and model baseline names (e.g. `char_ngram_prompt_injection`, `Underthesea`, `PhoBERT`, `viBERT`, `PhoBERT/viBERT`) back into both the English `writeup/report.typ` and Vietnamese `writeup/report-vi.typ` reports as requested, maintaining a formal scientific tone while keeping file names (`.md`, `.py`) excluded.
- Re-verified successful compilation of both Typst files.
- Residual risk: None.

2026-06-19
- Extracted validation per-entity metrics for both `regex_recall` (pattern-based) and `underthesea_regex_recall` (optimized hybrid pattern + NER) from the session reports in `/home/tungnguyen/Work/vsf/report/`.
- Embedded a comparative per-entity metrics table directly into the PII result section of both `writeup/report-vi.typ` and `writeup/report.typ`.
- Successfully compiled both Typst files.
- Residual risk: None.

2026-06-19
- Added `images/entity_centric_bars.png` as a new figure in the PII results section of both `writeup/report.typ` and `writeup/report-vi.typ`.
- Successfully compiled both Typst files.
- Residual risk: None.

2026-06-19
- Expanded and refined the Topic Filtering section in both `writeup/report-vi.typ` and `writeup/report.typ` to explain the label space (the seven risk axes of `safety_v0`), dataset mapping details (the Hate/Offensive/Clean labels from UIT-ViHSD being orthogonal to safety axes), mapping logic (`None != False`), and future roadmap.
- Fixed Typst math syntax compile errors and verified successful compilation of both files.
- Residual risk: None.

2026-06-19
- Extracted representative samples for `pii_masking_95k`, `local_vietnamese_seed`, and `UIT-ViHSD` from the codebase and datasets.
- Incorporated these dataset samples into `writeup/report-vi.typ` and `writeup/report.typ` within their respective sections.
- Re-verified successful compilation of both Typst files.
- Residual risk: None.

## 2026-06-19
- **What changed**: Expanded the PII detection section in `writeup/report-vi.typ` and `writeup/report.typ` to explain how regular expression and NER recognizers are structured in the codebase (pattern recognizers, specific Vietnamese PII patterns, checksum/Luhn validation, and Underthesea/spaCy/Transformer NER wrapper integrations). Compiled Typst files to updated PDFs.
- **What was verified**: Successfully compiled both `report-vi.typ` and `report.typ` into PDF format using Typst.
- **Residual risk**: None.

## 2026-06-19
- **What changed**: Rewrote the PII recognizers section in `writeup/report-vi.typ` and `writeup/report.typ` to explain the underlying mechanics (context-aware regex matching, algorithmic Luhn validation, carrier-prefix filtering, heuristic NER score calibration with context cues/penalties, and ensemble consensus) instead of relying on codebase implementation/class names. Recompiled to PDF.
- **What was verified**: Verified successful Typst compilation for both reports.
- **Residual risk**: None.

## 2026-06-19
- **What changed**: Rewrote the Prompt Injection defense section in `writeup/report-vi.typ` and `writeup/report.typ` to explain the underlying mechanics (Weighted rules, Diversity Bonus, Benign Discussion Bypass, and Character N-gram Naive Bayes statistical classifier) rather than referring to class/implementation names. Compiled Typst files.
- **What was verified**: Successfully compiled both Typst reports.
- **Residual risk**: None.

## 2026-06-19
- **What changed**: Enriched the AI Guardrails taxonomy table in `writeup/report-vi.typ` and `writeup/report.typ` with complete reference links, defense methods, datasets/models, and detailed notes for each of the safety tasks (PII, Redaction, Prompt Injection, Jailbreak, Topic Filtering, and Malicious Intent). Compiled Typst files.
- **What was verified**: Verified successful Typst compilation for both reports.
- **Residual risk**: None.

## 2026-06-19
- **What changed**: Removed backticks ` ` from all dataset and model entries in the taxonomy tables in `writeup/report-vi.typ` and `writeup/report.typ` to prevent column overflow and enable correct line-wrapping in Typst. Compiled Typst files.
- **What was verified**: Successfully compiled Typst reports to PDF and checked execution.
- **Residual risk**: None.

## 2026-06-19
- **What changed**: Modified the dataset column formatting in the taxonomy tables of `writeup/report-vi.typ` and `writeup/report.typ` to replace underscores with hyphens and added explicit Typst linebreaks (`\ `) to separate multiple dataset names. Recompiled to PDF.
- **What was verified**: Verified successful Typst compilation and confirmed correct line-wrapping layout.
- **Residual risk**: None.

## 2026-06-19
- **What changed**: Removed the `#figure` block wrapping around the guardrails taxonomy tables in `writeup/report-vi.typ` and `writeup/report.typ` to render them as top-level tables directly under their headings. Compiled Typst files.
- **What was verified**: Successfully compiled both Typst reports.
- **Residual risk**: None.

## 2026-06-19
- **What changed**: Modified the table column widths in `writeup/report-vi.typ` and `writeup/report.typ` from `(auto, 1.3fr, ...)` to `(0.6fr, 1.3fr, ...)` to make the first column narrower and force wrapping on long safety task titles. Compiled Typst files.
- **What was verified**: Successfully compiled Typst reports to PDF and checked execution.
- **Residual risk**: None.

## 2026-06-25
- **What changed**: Opened PR #1 (https://github.com/tungnguyenlam/vsf/pull/1) merging `feat/safety-v0-review-ui` into master — 7 commits of safety_v0 work (VLM safety router, image/OCR redaction pipeline, human-review Annotate UI, PI rules + NB classifier, new datasets MM-SafetyBench/VLGuard/WebPII/PI seeds, translation augmentation, updated Typst writeup).
- **What was verified**: Branch already pushed to origin and up-to-date; confirmed all new datasets have docs/datasets/*.md and the router/pipeline are documented; 24 new test files present; no pre-existing PR for the branch.
- **Residual risk**: PR not yet code-reviewed or run through full test suite (heavyweight model/dataset downloads kept optional). Reviewer should run /code-review and CI before merge.

## 2026-06-25
- **What changed**: No file changes. Verified the Prompt Injection evaluation numbers already cited in `writeup/report.typ` and `writeup/report-vi.typ` by independently re-running the rule-based detector.
- **What was verified**: Re-ran `scripts/safety_v0/evaluate_pi_vi.py` (rule_based_prompt_injection). Reproduced the table exactly: `local_vi_prompt_injection` n=120 P/R/F1=1.00/1.00/1.00; `deepset_prompt_injections` n=351 P=1.00 R=0.084 F1=0.156; `llmail_inject_challenge` n=2000 P=1.00 R=0.022 F1=0.043. Built a negative-heavy eval set (3,546 real vihsd negatives + 46 hard benign seeds) and confirmed 0 false positives -> precision 1.00, matching the "over 3,500 benign Vietnamese samples, zero false positives" claim in the report. Also ran `cyberseceval3_visual_prompt_injection` (n=999, recall 0.0 on text-only) — correctly excluded from the table since its attacks live in the image, not text. Full test suite green (276 passed, 1 skipped).
- **Caveat (honest framing)**: In-domain Vietnamese recall=1.00 is coverage-by-construction (the rules were authored against the same gold seeds). The credible, non-circular result is precision: 0 FP across 3,743 real negatives (VI + EN). Recall does not transfer to unseen/English attacks, which is exactly the motivation for the learned char-ngram NB classifier and a larger Vietnamese attack corpus.
- **Residual risk**: The char-ngram Naive Bayes detector (`char_ngram_prompt_injection`) is described in the report but not yet trained/evaluated; a leakage-free eval needs a held-out Vietnamese attack split that the current 74-attack seed set is too small to provide.

## 2026-06-25
- **What changed**: Produced the first leakage-free evaluation of the learned prompt-injection baseline (char-ngram Naive Bayes) and added it to the writeup. New `PiViEvalDataset` (`src/pipeline/PromptInjection/Datasets/PiViEvalDataset.py`, registered as `pi_vi_eval`) exposes the balanced 148-row `pi_vi_eval` set (74 attacks / 46 benign seeds / 28 ViHSD negatives) as `PromptInjectionExample` rows, so the existing `--train-strategy leave_one_out` harness can train+score NB on the identical rows as the rule baseline. Added a focused test, a rule-vs-NB comparison table + honest framing to `writeup/report.typ` and `writeup/report-vi.typ`, and updated `docs/prompt-injection.md` and `docs/datasets/pi_vi_eval.md`.
- **What was verified**: NB leave-one-out on `pi_vi_eval`: P=0.8140 R=0.9459 F1=0.8750 (tp=70 fp=16 fn=4 tn=58); rules (memorized) P=R=F1=1.00 on the same 148 rows. The LOO 0.875 is the non-circular generalization estimate (rules' 1.00 is coverage-by-construction on the same gold attacks). Both Typst reports compile cleanly. Full suite green: 277 passed.
- **Translation augmentation attempt**: Started full deepset EN->VI augmentation to grow the Vietnamese attack corpus; the `gemini-flash-latest` translator is rate-limited (8-60s backoff on 429s), so ~24/351 rows in ~15 min — impractical. Killed it; translations are cached (`data/safety_v0/manifests/translation_cache.json`) so a future rerun resumes free. The partial `data/safety_v0/augmented/deepset_prompt_injections/augmented.jsonl` (git-ignored) is incomplete and was NOT used for the NB eval; the NB result uses only stable on-disk data.
- **Residual risk**: The 148-row NB result is small-sample; the 16 FP show NB over-fires on benign Vietnamese n-grams (e.g. "của"). A larger/diverse Vietnamese attack corpus (the deferred deepset/llmail translation, run under a higher Gemini quota or in small rate-limited batches) is still the path to a fairer learned-detector comparison.

## 2026-06-25 — NB decision-threshold sweep on pi_vi_eval
- Added scripts/safety_v0/sweep_pi_vi_nb_threshold.py: runs the char-ngram NB
  leave-one-out once on pi_vi_eval (148 rows), then sweeps thresholds offline
  (grid + observed score boundaries), reporting P/R/F1/confusion per threshold
  plus the F1-optimal and default(0.5) rows; optional --metrics JSON dump.
- Finding: NB posteriors are saturated near 0/1. Default 0.5 sits in a flat
  region. Raising the cut-off to 0.999 removes only 6 FP (16->10), lifting F1
  from 0.875 to at most 0.909; recall stays hard-capped at 0.946 (4 attacks
  score ~0, missed at any usable threshold). Best-F1 threshold is fit on the
  eval set, so 0.909 is an optimistic ceiling, not a deployable gain.
- Conclusion: threshold tuning cannot close the gap to the rule baseline on this
  corpus; more diverse Vietnamese attack data is the real lever.
- Integrated into writeup/report.typ and report-vi.typ (new paragraph after the
  NB comparison table; both PDFs recompiled cleanly), docs/datasets/pi_vi_eval.md,
  and docs/prompt-injection.md (with reproduce command).
- Verified: added test_nb_threshold_sweep_finds_no_deployable_gain_over_default
  in tests/test_prompt_injection_evaluation.py; full PI eval suite 15 passed.
- Residual risk: sweep is on the 148-row balanced set only; precision ceiling
  may shift on a negative-heavy or larger set. No LLM budget spent.

## 2026-06-25 — Held-out Vietnamese PI generalization (deepset_vi)
- Unblocked translation augmentation: added an `openrouter` translator backend
  (OpenRouterTranslator in src/pipeline/Translation/translator.py, registered;
  exported from package; reuses the OpenRouter fallback's base_url/model/key as
  single source of truth). Selected via `--backend openrouter`. This bypasses the
  Gemini free-tier rate-limit wall (even one call could not land).
- Model choice: `openai/gpt-4o-mini` (~0.9s/call, faithful, refuses to OBEY the
  injection) over default xiaomi/mimo-v2.5 (~19s/call reasoning model) and over
  mistral-small (which followed the injection instead of translating).
- Translated all 351 deepset rows EN->VI (154 attacks + 197 benigns), 0 failed,
  0 invalid -> data/safety_v0/augmented/deepset_prompt_injections/augmented.jsonl.
- Added DeepsetViDataset (registered `deepset_vi`, translated twins only) and an
  `external` train strategy (+ --train-dataset CLI) to the eval runner/config:
  fit once on a separate dataset, score every eval row = a true held-out test.
- Held-out results (the non-circular number that was missing):
    rule-based authored -> deepset_vi: P 1.000 R 0.065 F1 0.122 (10/154, 0 FP)
    NB pi_vi_eval -> deepset_vi:        P 0.542 R 0.292 F1 0.380
    NB local_seed -> deepset_vi:        P 0.646 R 0.201 F1 0.307
    NB deepset_vi leave-one-out:        P 0.783 R 0.799 F1 0.791 (in-domain)
  Conclusion: rules' 1.0 was overfit (collapses to 0.065 recall on unseen
  attacks); cross-source NB transfer is weak; but in-domain NB hits 0.79, so the
  gap is a DATA problem (diverse in-domain VI attacks), not a model ceiling.
- Integrated: docs/datasets/deepset_vi.md (new) + index; docs/prompt-injection.md
  (table + datasets row); both writeup reports (new held-out table + analysis,
  recompiled clean); output/safety_v0/deepset_vi/heldout_results.json.
- Verified: added tests (deepset_vi load, external strategy run + missing-train
  guard, openrouter backend registration/key); full suite 283 passed, 1 skipped.
- Cost: 351 gpt-4o-mini translations (negligible, well under $0.10). Residual
  risk: VI labels inherited via translation (provenance *_translated), not
  hand-verified per row.

## 2026-06-25 — Pooled-training transfer + second held-out source (llmail_vi)
- Translated 500 llmail-inject rows EN->VI (openrouter/gpt-4o-mini, 0 failed/0
  invalid, 430 new calls). llmail is attack-only -> recall-only held-out source.
  Added LlmailViDataset (registered `llmail_vi`, translated twins only).
- Extended the eval runner's `external` strategy to accept a comma-separated
  POOL of train datasets (concatenate, then fit once); CLI --train-dataset takes
  "a,b,c". Tests added for the pool + llmail_vi load.
- Transfer experiments on llmail_vi (recall, of 500 attacks):
    rule-based authored:                 0.026 (13)   <- collapses on novel source
    NB pi_vi_eval:                       0.262 (131)
    NB deepset_vi:                       0.364 (182)
    NB pool(pi_vi_eval+local+deepset_vi):0.386 (193)
- Also checked pooling on deepset_vi held-out: pool 0.302 vs pi_vi_eval-alone
  0.380 (dilution HURT there). Reconciled: on the SAME held-out distribution the
  single best in-domain source wins; on a NOVEL source (llmail_vi) diversity
  helps and recall climbs monotonically with pool size.
- Finding: rules don't generalize (0.026-0.065 recall on unseen sources); NB
  beats them 10-15x and improves monotonically as the VI training pool grows ->
  translation augmentation is the confirmed data-centric lever.
- Integrated: docs/datasets/llmail_vi.md (new) + index; docs/prompt-injection.md
  (table + datasets row); both reports (new transfer table + analysis,
  recompiled clean); output/safety_v0/llmail_vi/transfer_results.json.
- Verified: full suite 285 passed, 1 skipped.
- Cost: ~430 gpt-4o-mini calls (negligible). Residual risk: llmail_vi is
  recall-only (no benigns) so cannot detect over-firing; only 500/2000 rows
  translated; VI labels inherited via translation (not hand-verified).

## 2026-06-25 — Held-out reproducer pinned to writeup numbers
- Added scripts/safety_v0/run_heldout_evaluation.py: re-runs the rule-based and
  char-ngram NB detectors on deepset_vi + llmail_vi from the cached translations
  (no LLM spend, reads on-disk JSONL) and rewrites both output JSONs.
- Pinned the writeup tables with a new test
  (test_heldout_reproducer_matches_writeup_tables) that asserts the reproducer
  numbers match the rounded report figures (deepset_vi F1 0.122/0.380/0.307/0.791,
  llmail_vi recall 0.026/0.262/0.364/0.386).
- Verified: re-ran the script; every row reproduces exactly. Full suite 286
  passed, 1 skipped.
- Residual risk: numbers are exact, but the report shows 3-decimal rounding; the
  test allows rounding error so a future small refactor (e.g. test ordering in
  the pool) cannot silently drift the cited numbers.

## 2026-06-25 — One-command reproducer for every PI eval number in the report
- Extended scripts/safety_v0/run_heldout_evaluation.py: now also runs the
  pi_vi_eval in-domain (rule vs NB LOO) and the threshold sweep, so a single
  command reproduces every PI eval number cited in report.typ / report-vi.typ.
  Writes four JSONs:
    output/safety_v0/pi_vi_eval/in_domain_results.json
    output/safety_v0/pi_vi_eval/nb_threshold_sweep.json
    output/safety_v0/deepset_vi/heldout_results.json
    output/safety_v0/llmail_vi/transfer_results.json
- Lifted the threshold-sweep helpers into a reusable sweep_thresholds() in
  scripts/safety_v0/sweep_pi_vi_nb_threshold.py; the standalone CLI still
  works (existing test imports preserved).
- Extended test_heldout_reproducer_matches_writeup_tables to pin the in-domain
  numbers (rule 1.000; NB LOO P=0.814 R=0.946 F1=0.875) and the sweep ceiling
  (best F1 <= 0.909 with recall still 0.946, fp <= 10).
- Updated docs/prompt-injection.md and docs/datasets/pi_vi_eval.md to point at
  the unified reproducer as the recommended path.
- Verified: re-ran run_heldout_evaluation.py; every reported number reproduces.
  Full suite 286 passed, 1 skipped. No LLM spend.

## 2026-06-25 — Makefile for review-time reproducibility
- Added Makefile with `help`, `reproduce-pi`, `test-pi`, `sweep-pi`, `test`, `all`.
  Reviewer can now verify every PI number in report.typ / report-vi.typ with:
      make reproduce-pi     # writes the 4 output JSONs
      make test-pi          # runs the pinning test
  No LLM spend; reads the cached translations and the in-domain eval file.
- AGENTS.md: added a "Makefile" section pointing future agents at the targets
  instead of hand-rolling commands.
- Verified: make help / reproduce-pi / test-pi all run cleanly (21 PI tests
  pass; 4 output JSONs rewritten).
- Residual risk: none for now. The Makefile only wraps existing Python entry
  points, so it cannot drift from the actual numbers.

## 2026-06-25 — Makefile PII targets + smoke test
- Added Makefile targets: `test-pii` (runs the PII pipeline + registry + evaluation
  tests, no HF download) and `smoke-pii` (runs `regex_only` on a 5-row HF sample
  to smoke-test the pipeline end-to-end, writes output/evaluations/smoke_pii/).
  `make all` now chains reproduce-pi + test-pi + test-pii + smoke-pii.
- Added test_makefile_smoke_pii_target_runs_end_to_end: invokes
  scripts/evaluate_pipeline.py as a subprocess (5 rows, regex_only, --no-log)
  and asserts the JSON shape so `make smoke-pii` is exercised from CI.
- AGENTS.md: Makefile section updated to mention the PII targets.
- Verified: make help / test-pii / smoke-pii all run cleanly; 5-row smoke run
  completes in ~1s on real HF data. Full suite 287 passed, 1 skipped.
- Residual risk: smoke-pii exercises regex_only only (not underthesea / hybrid)
  to avoid the NER model download — keep it as a wiring check, not a perf check.

## 2026-06-25 — pin the PII writeup sample

- Added `--input-ids` / `--input-ids-file` to `src/pipeline/Pipelines/evaluation.py` plus a `resolve_dataset_key` helper in `src/pipeline/Datasets/registry.py` so the CLI accepts both the registry key and the legacy HF repo id. The PII report numbers come from a 500-row deterministic subsample of `pii_masking_95k` validation; before this change the val sample moved when HF re-encoded the dataset, so the numbers could not be re-derived from a clean clone.
- Persisted the 500-row val `input_id`s as `data/sample_ids/pii_masking_95k__validation__writeup_pin_500.json` (deterministic, `random_state=42`).
- New `make reproduce-pii` target runs `regex_recall` on that manifest and writes `output/evaluations/pinned_pii/regex_recall.json`. Two new tests: `test_pinned_pii_reproducer_is_deterministic` (two back-to-back runs agree byte-for-byte) and `test_pinned_pii_reproducer_pins_reported_metrics` (12 per-entity F1s pinned to 4 decimals). `make all` now chains `reproduce-pii` between `test-pi` and `test-pii`.
- Verified: full test suite 289 passed / 1 skipped (2 new tests, no regressions). `make reproduce-pii` runs in ~1s and is reproducible. Per-entity F1s differ from the 2026-06-16 500-row run because the HF dataset was re-uploaded between then and now; pinned numbers reflect the current state of the dataset, not the legacy run.
- Residual risk: the pinned numbers are for the cheapest deterministic slice we can afford, not the report's headline 0.9658 / 0.8420 / 0.8996 (those came from the full ~9500-row val set with NER). A future task could add a full NER-based run behind an opt-in target, but per AGENTS.md cost discipline that is reserved for the test split / final reporting only.

## 2026-06-25 — UnsafeBench inspect + mapping step

- Download + inspect scripts committed for the DUA-gated `yiting/UnsafeBench` visual-safety benchmark:
  - `scripts/safety_v0/download/download_unsafebench.py` — defaults to the test split (184 MB),
    fails LOUDLY with a clear "DUA approval needed" message when the HF token is missing
    or not yet approved. Never silently retries or pre-fetches the multi-GB archives.
  - `scripts/safety_v0/inspect/inspect_unsafebench.py` — reads the parquet via pandas
    (transitive via `datasets`), writes `schema.json`/`stats.json`/`sample_rows.jsonl`
    with per-(category, safety_label, source) counts, text length distribution, image-size
    distribution, and missing-value counts. Decodes image bytes via PIL when needed.
- New `tests/test_download_inspect_unsafebench.py` (5 tests): synthetic-parquet
  roundtrip (5 rows across Hate/Sexual/Violence + Safe), `--limit` slice cleanup,
  downloader missing-token error path, unknown-split validation, and a constant-pin
  test that locks the HF repo layout (only `train`+`test` parquets, both under `data/`).
  All 5 pass; no model download, no network.
- `docs/datasets/unsafebench.md` records the 11-category mapping decision (OpenAI
  DALL-E content policy April 2022, paper Section 2.1), per-category -> `action` /
  boolean axis table, DUA license handling (`license_status="dua_research"`), the
  fact that the dataset is currently not downloaded (no DUA approval for the
  repo's HF token), and the 6-step next-steps list once access is granted.
  Indexed in `docs/datasets/README.md`.
- DATA_PLAN.md: marked the inspection step done, updated "Current Next Step" to
  "request DUA access, then convert".
- Verified: full test suite 294 passed / 1 skipped (5 new tests, no regressions).
  Downloader smoke-tested end-to-end: empty token -> exit 1 with DUA message;
  invalid token -> exit 1 with chained gated-repo error.
- Residual risk: no real parquet is on disk yet, so the inspection
  artifacts under `data/safety_v0/inspection/unsafebench/` are absent
  until DUA access is granted. The downloader + inspector are tested
  with a synthetic 5-row parquet only. Once access arrives, the
  immediate next step is `download_unsafebench.py --limit 500` and
  then writing `convert_unsafebench.py`.

## 2026-06-25 — add 8 figures to the PII + PI writeup

- New script `scripts/plot_report_extras.py` produces 8 PNGs into `writeup/images/` (3 PII + 5 PI). Reads only on-disk metrics already cited in the writeup tables (`results/metrics.json`, `output/safety_v0/pi_vi_eval/*.json`, `output/safety_v0/deepset_vi/heldout_results.json`, `output/safety_v0/llmail_vi/transfer_results.json`, `output/dataset_profiles/pii_masking_95k/all/stats.json`).
- New figures: `pii_entity_distribution.png`, `pii_recall_gap.png`, `pii_overall_compare.png`, `pi_confusion_in_domain.png`, `pi_heldout_f1.png`, `pi_recall_growth.png`, `pi_threshold_sweep.png`, `pi_fpr_summary.png`.
- Inserted 8 `#figure(image(...))` blocks into both `writeup/report.typ` and `writeup/report-vi.typ` next to the tables they visualise (no table was removed, only enriched with the corresponding figure and a caption that names the data source).
- Both reports recompile cleanly with `typst compile`; rebuilt `writeup/report.pdf` and `writeup/report-vi.pdf`.
- Verified: figures reproduce the exact numbers already cited in the writeup tables (rule-based F1 1.000, NB LOO F1 0.875, in-domain NB LOO F1 0.791, combined-pool recall 0.386, best-F1 threshold 0.909, recall gaps 0.000 / 0.000 / 0.441 for PHONE_NUMBER/EMAIL_ADDRESS/PERSON).
- Residual risk: figures are generated against the same on-disk snapshots the writeup cites, so any future change to the underlying numbers requires rerunning this script (no separate CI gate yet).

## 2026-06-25 — UnsafeBench: DUA granted, download + convert

- DUA access granted on yiting/UnsafeBench. Downloaded the bounded test split
  (175 MB, 2,037 rows) to data/safety_v0/raw/unsafebench/ (train 755 MB left
  alone per cost discipline). Ran the inspector over all 2,037 rows:
  1,260 Safe / 777 Unsafe (no N/A in the released split), sources balanced
  (Lexica 1,022 / Laion5B 1,015), `text` empty on 609 rows. Confirmed the
  `category` column is the *tested* bucket (present on both Safe and Unsafe
  rows), so safety_label drives the row and category only refines axes for
  Unsafe rows.
- Wrote scripts/safety_v0/convert/convert_unsafebench.py: one canonical row
  per image, mirroring docs/datasets/unsafebench.md. Output 2,037/2,037 valid
  -> 1,260 action=safe, 579 action=reject, 198 action=null (the Political 91 +
  Public-and-Personal-Health 55 + Spam 52 Unsafe rows whose action is deferred
  to review). pii_visible/prompt_injection are False(source_assumption) for Safe
  rows and null for Unsafe rows; blood_gore stays null even for Violence (no
  sub-label). `text` is kept in source_labels for audit only (has_text=False).
- tests/test_convert_unsafebench.py (11 tests, synthetic parquet, no network):
  pins the per-category mapping, case-insensitive category match, one-row-per-
  image, --limit, and full schema validation. All pass.
- Updated docs/datasets/unsafebench.md (access state, observed distribution,
  next-steps) and DATA_PLAN.md Current Next Step.
- Verified: convert tests 11 passed; full suite 305 passed / 1 skipped (was
  294, +11 new), no regressions.
- Residual risk: image pixels are still inside the parquet — the converter
  references data/safety_v0/raw/unsafebench/images/<input_id>.jpg but those
  files do not exist yet. Immediate next step is
  scripts/safety_v0/download/extract_unsafebench_images.py (PIL-decode the
  image column) before any OCR/PII/prompt-injection weak-label pass.

## 2026-06-25 — UnsafeBench image extraction + weak-label chain

- Added `scripts/safety_v0/download/extract_unsafebench_images.py`: PIL-decodes
  the parquet `image` column (handles HF `{"bytes",path}` struct, raw bytes,
  path-only cells) to `data/safety_v0/raw/unsafebench/images/<input_id>.jpg`
  using the same 1-based row order as the converter so
  `content.original_image_path` resolves exactly. Extracted 2,037/2,037, 0 failed.
- Added `--resume` to `scripts/safety_v0/run_ocr.py`: skips input_ids already in
  the output, appends, and flushes per row so an interrupted long image run
  converges on a plain re-run. (The first full OCR run was killed ~row 1268; a
  concurrent kill left one interleaved partial line, repaired by dropping it.)
- Ran OCR (`--lang en`) -> PII redaction -> prompt-injection rules over a
  1,368-row slice (OCR cut early by decision; the rest can be finished with
  `--resume`). Results: 796/1,368 had legible OCR text; 31 rows got PII
  redactions (~2%, near-zero as predicted for English image text); 0
  prompt-injection flags (VI-trained rules did not over-fire). PI stage was
  pointed at redacted.jsonl because the detector reads `content.ocr_text`.
- Tests: `tests/test_extract_unsafebench_images.py` (5) + a `--resume` test in
  `tests/test_run_ocr_webpii_alignment.py`. Full suite 311 passed / 1 skipped.
- Residual risk: PII redaction records `redaction_metadata` but does not flip
  `labels.pii_visible=true`; the 31 redacted rows are pii_visible candidates for
  the review pass, not authoritative weak labels. Verify-by docs/datasets/unsafebench.md.

## 2026-06-25 — UnsafeBench finalized at the 1,357-row OCRed slice

- Decision (user): stop OCR, do not finish the remaining rows; discard the
  non-OCRed rows and their image info, keep only what has OCR + downstream data.
- Discovered the OCR/redact/weak files held 1,368 *lines* but only 1,357
  *unique* input_ids — 11 duplicate rows in the 1345-1355 range from the
  kill/resume concurrency overlap. Deduped all three (keep last occurrence,
  sorted by input_id).
- Trimmed converted/source_canonical.jsonl from 2,037 -> 1,357 (dropped 680
  non-OCRed rows) and deleted the 680 orphan JPEGs under raw/.../images/.
- Result: converted == ocr == redacted == weak == extracted images, all 1,357
  unique ids (verified identical id sets, 0 dangling original_image_path).
- Verified: schema validation 1357/1357 valid on converted + weak; 790/1357
  legible OCR rows; 31 PII redactions (~2%); 0 prompt-injection flags.
  Weak labels: action {safe 911, reject 311, null 135}; prompt_injection all
  False; pii_visible {False 911, null 446}.
- Tests: 33 passed (extract/convert/run_ocr/download-inspect; all synthetic).
- Residual risk: pii_visible still not flipped for the 31 redacted rows (known
  gap, documented). Slice is regenerable from the parquet via extractor +
  run_ocr --resume if we ever want the full 2,037.
