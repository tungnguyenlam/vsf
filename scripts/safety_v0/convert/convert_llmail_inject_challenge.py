"""Convert sampled `microsoft/llmail-inject-challenge` rows into `safety_v0` rows.

Source: the bounded per-phase JSONL written by
``scripts/safety_v0/download/download_llmail_inject_challenge.py``. Each record is
a submission to a prompt-injection challenge against an email assistant: an
attacker-crafted email (``subject`` + ``body``) plus an ``objectives`` JSON of
success flags and a ``scenario`` level code. **Every row is an injection
attempt**, so this source contributes only prompt-injection POSITIVES (no
benign rows).

Label policy (see ``llmail_labels``):

- ``prompt_injection`` -> True (always; the corpus is injection submissions) (source_gold)
- ``action``           -> "reject"                                            (source_assumption)
- ``pii_visible`` / ``sexual`` / ``violence`` / ``blood_gore`` -> False       (source_assumption)
- ``political`` / ``religious`` -> None (UNKNOWN; no topic gold)

Each row gets a whole-text ``prompt_injection_span`` whose ``attack_type`` is the
scenario level code (e.g. ``level4e``); ``objectives``/scenario/team are kept in
``source_labels`` for audit. The challenge level descriptions live under
``data/safety_v0/raw/llmail_inject_challenge/meta/``.

Language: the challenge is English by construction, but the payloads are
adversarial/obfuscated, which breaks word-level language detection (langdetect
mislabels obfuscated English as French/Chinese). So we filter by SCRIPT
(``is_mostly_latin``) instead of langdetect: Latin-script text (English +
Vietnamese) is kept, genuine non-Latin scripts are dropped. On the sample this
drops zero rows.

Split: Phase1 -> train, Phase2 -> test (the phases use different defenses, so
Phase2 is a useful distribution-shift held-out set). The phase is also kept in
``source_labels``.

Usage::

    python scripts/safety_v0/convert/convert_llmail_inject_challenge.py
    python scripts/safety_v0/convert/convert_llmail_inject_challenge.py --limit 200

Output: ``data/safety_v0/converted/llmail_inject_challenge/source_canonical.jsonl``.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.language import is_mostly_latin  # noqa: E402
from src.pipeline.Datasets.safety_v0_schema import (  # noqa: E402
    new_prompt_injection_span,
    new_row,
    validate_row,
)
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    converted_path,
    format_input_id,
    source_dir,
)

SLUG = "llmail_inject_challenge"
SOURCE_NAME = "microsoft/llmail-inject-challenge"
# Phase -> canonical split. Phase2 uses different/stronger defenses, so it makes
# a meaningful distribution-shift test set.
PHASE_TO_SPLIT = {"Phase1": "train", "Phase2": "test"}
DEFAULT_PHASES = ["Phase1", "Phase2"]


def llmail_labels() -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    """Safety labels for one llmail submission (always an injection attempt)."""
    labels = {
        "action": "reject",
        "pii_visible": False,
        "prompt_injection": True,
        "sexual": False,
        "violence": False,
        "blood_gore": False,
        "political": None,
        "religious": None,
    }
    label_source = {
        "action": "source_assumption",
        "pii_visible": "source_assumption",
        "prompt_injection": "source_gold",
        "sexual": "source_assumption",
        "violence": "source_assumption",
        "blood_gore": "source_assumption",
        "political": None,
        "religious": None,
    }
    return labels, label_source


def compose_email_text(record: Dict[str, Any]) -> str:
    subject = (record.get("subject") or "").strip()
    body = (record.get("body") or "").strip()
    if subject:
        return f"Subject: {subject}\n\n{body}"
    return body


def parse_objectives(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return {}


def build_canonical_row(index: int, phase: str, record: Dict[str, Any]) -> Dict[str, Any]:
    text = compose_email_text(record)
    scenario = record.get("scenario") or "prompt_injection"
    labels, label_source = llmail_labels()

    row = new_row(
        format_input_id(SLUG, index),
        SOURCE_NAME,
        split=PHASE_TO_SPLIT.get(phase, "train"),
        source_sample_id=record.get("RowKey") or record.get("job_id"),
        license_status="needs_verification",
        has_text=True,
        input_text=text,
        sanitized_text=text,  # no PII removal at convert time
    )
    if text:
        row["detections"]["prompt_injection_spans"] = [
            new_prompt_injection_span(
                "pi_0001",
                scenario,  # challenge level code as the attack sub-type
                0,
                len(text),
                text,
                score=1.0,
                box_ids=None,
                detector="source_gold",
            )
        ]
    row["labels"] = labels
    row["label_source"] = label_source
    row["source_labels"] = {
        "phase": phase,
        "scenario": scenario,
        "objectives": parse_objectives(record.get("objectives")),
        "team_id": record.get("team_id"),
        "job_id": record.get("job_id"),
        "row_key": record.get("RowKey"),
    }
    return row


def load_records(raw_dir: Path, phase: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    path = raw_dir / f"{phase}.jsonl"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing raw phase {path}. Run download_llmail_inject_challenge.py first."
        )
    records: List[Dict[str, Any]] = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
            if limit is not None and len(records) >= limit:
                break
    return records


def filter_by_script(records: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Keep only mostly-Latin (English/Vietnamese-script) rows; return (kept, dropped)."""
    kept = [r for r in records if is_mostly_latin(compose_email_text(r))]
    return kept, len(records) - len(kept)


def iter_canonical_rows(
    phase: str, records: List[Dict[str, Any]], start_index: int = 1
) -> Iterator[Dict[str, Any]]:
    index = start_index
    for record in records:
        yield build_canonical_row(index, phase, record)
        index += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=source_dir("raw", SLUG))
    parser.add_argument("--phases", nargs="*", default=DEFAULT_PHASES)
    parser.add_argument("--limit", type=int, default=None, help="Rows per phase.")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    out_path = args.out or converted_path(SLUG, create=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    invalid = 0
    dropped_script = 0
    index = 1
    with open(out_path, "w", encoding="utf-8") as handle:
        for phase in args.phases:
            records = load_records(args.raw_dir, phase, limit=args.limit)
            records, dropped = filter_by_script(records)
            dropped_script += dropped
            print(f"Loading {phase} ({len(records)} rows kept, {dropped} dropped by script)...")
            for row in iter_canonical_rows(phase, records, start_index=index):
                errors = validate_row(row)
                if errors:
                    invalid += 1
                    print(f"  invalid row {row['input_id']}: {errors[0]}", file=sys.stderr)
                    continue
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                written += 1
                index += 1

    print(
        f"Wrote {written} rows to {out_path} "
        f"({dropped_script} dropped by script, {invalid} invalid skipped)."
    )
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
