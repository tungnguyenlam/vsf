# DATA_PLAN.md

This is the working plan for building `safety_v0`, a max-10,000-sample dataset
for the shared VLM safety router.

The dataset must support:

- text-only, image-only, and image-plus-text samples
- OCR text plus OCR boxes
- PII detection and redaction metadata
- prompt-injection weak labels and spans
- visual safety labels for sexual, violence, and blood/gore content
- topic labels for political and religious content
- human review and relabeling in `webdemo`

The current goal is not to download everything. The goal is to inspect and
process one active source at a time, write a converter, run our weak-label
pipeline, then move to human review only for the fields that remain wrong,
missing, or uncertain.

## Progress Checklist

Done for one dataset means:

1. sample inspected
2. source-specific notes written in `docs/datasets/<name>.md`
3. mapping decision written down
4. converter implemented
5. OCR is run for image rows
6. current PII pipeline is run on input text and OCR text
7. prompt-injection weak detector is run on input text and OCR text
8. visual/topic weak labels are mapped or filled by a limited API pass where needed
9. converted rows pass schema validation
10. a small reviewed sample looks usable

Human review is for correction and completion, not first-pass labeling. The
first version of every accepted row should be produced by source labels plus
our weak pipeline:

```text
source sample
  -> source-specific converter
  -> OCR if image exists
  -> PII detection and redaction for text and OCR text
  -> prompt-injection weak detector for text and OCR text
  -> visual/topic weak classifier or source-label mapping
  -> schema validation
  -> human/API review only for uncertain, conflicting, or missing fields
```

## Project Folder Structure

All safety dataset work should use this layout so future sessions can continue
without guessing where artifacts belong.

```text
scripts/safety_v0/
  download/
    download_<source>.py
  inspect/
    inspect_<source>.py
  convert/
    convert_<source>.py
  run_ocr.py
  run_pii_redaction.py
  run_prompt_injection_rules.py
  run_visual_topic_weak_labels.py
  build_review_queue.py
  apply_review_overrides.py
  build_final_dataset.py
  validate_safety_v0.py

src/pipeline/Datasets/
  safety_v0_schema.py
  safety_v0_sources.py

docs/datasets/
  <source>.md

data/safety_v0/
  raw/<source>/
  samples/<source>/
  inspection/<source>/
  converted/<source>/
  rendered/<source>/
  ocr/<source>/
  redacted/<source>/
  weak/<source>/
  review/queue/
  review/human_overrides/
  review/api_labels/
  verified/<source>/
  final/
  manifests/
```

Directory meaning:

- `scripts/safety_v0/download/`: one download script per external source. These
  scripts should download only a bounded sample by default.
- `scripts/safety_v0/inspect/`: one inspection script per source. It writes raw
  schema summaries, a few examples, and notes needed before conversion.
- `scripts/safety_v0/convert/`: one converter per source. It converts source
  fields into the canonical schema without running OCR, PII, or weak labels.
- `scripts/safety_v0/run_ocr.py`: fills `content.ocr_text` and
  `geometry.ocr_boxes` for image rows.
- `scripts/safety_v0/run_pii_redaction.py`: runs the current PII pipeline on
  input text and OCR text, writes PII spans, sanitized text, redacted images,
  and redaction metadata.
- `scripts/safety_v0/run_prompt_injection_rules.py`: runs rule-based
  prompt-injection detection on input text and OCR text.
- `scripts/safety_v0/run_visual_topic_weak_labels.py`: maps source labels and
  optionally uses a small API pass for missing visual/topic labels.
- `scripts/safety_v0/build_review_queue.py`: selects uncertain, conflicting,
  or low-confidence rows for human review in `webdemo`.
- `scripts/safety_v0/apply_review_overrides.py`: applies human/API corrections
  after weak labels are produced.
- `scripts/safety_v0/build_final_dataset.py`: builds train/dev/test JSONL files
  from verified rows.
- `scripts/safety_v0/validate_safety_v0.py`: validates JSONL files against the
  canonical schema.
- `src/pipeline/Datasets/safety_v0_schema.py`: reusable schema constants and
  row validation logic.
- `src/pipeline/Datasets/safety_v0_sources.py`: stable source names, path
  helpers, and source configuration.
- `docs/datasets/<source>.md`: detailed source notes: raw columns, taxonomy,
  mapping, license/access notes, converter command, and review findings.
- `data/safety_v0/raw/<source>/`: downloaded raw files. Do not manually edit.
- `data/safety_v0/samples/<source>/`: tiny user-provided or curated samples for
  inspection and debugging.
- `data/safety_v0/inspection/<source>/`: inspection outputs such as
  `schema.json`, `sample.jsonl`, and `notes.md`.
- `data/safety_v0/converted/<source>/`: canonical rows from source labels only.
  This is where converted labels are first placed.
- `data/safety_v0/rendered/<source>/`: generated images for text datasets.
- `data/safety_v0/ocr/<source>/`: canonical rows after OCR boxes/text are added.
- `data/safety_v0/redacted/<source>/`: redacted image files.
- `data/safety_v0/weak/<source>/`: canonical rows after OCR, PII redaction,
  prompt-injection rules, and weak visual/topic labels.
- `data/safety_v0/review/queue/`: JSONL rows selected for human review.
- `data/safety_v0/review/human_overrides/`: human corrections from `webdemo`.
- `data/safety_v0/review/api_labels/`: limited API weak-label outputs.
- `data/safety_v0/verified/<source>/`: rows after applying human/API
  corrections.
- `data/safety_v0/final/`: final train/dev/test JSONL files used for training.
- `data/safety_v0/manifests/`: deterministic sample IDs, split manifests, and
  source count summaries.

## Dataset Work Queue

Use these blocks as the active working checklist. Datasets not used in v0 are
not listed here. Tick a source only after its own converter, notes, weak-label
pass, and sanity review are done.

### [ ] Existing Repo PII Datasets

Decision: accept.

Sources: `pii_masking_95k`, `hoangha_vie_pii`, and existing local PII rows.

Why use it: this is closest to the current Vietnamese Presidio pipeline and
should be the first place to test schema, span conversion, anonymization, and
rendering.

First-pass pipeline:

- convert source spans into `detections.pii_spans`
- run the current PII pipeline anyway and keep detector output for comparison
- render selected text rows into simple document/chat/email images
- generate synthetic OCR boxes for rendered samples
- blur detected boxes and write `redaction_metadata`

Human review focus:

- false PII spans
- missed PII spans
- wrong entity types
- bad rendered boxes
- rows where source labels disagree with our detector

Completion notes:

- write `docs/datasets/existing_repo_pii.md`
- converter output:
  `data/safety_v0/converted/existing_repo_pii/source_canonical.jsonl`
- weak-label output:
  `data/safety_v0/weak/existing_repo_pii/weak_labeled.jsonl`

### [ ] `WebPII/webpii`

Decision: accept. Sample inspection passed on 2026-06-16.

Why use it: directly relevant to visible/web PII and image-based PII risk.

First-pass pipeline:

- download a small sample first (done 2026-06-16)
- inspect whether images, OCR text, boxes, and labels are present (sample
  inspected 2026-06-16: images and source boxes are present; OCR text and
  character offsets are not source-provided)
- run OCR even if source text exists so we test our real image path
- align source PII boxes to OCR boxes after OCR (implemented 2026-06-16)
- run PII detection on OCR text
- map source PII labels only when their meaning is clear
- redact detected PII boxes before router training

Human review focus:

- missed visible PII
- boxes that are too small, too large, or mapped to the wrong text
- false positives from web UI labels, buttons, and boilerplate

Bootstrap state:

- 2026-06-16: downloaded the upstream sample files only, not the full multi-GB
  shard set, into the Hugging Face cache.
- repo raw link:
  `data/safety_v0/raw/webpii -> ~/.cache/huggingface/hub/datasets--WebPII--webpii/snapshots/6d3317721b72bde719a361c564ceaf1fbded3a8e`
- cached sample files:
  `README.md`, `sample/README.md`, `sample/sample_manifest.json`,
  `sample/schema_sample_100.parquet`, and
  `sample/webpii_visual_samples.zip`
- reproducible command:
  `python scripts/safety_v0/download/download_webpii.py`

Inspection state:

- 2026-06-16: added `scripts/safety_v0/inspect/inspect_webpii.py` and wrote
  inspection artifacts under `data/safety_v0/inspection/webpii/`.
- sample parquet: 100 rows x 18 columns, image bytes plus source UI element
  boxes, 933 PII elements, 124 unique PII keys.
- visual zip: 28 page directories, 132 PNG files, 28 metadata files, 10
  companies, 11 page types.
- mapping notes written in `docs/datasets/webpii.md`.
- 2026-06-16: added `scripts/safety_v0/convert/convert_webpii.py` and wrote
  `data/safety_v0/converted/webpii/source_canonical.jsonl` for the cached
  100-row sample. Output has image paths and source PII boxes, but no OCR text,
  OCR boxes, or PII character spans yet.
- 2026-06-16: extended `scripts/safety_v0/run_ocr.py` so WebPII source boxes
  are aligned to OCR boxes after OCR and written as source-provenance
  `detections.pii_spans`. PaddleOCR/model setup remains optional for full runs.
- 2026-06-16: ran real English PaddleOCR on all 100 cached WebPII sample rows
  using the `vinai` conda env (`paddleocr==3.7.0`, `paddlepaddle==3.2.2`,
  `HOME=/tmp/paddle-home`). Output:
  `data/safety_v0/ocr/webpii/ocr.jsonl`, 100/100 valid rows, 4,937 OCR boxes,
  333 source-aligned PII spans across 90 rows.
- 2026-06-16: ran redaction over the 100-row OCR output. Output:
  `data/safety_v0/redacted/webpii/redacted.jsonl`, 100/100 valid rows, 90
  redacted images, 335 PII spans/redactions total. The 10 no-redaction rows
  still have source PII boxes and need alignment review.

Completion notes:

- write `docs/datasets/webpii.md`
- converter output: `data/safety_v0/converted/webpii/source_canonical.jsonl`
  (done for cached 100-row sample)
- OCR/source alignment stage: implemented in `scripts/safety_v0/run_ocr.py`
  and covered by `tests/test_run_ocr_webpii_alignment.py`; real English OCR
  done for all 100 cached sample rows
- redaction output: `data/safety_v0/redacted/webpii/redacted.jsonl` (done for
  the 100-row cached sample)
- weak-label output: `data/safety_v0/weak/webpii/weak_labeled.jsonl`

### [ ] `Meddies/meddies-pii`

Decision: maybe.

Why use it: can add noisy PII variety, but only after aggressive filtering.

First-pass pipeline:

- keep Vietnamese rows
- keep English rows only if useful for transfer experiments
- drop rows dominated by non-Vietnamese/non-English scripts
- drop rows with unreadable Unicode artifacts
- run PII detection after filtering

Human review focus:

- whether retained rows are actually readable
- label mismatch caused by multilingual artifacts
- whether this source is worth keeping beyond a small calibration slice

Completion notes:

- write `docs/datasets/meddies_pii.md`
- converter output:
  `data/safety_v0/converted/meddies_pii/source_canonical.jsonl`
- weak-label output: `data/safety_v0/weak/meddies_pii/weak_labeled.jsonl`

### [ ] Local Vietnamese Prompt-Injection Seed Files

Decision: accept.

Why use it: clean Vietnamese prompt-injection data is needed because most public
prompt-injection data is English.

First-pass pipeline:

- normalize into text-only canonical rows
- render selected rows into chat/email/document images
- run OCR on rendered images
- run prompt-injection weak detector on text and OCR text
- keep exact source labels as audit metadata

Human review focus:

- attack type
- hard negatives that look similar to attacks
- Vietnamese wording that should be added to the rule detector

Completion notes:

- write `docs/datasets/local_vi_prompt_injection.md`
- converter output:
  `data/safety_v0/converted/local_vi_prompt_injection/source_canonical.jsonl`
- weak-label output:
  `data/safety_v0/weak/local_vi_prompt_injection/weak_labeled.jsonl`

### [ ] `microsoft/llmail-inject-challenge`

Decision: accept.

Why use it: useful prompt-injection source with email-like structure.

First-pass pipeline:

- convert attack/benign labels if available
- render selected messages as email screenshots or document screenshots
- OCR rendered images
- run prompt-injection weak detector
- keep source fields for attack scenario and target behavior

Human review focus:

- whether source labels map cleanly to `prompt_injection`
- email boilerplate false positives
- hidden or indirect attack text after rendering

Completion notes:

- write `docs/datasets/llmail_inject_challenge.md`
- converter output:
  `data/safety_v0/converted/llmail_inject_challenge/source_canonical.jsonl`
- weak-label output:
  `data/safety_v0/weak/llmail_inject_challenge/weak_labeled.jsonl`

### [ ] `deepset/prompt-injections`

Decision: accept.

Why use it: simple text prompt-injection positives and negatives for rule
detector development.

First-pass pipeline:

- convert text rows and source labels
- run prompt-injection weak detector
- render a subset into chat/document images
- OCR rendered images and verify span-to-box mapping

Human review focus:

- hard negatives
- short ambiguous instructions
- rule false positives caused by ordinary instruction text

Completion notes:

- write `docs/datasets/deepset_prompt_injections.md`
- converter output:
  `data/safety_v0/converted/deepset_prompt_injections/source_canonical.jsonl`
- weak-label output:
  `data/safety_v0/weak/deepset_prompt_injections/weak_labeled.jsonl`

### [ ] `facebook/cyberseceval3-visual-prompt-injection`

Decision: accept after sample inspection.

Why use it: most directly aligned with visual prompt injection and should guide
our rule-based visual prompt-injection detector.

First-pass pipeline:

- inspect image/text/schema and license constraints
- OCR images
- run prompt-injection weak detector on OCR text
- map attack labels only after confirming taxonomy
- record boxes for suspicious OCR spans

Human review focus:

- tiny text, low contrast text, footer/sidebar attacks
- OCR failures
- whether suspicious text is actually an instruction attack

Completion notes:

- write `docs/datasets/cyberseceval3_visual_prompt_injection.md`
- converter output:
  `data/safety_v0/converted/cyberseceval3_visual_prompt_injection/source_canonical.jsonl`
- weak-label output:
  `data/safety_v0/weak/cyberseceval3_visual_prompt_injection/weak_labeled.jsonl`

### [ ] `uitnlp/vihsd` And Related Vietnamese Hate/Toxicity Datasets

Decision: accept as weak topic/safety data.

Why use it: useful Vietnamese text for hate/toxicity and topic filtering, but
it should not be blindly mapped to violence.

First-pass pipeline:

- convert source toxicity/hate labels into `source_labels`
- map only obvious labels to canonical fields
- keep political/religious as `null` unless explicit
- render selected rows into chat/social-comment images
- OCR rendered images

Human review focus:

- political topic
- religious topic
- whether a hate/toxic sample is actually violent
- whether `action` should be `reject` or `unsure`

Completion notes:

- write `docs/datasets/vihsd_topic_safety.md`
- converter output:
  `data/safety_v0/converted/vihsd_topic_safety/source_canonical.jsonl`
- weak-label output:
  `data/safety_v0/weak/vihsd_topic_safety/weak_labeled.jsonl`

### [ ] `ys-zong/VLGuard`

Decision: accept after sample inspection.

Why use it: image-rich visual safety source.

First-pass pipeline:

- inspect available labels and image fields
- map only clear categories to `sexual`, `violence`, and `blood_gore`
- run OCR because images may contain text and visible PII
- run PII and prompt-injection detectors on OCR text
- use API weak labeling only for unclear categories, with a small budget

Human review focus:

- unclear visual labels
- PII found inside otherwise visual-safety images
- distinction between violence, weapons, injury, and blood/gore

Completion notes:

- write `docs/datasets/vlguard.md`
- converter output: `data/safety_v0/converted/vlguard/source_canonical.jsonl`
- weak-label output: `data/safety_v0/weak/vlguard/weak_labeled.jsonl`

### [ ] `PKU-Alignment/MM-SafetyBench`

Decision: accept after sample inspection.

Why use it: useful multimodal safety source.

First-pass pipeline:

- inspect label taxonomy
- map obvious unsafe categories only
- OCR every image
- run PII and prompt-injection detectors on OCR text
- keep unclear labels as `null`

Human review focus:

- category mapping
- whether the image alone is unsafe or only the prompt is unsafe
- action label for multimodal conflicts

Completion notes:

- write `docs/datasets/mm_safetybench.md`
- converter output:
  `data/safety_v0/converted/mm_safetybench/source_canonical.jsonl`
- weak-label output:
  `data/safety_v0/weak/mm_safetybench/weak_labeled.jsonl`

### [ ] `yiting/UnsafeBench`

Decision: accept after sample inspection.

Why use it: useful for sexual, violence, and blood/gore visual labels.

First-pass pipeline:

- inspect categories and image availability
- map obvious categories
- OCR images
- run PII and prompt-injection detectors on OCR text
- leave unclear categories as `null`

Human review focus:

- sexual vs non-sexual body/medical/contextual images
- violence vs blood/gore
- labels that are unsafe only because of text in the image

Completion notes:

- write `docs/datasets/unsafebench.md`
- converter output:
  `data/safety_v0/converted/unsafebench/source_canonical.jsonl`
- weak-label output: `data/safety_v0/weak/unsafebench/weak_labeled.jsonl`

## Unified Dataset Format

Every converter writes JSONL. One line is one training/review sample.

Important rule:

```text
null means unknown, not false.
```

Training masks are derived from `labels[field] != null`.

### Canonical Row

```json
{
  "input_id": "safety_v0_webpii_000001",
  "source": {
    "name": "WebPII/webpii",
    "split": "train",
    "source_sample_id": "original-id-or-row-number",
    "license_status": "needs_verification"
  },
  "modality": {
    "has_image": true,
    "has_text": false,
    "has_ocr": true
  },
  "content": {
    "original_image_path": "data/safety_v0/raw/webpii/000001.png",
    "redacted_image_path": "data/safety_v0/redacted/webpii/000001.png",
    "input_text": "",
    "sanitized_text": "",
    "ocr_text": "OCR text extracted from the image",
    "sanitized_ocr_text": "OCR text after PII anonymization"
  },
  "geometry": {
    "ocr_boxes": [
      {
        "box_id": "box_0001",
        "text": "Nguyen Van A",
        "start": 0,
        "end": 12,
        "box": [120, 80, 260, 112],
        "confidence": 0.94
      }
    ]
  },
  "detections": {
    "pii_spans": [
      {
        "span_id": "pii_0001",
        "entity_type": "PERSON",
        "start": 0,
        "end": 12,
        "text": "Nguyen Van A",
        "score": 0.91,
        "box_ids": ["box_0001"],
        "detector": "presidio"
      }
    ],
    "prompt_injection_spans": [
      {
        "span_id": "pi_0001",
        "attack_type": "instruction_override",
        "start": 35,
        "end": 82,
        "text": "ignore all previous instructions",
        "score": 0.8,
        "box_ids": ["box_0004", "box_0005"],
        "detector": "rule"
      }
    ],
    "redaction_metadata": [
      {
        "redaction_id": "redact_0001",
        "reason": "pii",
        "source_span_ids": ["pii_0001"],
        "box_ids": ["box_0001"],
        "merged_box": [116, 76, 264, 116],
        "method": "blur"
      }
    ]
  },
  "labels": {
    "action": null,
    "pii_visible": true,
    "prompt_injection": null,
    "sexual": null,
    "violence": null,
    "blood_gore": null,
    "political": null,
    "religious": null
  },
  "label_source": {
    "action": null,
    "pii_visible": "pipeline",
    "prompt_injection": null,
    "sexual": null,
    "violence": null,
    "blood_gore": null,
    "political": null,
    "religious": null
  },
  "source_labels": {
    "raw_label": "source-specific label here",
    "raw_category": "source-specific category here"
  },
  "review": {
    "status": "unreviewed",
    "reviewer": null,
    "notes": ""
  }
}
```

## How Multiple Boxes Work

Multiple boxes are expected. The schema handles them through IDs:

- `geometry.ocr_boxes[*].box_id` identifies every OCR box.
- `detections.pii_spans[*].box_ids` references one or more OCR boxes.
- `detections.prompt_injection_spans[*].box_ids` references one or more OCR boxes.
- `detections.redaction_metadata[*].box_ids` records the boxes actually redacted.
- `detections.redaction_metadata[*].merged_box` stores the final padded/merged
  box if the renderer chooses to blur one larger region.

Examples:

- A name on one line uses one `box_id`.
- An address spanning three OCR boxes uses one `span_id` with three `box_ids`.
- A prompt injection split over two lines uses one `span_id` with two `box_ids`.
- A blur operation can redact each box separately or use one `merged_box`.

This keeps human review simple: the UI can highlight a span and all referenced
boxes at the same time.

## Model Target Format

The training target remains compact. The model should not generate the full
metadata object.

```json
{
  "action": "safe",
  "pii_visible": false,
  "prompt_injection": false,
  "sexual": false,
  "violence": false,
  "blood_gore": false,
  "political": false,
  "religious": false
}
```

Allowed `action` values:

```text
safe
reject
unsure
```

For v0:

- `action=reject` if any confirmed blocking risk is true.
- `action=unsure` if OCR is poor, labels conflict, or human/API review is needed.
- `action=safe` only when enough labels are known and all risks are false.

## Prompt-Injection Rule Detector

Add a naive rule-based prompt-injection detector alongside the PII pipeline.
This is for weak labels, review prioritization, and possible future
anonymization/redaction. It should emit spans, scores, and `box_ids` when OCR
boxes are available.

Initial pattern families:

- instruction override: `ignore previous instructions`, `bỏ qua hướng dẫn trước`
- system disclosure: `show system prompt`, `hiển thị system prompt`
- data exfiltration: `export all data`, `xuất toàn bộ dữ liệu`
- role manipulation: `you are now`, `từ bây giờ bạn là`
- tool misuse: `call tool`, `gọi công cụ`, `send request`
- hidden instruction markers: tiny text, low contrast text, footer/sidebar
  instructions

Hard-negative patterns are mandatory:

- software manuals
- legal clauses
- ordinary instructions
- documentation that discusses prompt injection defensively
- text containing `ignore`, `bỏ qua`, `system`, or `assistant` without attack
  intent

## Review-Friendly Correction Rules

Human review happens after source mapping, OCR, PII detection, prompt-injection
detection, weak visual/topic labeling, and optional limited API labeling. The
review UI should make correction cheap; it should not ask humans to label from
blank samples.

For most rows, human annotation should only need to set or correct these fields:

```json
{
  "action": "safe|reject|unsure",
  "pii_visible": true,
  "prompt_injection": false,
  "sexual": false,
  "violence": false,
  "blood_gore": false,
  "political": false,
  "religious": false,
  "review.status": "human_reviewed",
  "review.notes": ""
}
```

For rows where the first pass is wrong, human review can also correct:

- `geometry.ocr_boxes`
- `detections.pii_spans`
- `detections.prompt_injection_spans`
- `detections.redaction_metadata`
- source-to-canonical label mapping notes

Human labels and box/span corrections override source labels, pipeline labels,
and API weak labels.

Priority for review:

1. rows with conflicting source/pipeline labels
2. rows with `action=null`
3. rows where visual datasets have unclear label mapping
4. rows with detected PII boxes after redaction
5. prompt-injection hard negatives

## Target 10,000-Sample Mix

The mix is a cap, not a quota. If a source is noisy, keep fewer rows and spend
review time on higher-value samples.

- Vietnamese PII text/rendered PII: up to 1,000 rows from repo PII datasets.
- Web/image PII: up to 1,200 rows from `WebPII/webpii`.
- Filtered multilingual PII: up to 300 rows from filtered
  `Meddies/meddies-pii`.
- Prompt-injection positives: up to 1,500 rows from local seeds, LLMail,
  deepset, and CyberSecEval 3.
- Prompt-injection hard negatives: up to 1,000 rows from rendered docs,
  manuals, legal text, and software instructions.
- Vietnamese hate/topic text rendered as images: up to 1,300 rows from ViHSD
  and related datasets.
- Visual safety images: up to 2,200 rows from VLGuard, MM-SafetyBench, and
  UnsafeBench.
- Uncertain/manual calibration: up to 1,200 rows from low-confidence,
  conflicting, or missing-label rows across all sources.

## Step-By-Step Build Plan

### Step 1: Lock Schema And Validator

- write JSON schema or Python validator for `safety_v0`
- validate IDs are unique inside each row
- validate span `box_ids` reference existing OCR boxes
- validate redaction `source_span_ids` reference existing span IDs
- validate `labels` only contain booleans, `safe/reject/unsure`, or `null`

### Step 2: Inspect One Candidate Dataset

For each source:

- load 20-50 raw samples
- save a small inspection JSONL/Markdown summary
- decide whether the source remains in v0
- write source-specific mapping notes in `docs/datasets/<name>.md`

### Step 3: Write One Converter

Each converter should output:

```text
data/safety_v0/converted/<source_name>/source_canonical.jsonl
```

The converter must not silently invent negative labels. Unknown fields remain
`null`.

### Step 4: Run Existing PII Pipeline

For text:

- run current Vietnamese PII pipeline on `input_text`
- write `sanitized_text`
- write `pii_spans`

For image:

- OCR image
- run current Vietnamese PII pipeline on `ocr_text`
- map spans to `box_ids`
- blur PII boxes
- write `redacted_image_path`, `sanitized_ocr_text`, and `redaction_metadata`

### Step 5: Run Prompt-Injection Rule Detector

- run rules on `input_text` and `ocr_text`
- write `prompt_injection_spans`
- set weak `prompt_injection=true` only when confidence is high
- keep ambiguous rows as `prompt_injection=null` and send to review

### Step 6: Review In `webdemo`

The review UI should show:

- original image
- redacted image
- OCR text
- sanitized OCR text
- highlighted OCR boxes
- detected PII spans
- detected prompt-injection spans
- source labels
- canonical labels

The UI writes human overrides to a separate JSONL:

```text
data/safety_v0/review/human_overrides/<source_name>.jsonl
```

### Step 7: Build Combined Dataset

Final build output:

```text
data/safety_v0/final/safety_v0_train.jsonl
data/safety_v0/final/safety_v0_dev.jsonl
data/safety_v0/final/safety_v0_test.jsonl
data/safety_v0/final/safety_v0_combined.jsonl
```

Rules:

- max 10,000 rows
- apply human overrides last
- split by source document/group, not by rendered variant
- keep source and weak-label metadata for audit
- keep a human-reviewed dev/test subset separate from weak-only rows

## Per-Source Notes

`DATA_PLAN.md` is the high-level tracker. Detailed source notes should live in
`docs/datasets/<name>.md` because each dataset needs room for:

- raw columns and examples
- license/access notes
- source label taxonomy
- mapping into the canonical labels
- fields that cannot be mapped automatically
- OCR behavior
- PII/prompt-injection/visual weak-label behavior
- converter command and output paths
- human-review findings

## Testing Checklist

- [ ] schema validator passes for every converted, weak-labeled, verified, and
  final JSONL
- [ ] all referenced `box_id`s exist
- [ ] all referenced `span_id`s exist
- [ ] no row has missing required top-level keys
- [ ] `null` labels are preserved as unknown
- [ ] sanitized text is used when PII was detected
- [ ] redacted image exists when PII boxes were found
- [ ] prompt-injection hard negatives are present
- [ ] source counts do not exceed target mix
- [ ] manual review overrides apply correctly

## Current Next Step

Start with the existing repo PII datasets. They are already local to the project
and fit the current Presidio pipeline best. After that, inspect `WebPII/webpii`
with a small sample before writing a converter.
