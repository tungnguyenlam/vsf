# WebPII/webpii (safety_v0 source)

Image-based web UI PII source for `safety_v0` (see `DATA_PLAN.md`). This is not
a normal text `BaseDataset`: the useful source annotations are visible UI
elements with boxes, and the converter should produce image/OCR/redaction rows
for the canonical `safety_v0` schema.

- Slug: `webpii`
- Hugging Face source: `WebPII/webpii`
- License in dataset card: `apache-2.0`
- Sample license note: upstream sample README declares `cc-by-4.0`
- Raw link: `data/safety_v0/raw/webpii`
- Download helper: `scripts/safety_v0/download/download_webpii.py`
- Inspection helper: `scripts/safety_v0/inspect/inspect_webpii.py`
- Converter: `scripts/safety_v0/convert/convert_webpii.py`
- Inspection outputs: `data/safety_v0/inspection/webpii/`
- Converted output: `data/safety_v0/converted/webpii/source_canonical.jsonl`

## Current Download State

Only the bounded upstream sample is cached locally. The full train/test shard set
is about 6.7 GB and was intentionally not downloaded during first inspection.

Cached files:

| File | Purpose |
|---|---|
| `README.md` | HF dataset card metadata |
| `sample/README.md` | reviewer sample notes |
| `sample/sample_manifest.json` | machine-readable visual sample summary |
| `sample/schema_sample_100.parquet` | 100 rows with released parquet schema |
| `sample/webpii_visual_samples.zip` | 28 visual sample pages with PNG variants and `metadata.json` |

## What It Is

WebPII is an English web UI privacy dataset with synthetic PII rendered inside
reproduced ecommerce/application pages. The dataset card reports 40,384 train
rows and 4,481 test rows. The source is useful for `safety_v0` because it gives
visible PII boxes in realistic UI layouts, which lets us test OCR, box
alignment, and image redaction.

This is an explicit image-PII exception to the repo's Vietnamese-first default.
It should not become an English text benchmark; use it for visual PII detection,
OCR/redaction behavior, and UI false-positive analysis.

## Sample Inspection

Run:

```bash
python scripts/safety_v0/inspect/inspect_webpii.py
```

Generated artifacts:

| Artifact | Contents |
|---|---|
| `schema.json` | parquet columns and dtypes |
| `stats.json` | source/page/variant counts, element counts, PII key counts |
| `manifest_summary.json` | upstream `sample_manifest.json` copy |
| `sample_rows.jsonl` | compact first rows for converter debugging |

The parquet sample has 100 rows x 18 columns. It is schema-compatible, not
representative: all 100 rows are `amazon`, and 83 are `gifting` pages. The visual
zip is more representative: 28 page directories, 132 PNG files, 28 metadata
files, 10 companies, and 11 page types.

## Columns And Format

`sample/schema_sample_100.parquet` columns:

| Column | Meaning |
|---|---|
| `image` | dict with image `bytes` and source image `path` |
| `source_id` | upstream page/sample id |
| `variant` | `full`, `empty`, or `partial_00` in the parquet sample |
| `page_type` | UI page category |
| `company` | reproduced website/app brand |
| `image_width`, `image_height` | pixel dimensions |
| `num_pii_elements` | count of source PII elements |
| `num_product_elements` | count of product elements |
| `num_order_elements` | count of order elements |
| `num_search_elements` | count of search elements |
| `num_misc_elements` | count of misc elements |
| `fillable_count` | count of fillable fields |
| `pii_elements_json` | JSON list of PII UI elements |
| `product_elements_json` | JSON list of product UI elements |
| `order_elements_json` | JSON list of order UI elements |
| `search_elements_json` | JSON list of search UI elements |
| `misc_elements_json` | JSON list of other UI elements |

Each element JSON item has this shape:

```json
{
  "key": "PII_EMAIL",
  "value": "example@example.com",
  "bbox_x": 180,
  "bbox_y": 267.5,
  "bbox_width": 200,
  "bbox_height": 28,
  "visible": true,
  "clipped": false,
  "element_type": "input"
}
```

The visual zip metadata uses the same concept with nested boxes:

```json
{
  "key": "PII_EMAIL",
  "value": "example@example.com",
  "bbox": {"x": 180, "y": 267.5, "width": 200, "height": 28},
  "visible": true,
  "clipped": false,
  "element_type": "input"
}
```

## Span And Box Format

The source gives image boxes, not character spans. There are no reliable
`start`/`end` offsets into OCR text. For canonical conversion:

- write source boxes as `geometry.ocr_boxes` or a source-box side field once the
  converter chooses the exact representation;
- convert `x, y, width, height` into canonical `[x0, y0, x1, y1]`;
- keep only visible, non-empty PII values as source PII candidates;
- run OCR anyway and map OCR boxes to source PII boxes by overlap/text match;
- write `detections.pii_spans[*].box_ids` only after OCR/source box alignment is
  known.

## Label Taxonomy

Source element families:

| Family | Examples | safety_v0 use |
|---|---|---|
| `PII_*` | names, addresses, phones, email, DOB, cards, credentials | PII candidates |
| `PRODUCT*` | product names, prices, ratings, images | keep as source metadata, not PII |
| `ORDER_*` | dates, totals, shipping cost, order ids | mostly non-PII; do not map blindly |
| `SEARCH_*`, `HEADER_SEARCH` | search boxes/query placeholders | not PII by default |
| misc keys | gift wrap price, tracking id, other UI facts | not PII by default unless reviewed |

Sample PII stats from `schema_sample_100.parquet`:

- 933 PII elements, 124 unique PII keys.
- All sampled PII elements have `visible = true`; 7 have empty values.
- Element types: 823 `text`, 107 `input`, 3 `image`.
- Frequent keys: `PII_STREET`, `PII_CITY`, `PII_COUNTRY`,
  `PII_POSTCODE_FULL`, `PII_STATE_ABBR`, `PII_GIFT_MESSAGE`,
  `PII_GIFT_FULLNAME`, `PII_FULLNAME`, `PII_FIRSTNAME`.

## Provisional Presidio Mapping

Map only when the source key meaning is clear and the element value is non-empty.
Strip trailing numeric suffixes such as `PII_FULLNAME2` before mapping.

| WebPII key pattern | Presidio type | Notes |
|---|---|---|
| `PII_FIRSTNAME`, `PII_LASTNAME`, `PII_FULLNAME`, `PII_GIFT_*NAME`, derived name keys | `PERSON` | Names only |
| `PII_EMAIL`, `PII_GIFT_EMAIL` | `EMAIL_ADDRESS` | Includes numbered variants |
| `PII_PHONE*` | `PHONE_NUMBER` | Phone, area, prefix, line, suffix |
| `PII_ADDRESS`, `PII_STREET*`, `PII_CITY*`, `PII_STATE*`, `PII_POSTCODE*`, `PII_COUNTRY*`, `PII_CITY_STATE*`, `PII_LOCATION*` address/city/postcode keys | `LOCATION` | Includes compound address strings |
| `PII_COMPANY` | `ORGANIZATION` | Only when non-empty and actually visible |
| `PII_DOB*`, `PII_CARD_EXPIRY*` | `DATE_TIME` | DOB and card expiry are date-like |
| `PII_CARD_NUMBER`, `PII_CARD_LAST4`, `PII_CARD_CVV`, `PII_LOGIN_USERNAME`, `PII_LOGIN_PASSWORD*`, `PII_PO_NUMBER`, `PII_JOB_CODE`, `PII_SECURITY_CODE` | `MISC` | Sensitive but outside the narrow target taxonomy |

Drop or keep only as source metadata:

- `PII_CARD_IMAGE`, `PII_AVATAR`: image/logo/avatar references, not text spans.
- Empty values in empty/partial variants.
- `PRODUCT*`, most `ORDER_*`, `SEARCH_*`, and generic misc UI labels.

There is no direct `BANK_ACCOUNT` evidence in the inspected sample.

## Canonical Conversion Plan

For each accepted source row or visual sample variant:

| Source field | Canonical field |
|---|---|
| `source_id` plus `variant` | `source.source_sample_id` |
| `company`, `page_type`, `variant` | `source_labels` |
| image bytes or PNG file | `content.original_image_path` |
| source PII element boxes | candidate redaction boxes and source metadata |
| OCR text | `content.ocr_text` |
| OCR word boxes | `geometry.ocr_boxes` |
| mapped source PII keys | `detections.pii_spans` after OCR/source alignment |

Current converter behavior:

- reads `sample/schema_sample_100.parquet`;
- writes image bytes to `data/safety_v0/converted/webpii/images/`;
- writes mapped source boxes to `geometry.source_pii_boxes` with canonical
  `[x0, y0, x1, y1]` coordinates;
- leaves `geometry.ocr_boxes`, `content.ocr_text`, and `detections.pii_spans`
  empty for the OCR/alignment stage.

Current OCR/alignment behavior:

- `scripts/safety_v0/run_ocr.py --slug webpii --lang en` runs the configured
  OCR adapter and writes `data/safety_v0/ocr/webpii/ocr.jsonl`;
- after OCR, WebPII source boxes are aligned to OCR boxes by OCR-box coverage
  (`--min-ocr-coverage`, default `0.5`);
- aligned source PII boxes become `detections.pii_spans` with detector
  `source_webpii_ocr_alignment`, OCR character offsets, OCR `box_ids`, and
  source provenance fields (`source_box_id`, `source_key`, `source_text`);
- source boxes that do not overlap OCR boxes remain only in
  `geometry.source_pii_boxes` for review.

2026-06-16 cached-sample OCR/redaction result:

- environment: existing `vinai` conda env with `paddleocr==3.7.0` and
  `paddlepaddle==3.2.2`; `paddlepaddle==3.3.1` failed on CPU inference with a
  `ConvertPirAttribute2RuntimeAttribute` oneDNN/PIR error;
- cache: `HOME=/tmp/paddle-home` so PaddleX model files stay outside the repo;
- OCR command processed all 100 cached sample rows: 100/100 had OCR text, 4,937
  OCR boxes, 333 source-aligned PII spans across 90 rows, 0 invalid rows;
- redaction command processed those 100 rows: 90/100 redacted images, 335 PII
  spans total, 335 redaction metadata entries, 0 invalid rows;
- the 10 no-redaction rows still have source PII boxes but no aligned OCR boxes
  at the current threshold, so they are the first alignment-review targets.

Label policy for initial conversion:

| Label | Value | Reason |
|---|---|---|
| `action` | `safe` after redaction, otherwise `review`/unset until pipeline stage | raw rows contain visible PII |
| `pii_visible` | `true` before redaction, `false` after redaction if boxes are covered | source is selected for visible PII |
| `prompt_injection` | `false` or rule output after OCR | web UI source is not an injection corpus |
| visual harm/topic labels | `null` unless a later weak classifier fills them | source does not label sexual/violence/blood/political/religious content |

## Risks For Converter

- Boxes are source UI boxes, not OCR boxes; OCR alignment is required before
  writing character spans with `box_ids`.
- Some source keys are privacy-relevant but not in our target taxonomy, so
  mapping to `MISC` should be explicit and reviewable.
- Product, order, search, and misc UI text will create many false positives if
  treated as PII.
- The parquet sample is Amazon-heavy and not representative; use the visual zip
  to inspect other companies before final sampling.
- Full download is multi-GB; keep sample-first behavior unless a conversion run
  needs full shards.

## Run

```bash
python scripts/safety_v0/convert/convert_webpii.py
python scripts/safety_v0/validate_safety_v0.py \
  data/safety_v0/converted/webpii/source_canonical.jsonl
HOME=/tmp/paddle-home PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True \
  /home/tungnguyen/miniforge3/envs/vinai/bin/python \
  scripts/safety_v0/run_ocr.py --slug webpii --lang en
python scripts/safety_v0/validate_safety_v0.py \
  data/safety_v0/ocr/webpii/ocr.jsonl
python scripts/safety_v0/run_pii_redaction.py --slug webpii --method blur
python scripts/safety_v0/validate_safety_v0.py \
  data/safety_v0/redacted/webpii/redacted.jsonl
```

The sample converter logic is unit-tested in `tests/test_convert_webpii.py`.
The WebPII OCR/source alignment logic is unit-tested in
`tests/test_run_ocr_webpii_alignment.py` without requiring PaddleOCR.
