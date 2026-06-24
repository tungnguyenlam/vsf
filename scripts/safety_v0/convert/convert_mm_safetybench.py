"""Convert MM-SafetyBench metadata into canonical safety_v0 rows.

MM-SafetyBench is a multimodal jailbreak benchmark. Its ``Text_only`` split
carries the original harmful ``question`` for each (category, id); the image
splits (``TYPO`` / ``SD`` / ``SD_TYPO``) rewrite the question to point at an
image that hides the same harmful keyword as text.

This converter reads only the lightweight ``Text_only`` parquets and emits one
text-only canonical row per question, with labels mapped from the category. It
does not require any image parquet. The bounded multimodal image slice (rows
that actually carry an image for OCR) is produced separately by
``extract_mm_safetybench_images.py``.

Label mapping is documented in ``docs/datasets/mm_safetybench.md``. The single
source of truth for the mapping lives here in :func:`category_labels` so the
extractor can import it and label image-slice rows identically.

Usage:

    python scripts/safety_v0/convert/convert_mm_safetybench.py
    python scripts/safety_v0/convert/convert_mm_safetybench.py --limit-per-category 5
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from src.pipeline.Datasets.safety_v0_schema import new_row, validate_row  # noqa: E402
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    converted_path,
    format_input_id,
    get_source,
    source_dir,
)

SLUG = "mm_safetybench"
LICENSE_STATUS = "cc_by_nc_4.0"  # research / non-commercial only

# 13 harmful-scenario categories (upstream folder names, misspelling kept).
CATEGORIES = (
    "EconomicHarm",
    "Financial_Advice",
    "Fraud",
    "Gov_Decision",
    "HateSpeech",
    "Health_Consultation",
    "Illegal_Activitiy",
    "Legal_Opinion",
    "Malware_Generation",
    "Physical_Harm",
    "Political_Lobbying",
    "Privacy_Violence",
    "Sex",
)

# Categories whose intent is clearly refusal-worthy -> action=reject. The
# professional-advice categories (everything not listed) keep action=null
# because whether to refuse is policy-dependent (deferred to review).
_REJECT_CATEGORIES = {
    "Sex",
    "Physical_Harm",
    "Illegal_Activitiy",
    "Malware_Generation",
    "Fraud",
    "EconomicHarm",
    "HateSpeech",
    "Privacy_Violence",
}

# Direct category -> canonical boolean axis mappings (the only obvious ones).
_TOPIC_AXIS = {
    "Sex": "sexual",
    "Physical_Harm": "violence",
    "Political_Lobbying": "political",
    "Gov_Decision": "political",
}


def category_labels(category: str) -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    """Map an MM-SafetyBench category to canonical labels + provenance.

    Maps only obvious axes; everything unclear stays ``None`` (unknown, not
    false). ``prompt_injection`` is intentionally left ``None`` for every row:
    the image splits smuggle the instruction visually (injection-ambiguous), so
    neither ``true`` nor ``false`` is honest. See docs/datasets/mm_safetybench.md.
    """
    labels: Dict[str, Any] = {
        "action": "reject" if category in _REJECT_CATEGORIES else None,
        "pii_visible": None,
        "prompt_injection": None,
        "sexual": None,
        "violence": None,
        "blood_gore": None,
        "political": None,
        "religious": None,
    }
    label_source: Dict[str, Optional[str]] = {field: None for field in labels}
    if labels["action"] is not None:
        label_source["action"] = "source_derived"  # policy reading of the category
    axis = _TOPIC_AXIS.get(category)
    if axis is not None:
        labels[axis] = True
        label_source[axis] = "source_gold"  # direct category correspondence
    return labels, label_source


def load_text_only(raw_dir: Path, category: str) -> pd.DataFrame:
    path = raw_dir / "data" / category / "Text_only.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["id", "question", "image"])
    return pd.read_parquet(path)


def build_canonical_row(
    index: int,
    category: str,
    sample_id: Any,
    question: str,
) -> Dict[str, Any]:
    labels, label_source = category_labels(category)
    row = new_row(
        format_input_id(SLUG, index),
        get_source(SLUG).name,
        split="test",  # MM-SafetyBench is an eval benchmark; treat as held-out
        source_sample_id=f"{category}:{sample_id}:Text_only",
        license_status=LICENSE_STATUS,
        has_image=False,
        has_text=bool(question.strip()),
        has_ocr=False,
        input_text=question,
        sanitized_text=question,
    )
    row["labels"] = labels
    row["label_source"] = label_source
    row["source_labels"] = {
        "category": category,
        "id": sample_id,
        "split": "Text_only",
        "original_question": question,
    }
    return row


def iter_canonical_rows(
    raw_dir: Path,
    *,
    limit_per_category: Optional[int] = None,
) -> Iterator[Dict[str, Any]]:
    index = 1
    for category in CATEGORIES:
        df = load_text_only(raw_dir, category)
        if limit_per_category is not None:
            df = df.head(limit_per_category)
        for _, record in df.iterrows():
            question = str(record.get("question") or "")
            yield build_canonical_row(index, category, record.get("id"), question)
            index += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=source_dir("raw", SLUG))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit-per-category", type=int, default=None)
    args = parser.parse_args()

    out_path = args.output or converted_path(SLUG, create=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = invalid = 0
    with open(out_path, "w", encoding="utf-8") as handle:
        for row in iter_canonical_rows(args.raw_dir, limit_per_category=args.limit_per_category):
            errors = validate_row(row)
            if errors:
                invalid += 1
                print(f"  invalid row {row['input_id']}: {errors[0]}", file=sys.stderr)
                continue
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1

    print(f"Converted {written} MM-SafetyBench rows ({invalid} invalid) -> {out_path}")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
