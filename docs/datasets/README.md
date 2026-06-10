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
| `pii_masking_95k` | [pii-masking-95k.md](pii-masking-95k.md) | Vietnamese synthetic PII, ~95k rows, pre-tokenized, 111 labels (default). |

## Adding a dataset

1. Add a `BaseDataset` subclass in `variants.py` (set `name`, `hf_name`, `requires_token`,
   column names, and `label_to_presidio`); register it in `registry.py`.
2. Override `load()` only if the source needs handling the generic HF loader can't express.
3. Write `docs/datasets/<name>.md` and add a row to the index above.

## Our target entity types

`PERSON, LOCATION, ORGANIZATION, PHONE_NUMBER, EMAIL_ADDRESS, BANK_ACCOUNT, ID, DATE_TIME, MISC`
(defined in `src/pipeline/Verifiers/LLMVerifier.py` as `ENTITY_TYPES`). A dataset's `label_to_presidio`
should map its native labels onto this set; anything left unmapped is treated as out of scope and
dropped during mapped-type evaluation.
