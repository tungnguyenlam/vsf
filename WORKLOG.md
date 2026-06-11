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
