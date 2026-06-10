from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable


DEFAULT_SAMPLE_TIERS = {
    "train_dev_5k": 5000,
    "llm_smoke_50": 50,
    "llm_iter_300": 300,
    "llm_ab_500": 500,
    "llm_final_1000": 1000,
}


@dataclass(frozen=True)
class SampleManifest:
    dataset: str
    split: str
    sample_name: str
    sample_size: int
    actual_size: int
    random_state: int
    input_ids: list[str]

    def to_dict(self) -> dict:
        return {
            "dataset": self.dataset,
            "split": self.split,
            "sample_name": self.sample_name,
            "sample_size": self.sample_size,
            "actual_size": self.actual_size,
            "random_state": self.random_state,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "input_ids": self.input_ids,
        }


def parse_sample_tiers(values: Iterable[str] | None) -> dict[str, int]:
    """Parse CLI tier specs like ``train_dev_5k:5000`` into a size mapping."""
    if not values:
        return dict(DEFAULT_SAMPLE_TIERS)

    tiers: dict[str, int] = {}
    for value in values:
        if ":" not in value:
            raise ValueError(f"Sample tier {value!r} must use NAME:SIZE format.")
        name, raw_size = value.split(":", 1)
        name = name.strip()
        if not name:
            raise ValueError(f"Sample tier {value!r} has an empty name.")
        try:
            size = int(raw_size)
        except ValueError as exc:
            raise ValueError(f"Sample tier {value!r} has a non-integer size.") from exc
        if size <= 0:
            raise ValueError(f"Sample tier {value!r} must have a positive size.")
        tiers[name] = size
    return tiers


def deterministic_input_ids(df, sample_size: int, random_state: int = 42) -> list[str]:
    """Return deterministic sampled input_ids from a normalized dataset frame."""
    if "input_id" not in df.columns:
        raise ValueError("DataFrame must contain an input_id column.")
    if sample_size <= 0:
        raise ValueError("sample_size must be positive.")

    available = len(df)
    if available == 0:
        return []
    if available <= sample_size:
        sampled = df
    else:
        sampled = df.sample(n=sample_size, random_state=random_state)
    return [str(value) for value in sampled["input_id"].tolist()]


def build_sample_manifests(
    df,
    *,
    dataset: str,
    split: str,
    tiers: dict[str, int],
    random_state: int = 42,
) -> list[SampleManifest]:
    manifests = []
    for sample_name, sample_size in tiers.items():
        input_ids = deterministic_input_ids(
            df,
            sample_size=sample_size,
            random_state=random_state,
        )
        manifests.append(
            SampleManifest(
                dataset=dataset,
                split=split,
                sample_name=sample_name,
                sample_size=sample_size,
                actual_size=len(input_ids),
                random_state=random_state,
                input_ids=input_ids,
            )
        )
    return manifests


def write_sample_manifests(
    manifests: Iterable[SampleManifest],
    output_dir: str | Path,
    *,
    overwrite: bool = False,
) -> list[Path]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    written = []
    for manifest in manifests:
        path = output_path / f"{manifest.dataset}__{manifest.split}__{manifest.sample_name}.json"
        if path.exists() and not overwrite:
            raise FileExistsError(
                f"{path} already exists. Pass overwrite=True to replace it."
            )
        path.write_text(
            json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written
