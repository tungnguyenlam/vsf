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

## Bounded Image Extraction

The image zips are large (`train.zip` ~315 MB, `test.zip` ~125 MB) but not
multi-GB. Rather than download them whole, `extract_vlguard_images.py` opens the
remote zips through `HfFileSystem` (HTTP range requests) and pulls only the
members for a deterministic, diverse review slice. It reads each zip's central
directory plus the selected member byte ranges, so a 100-image slice costs ~14 MB
on disk and a few minutes of ranged reads instead of 440 MB of download.

Selection round-robins across `(split, bucket)` where `bucket` is `safe` or the
row's `harmful_subcategory`, so the slice covers every axis evenly rather than
one category. Zip member names are `<split>/<image-field>`; images are written
to `data/safety_v0/raw/vlguard/images/<image-field>` to match the converter's
`content.original_image_path`. A manifest of selected images is written to
`data/safety_v0/raw/vlguard/images/extracted_manifest.json`.

The 100-image slice (2026-06-18) covered 20 safe + 10 each of `political`,
`personal data`, `professional advice`, `disinformation`, `sexually explicit`,
`violence`, `other`, `race`, `sex`.

## OCR / PII / Prompt-Injection On The Slice

The 100 images expand to 111 canonical rows (some images have both a
`safe_instruction` and an `unsafe_instruction` pair). The slice JSONL is
`data/safety_v0/converted/vlguard/review_slice.jsonl` (converted rows whose image
exists on disk).

- OCR: English PaddleOCR (`--lang en`, PP-OCRv6), 111/111 valid, 94/111 with
  text. The 17 text-less rows are photos with no legible text.
- PII redaction: the Vietnamese `regex_recall` pipeline found 0 PII in the OCR
  text and produced 0 redactions. This is genuinely correct for this slice: the
  `personal data` rows are ad-style images ("locate anyone in 10 seconds",
  TruthFinder) that carry topic-level personal-data risk, not literal visible PII
  strings (names/emails/phones). Visible-PII redaction would need image rows that
  actually print identifiers.
- Prompt injection: 0 rule hits (VLGuard is not a prompt-injection source).

OCR adapter fix found here: `PaddleOcrAdapter._normalize` raised
`ValueError: truth value of an empty array is ambiguous` when PaddleOCR returned
empty numpy arrays for a text-less image (`page.get("rec_polys") or ...`).
WebPII never hit this because web screenshots always have text. Fixed with
explicit length checks; regression test
`test_paddle_normalize_v3_dict_empty_arrays`.

## Current State

Metadata, conversion, and a bounded 100-image (111-row) OCR/PII/PI slice are
done. The full image set is still not downloaded; scale up by raising
`--limit` on the extractor when more rows are needed for v0.

Run:

```bash
python scripts/safety_v0/download/download_vlguard.py
python scripts/safety_v0/inspect/inspect_vlguard.py
python scripts/safety_v0/convert/convert_vlguard.py
python scripts/safety_v0/run_prompt_injection_rules.py --slug vlguard

# bounded image slice -> OCR -> PII redaction -> prompt-injection rules
python scripts/safety_v0/download/extract_vlguard_images.py --limit 100
# build review_slice.jsonl (converted rows whose image is on disk), then:
HOME=/tmp/paddle-home python scripts/safety_v0/run_ocr.py \
  --input data/safety_v0/converted/vlguard/review_slice.jsonl \
  --output data/safety_v0/ocr/vlguard/ocr.jsonl --lang en --no-source-pii-alignment
python scripts/safety_v0/run_pii_redaction.py --slug vlguard --pipeline regex_recall
python scripts/safety_v0/run_prompt_injection_rules.py \
  --input data/safety_v0/redacted/vlguard/redacted.jsonl \
  --output data/safety_v0/weak/vlguard/weak_labeled_image_slice.jsonl
```

Inspection artifacts:

- `data/safety_v0/inspection/vlguard/schema.json`
- `data/safety_v0/inspection/vlguard/stats.json`
- `data/safety_v0/inspection/vlguard/sample_rows.jsonl`

Slice artifacts:

- `data/safety_v0/raw/vlguard/images/` (100 images + `extracted_manifest.json`)
- `data/safety_v0/converted/vlguard/review_slice.jsonl` (111 rows)
- `data/safety_v0/ocr/vlguard/ocr.jsonl` (111 rows, 94 with text)
- `data/safety_v0/redacted/vlguard/redacted.jsonl` (111 rows, 0 redactions)
- `data/safety_v0/weak/vlguard/weak_labeled_image_slice.jsonl` (111 rows)
