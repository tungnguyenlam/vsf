"""Tests for the WebPII safety_v0 converter logic.

Uses synthetic rows so the tests do not require the downloaded WebPII sample.
"""

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from src.pipeline.Datasets.safety_v0_schema import derive_label_mask, validate_row

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "safety_v0" / "convert" / "convert_webpii.py"


@pytest.fixture(scope="module")
def conv():
    spec = importlib.util.spec_from_file_location("convert_webpii", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_map_webpii_key_to_presidio(conv):
    assert conv.map_webpii_key_to_presidio("PII_FULLNAME2") == "PERSON"
    assert conv.map_webpii_key_to_presidio("PII_GIFT_EMAIL") == "EMAIL_ADDRESS"
    assert conv.map_webpii_key_to_presidio("PII_PHONE_AREA") == "PHONE_NUMBER"
    assert conv.map_webpii_key_to_presidio("PII_LOCATION12_POSTCODE_FULL") == "LOCATION"
    assert conv.map_webpii_key_to_presidio("PII_CARD_EXPIRY_MONTH") == "DATE_TIME"
    assert conv.map_webpii_key_to_presidio("PII_CARD_LAST4") == "CREDIT_CARD"
    assert conv.map_webpii_key_to_presidio("PII_CARD_CVV") == "CREDIT_CARD"
    assert conv.map_webpii_key_to_presidio("PII_LOGIN_USERNAME") == "USERNAME"
    assert conv.map_webpii_key_to_presidio("PII_LOGIN_PASSWORD") == "CREDENTIAL"
    assert conv.map_webpii_key_to_presidio("PII_CARD_IMAGE") is None
    assert conv.map_webpii_key_to_presidio("PRODUCT1_NAME") is None
    # Transaction identifiers are not personal identity -> not mapped/redacted
    # (see docs/redaction-policy.md).
    assert conv.map_webpii_key_to_presidio("PII_PROMO_CODE") is None
    assert conv.map_webpii_key_to_presidio("PII_PO_NUMBER") is None
    assert conv.map_webpii_key_to_presidio("PII_JOB_CODE") is None


def test_source_pii_boxes_maps_visible_non_empty_only(conv):
    elements = [
        {
            "key": "PII_EMAIL",
            "value": "a@example.com",
            "bbox_x": 10,
            "bbox_y": 20,
            "bbox_width": 30,
            "bbox_height": 40,
            "visible": True,
            "clipped": False,
            "element_type": "text",
        },
        {
            "key": "PII_CARD_IMAGE",
            "value": "/card.png",
            "bbox_x": 1,
            "bbox_y": 2,
            "bbox_width": 3,
            "bbox_height": 4,
            "visible": True,
            "clipped": False,
            "element_type": "image",
        },
        {
            "key": "PII_PHONE",
            "value": "",
            "bbox_x": 1,
            "bbox_y": 2,
            "bbox_width": 3,
            "bbox_height": 4,
            "visible": True,
            "clipped": False,
            "element_type": "input",
        },
    ]
    boxes, visible_non_empty = conv.source_pii_boxes(elements)
    assert visible_non_empty == 2
    assert len(boxes) == 1
    assert boxes[0]["entity_type"] == "EMAIL_ADDRESS"
    assert boxes[0]["box"] == [10.0, 20.0, 40.0, 60.0]


def make_record():
    return {
        "image": {"bytes": b"not-a-real-png-but-preserved", "path": "row_clean.png"},
        "source_id": "row1",
        "variant": "full",
        "page_type": "billing-address",
        "company": "amazon",
        "image_width": 1280,
        "image_height": 800,
        "num_pii_elements": 2,
        "num_product_elements": 1,
        "num_order_elements": 0,
        "num_search_elements": 0,
        "num_misc_elements": 0,
        "fillable_count": 1,
        "pii_elements_json": (
            '[{"key":"PII_FULLNAME","value":"Ada Lovelace","bbox_x":1,'
            '"bbox_y":2,"bbox_width":10,"bbox_height":20,"visible":true,'
            '"clipped":false,"element_type":"input"},'
            '{"key":"PII_EMAIL","value":"ada@example.com","bbox_x":50,'
            '"bbox_y":60,"bbox_width":30,"bbox_height":10,"visible":true,'
            '"clipped":false,"element_type":"text"}]'
        ),
        "product_elements_json": "[]",
        "order_elements_json": "[]",
        "search_elements_json": "[]",
        "misc_elements_json": "[]",
    }


def test_build_canonical_row_writes_image_and_defers_ocr(conv, tmp_path):
    row = conv.build_canonical_row(make_record(), index=1, images_dir=tmp_path)

    assert validate_row(row) == []
    assert row["input_id"] == "safety_v0_webpii_000001"
    assert row["source"]["name"] == "WebPII/webpii"
    assert row["source"]["source_sample_id"] == "row1:full"
    assert row["modality"] == {"has_image": True, "has_text": False, "has_ocr": False}
    assert row["content"]["ocr_text"] == ""
    assert row["geometry"]["ocr_boxes"] == []
    assert row["detections"]["pii_spans"] == []
    assert len(row["geometry"]["source_pii_boxes"]) == 2
    assert row["labels"]["pii_visible"] is True
    assert row["labels"]["action"] is None
    assert derive_label_mask(row)["pii_visible"] == 1
    assert derive_label_mask(row)["action"] == 0
    assert (tmp_path / "safety_v0_webpii_000001.png").read_bytes() == b"not-a-real-png-but-preserved"


def test_iter_canonical_rows_increments_ids(conv, tmp_path):
    df = pd.DataFrame([make_record(), {**make_record(), "source_id": "row2"}])
    rows = list(conv.iter_canonical_rows(df, images_dir=tmp_path, write_images=False))
    assert [row["input_id"] for row in rows] == [
        "safety_v0_webpii_000001",
        "safety_v0_webpii_000002",
    ]
    assert all(validate_row(row) == [] for row in rows)
