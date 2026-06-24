# `llmail_inject_challenge` (safety_v0 source)

safety_v0 source for **prompt-injection positives** with email structure. Every
row is an attacker-crafted email submitted to the Microsoft LLMail-Inject
challenge, so this source contributes only injection attacks (no benign rows —
hard negatives come from other sources).

- Repo: `microsoft/llmail-inject-challenge` (HF, MIT license).
- Slug: `llmail_inject_challenge` (registered in `safety_v0_sources.py`).
- Decision: accept.

## What it is

Submissions to a challenge where attackers embed prompt-injection / data-
exfiltration instructions in an email that an LLM email assistant then
processes. The attack lives in `subject` + `body` (often obfuscated, e.g.
"every second word" encodings). `objectives` records whether the attack
succeeded at each stage; it is a *success* label, not an attack-vs-benign label.

## Size and sampling

The full dataset is very large (Phase1 ~370,724 rows / 448 MB; Phase2 ~90,916
rows; raw shards are multi-GB) and highly repetitive. Per DATA_PLAN we take a
**bounded sample** via the HF datasets-server `/rows` API (no full-file
download): default 1,000 rows per phase. This is a first-N sample, not random,
so it under-represents rare scenarios — note this if scaling up. The tiny
description files (`scenarios`, `objectives_descriptions`, `levels_descriptions`,
`system_prompt`) are fetched whole into `raw/.../meta/`.

## Columns / format (raw row)

| Column | Meaning |
|---|---|
| `subject`, `body` | the attacker email (the injection payload) |
| `objectives` | JSON string of success flags (see below) |
| `scenario` | challenge level code, e.g. `level1a`, `level4e` |
| `output` | the assistant's output for that submission |
| `team_id`, `job_id`, `RowKey` | submission identifiers |
| `*_time` | scheduling/timing fields (unused) |

`objectives` flags: `email.retrieved`, `defense.undetected`, `exfil.sent`,
`exfil.destination`, `exfil.content`. `scenario` is `level{1-4}{a-z}`: the number
is the challenge stage, the letter is the defense config (e.g. `e` = Spotlight,
`g/h` = LLM Judge — see `meta/levels_descriptions.json`).

## Language

The challenge is **English by construction**, but payloads are adversarial /
obfuscated, which breaks word-level detection (langdetect mislabels ~9% of
obfuscated English as French/Chinese). So this source filters by **script**, not
langdetect: `is_mostly_latin` keeps Latin-script text (English **and**
Vietnamese — Vietnamese diacritics are Latin code points) and drops genuine
non-Latin scripts. On the sample this drops **zero** rows. This satisfies the
"English or Vietnamese only" rule without deleting legitimate obfuscated
attacks. (deepset, by contrast, has real German, so it uses strict langdetect.)

## Mapping into canonical labels

There is no benign class and no topic/PII gold — only "this is an injection
attempt":

| Canonical label | Value | `label_source` |
|---|---|---|
| `prompt_injection` | `True` (always) | `source_gold` |
| `action` | `reject` | `source_assumption` |
| `pii_visible`, `sexual`, `violence`, `blood_gore` | `False` | `source_assumption` |
| `political`, `religious` | `None` (unknown) | `None` |

Each row gets one whole-text `prompt_injection_span` with
`attack_type = scenario` (the level code) and `detector="source_gold"`. The
`objectives` dict, `scenario`, `phase`, and submission ids are kept in
`source_labels` for audit. `input_text` is `"Subject: {subject}\n\n{body}"`.

Split: **Phase1 -> train, Phase2 -> test** (Phase2 uses different/stronger
defenses, so it is a useful distribution-shift held-out set). `phase` is also in
`source_labels`.

## Mismatch vs our taxonomy

- All rows are positives; the binary `prompt_injection` flag maps cleanly.
  Failed attempts are still `prompt_injection=true` (the content is an attack
  regardless of whether it beat the defense).
- `attack_type` carries the challenge *level*, not a semantic attack family
  (instruction-override vs exfiltration vs obfuscation). Semantic sub-typing is a
  possible later refinement; the `objectives` flags in `source_labels` already
  separate retrieval vs exfiltration success.
- `objectives` success flags are challenge metadata, not safety labels; they are
  preserved but not mapped.

## Commands

```bash
python scripts/safety_v0/download/download_llmail_inject_challenge.py --limit 1000
python scripts/safety_v0/inspect/inspect_llmail_inject_challenge.py
python scripts/safety_v0/convert/convert_llmail_inject_challenge.py
python scripts/safety_v0/validate_safety_v0.py \
  data/safety_v0/converted/llmail_inject_challenge/source_canonical.jsonl
```

Output: `data/safety_v0/converted/llmail_inject_challenge/source_canonical.jsonl`
(2,000 rows from the 1,000/phase sample; train 1,000 / test 1,000; all valid;
all prompt-injection positives).

## Next stages (per DATA_PLAN)

- run the prompt-injection rule detector over `input_text` and measure recall on
  these known positives (and which obfuscations it misses);
- optionally render a subset as email screenshots + OCR to exercise the image
  path and hidden/low-contrast attack text;
- human review for indirect/obfuscated attacks the rule detector misses.
