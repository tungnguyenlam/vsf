# VLGuard (safety_v0 source)

VLGuard is a gated Hugging Face image-to-text safety dataset:
`ys-zong/VLGuard`. It is MIT licensed but requires accepting the dataset access
terms because it may contain visually harmful content.

- Slug: `vlguard`
- Raw metadata: `data/safety_v0/raw/vlguard/train.json`,
  `data/safety_v0/raw/vlguard/test.json`
- Images: `train.zip` and `test.zip` upstream; not downloaded by default
- Downloader: `scripts/safety_v0/download/download_vlguard.py`
- Inspector: `scripts/safety_v0/inspect/inspect_vlguard.py`
- Converter: `scripts/safety_v0/convert/convert_vlguard.py`

## Raw Format

Each metadata row has:

| Field | Meaning |
|---|---|
| `id` | source sample id |
| `image` | relative image path inside the upstream zip |
| `safe` | image-level safety flag |
| `harmful_category` | unsafe rows only |
| `harmful_subcategory` | unsafe rows only |
| `instr-resp` | list of instruction/response objects |

Safe image rows usually contain two instruction/response entries:
`safe_instruction` and `unsafe_instruction`. Unsafe image rows contain one
`instruction`.

Downloaded metadata summary:

| Split | Rows | Safe Images | Unsafe Images |
|---|---:|---:|---:|
| train | 2,000 | 977 | 1,023 |
| test | 1,000 | 558 | 442 |

Unsafe subcategories:

| Category | Subcategories |
|---|---|
| `risky behavior` | `sexually explicit`, `violence`, `political`, `professional advice` |
| `privacy` | `personal data` |
| `deception` | `disinformation` |
| `discrimination` | `race`, `sex`, `other` |

## Canonical Mapping

The converter writes one canonical row per instruction/response pair. The image
path is recorded as `content.original_image_path` under
`data/safety_v0/raw/vlguard/images/...`, where a later bounded extraction step
will place files from the upstream zips.

| VLGuard signal | Canonical mapping |
|---|---|
| safe image + `safe_instruction` | `action=safe` |
| safe image + `unsafe_instruction` | `action=reject` |
| unsafe image + `instruction` | `action=reject` |
| `harmful_subcategory=sexually explicit` | `sexual=true` |
| `harmful_subcategory=violence` | `violence=true` |
| `harmful_subcategory=political` | `political=true` |
| `harmful_subcategory=personal data` | `pii_visible=true` |
| safe image | `sexual=false`, `violence=false`, `blood_gore=false`, `political=false`, `pii_visible=false` |

`prompt_injection=false` is a source assumption: this is not a prompt-injection
dataset. `religious` is left `null` because VLGuard does not expose a religious
topic label. For unsafe rows whose subcategory is outside our canonical axes
(`professional advice`, `disinformation`, `race`, `sex`, `other`), the original
labels are preserved in `source_labels` and unmapped canonical axes remain
`null`.

`blood_gore` is not mapped from `violence`; VLGuard does not distinguish blood
or gore, so that axis stays unknown for unsafe violence rows until human/API
review.

## Current State

Metadata download and inspection are done. Image zips are intentionally not
downloaded yet. OCR, PII redaction, and visual review require a bounded image
extraction pass.

Run:

```bash
python scripts/safety_v0/download/download_vlguard.py
python scripts/safety_v0/inspect/inspect_vlguard.py
python scripts/safety_v0/convert/convert_vlguard.py
python scripts/safety_v0/run_prompt_injection_rules.py --slug vlguard
```

Inspection artifacts:

- `data/safety_v0/inspection/vlguard/schema.json`
- `data/safety_v0/inspection/vlguard/stats.json`
- `data/safety_v0/inspection/vlguard/sample_rows.jsonl`
