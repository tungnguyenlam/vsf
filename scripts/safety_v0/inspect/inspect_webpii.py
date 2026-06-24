"""Inspect the cached WebPII sample for safety_v0 conversion planning.

Reads the bounded upstream sample downloaded by
``scripts/safety_v0/download/download_webpii.py`` and writes lightweight
inspection artifacts under ``data/safety_v0/inspection/webpii/``.

Usage:

    python scripts/safety_v0/inspect/inspect_webpii.py
"""

import argparse
import json
import re
import sys
import zipfile
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List

import pandas as pd
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets import safety_v0_sources as sv  # noqa: E402


JSON_COLUMNS = [
    "pii_elements_json",
    "product_elements_json",
    "order_elements_json",
    "search_elements_json",
    "misc_elements_json",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=sv.source_dir("raw", "webpii"),
        help="Cached WebPII raw directory or symlink.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=sv.source_dir("inspection", "webpii"),
        help="Inspection output directory.",
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=10,
        help="Number of compact parquet rows to write to sample_rows.jsonl.",
    )
    return parser.parse_args()


def load_json_list(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if isinstance(raw, str):
        if not raw:
            return []
        data = json.loads(raw)
    else:
        data = raw
    if data is None:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    raise TypeError(f"Expected JSON list, got {type(data).__name__}")


def normalize_numbered_key(key: str) -> str:
    return re.sub(r"\d+$", "", key)


def summarize_elements(df: pd.DataFrame, column: str) -> Dict[str, Any]:
    key_counts: Counter[str] = Counter()
    base_key_counts: Counter[str] = Counter()
    element_type_counts: Counter[str] = Counter()
    visible_counts: Counter[str] = Counter()
    clipped_counts: Counter[str] = Counter()
    value_empty = 0
    total = 0

    for raw in df[column]:
        for item in load_json_list(raw):
            total += 1
            key = str(item.get("key", ""))
            key_counts[key] += 1
            base_key_counts[normalize_numbered_key(key)] += 1
            element_type_counts[str(item.get("element_type"))] += 1
            visible_counts[str(item.get("visible"))] += 1
            clipped_counts[str(item.get("clipped"))] += 1
            if item.get("value") in ("", None):
                value_empty += 1

    return {
        "total_elements": total,
        "unique_keys": len(key_counts),
        "empty_values": value_empty,
        "top_keys": key_counts.most_common(100),
        "top_base_keys": base_key_counts.most_common(100),
        "element_type_counts": element_type_counts.most_common(),
        "visible_counts": visible_counts.most_common(),
        "clipped_counts": clipped_counts.most_common(),
    }


def compact_row(row: pd.Series) -> Dict[str, Any]:
    image = row["image"]
    image_summary: Dict[str, Any]
    if isinstance(image, dict):
        image_summary = {
            "path": image.get("path"),
            "bytes_len": len(image.get("bytes") or b""),
        }
    else:
        image_summary = {"type": type(image).__name__}

    out = {
        "source_id": row["source_id"],
        "variant": row["variant"],
        "page_type": row["page_type"],
        "company": row["company"],
        "image": image_summary,
        "image_width": int(row["image_width"]),
        "image_height": int(row["image_height"]),
        "counts": {
            "pii": int(row["num_pii_elements"]),
            "product": int(row["num_product_elements"]),
            "order": int(row["num_order_elements"]),
            "search": int(row["num_search_elements"]),
            "misc": int(row["num_misc_elements"]),
            "fillable": int(row["fillable_count"]),
        },
    }
    for column in JSON_COLUMNS:
        out[column] = load_json_list(row[column])[:3]
    return out


def summarize_visual_zip(zip_path: Path) -> Dict[str, Any]:
    if not zip_path.exists():
        return {"exists": False}

    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        png_names = [name for name in names if name.endswith(".png")]
        metadata_names = [name for name in names if name.endswith("metadata.json")]

        metadata_top_keys: Counter[str] = Counter()
        companies: Counter[str] = Counter()
        page_types: Counter[str] = Counter()
        image_variants: Counter[str] = Counter()
        pii_key_counts: Counter[str] = Counter()
        element_type_counts: Counter[str] = Counter()
        png_dimensions: Counter[str] = Counter()

        for name in png_names:
            stem = Path(name).stem
            if stem.endswith("_empty_clean"):
                variant = "empty_clean"
            elif stem.endswith("_partial_clean"):
                variant = "partial_clean"
            elif stem.endswith("_clean"):
                variant = "filled_clean"
            elif stem.endswith("_empty"):
                variant = "empty"
            elif stem.endswith("_partial"):
                variant = "partial"
            else:
                variant = "filled"
            image_variants[variant] += 1

        for name in png_names[:50]:
            image = Image.open(BytesIO(zf.read(name)))
            png_dimensions[f"{image.width}x{image.height}"] += 1

        for name in metadata_names:
            metadata = json.loads(zf.read(name).decode("utf-8"))
            metadata_top_keys.update(metadata.keys())
            companies[str(metadata.get("company"))] += 1
            page_types[str(metadata.get("page_type"))] += 1
            for item in metadata.get("pii_elements", []):
                key = str(item.get("key", ""))
                pii_key_counts[key] += 1
                element_type_counts[str(item.get("element_type"))] += 1

    return {
        "exists": True,
        "zip_path": str(zip_path),
        "num_files": len(names),
        "num_png_images": len(png_names),
        "num_metadata_json_files": len(metadata_names),
        "companies": companies.most_common(),
        "page_types": page_types.most_common(),
        "image_variants": image_variants.most_common(),
        "metadata_top_keys": metadata_top_keys.most_common(),
        "top_pii_keys": pii_key_counts.most_common(100),
        "pii_element_type_counts": element_type_counts.most_common(),
        "sample_png_dimensions_first_50": png_dimensions.most_common(),
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    args = parse_args()
    parquet_path = args.raw_dir / "sample" / "schema_sample_100.parquet"
    manifest_path = args.raw_dir / "sample" / "sample_manifest.json"
    visual_zip_path = args.raw_dir / "sample" / "webpii_visual_samples.zip"

    if not parquet_path.exists():
        raise FileNotFoundError(f"Missing WebPII parquet sample: {parquet_path}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_parquet(parquet_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    schema = {
        "parquet_path": str(parquet_path),
        "shape": {"rows": int(df.shape[0]), "columns": int(df.shape[1])},
        "columns": [{"name": name, "dtype": str(dtype)} for name, dtype in df.dtypes.items()],
        "manifest_keys": sorted(manifest.keys()),
    }
    stats = {
        "source_id_unique": int(df["source_id"].nunique(dropna=False)),
        "company_counts": df["company"].value_counts(dropna=False).to_dict(),
        "page_type_counts": df["page_type"].value_counts(dropna=False).to_dict(),
        "variant_counts": df["variant"].value_counts(dropna=False).to_dict(),
        "image_width_counts": df["image_width"].value_counts(dropna=False).to_dict(),
        "image_height_min": int(df["image_height"].min()),
        "image_height_max": int(df["image_height"].max()),
        "element_count_summary": {
            column: {
                "min": int(df[column].min()),
                "max": int(df[column].max()),
                "mean": float(df[column].mean()),
            }
            for column in [
                "num_pii_elements",
                "num_product_elements",
                "num_order_elements",
                "num_search_elements",
                "num_misc_elements",
                "fillable_count",
            ]
        },
        "element_columns": {
            column: summarize_elements(df, column)
            for column in JSON_COLUMNS
        },
        "visual_zip": summarize_visual_zip(visual_zip_path),
    }

    write_json(args.out_dir / "schema.json", schema)
    write_json(args.out_dir / "stats.json", stats)
    write_json(args.out_dir / "manifest_summary.json", manifest)
    write_jsonl(
        args.out_dir / "sample_rows.jsonl",
        (compact_row(row) for _, row in df.head(args.sample_rows).iterrows()),
    )

    print(f"Wrote {args.out_dir / 'schema.json'}")
    print(f"Wrote {args.out_dir / 'stats.json'}")
    print(f"Wrote {args.out_dir / 'manifest_summary.json'}")
    print(f"Wrote {args.out_dir / 'sample_rows.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
