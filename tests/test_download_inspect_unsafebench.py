"""Tests for the UnsafeBench download + inspect pipeline.

Uses a tiny synthetic parquet so the inspector can be exercised end-to-end
without the gated HF dataset. The downloader is only tested for its
"missing token -> clear error" path; we do not attempt to call Hugging Face
because the dataset is DUA-gated and the test environment does not have
access.
"""

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INSPECT = PROJECT_ROOT / "scripts" / "safety_v0" / "inspect" / "inspect_unsafebench.py"
DOWNLOAD = PROJECT_ROOT / "scripts" / "safety_v0" / "download" / "download_unsafebench.py"


def _write_synthetic_parquet(path: Path) -> None:
    """Build a tiny parquet that mirrors the real column shape.

    PyArrow can serialize PIL images inside a parquet cell; we don't need to
    roundtrip a real image for these tests -- a 1x1 PNG is enough to exercise
    the size-decode path.
    """
    from PIL import Image

    def tiny_image(color: str) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (4, 3), color=color).save(buf, format="PNG")
        return buf.getvalue()

    df = pd.DataFrame(
        {
            "image": [tiny_image("red"), tiny_image("green"), tiny_image("blue"), tiny_image("red"), tiny_image("yellow")],
            "safety_label": ["Unsafe", "Safe", "Unsafe", "Safe", "Unsafe"],
            "category": ["Hate", "Safe", "Sexual", "Violence", "Hate"],
            "source": ["Laion5B", "Laion5B", "Lexica", "Laion5B", "Lexica"],
            "text": ["a hateful symbol", "a calm beach", "nude photo prompt", "fight scene", "another hateful image"],
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def test_inspect_writes_schema_stats_and_samples(tmp_path, monkeypatch):
    parquet = tmp_path / "tiny.parquet"
    _write_synthetic_parquet(parquet)

    inspect_mod = _load("inspect_unsafebench", INSPECT)
    out_dir = tmp_path / "inspect"

    # Drive the inspector's main() via subprocess so we also exercise the CLI
    # path; the synthetic parquet is on disk and the script reads --parquet.
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
    result = subprocess.run(
        [
            sys.executable,
            str(INSPECT),
            "--parquet",
            str(parquet),
            "--out-dir",
            str(out_dir),
            "--sample-per-bucket",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "Wrote UnsafeBench inspection artifacts" in result.stdout

    schema = json.loads((out_dir / "schema.json").read_text(encoding="utf-8"))
    stats = json.loads((out_dir / "stats.json").read_text(encoding="utf-8"))
    samples = [
        json.loads(line)
        for line in (out_dir / "sample_rows.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    # Schema carries the canonical taxonomy + license info.
    assert schema["repo_id"] == "yiting/UnsafeBench"
    assert "Hate" in schema["unsafe_categories_paper"]
    assert "Public and Personal Health" in schema["unsafe_categories_paper"]
    assert schema["license"] == "dua_gated"
    assert schema["access"] == "gated"

    # Stats reflect the synthetic 5 rows.
    assert stats["rows"] == 5
    assert stats["safety_label_dist"] == {"Unsafe": 3, "Safe": 2}
    assert stats["category_dist"]["Hate"] == 2
    assert stats["category_dist"]["Sexual"] == 1
    assert stats["source_dist"] == {"Laion5B": 3, "Lexica": 2}
    assert stats["joint_category_safety_dist"]["Hate::Unsafe"] == 2
    assert stats["joint_category_safety_dist"]["Safe::Safe"] == 1
    # Text length stats: 5 rows with lengths 16, 12, 17, 11, 21.
    assert stats["text_stats"]["max"] == 21
    assert stats["text_stats"]["min"] == 11
    # Image widths are all 4 (the synthetic image is 4x3).
    assert stats["image_stats"]["width"]["max"] == 4
    # Missing values reported on every column we shipped.
    assert stats["missing_per_column"]["safety_label"] == 0
    assert stats["missing_per_column"]["source"] == 0

    # One sample per (category, safety_label) bucket -- we have 4 distinct
    # buckets in the synthetic data, so we get 4 samples (capped at 1 each).
    assert len(samples) == 4
    for sample in samples:
        # Image bytes are NOT written into the sample JSONL (the doc is small
        # on purpose and image bytes are review-noise).
        assert "image" not in sample
        assert "image_size" in sample
        assert sample["image_size"] == [4, 3]


def test_inspect_handles_limit_slice(tmp_path):
    parquet = tmp_path / "tiny.parquet"
    _write_synthetic_parquet(parquet)
    out_dir = tmp_path / "inspect"
    env = {**os.environ, "PYTHONPATH": str(PROJECT_ROOT)}
    result = subprocess.run(
        [
            sys.executable,
            str(INSPECT),
            "--parquet",
            str(parquet),
            "--out-dir",
            str(out_dir),
            "--limit",
            "2",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    stats = json.loads((out_dir / "stats.json").read_text(encoding="utf-8"))
    assert stats["rows"] == 2
    # Sliced temp file is cleaned up.
    assert not (out_dir / "_sliced.parquet").exists()


def test_download_missing_token_exits_with_clear_message(tmp_path, monkeypatch):
    # Unset HF_TOKEN and any cached .env so the script reports a DUA-needed
    # error instead of attempting the network call.
    monkeypatch.delenv("HF_TOKEN", raising=False)
    # load_hf_token calls load_env -> load_dotenv(find_dotenv(usecwd=True)),
    # so we have to chdir away from the repo (or delete HF_TOKEN in the .env
    # at the chdir). Simpler: patch load_hf_token at the import site.
    dl = _load("download_unsafebench", DOWNLOAD)
    monkeypatch.setattr(dl, "load_hf_token", lambda: None)
    monkeypatch.setattr(dl, "load_env", lambda: None)
    # Re-require with patched dependency.
    with pytest.raises(SystemExit) as excinfo:
        dl._require_hf_token()
    msg = str(excinfo.value)
    assert "gated" in msg.lower() or "DUA" in msg
    assert "HF_TOKEN" in msg


def test_download_split_rejects_unknown_split():
    dl = _load("download_unsafebench", DOWNLOAD)
    with pytest.raises(ValueError):
        dl.download_split("bogus", Path("/tmp"), token="x")


def test_parquet_files_constant_matches_repo_layout():
    # Lock the downloader's view of the HF repo layout: only train + test
    # parquets exist, both under data/. If the repo ever adds a different
    # split name the test forces an explicit decision instead of a silent
    # default.
    dl = _load("download_unsafebench", DOWNLOAD)
    assert set(dl.PARQUET_FILES) == {"train", "test"}
    for split, name in dl.PARQUET_FILES.items():
        assert name.startswith("data/"), name
        assert name.endswith(".parquet"), name
