"""Tests for the UnsafeBench image extractor using a synthetic parquet.

No network, no DUA token. A tiny in-memory DataFrame stands in for the gated
parquet; image cells cover the three shapes the extractor must handle (HF
``{"bytes": ...}`` struct, raw bytes, undecodable junk). The key contract is
that the on-disk filenames line up with the converter's 1-based ``input_id``.
"""

import importlib.util
import io
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    PROJECT_ROOT / "scripts" / "safety_v0" / "download" / "extract_unsafebench_images.py"
)


@pytest.fixture(scope="module")
def ext():
    spec = importlib.util.spec_from_file_location("extract_unsafebench_images", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _png_bytes(color: str, size=(4, 3)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


def _df_hf_struct() -> pd.DataFrame:
    # Mirrors the real HF Image feature: a {"bytes": ..., "path": ...} struct.
    return pd.DataFrame(
        {
            "image": [
                {"bytes": _png_bytes("red"), "path": None},
                {"bytes": _png_bytes("green"), "path": None},
            ],
            "safety_label": ["Safe", "Unsafe"],
        }
    )


def test_decode_handles_struct_bytes_and_path(ext, tmp_path):
    from PIL import Image

    assert ext._decode_image_cell({"bytes": _png_bytes("red"), "path": None}) is not None
    assert ext._decode_image_cell(_png_bytes("blue")) is not None

    p = tmp_path / "x.png"
    Image.new("RGB", (2, 2), "yellow").save(p, format="PNG")
    assert ext._decode_image_cell(str(p)) is not None

    assert ext._decode_image_cell(None) is None
    assert ext._decode_image_cell({"bytes": None, "path": None}) is None


def test_extract_writes_jpegs_matching_converter_input_ids(ext, tmp_path):
    from PIL import Image

    parquet = tmp_path / "test.parquet"
    _df_hf_struct().to_parquet(parquet, index=False)
    images_root = tmp_path / "images"

    summary = ext.extract_images(parquet, images_root)

    assert summary == {"written": 2, "skipped": 0, "failed": 0, "total": 2}
    # 1-based filenames identical to format_input_id(SLUG, row+1).
    expected = [
        images_root / "safety_v0_unsafebench_000001.jpg",
        images_root / "safety_v0_unsafebench_000002.jpg",
    ]
    for path in expected:
        assert path.exists()
        with Image.open(path) as img:
            assert img.format == "JPEG"
            assert img.mode == "RGB"


def test_extract_skips_existing_unless_overwrite(ext, tmp_path):
    parquet = tmp_path / "test.parquet"
    _df_hf_struct().to_parquet(parquet, index=False)
    images_root = tmp_path / "images"

    first = ext.extract_images(parquet, images_root)
    assert first["written"] == 2

    again = ext.extract_images(parquet, images_root)
    assert again == {"written": 0, "skipped": 2, "failed": 0, "total": 2}

    forced = ext.extract_images(parquet, images_root, overwrite=True)
    assert forced["written"] == 2 and forced["skipped"] == 0


def test_extract_respects_limit(ext, tmp_path):
    parquet = tmp_path / "test.parquet"
    _df_hf_struct().to_parquet(parquet, index=False)
    images_root = tmp_path / "images"

    summary = ext.extract_images(parquet, images_root, limit=1)
    assert summary["total"] == 1 and summary["written"] == 1
    assert (images_root / "safety_v0_unsafebench_000001.jpg").exists()
    assert not (images_root / "safety_v0_unsafebench_000002.jpg").exists()


def test_extract_counts_undecodable_cells_as_failed(ext, tmp_path):
    parquet = tmp_path / "test.parquet"
    pd.DataFrame(
        {"image": [{"bytes": b"not a real image", "path": None}, {"bytes": None, "path": None}]}
    ).to_parquet(parquet, index=False)
    images_root = tmp_path / "images"

    summary = ext.extract_images(parquet, images_root)
    assert summary["failed"] == 2 and summary["written"] == 0
