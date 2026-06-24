# Datasets

Each evaluation dataset is:

1. A **class** under `src/pipeline/Datasets/` (subclass of `BaseDataset`, registered in
   `registry.py`). The class owns where the data lives, its column schema, and its own
   `label_to_presidio` mapping — because every dataset ships a different label taxonomy.
2. A **doc** in this folder, `docs/datasets/<name>.md`, describing what it is, columns, span
   format, the label taxonomy, and the **mismatch** vs our Presidio entity types.

Combining datasets (future) is just instantiating several and concatenating their loaded frames;
the evaluator takes each dataset's mapping rather than assuming one global dict.

## Index

| Key | Doc | Summary |
|-----|-----|---------|
| `hoangha_vie_pii` | [hoangha-vie-pii.md](hoangha-vie-pii.md) | Gated Vietnamese PII dataset, 10k rows, inline `[value]<label>` spans; locally split into train/dev/test. |
| `hf_prompt_injection_multilingual` | [prompt-injection-multilingual.md](prompt-injection-multilingual.md) | Public HF binary prompt-injection dataset; useful as cross-language smoke coverage, not the main Vietnamese metric. |
| `local_vietnamese_app_seed` | [local-vietnamese-prompt-injection-app-seed.md](local-vietnamese-prompt-injection-app-seed.md) | Repo-owned Vietnamese application-shaped prompt-injection smoke benchmark. |
| `local_vietnamese_mentor_seed` | [local-vietnamese-prompt-injection-mentor-seed.md](local-vietnamese-prompt-injection-mentor-seed.md) | Repo-owned Vietnamese mentor/application-style prompt-injection smoke benchmark. |
| `local_vietnamese_seed` | [local-vietnamese-prompt-injection-seed.md](local-vietnamese-prompt-injection-seed.md) | Repo-owned Vietnamese binary prompt-injection seed benchmark. |
| `pii_masking_95k` | [pii-masking-95k.md](pii-masking-95k.md) | Vietnamese synthetic PII, ~95k rows, pre-tokenized, 111 labels (default). |
| `existing_repo_pii` | [existing_repo_pii.md](existing_repo_pii.md) | safety_v0 source: converts repo PII datasets into canonical safety_v0 rows (PII-only, straight convert). |
| `webpii` | [webpii.md](webpii.md) | safety_v0 source: English web UI image PII boxes for OCR/redaction and visible PII review. |
| `local_vi_prompt_injection` | [local_vi_prompt_injection.md](local_vi_prompt_injection.md) | safety_v0 source: converts the local Vietnamese prompt-injection seeds into canonical rows (text-only, gold injection flag, straight convert). |
| `deepset_prompt_injections` | [deepset_prompt_injections.md](deepset_prompt_injections.md) | safety_v0 source: public prompt-injection text, filtered to English (351 of 662 rows, train/test), gold injection flag, topic axes left null. |
| `llmail_inject_challenge` | [llmail_inject_challenge.md](llmail_inject_challenge.md) | safety_v0 source: bounded sample of LLMail-Inject email prompt-injection submissions (2,000 rows, all positives; Phase1=train/Phase2=test); script-filtered to Latin. |
| `vihsd_topic_safety` | [vihsd_topic_safety.md](vihsd_topic_safety.md) | safety_v0 source: bounded UIT-ViHSD Vietnamese hate/offensive comments (3,500 rows, train/dev/test); topic axes left null (orthogonal taxonomy), PI=False negatives, hate label kept in source_labels. |
| `cyberseceval3_visual_prompt_injection` | [cyberseceval3_visual_prompt_injection.md](cyberseceval3_visual_prompt_injection.md) | safety_v0 source: CyberSecEval 3 visual prompt-injection (999 rows, all attacks, English, no image binaries); injection mapped to OCR text, gold PI flag, topic axes null. |
| `vlguard` | [vlguard.md](vlguard.md) | safety_v0 source: gated VLGuard image-plus-instruction safety metadata (4,535 converted instruction rows); maps clear sexual/violence/political/visible-PII subcategories, image OCR pending large zip extraction. |
| `mm_safetybench` | [mm_safetybench.md](mm_safetybench.md) | safety_v0 source: public (CC BY-NC) multimodal jailbreak benchmark, 13 categories / 1,680 converted rows; harmful keyword hidden as image typography (OCR-recoverable). Maps Sex/Physical_Harm/political only, action=reject for clearly-harmful, prompt_injection left null; bounded 26-image TYPO OCR/PII/PI slice done. |
| `pi_vi_eval` | [pi_vi_eval.md](pi_vi_eval.md) | safety_v0 eval set (not a build source): balanced Vietnamese prompt-injection benchmark (local_vi gold attacks + local_vi gold benigns + vihsd negatives) scoring precision AND recall together; default 148 rows. |
| `deepset_vi` | [deepset_vi.md](deepset_vi.md) | safety_v0 held-out eval set: Vietnamese twins of `deepset/prompt-injections` (EN->VI via openrouter/gpt-4o-mini), 351 rows (154 attacks + 197 benigns). First attack data the rules were NOT authored against — the non-circular generalization estimate. |
| `llmail_vi` | [llmail_vi.md](llmail_vi.md) | safety_v0 second held-out source: Vietnamese twins of `llmail-inject` (EN->VI), 500 rows, attack-only (recall-only). Shows NB recall climbs as the Vietnamese training pool grows; rules collapse to 0.026. |

## Adding a dataset

1. Add a `BaseDataset` subclass under `src/pipeline/Datasets/` (currently small datasets may live
   in `variants.py`; split to a dedicated file when the class grows). Set `name`, `hf_name`,
   `requires_token`, column names, and `label_to_presidio`; register it in `registry.py`.
2. Override `load()` only if the source needs handling the generic HF loader can't express.
3. Write `docs/datasets/<name>.md` and add a row to the index above.

## Our target entity types

`PERSON, LOCATION, ORGANIZATION, PHONE_NUMBER, EMAIL_ADDRESS, BANK_ACCOUNT, ID, DATE_TIME, MISC`
(defined in `src/pipeline/Verifiers/LLMVerifier.py` as `ENTITY_TYPES`). A dataset's `label_to_presidio`
should map its native labels onto this set; anything left unmapped is treated as out of scope and
dropped during mapped-type evaluation.
