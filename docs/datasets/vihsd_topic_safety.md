# vihsd_topic_safety (UIT-ViHSD)

safety_v0 source slug: `vihsd_topic_safety`. Canonical dataset identity recorded
on every row: `uitnlp/vihsd`.

## What it is

UIT-ViHSD (Vietnamese Hate Speech Detection) is a corpus of Vietnamese
social-media comments labelled for hate / offensive / clean content. We use it as
weak **topic-safety** material and as Vietnamese **negatives** for the
prompt-injection classifier (these comments are not prompt injections).

## Download / access

The canonical `uitnlp/vihsd` repo is a loading-script dataset and is not
parquet-indexed by the Hugging Face datasets-server, so we download a bounded
sample from the `phucdev/ViHSD` mirror (same schema and splits) via the
datasets-server `/rows` API. Only the download location is the mirror; the
recorded `source.name` stays `uitnlp/vihsd`.

Bounded sample (DATA_PLAN cost discipline): default 2,000 train / 500 validation
/ 1,000 test = 3,500 rows. The sample follows source row order, so it keeps the
source's heavy CLEAN skew; class balancing happens later at review-queue /
final-build selection. Converted sample label distribution: CLEAN 2,879 /
HATE 362 / OFFENSIVE 259.

## Columns / format

| Column | Meaning |
|---|---|
| `free_text` | The comment text (Vietnamese). |
| `label_id` | `0` = CLEAN, `1` = OFFENSIVE, `2` = HATE. |

Splits: source `train` / `validation` / `test` map to our `train` / `dev` /
`test`. Text-only; no spans, no images. Comments are short (median ~32 chars).

## Label taxonomy vs our entity/label types

Our label space is `action` plus seven risk axes (`pii_visible`,
`prompt_injection`, `sexual`, `violence`, `blood_gore`, `political`,
`religious`). ViHSD's hate/offensive/clean taxonomy is **orthogonal** to these —
there is no "hate/toxicity" axis, and a hate comment is not inherently sexual,
violent, political, or religious. The converter is therefore conservative
("null means unknown, not false"):

| Field | Value | Provenance | Rationale |
|---|---|---|---|
| `prompt_injection` | `False` | `source_assumption` | Not a PI dataset -> useful Vietnamese negatives. |
| `pii_visible` | `False` | `source_assumption` | Text-only rows, no image. |
| `sexual` | `None` | — | May be true for some hate comments; not sub-labelled. |
| `violence` | `None` | — | DATA_PLAN: do not blindly map hate -> violence. |
| `blood_gore` | `None` | — | Not sub-labelled. |
| `political` | `None` | — | Keep null unless explicit. |
| `religious` | `None` | — | Keep null unless explicit. |
| `action` | `None` | — | reject vs unsure is a review decision. |

The original label is preserved in `source_labels`
(`{label_id, label_name, split}`) so a later deterministic mapping
(e.g. HATE -> reject) or a topic teacher/human pass can use it.

## Human review focus

- political vs religious topic (currently null for all rows)
- whether a hate/offensive sample is actually sexual / violent
- whether `action` should be `reject` or `unsure`

## Commands

```bash
python scripts/safety_v0/download/download_vihsd_topic_safety.py
python scripts/safety_v0/inspect/inspect_vihsd_topic_safety.py
python scripts/safety_v0/convert/convert_vihsd_topic_safety.py
python scripts/safety_v0/validate_safety_v0.py \
    data/safety_v0/converted/vihsd_topic_safety/source_canonical.jsonl
```

- converter output:
  `data/safety_v0/converted/vihsd_topic_safety/source_canonical.jsonl`
