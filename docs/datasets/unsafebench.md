# yiting/UnsafeBench (safety_v0 source)

safety_v0 source slug: `unsafebench`. Canonical dataset identity recorded on
every row: `yiting/UnsafeBench`. Mapped for the visual-safety (sexual / violence
/ blood-gore) axes per the **OpenAI DALL-E content-policy taxonomy (April
2022)** that the upstream paper uses.

## What it is

`yiting/UnsafeBench` (paper: [Qu et al., CCS 2025, arXiv:2405.03486](https://arxiv.org/abs/2405.03486))
is a 10,146-image benchmark of safe/unsafe images for evaluating image-safety
classifiers. It covers **11 unsafe categories** — Hate, Harassment, Violence,
Self-Harm, Sexual, Shocking, Illegal Activity, Deception, Political, Public
and Personal Health, Spam — and two image sources: real-world images from
LAION-5B and AI-generated images from Lexica. Annotations are three-author
majority votes (Fleiss' Kappa 0.47, moderate agreement).

The dataset is **GATED** under a Data Use Agreement (DUA) on Hugging Face.
Access has to be requested manually on
https://huggingface.co/datasets/yiting/UnsafeBench and approval takes
1-2 days. The DUA permits research, education, and *responsible* commercial
use; misuse is prohibited. Rows carry `license_status="dua_research"`.

## Access state (this repo)

DUA access was **granted** on 2026-06-25. The bounded `test` split (175 MB,
2,037 rows) has been downloaded to
`data/safety_v0/raw/unsafebench/data/test-00000-of-00001.parquet`, inspected,
and converted. The converted file initially held 2,037/2,037 valid rows but was
**finalized at the 1,357-row OCRed slice** (see Next steps item 5) — every
downstream stage now covers the same 1,357 ids. The larger `train` parquet (755 MB) is intentionally not
downloaded. **Per DATA_PLAN cost discipline we do not download gated multi-GB
archives automatically** — the downloader defaults to the smaller `test` split
and the test suite never reaches the network (it uses a synthetic parquet, see
`tests/test_download_inspect_unsafebench.py` and `tests/test_convert_unsafebench.py`).

Observed test-split distribution (matches the paper's category buckets):
1,260 Safe / 777 Unsafe (no N/A in the released split); sources balanced
(Lexica 1,022 / Laion5B 1,015); `text` empty on 609 rows. The converter emits
1,260 `action=safe`, 579 `action=reject`, and 198 `action=null` rows (the
Political 91 + Public-and-Personal-Health 55 + Spam 52 Unsafe rows whose action
is deferred to review).

## Raw format

The repo ships a single train parquet (755 MB, 8,109 rows) and a single
test parquet (184 MB, 2,037 rows). Both share the same HF `Image` feature
schema (`dataset_info.features` in the README):

| Column         | Type   | Meaning |
|----------------|--------|---------|
| `image`        | Image  | PIL/JPEG bytes (RGB). Size not fixed. |
| `safety_label` | string | One of `Safe`, `Unsafe`, `N/A` (human majority vote). |
| `category`     | string | One of `Safe`, `N/A`, or the 11 unsafe category names below. |
| `source`       | string | One of `Laion5B` (real-world) or `Lexica` (AI-generated). |
| `text`         | string | The source caption / prompt that fetched the image. Often literally `"xxx"` for Lexica rows (the prompt is not preserved there). |

The `text` field is **not** a reliable instruction (UnsafeBench is a
classifier benchmark, not a prompt-injection benchmark), so it goes into
`source_labels` for audit only and is not used as a `prompt_injection_span`
or `pii_span` source.

## Label taxonomy vs our canonical axes

The 11 unsafe categories come from the OpenAI DALL-E content policy
(archived April 2022). The paper's table 3 reduces some categories to
"Health" for short. The mapping is intentionally conservative
(`null = unknown, not false`) — we only set a boolean axis `True` when
the upstream category has a clear, unambiguous meaning, and we leave the
rest `null` for review.

### Per-category mapping decision

| Upstream category | `action` | `sexual` | `violence` | `blood_gore` | `political` | `religious` | Notes |
|---|---|---|---|---|---|---|---|
| `Safe` (label) | `safe` | `false` | `false` | `false` | `false` | `false` | source_gold safe image; all booleans asserted `false` from the source label |
| `Hate` | `reject` | `null` | `null` | `null` | `null` | `null` | hateful symbols / negative stereotypes; no canonical axis — refuse, do not assert which visual sub-axis fired |
| `Harassment` | `reject` | `null` | `null` | `null` | `null` | `null` | bullying / targeting; same as Hate — no axis |
| `Violence` | `reject` | `false` | `true` | `null` | `false` | `false` | clear physical violence; `blood_gore` left null because VLGuard-style violent images do not always contain blood (and UnsafeBench does not sub-label it) |
| `Self-Harm` | `reject` | `null` | `null` | `null` | `null` | `null` | self-injury imagery; not a canonical axis — refuse only |
| `Sexual` | `reject` | `true` | `false` | `false` | `false` | `false` | explicit sexual imagery; the cleanest axis in the taxonomy |
| `Shocking` | `reject` | `null` | `null` | `null` | `null` | `null` | "shocking" / gross / disgusting; not a canonical axis — refuse only |
| `Illegal Activity` | `reject` | `null` | `null` | `null` | `null` | `null` | depicts illegal acts; not a canonical axis — refuse only |
| `Deception` | `reject` | `null` | `null` | `null` | `null` | `null` | scam / fraud / phishing imagery; not a canonical axis — refuse only |
| `Political` | `null` | `false` | `false` | `false` | `true` | `false` | political persuasion; `action` deferred to review (refusal is policy-debatable) |
| `Public and Personal Health` | `null` | `false` | `false` | `false` | `false` | `false` | medical / health-content imagery; `action` deferred to review (medical info can be educational, not always harmful) |
| `Spam` | `null` | `false` | `false` | `false` | `false` | `false` | spam / unsolicited content; `action` deferred to review (low-severity, often borderline) |
| `N/A` (label) | `null` | `null` | `null` | `null` | `null` | `null` | annotators could not decide; leave all axes unknown and send to review |

`prompt_injection` and `pii_visible` are **always `false`** for Safe rows
(`source_assumption`: these are single-image classifier rows, not
prompt-injection training data, and there is no OCR text in the source).
For Unsafe rows we keep them `null` until the OCR/PII detector and the
prompt-injection rules actually fire; the source category does not tell
us whether the image text smuggles an instruction or carries literal
PII strings.

`blood_gore` is set `true` only when the OCR/PII or a downstream
weak-label pass decides that; it is **not** set by the upstream
`Violence` category because UnsafeBench does not sub-label it
(same gap as VLGuard).

### License-status handling

Every UnsafeBench row gets `license_status = "dua_research"`. The
`source.license_status` field is what the review UI keys off to gate
non-research use; we never silently set it to `mit_gated` or
`cc_by_nc_4_0`.

## Inspection without the parquet

`scripts/safety_v0/inspect/inspect_unsafebench.py` reads the parquet
written by the downloader and emits `data/safety_v0/inspection/unsafebench/`:

- `schema.json` — columns, dtype summaries, the 11-category taxonomy
  (canonical paper order), license / gating note, split row counts
- `stats.json` — per-(category, safety_label, source) row counts,
  text length distribution, image-size distribution, missing-value
  counts, one joint distribution
- `sample_rows.jsonl` — a few compact example rows per
  (category, safety_label) bucket; image bytes are dropped (the
  document is small on purpose), image dimensions are kept

The inspector is **synthetic-friendly** (the test
`test_inspect_writes_schema_stats_and_samples` builds a 5-row parquet
and exercises the CLI end-to-end) so future agents do not need a DUA
key just to iterate on the script.

## Human review focus

- whether the "refuse without a canonical axis" rows (Hate, Harassment,
  Self-Harm, Shocking, Illegal Activity, Deception) should be split
  into specific booleans — currently the visual content is unknown
  because UnsafeBench does not ship multi-label taxonomy
- whether `action=reject` should also apply to `Political`,
  `Public and Personal Health`, `Spam` (paper treats these as
  "lower priority" categories; we treat them as `action=null` and
  push the call to review)
- PII strings in `text` (rare but possible for `Deception` rows that
  advertise a phone number or address)
- distinguishing `Violence` from `blood_gore` — the upstream does not
  sub-label, so any `blood_gore=true` row needs a human check

## Next steps

Done (2026-06-25): download (test split) -> inspect -> convert -> extract
images -> OCR -> PII redaction -> prompt-injection rules. Remaining work-queue:

1. ~~Download the test parquet.~~ Done.
2. ~~Inspect.~~ Done — distribution above.
3. ~~Write `convert_unsafebench.py` + `tests/test_convert_unsafebench.py`,
   one canonical row per image (no instruction pairing, unlike VLGuard).~~ Done.
4. ~~Write `scripts/safety_v0/download/extract_unsafebench_images.py` to pull
   the actual image bytes (PIL-decode from the parquet column) and write
   them to `data/safety_v0/raw/unsafebench/images/<input_id>.jpg` so
   `content.original_image_path` lines up.~~ Done — 2,037/2,037 extracted,
   0 failed (`tests/test_extract_unsafebench_images.py`, 5 tests).
5. ~~Run the standard OCR -> PII -> prompt-injection stages.~~ Done, then the
   source was **finalized at the 1,357-row OCRed slice** (OCR was cut early by
   decision; the remaining ~680 non-OCRed rows were **discarded** along with
   their extracted images so every stage covers the same id set — we do not
   carry rows with no OCR text). The slice is internally consistent at 1,357
   unique rows: `converted` == `ocr` == `redacted` == `weak` == the 1,357
   extracted JPEGs (verified: identical id sets, 0 dangling
   `original_image_path`). Results matched expectations: 790/1,357 rows had
   legible OCR text; **31 rows got PII redactions** (~2%, near-zero as
   predicted for English image text); **0 prompt-injection flags** (the
   Vietnamese-trained rules did not over-fire). Weak-label distribution:
   `action` {safe 911, reject 311, null 135}; `prompt_injection` all False;
   `pii_visible` {False 911, null 446}. The prompt-injection stage must be
   pointed at the redacted JSONL
   (`--input data/safety_v0/redacted/unsafebench/redacted.jsonl`) because the
   detector reads `content.ocr_text`, which only the OCR/redact stages fill —
   the converted rows have empty `input_text` (text is audit metadata).

   Note: the converter is deterministic over the parquet row order, so the
   discarded rows are fully regenerable — re-run the extractor + `run_ocr.py
   --resume` to grow the slice back toward 2,037 if ever needed.
6. Add a `safety_v0_webdemo` review pass for the rows where the upstream
   category maps to a `null` axis — these are the highest-value reviews.

### Known gap (for the review pass)

The PII redaction stage records `detections.redaction_metadata` for the 31
rows where regex matched PII in the OCR text, but it does **not** flip
`labels.pii_visible` to `true` — `pii_visible` stays `false` (safe rows,
source_assumption) or `null` (unsafe rows). Treat the 31 redacted rows as
`pii_visible` candidates during review; do not read the weak-label column as
authoritative for PII on this source.

## Commands

```bash
# Download the bounded test-slice (requires DUA-approved HF_TOKEN in .env).
python scripts/safety_v0/download/download_unsafebench.py --split test --limit 500
# Inspect (writes schema/stats/sample under data/safety_v0/inspection/unsafebench/).
python scripts/safety_v0/inspect/inspect_unsafebench.py
# Test the download/inspect path with a synthetic parquet (no network).
python -m pytest tests/test_download_inspect_unsafebench.py -v
```

- converter output (finalized, 1,357 rows; trimmed from 2,037 to the OCRed slice):
  `data/safety_v0/converted/unsafebench/source_canonical.jsonl`
- extracted images (1,357 JPEGs; orphans for non-OCRed rows deleted):
  `data/safety_v0/raw/unsafebench/images/<input_id>.jpg`
- weak-label chain (built on the 1,357-row slice):
  `data/safety_v0/ocr/unsafebench/ocr.jsonl` ->
  `data/safety_v0/redacted/unsafebench/redacted.jsonl` ->
  `data/safety_v0/weak/unsafebench/weak_labeled.jsonl`
- inspection artifacts (generated):
  `data/safety_v0/inspection/unsafebench/{schema,stats}.json`,
  `sample_rows.jsonl`

```bash
# Extract the parquet image column to JPEGs (no HF token needed).
python scripts/safety_v0/download/extract_unsafebench_images.py
# OCR (English) -> PII redaction -> prompt-injection rules. --resume on OCR
# lets an interrupted long run converge on a plain re-run.
python scripts/safety_v0/run_ocr.py --slug unsafebench --lang en --resume
python scripts/safety_v0/run_pii_redaction.py --slug unsafebench
python scripts/safety_v0/run_prompt_injection_rules.py --slug unsafebench \
    --input data/safety_v0/redacted/unsafebench/redacted.jsonl
```
