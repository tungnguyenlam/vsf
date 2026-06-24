# PII-dropout augmentation (DEFERRED — design note, not built)

Status: parked. Captured so the design is not lost. Do **not** implement until we
explicitly come back to it; we are working through the rest of `DATA_PLAN.md`
first.

## Idea

From one redacted image PII source row (e.g. WebPII), emit K training variants
that differ only in **which real PII boxes are left visible**. The
`pii_visible` label is **derived** from that choice, so the augmentation is
self-labeling — no model call, no human, no spend.

Two endpoints plus sampled middles:
- redact all boxes -> `pii_visible = false`
- redact nothing      -> `pii_visible = true`
- random subset at rate `pii_drop_out` -> `pii_visible = (any box left visible)`

Why it is valuable:
- **Self-labeling matched pairs.** Same image, redaction on vs off, label
  flipped — forces the model to learn "is there residual PII" rather than
  layout/style. Highest-value training signal.
- **Difficulty dial.** Drop one small box (subtle leak, hard) vs drop everything
  (easy). Enables stratifying/curriculum.
- **Free.** Uses only existing image + string ops; respects the LLM budget.

## Both modalities must co-vary

The guard VLM receives OCR text **and** image jointly. So a variant that leaves
a box visible must reflect it in both:
- image: render with that box excluded from the redaction set,
- `sanitized_ocr_text`: mask only the redacted spans; keep the dropped ones in
  clear text.

Otherwise the image leaks PII while the text claims it is clean (or vice versa),
and the derived `pii_visible` label is supported by only one modality.

## Sketch of the build (when resumed)

1. **Schema** (`safety_v0_schema.py`): add optional top-level `augmentation`
   block (`kind`, `source_input_id`, `variant_index`, `pii_drop_out`,
   `kept_visible_box_ids`, `redacted_box_ids`, `seed`); default `None`; originals
   stay valid. Variant id: `"{source_input_id}_aug{variant_index:02d}"`.
2. **Generator** (`src/pipeline/Image/augmentation.py`): choose kept boxes;
   filter the row's spans/boxes to the redact set; reuse
   `recompute_redactions` to render; co-vary `sanitized_ocr_text`; set
   `labels.pii_visible` with `label_source="augmentation_derived"`.
3. **Driver** (`scripts/safety_v0/run_pii_augmentation.py`): in
   `redacted/<slug>/redacted.jsonl` -> out `augmented/<slug>/augmented.jsonl`
   (+ `images/`); flags `--rates`, `--max-variants-per-source`, `--seed 42`,
   `--limit`; prints the true/false `pii_visible` balance.
4. **Split-safety**: every variant copies its parent `source.split` and carries
   `augmentation.source_input_id`; all splitting/sampling groups by
   `source_input_id` so variants never straddle train/test (DATA_PLAN Step 7
   already says "split by source document/group, not by rendered variant").
5. **Tests** (`tests/test_pii_augmentation.py`): rate 0.0 / 1.0 / partial
   determinism, OCR co-variation, schema validity, id uniqueness.

## Open prerequisite for the multimodal-injection variant (separate idea)

Modality ablation (text-only / image-only / image+text) for prompt-injection and
topic — where the *combination* is the attack but each part alone is benign —
needs source data that actually contains emergent multimodal risk. WebPII has
none. That augmentation waits on the prompt-injection / visual sources in
`DATA_PLAN.md` and needs per-variant relabeling (cannot inherit the combined
label), so it is a teacher-labeled path, not a free one.
