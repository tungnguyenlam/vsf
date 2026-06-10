import json

import pandas as pd
import pytest

from src.pipeline.Datasets.sampling import (
    build_sample_manifests,
    deterministic_input_ids,
    parse_sample_tiers,
    write_sample_manifests,
)
from src.pipeline.Utils import split_train_validation_frame


def test_parse_sample_tiers_defaults_and_custom_values():
    defaults = parse_sample_tiers(None)
    assert defaults["train_dev_5k"] == 5000
    assert defaults["llm_smoke_50"] == 50

    custom = parse_sample_tiers(["debug:12", "decision:500"])

    assert custom == {"debug": 12, "decision": 500}


def test_parse_sample_tiers_rejects_bad_specs():
    with pytest.raises(ValueError, match="NAME:SIZE"):
        parse_sample_tiers(["debug"])

    with pytest.raises(ValueError, match="positive"):
        parse_sample_tiers(["debug:0"])


def test_deterministic_input_ids_are_stable_and_capped():
    df = pd.DataFrame({"input_id": [f"row-{i}" for i in range(10)]})

    first = deterministic_input_ids(df, sample_size=5, random_state=42)
    second = deterministic_input_ids(df, sample_size=5, random_state=42)
    capped = deterministic_input_ids(df, sample_size=20, random_state=42)

    assert first == second
    assert len(first) == 5
    assert capped == [f"row-{i}" for i in range(10)]


def test_build_and_write_sample_manifests(tmp_path):
    df = pd.DataFrame({"input_id": [f"row-{i}" for i in range(5)]})
    manifests = build_sample_manifests(
        df,
        dataset="pii_masking_95k",
        split="train",
        tiers={"tiny": 3},
        random_state=7,
    )

    paths = write_sample_manifests(manifests, tmp_path)

    assert len(paths) == 1
    payload = json.loads(paths[0].read_text(encoding="utf-8"))
    assert payload["dataset"] == "pii_masking_95k"
    assert payload["split"] == "train"
    assert payload["sample_name"] == "tiny"
    assert payload["sample_size"] == 3
    assert payload["actual_size"] == 3
    assert payload["random_state"] == 7
    assert len(payload["input_ids"]) == 3

    with pytest.raises(FileExistsError):
        write_sample_manifests(manifests, tmp_path)


def test_train_validation_partition_is_deterministic_and_disjoint():
    df = pd.DataFrame({"input_id": [f"row-{i}" for i in range(100)]})

    first_val = split_train_validation_frame(df, "train_val", random_state=42)
    second_val = split_train_validation_frame(df, "train_val", random_state=42)
    train_main = split_train_validation_frame(df, "train_main", random_state=42)

    assert first_val["input_id"].tolist() == second_val["input_id"].tolist()
    assert len(first_val) == 10
    assert len(train_main) == 90
    assert set(first_val["input_id"]).isdisjoint(set(train_main["input_id"]))
    assert set(first_val["input_id"]) | set(train_main["input_id"]) == set(df["input_id"])
