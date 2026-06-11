"""Profile a PII dataset: counts, statistics, and plots.

Loads a registered dataset (or a split of it), computes descriptive statistics
with ``src.pipeline.Datasets.stats``, and writes a JSON summary, a Markdown
report, and PNG charts. Mirrors the shape of ``scripts/mine_prediction_errors``:
plain functions, argparse, Markdown + JSON output.

Examples
--------
    PYTHONPATH=. .venv/bin/python scripts/profile_dataset.py \
        --dataset pii_masking_95k --split validation

    PYTHONPATH=. .venv/bin/python scripts/profile_dataset.py \
        --dataset hoangha_vie_pii --split test --limit 1000
"""

import argparse
import json
from pathlib import Path

from src.pipeline.Datasets import get_dataset, list_dataset_names
from src.pipeline.Datasets.stats import compute_dataset_stats


# Stable, colour-blind-friendly palette reused across charts.
BAR_COLOR = "#4a90e2"
ACCENT_COLOR = "#9013fe"
MUTED_COLOR = "#b0bec5"


def create_arg_parser():
    parser = argparse.ArgumentParser(description="Profile a PII dataset and emit stats + plots.")
    parser.add_argument(
        "--dataset",
        default="pii_masking_95k",
        help=f"Registered dataset name. One of: {', '.join(list_dataset_names())}.",
    )
    parser.add_argument("--split", default="validation", help="Split to load (e.g. train, validation, test, all).")
    parser.add_argument("--limit", type=int, default=None, help="Optional row cap for a quick profile.")
    parser.add_argument("--random-state", type=int, default=42, help="Sampling seed when --limit is set.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory. Default: output/dataset_profiles/<dataset>/<split>/.",
    )
    parser.add_argument("--no-plots", action="store_true", help="Skip PNG chart generation.")
    parser.add_argument("--top", type=int, default=25, help="Rows to show in 'top labels' tables/charts.")
    return parser


def write_json(path: Path, payload):
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def markdown_table(headers, rows):
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(value).replace("\n", " ") for value in row) + " |")
    return "\n".join(lines)


def summary_rows(summary):
    """Flatten the numeric summary block into (metric, value) rows."""
    return [(key, value) for key, value in summary.items()]


def write_markdown(path: Path, stats, *, dataset, split, limit, top, plot_files):
    spans = stats["spans"]
    lines = [
        f"# Dataset Profile: `{dataset}`",
        "",
        f"- **Split:** `{split}`" + (f" (limited to {limit} rows)" if limit else ""),
        f"- **Rows:** {stats['rows']:,}",
        f"- **Splits present in frame:** {', '.join(stats['splits_present']) or 'n/a'}",
        f"- **Distinct native labels:** {stats['distinct_native_labels']}",
        f"- **Rows with no mapped span:** {stats['rows_without_mapped_span']:,}",
        "",
        "## Span coverage",
        "",
        markdown_table(
            ["total spans", "mapped", "unmapped", "mapped share"],
            [[spans["total"], spans["mapped"], spans["unmapped"], f"{spans['mapped_share']:.2%}"]],
        ),
        "",
        "## Spans per row",
        "",
        markdown_table(["metric", "value"], summary_rows(stats["spans_per_row"])),
        "",
        "## Mapped spans per row",
        "",
        markdown_table(["metric", "value"], summary_rows(stats["mapped_spans_per_row"])),
        "",
        "## Source text length (characters)",
        "",
        markdown_table(["metric", "value"], summary_rows(stats["text_length_chars"])),
        "",
        "## Presidio entity-type counts (mapped)",
        "",
        markdown_table(
            ["entity_type", "count"],
            list(stats["presidio_type_counts"].items()),
        ),
        "",
        "## Native label -> Presidio type breakdown",
        "",
    ]

    for presidio_type, labels in sorted(stats["label_to_type_breakdown"].items()):
        rows = sorted(labels.items(), key=lambda item: -item[1])
        lines.append(f"### {presidio_type}")
        lines.append("")
        lines.append(markdown_table(["native label", "count"], rows))
        lines.append("")

    lines.extend(
        [
            f"## Top {top} native labels",
            "",
            markdown_table(["native label", "count"], list(stats["native_label_counts"].items())[:top]),
            "",
            f"## Top {top} unmapped labels (dropped during mapped-type eval)",
            "",
            markdown_table(["native label", "count"], list(stats["unmapped_label_counts"].items())[:top]),
            "",
        ]
    )

    if stats["mapped_labels_absent"]:
        lines.extend(
            [
                "## Mapped labels with zero occurrences",
                "",
                ", ".join(f"`{label}`" for label in stats["mapped_labels_absent"]),
                "",
            ]
        )

    if plot_files:
        lines.append("## Charts")
        lines.append("")
        for plot in plot_files:
            lines.append(f"![{plot.stem}]({plot.name})")
            lines.append("")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _bar_chart(ax, labels, values, *, title, xlabel, color=BAR_COLOR, rotate=0):
    positions = range(len(labels))
    ax.bar(list(positions), values, color=color, alpha=0.85, edgecolor="#ffffff", linewidth=0.8)
    ax.set_title(title, fontsize=12, fontweight="bold", color="#333333")
    ax.set_xlabel(xlabel, fontsize=10, color="#555555")
    ax.set_xticks(list(positions))
    ax.set_xticklabels(labels, fontsize=8, rotation=rotate, ha="right" if rotate else "center")
    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)


def generate_plots(stats, out_dir: Path, *, top: int):
    """Render PNG charts and return the list of written paths."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    written = []

    # 1. Presidio entity-type distribution.
    type_counts = stats["presidio_type_counts"]
    if type_counts:
        fig, ax = plt.subplots(figsize=(9, 5), dpi=120)
        _bar_chart(
            ax,
            list(type_counts.keys()),
            list(type_counts.values()),
            title=f"{stats['dataset']}: mapped entity-type counts",
            xlabel="Presidio entity type",
            rotate=30,
        )
        fig.tight_layout()
        path = out_dir / "entity_type_counts.png"
        fig.savefig(path)
        plt.close(fig)
        written.append(path)

    # 2. Top native labels.
    native = list(stats["native_label_counts"].items())[:top]
    if native:
        fig, ax = plt.subplots(figsize=(11, 6), dpi=120)
        _bar_chart(
            ax,
            [label for label, _ in native],
            [count for _, count in native],
            title=f"{stats['dataset']}: top {len(native)} native labels",
            xlabel="native label",
            color=ACCENT_COLOR,
            rotate=60,
        )
        fig.tight_layout()
        path = out_dir / "top_native_labels.png"
        fig.savefig(path)
        plt.close(fig)
        written.append(path)

    # 3. Mapped vs unmapped span share.
    spans = stats["spans"]
    if spans["total"]:
        fig, ax = plt.subplots(figsize=(6, 5), dpi=120)
        ax.bar(["mapped", "unmapped"], [spans["mapped"], spans["unmapped"]],
               color=[BAR_COLOR, MUTED_COLOR], alpha=0.9, edgecolor="#ffffff")
        ax.set_title(f"{stats['dataset']}: mapped vs unmapped spans", fontsize=12, fontweight="bold")
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        ax.set_axisbelow(True)
        fig.tight_layout()
        path = out_dir / "mapped_vs_unmapped.png"
        fig.savefig(path)
        plt.close(fig)
        written.append(path)

    return written


def main(argv=None):
    args = create_arg_parser().parse_args(argv)

    if args.dataset not in list_dataset_names():
        raise SystemExit(f"Unknown dataset {args.dataset!r}. Available: {list_dataset_names()}")

    dataset = get_dataset(args.dataset)
    df = dataset.load(split=args.split, limit=args.limit, random_state=args.random_state)
    stats = compute_dataset_stats(df, dataset)

    out_dir = args.out_dir or Path("output/dataset_profiles") / args.dataset / args.split
    out_dir.mkdir(parents=True, exist_ok=True)

    plot_files = []
    if not args.no_plots:
        plot_files = generate_plots(stats, out_dir, top=args.top)

    write_json(out_dir / "stats.json", stats)
    write_markdown(
        out_dir / "profile.md",
        stats,
        dataset=args.dataset,
        split=args.split,
        limit=args.limit,
        top=args.top,
        plot_files=plot_files,
    )

    print(json.dumps(
        {
            "dataset": args.dataset,
            "split": args.split,
            "rows": stats["rows"],
            "total_spans": stats["spans"]["total"],
            "mapped_share": stats["spans"]["mapped_share"],
            "out_dir": str(out_dir),
            "plots": [str(p) for p in plot_files],
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
