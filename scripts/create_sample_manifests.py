import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.pipeline.Datasets import get_dataset, list_dataset_names
from src.pipeline.Datasets.sampling import (
    build_sample_manifests,
    parse_sample_tiers,
    write_sample_manifests,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Create deterministic dataset sample input_id manifests."
    )
    parser.add_argument(
        "--dataset",
        default="pii_masking_95k",
        choices=list_dataset_names(),
        help="Registered dataset key.",
    )
    parser.add_argument(
        "--split",
        default="train",
        help="Dataset split to sample from, usually train.",
    )
    parser.add_argument(
        "--random-state",
        type=int,
        default=42,
        help="Deterministic pandas sample seed.",
    )
    parser.add_argument(
        "--tier",
        action="append",
        default=None,
        metavar="NAME:SIZE",
        help="Sample tier to write. Repeatable. Defaults to the project cost policy tiers.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "data" / "sample_ids"),
        help="Directory for JSON sample manifests.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing manifest files.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    tiers = parse_sample_tiers(args.tier)

    dataset = get_dataset(args.dataset)
    df = dataset.load(split=args.split)
    manifests = build_sample_manifests(
        df,
        dataset=args.dataset,
        split=args.split,
        tiers=tiers,
        random_state=args.random_state,
    )
    paths = write_sample_manifests(
        manifests,
        args.output_dir,
        overwrite=args.overwrite,
    )

    summary = {
        "dataset": args.dataset,
        "split": args.split,
        "random_state": args.random_state,
        "output_dir": str(Path(args.output_dir)),
        "files": [
            {
                "path": str(path),
                "sample_name": manifest.sample_name,
                "actual_size": manifest.actual_size,
            }
            for path, manifest in zip(paths, manifests)
        ],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
