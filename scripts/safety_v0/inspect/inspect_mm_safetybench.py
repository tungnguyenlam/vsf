"""Inspect MM-SafetyBench metadata for safety_v0 conversion planning.

Reads the per-category ``Text_only.parquet`` files from
``data/safety_v0/raw/mm_safetybench/data/<Category>/`` and writes:

- ``schema.json``: columns, the four upstream splits, and per-category row counts
- ``stats.json``: row counts per category and question-length summary
- ``sample_rows.jsonl``: a few sample questions per category for manual review

Only the lightweight ``Text_only`` metadata is read; the image parquets are not
required for inspection. ``Text_only`` carries the original harmful ``question``
(``image`` is null); the image splits rewrite the question to point at an image
that encodes the same harmful keyword as text (recoverable by OCR).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

from src.pipeline.Datasets.safety_v0_sources import source_dir  # noqa: E402

SLUG = "mm_safetybench"
SPLITS = ("Text_only", "TYPO", "SD", "SD_TYPO")
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


def load_text_only(raw_dir: Path, category: str) -> pd.DataFrame:
    path = raw_dir / "data" / category / "Text_only.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["id", "question", "image"])
    return pd.read_parquet(path)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def summarize(frames: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
    per_category: Dict[str, Any] = {}
    total = 0
    for category, df in frames.items():
        lengths = df["question"].astype(str).str.len()
        per_category[category] = {
            "rows": int(len(df)),
            "question_chars_min": int(lengths.min()) if len(df) else 0,
            "question_chars_max": int(lengths.max()) if len(df) else 0,
            "question_chars_mean": round(float(lengths.mean()), 1) if len(df) else 0.0,
        }
        total += len(df)
    return {"total_text_only_rows": total, "per_category": per_category}


def sample_rows(frames: Dict[str, pd.DataFrame], per_category: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for category, df in frames.items():
        for _, row in df.head(per_category).iterrows():
            out.append(
                {
                    "category": category,
                    "id": row.get("id"),
                    "question": row.get("question"),
                }
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=source_dir("raw", SLUG))
    parser.add_argument("--out-dir", type=Path, default=source_dir("inspection", SLUG, create=True))
    parser.add_argument("--sample-per-category", type=int, default=3)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    frames = {cat: load_text_only(args.raw_dir, cat) for cat in CATEGORIES}
    if not any(len(df) for df in frames.values()):
        raise FileNotFoundError(
            f"No MM-SafetyBench Text_only parquets under {args.raw_dir}. "
            "Run download_mm_safetybench.py first."
        )

    schema = {
        "repo_id": "PKU-Alignment/MM-SafetyBench",
        "columns": {
            "id": "string, per-category sample id",
            "question": "string, the (rephrased) instruction shown to the model",
            "image": "image; null in Text_only, PNG bytes in TYPO/SD/SD_TYPO",
        },
        "splits": {
            "Text_only": "original harmful question, no image",
            "TYPO": "harmful keyword rendered as typography in the image",
            "SD": "Stable-Diffusion image for the keyword",
            "SD_TYPO": "SD image with the keyword typed at the bottom",
        },
        "categories": list(CATEGORIES),
        "category_row_counts": {cat: int(len(df)) for cat, df in frames.items()},
        "license": "cc-by-nc-4.0",
        "access": "public",
    }
    stats = summarize(frames)

    write_json(args.out_dir / "schema.json", schema)
    write_json(args.out_dir / "stats.json", stats)
    write_jsonl(args.out_dir / "sample_rows.jsonl", sample_rows(frames, args.sample_per_category))

    print(f"Wrote MM-SafetyBench inspection artifacts to {args.out_dir}")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
