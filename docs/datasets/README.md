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
| `local_vietnamese_seed` | [local-vietnamese-prompt-injection-seed.md](local-vietnamese-prompt-injection-seed.md) | Repo-owned Vietnamese binary prompt-injection seed benchmark. |
| `pii_masking_95k` | [pii-masking-95k.md](pii-masking-95k.md) | Vietnamese synthetic PII, ~95k rows, pre-tokenized, 111 labels (default). |

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
