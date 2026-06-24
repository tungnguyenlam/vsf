"""Convert VLGuard metadata into canonical safety_v0 rows.

VLGuard is image-plus-instruction safety data. Metadata rows have an image path,
an image-level ``safe`` flag, and one or two instruction/response pairs:

- unsafe image rows: one ``instruction`` + refusal response, with
  ``harmful_category`` / ``harmful_subcategory``
- safe image rows: one ``safe_instruction`` and one ``unsafe_instruction``

This converter emits one canonical row per instruction/response pair. It does
not require image zips to be downloaded; ``content.original_image_path`` points
to where the image will live under ``data/safety_v0/raw/vlguard/images`` after a
future bounded image extraction step.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets.safety_v0_schema import new_row, validate_row  # noqa: E402
from src.pipeline.Datasets.safety_v0_sources import (  # noqa: E402
    converted_path,
    format_input_id,
    get_source,
    source_dir,
)

SLUG = "vlguard"
SPLITS = ("train", "test")


def _project_relative(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _visual_axis_labels(
    *,
    image_safe: bool,
    harmful_subcategory: Optional[str],
) -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    labels = {
        "action": "safe" if image_safe else "reject",
        "pii_visible": False if image_safe else None,
        "prompt_injection": False,
        "sexual": False if image_safe else None,
        "violence": False if image_safe else None,
        "blood_gore": False if image_safe else None,
        "political": False if image_safe else None,
        "religious": None,
    }
    label_source = {
        "action": "source_gold",
        "pii_visible": "source_gold" if image_safe else None,
        "prompt_injection": "source_assumption",
        "sexual": "source_gold" if image_safe else None,
        "violence": "source_gold" if image_safe else None,
        "blood_gore": "source_gold" if image_safe else None,
        "political": "source_gold" if image_safe else None,
        "religious": None,
    }

    if not image_safe:
        sub = (harmful_subcategory or "").strip().lower()
        if sub == "sexually explicit":
            labels["sexual"] = True
            label_source["sexual"] = "source_gold"
        elif sub == "violence":
            labels["violence"] = True
            label_source["violence"] = "source_gold"
        elif sub == "political":
            labels["political"] = True
            label_source["political"] = "source_gold"
        elif sub == "personal data":
            labels["pii_visible"] = True
            label_source["pii_visible"] = "source_gold"
    return labels, label_source


def _instruction_pairs(record: Dict[str, Any]) -> List[Tuple[str, str, str]]:
    pairs: List[Tuple[str, str, str]] = []
    for item in record.get("instr-resp") or []:
        response = item.get("response") or ""
        if "instruction" in item:
            pairs.append(("unsafe_image_instruction", item.get("instruction") or "", response))
        if "safe_instruction" in item:
            pairs.append(("safe_instruction", item.get("safe_instruction") or "", response))
        if "unsafe_instruction" in item:
            pairs.append(("unsafe_instruction", item.get("unsafe_instruction") or "", response))
    return pairs


def _action_for_pair(image_safe: bool, instruction_kind: str) -> str:
    if instruction_kind == "safe_instruction":
        return "safe"
    return "reject" if (not image_safe or instruction_kind == "unsafe_instruction") else "safe"


def build_canonical_row(
    index: int,
    split: str,
    record: Dict[str, Any],
    instruction_index: int,
    instruction_kind: str,
    instruction: str,
    response: str,
    *,
    images_root: Path,
) -> Dict[str, Any]:
    image_safe = bool(record.get("safe"))
    labels, label_source = _visual_axis_labels(
        image_safe=image_safe,
        harmful_subcategory=record.get("harmful_subcategory"),
    )
    labels["action"] = _action_for_pair(image_safe, instruction_kind)
    label_source["action"] = "source_gold"

    image_path = images_root / str(record.get("image", ""))
    source_id = f"{split}:{record.get('id')}:{instruction_index}:{instruction_kind}"
    row = new_row(
        format_input_id(SLUG, index),
        get_source(SLUG).name,
        split=split,
        source_sample_id=source_id,
        license_status="mit_gated",
        has_image=True,
        has_text=bool(instruction.strip()),
        has_ocr=False,
        original_image_path=_project_relative(image_path),
        input_text=instruction,
        sanitized_text=instruction,
    )
    row["labels"] = labels
    row["label_source"] = label_source
    row["source_labels"] = {
        "id": record.get("id"),
        "image": record.get("image"),
        "image_safe": image_safe,
        "instruction_kind": instruction_kind,
        "response": response,
        "harmful_category": record.get("harmful_category"),
        "harmful_subcategory": record.get("harmful_subcategory"),
        "split": split,
    }
    return row


def load_split(raw_dir: Path, split: str) -> List[Dict[str, Any]]:
    path = raw_dir / f"{split}.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def iter_canonical_rows(
    raw_dir: Path,
    *,
    images_root: Path,
    limit_per_split: Optional[int] = None,
) -> Iterator[Dict[str, Any]]:
    index = 1
    for split in SPLITS:
        records = load_split(raw_dir, split)
        if limit_per_split is not None:
            records = records[:limit_per_split]
        for record in records:
            for instruction_index, (kind, instruction, response) in enumerate(
                _instruction_pairs(record), start=1
            ):
                yield build_canonical_row(
                    index,
                    split,
                    record,
                    instruction_index,
                    kind,
                    instruction,
                    response,
                    images_root=images_root,
                )
                index += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=source_dir("raw", SLUG))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--limit-per-split", type=int, default=None)
    parser.add_argument(
        "--images-root",
        type=Path,
        default=source_dir("raw", SLUG) / "images",
        help="Root where extracted VLGuard images will live.",
    )
    args = parser.parse_args()

    out_path = args.output or converted_path(SLUG, create=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = invalid = 0
    with open(out_path, "w", encoding="utf-8") as handle:
        for row in iter_canonical_rows(
            args.raw_dir,
            images_root=args.images_root,
            limit_per_split=args.limit_per_split,
        ):
            errors = validate_row(row)
            if errors:
                invalid += 1
                print(f"  invalid row {row['input_id']}: {errors[0]}", file=sys.stderr)
                continue
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1

    print(f"Converted {written} VLGuard rows ({invalid} invalid) -> {out_path}")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
