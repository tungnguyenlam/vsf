"""Convert the cached WebPII parquet sample into canonical `safety_v0` rows.

This converter is source-only. It writes image bytes to the converted artifact
directory and carries WebPII source PII boxes in ``geometry.source_pii_boxes``.
It does not invent OCR text, OCR boxes, or character spans. Those are filled by
the later OCR/alignment/redaction stages.

Usage:

    python scripts/safety_v0/convert/convert_webpii.py
    python scripts/safety_v0/validate_safety_v0.py \
      data/safety_v0/converted/webpii/source_canonical.jsonl
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

import pandas as pd

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


SLUG = "webpii"
SOURCE_NAME = get_source(SLUG).name

JSON_COLUMNS = (
    "pii_elements_json",
    "product_elements_json",
    "order_elements_json",
    "search_elements_json",
    "misc_elements_json",
)


def parse_json_list(raw: Any) -> List[Dict[str, Any]]:
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
    if not isinstance(data, list):
        raise TypeError(f"Expected WebPII element list, got {type(data).__name__}")
    return [item for item in data if isinstance(item, dict)]


def box_xywh_to_xyxy(element: Dict[str, Any]) -> Optional[List[float]]:
    try:
        x = float(element["bbox_x"])
        y = float(element["bbox_y"])
        width = float(element["bbox_width"])
        height = float(element["bbox_height"])
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return [x, y, x + width, y + height]


def normalize_for_suffix_match(key: str) -> str:
    """Strip numeric copy suffixes while preserving semantic digits.

    Examples:
    - ``PII_FULLNAME2`` -> ``PII_FULLNAME``
    - ``PII_CARD_LAST4`` stays ``PII_CARD_LAST4``
    - ``PII_LOCATION12_STREET`` is handled by regexes before this is needed.
    """
    if key == "PII_CARD_LAST4":
        return key
    return re.sub(r"\d+$", "", key)


def map_webpii_key_to_presidio(key: str) -> Optional[str]:
    """Map clear WebPII PII keys to the project's target entity taxonomy."""
    key = str(key or "").upper()
    base = normalize_for_suffix_match(key)

    if key in {"PII_CARD_IMAGE", "PII_AVATAR"}:
        return None

    if re.fullmatch(r"PII_(GIFT_)?(FIRSTNAME|LASTNAME|FULLNAME)(?:_DERIVED)?\d*", key):
        return "PERSON"
    if base in {"PII_NAME_FULL_DERIVED"}:
        return "PERSON"

    if re.fullmatch(r"PII_(GIFT_)?EMAIL\d*", key):
        return "EMAIL_ADDRESS"

    if key.startswith("PII_PHONE"):
        return "PHONE_NUMBER"

    if (
        base in {"PII_ADDRESS", "PII_STREET", "PII_CITY", "PII_STATE", "PII_STATE_ABBR"}
        or base.startswith("PII_POSTCODE")
        or base.startswith("PII_COUNTRY")
        or base.startswith("PII_CITY_STATE")
        or re.fullmatch(
            r"PII_LOCATION\d+_(STREET|CITY|STATE|STATE_ABBR|POSTCODE|POSTCODE_EXT|POSTCODE_FULL|CITY_STATE|CITY_STATE_ZIP)",
            key,
        )
    ):
        return "LOCATION"

    if base == "PII_COMPANY":
        return "ORGANIZATION"

    if base.startswith("PII_DOB") or base.startswith("PII_CARD_EXPIRY"):
        return "DATE_TIME"

    # Card data -> CREDIT_CARD (number, last4, CVV) (expiry handled above as DATE_TIME).
    if base in {"PII_CARD_NUMBER", "PII_CARD_LAST4", "PII_CARD_CVV", "PII_SECURITY_CODE"}:
        return "CREDIT_CARD"

    # Account secrets / handles, aligned with the expanded taxonomy.
    if base == "PII_LOGIN_USERNAME":
        return "USERNAME"
    if base in {"PII_LOGIN_PASSWORD", "PII_LOGIN_PASSWORD_CONFIRM"}:
        return "CREDENTIAL"

    # Order/job/promo codes are identifiers but not one of the named types.
    if base in {"PII_PO_NUMBER", "PII_JOB_CODE", "PII_PROMO_CODE"}:
        return "ID"

    # Free-text fields that may carry incidental PII; keep as MISC catch-all.
    if base in {"PII_DELIVERY_INSTRUCTIONS", "PII_GIFT_MESSAGE"}:
        return "MISC"

    return None


def source_pii_boxes(elements: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    """Return mapped source PII boxes plus the count of visible non-empty PII elements."""
    boxes: List[Dict[str, Any]] = []
    visible_non_empty = 0
    for element in elements:
        value = element.get("value")
        if value in ("", None):
            continue
        if element.get("visible") is not True:
            continue
        box = box_xywh_to_xyxy(element)
        if box is None:
            continue

        visible_non_empty += 1
        entity_type = map_webpii_key_to_presidio(str(element.get("key", "")))
        if entity_type is None:
            continue

        boxes.append(
            {
                "box_id": f"source_pii_box_{len(boxes) + 1:04d}",
                "source_key": str(element.get("key", "")),
                "entity_type": entity_type,
                "text": str(value),
                "box": box,
                "visible": bool(element.get("visible")),
                "clipped": bool(element.get("clipped")),
                "element_type": element.get("element_type"),
            }
        )
    return boxes, visible_non_empty


def webpii_source_labels(record: Dict[str, Any], source_box_count: int, mapped_box_count: int) -> Dict[str, Any]:
    counts = {}
    for name in (
        "num_pii_elements",
        "num_product_elements",
        "num_order_elements",
        "num_search_elements",
        "num_misc_elements",
        "fillable_count",
    ):
        value = record.get(name)
        counts[name] = int(value) if value is not None else None

    return {
        "company": record.get("company"),
        "page_type": record.get("page_type"),
        "variant": record.get("variant"),
        "image_source_path": (record.get("image") or {}).get("path")
        if isinstance(record.get("image"), dict)
        else None,
        "image_width": int(record["image_width"]) if record.get("image_width") is not None else None,
        "image_height": int(record["image_height"]) if record.get("image_height") is not None else None,
        "counts": counts,
        "visible_non_empty_pii_box_count": source_box_count,
        "mapped_source_pii_box_count": mapped_box_count,
    }


def source_labels_only_policy(has_visible_pii: bool) -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    labels = {
        "action": None,
        "pii_visible": bool(has_visible_pii),
        "prompt_injection": False,
        "sexual": None,
        "violence": None,
        "blood_gore": None,
        "political": False,
        "religious": False,
    }
    label_source = {
        "action": None,
        "pii_visible": "source",
        "prompt_injection": "source_assumption",
        "sexual": None,
        "violence": None,
        "blood_gore": None,
        "political": "source_assumption",
        "religious": "source_assumption",
    }
    return labels, label_source


def project_relative(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def write_image(record: Dict[str, Any], path: Path) -> None:
    image = record.get("image")
    if not isinstance(image, dict) or not image.get("bytes"):
        raise ValueError("WebPII row has no image bytes")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image["bytes"])


def build_canonical_row(
    record: Dict[str, Any],
    *,
    index: int,
    images_dir: Path,
    split: str = "test",
    write_images: bool = True,
) -> Dict[str, Any]:
    input_id = format_input_id(SLUG, index)
    image_path = images_dir / f"{input_id}.png"
    if write_images:
        write_image(record, image_path)

    pii_elements = parse_json_list(record.get("pii_elements_json"))
    source_boxes, visible_non_empty_count = source_pii_boxes(pii_elements)
    labels, label_source = source_labels_only_policy(visible_non_empty_count > 0)

    source_sample_id = f"{record.get('source_id')}:{record.get('variant')}"
    row = new_row(
        input_id,
        SOURCE_NAME,
        split=split,
        source_sample_id=source_sample_id,
        license_status="needs_verification",
        has_image=True,
        has_text=False,
        has_ocr=False,
        original_image_path=project_relative(image_path),
    )
    row["geometry"]["source_pii_boxes"] = source_boxes
    row["labels"] = labels
    row["label_source"] = label_source
    row["source_labels"] = webpii_source_labels(
        record,
        source_box_count=visible_non_empty_count,
        mapped_box_count=len(source_boxes),
    )
    return row


def iter_canonical_rows(
    df: pd.DataFrame,
    *,
    images_dir: Path,
    split: str = "test",
    start_index: int = 1,
    write_images: bool = True,
) -> Iterator[Dict[str, Any]]:
    index = start_index
    for record in df.to_dict("records"):
        yield build_canonical_row(
            record,
            index=index,
            images_dir=images_dir,
            split=split,
            write_images=write_images,
        )
        index += 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=source_dir("raw", SLUG) / "sample" / "schema_sample_100.parquet",
    )
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--split", default="test")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    out_path = args.out or converted_path(SLUG, create=True)
    images_dir = out_path.parent / "images"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    df = pd.read_parquet(args.input)
    if args.limit is not None:
        df = df.head(args.limit)

    written = 0
    invalid = 0
    with open(out_path, "w", encoding="utf-8") as handle:
        for row in iter_canonical_rows(df, images_dir=images_dir, split=args.split):
            errors = validate_row(row)
            if errors:
                invalid += 1
                print(f"invalid row {row['input_id']}: {errors[0]}", file=sys.stderr)
                continue
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1

    print(f"Wrote {written} rows to {out_path} ({invalid} invalid skipped).")
    print(f"Wrote images to {images_dir}.")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
