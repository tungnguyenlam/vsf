import argparse
import json
from collections import Counter
from pathlib import Path


def create_arg_parser():
    parser = argparse.ArgumentParser(
        description="Mine false positives, false negatives, and action mismatches from prompt-injection decision logs."
    )
    parser.add_argument("log_path", type=Path, help="Prompt-injection decision JSONL path.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("output/prompt_injection_error_analysis/latest"),
        help="Directory for Markdown and JSON summaries.",
    )
    parser.add_argument("--top", type=int, default=25, help="Rows per summary section.")
    return parser


def load_records(path: Path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def mine_errors(records):
    totals = Counter()
    false_positives = []
    false_negatives = []
    action_mismatches = []

    for record in records:
        ground_truth = record.get("ground_truth", {})
        prediction = record.get("prediction", {})
        actual = bool(ground_truth.get("is_injection"))
        predicted = bool(prediction.get("is_injection"))
        expected_action = ground_truth.get("expected_action")
        predicted_action = prediction.get("action")

        if predicted and actual:
            totals["tp"] += 1
        elif predicted and not actual:
            totals["fp"] += 1
            false_positives.append(error_item(record))
        elif not predicted and not actual:
            totals["tn"] += 1
        else:
            totals["fn"] += 1
            false_negatives.append(error_item(record))

        if expected_action is not None:
            totals["action_total"] += 1
            if predicted_action == expected_action:
                totals["action_correct"] += 1
            else:
                totals["action_mismatch"] += 1
                action_mismatches.append(error_item(record))

    return {
        "records": len(records),
        "totals": dict(totals),
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "action_mismatches": action_mismatches,
    }


def error_item(record):
    ground_truth = record.get("ground_truth", {})
    prediction = record.get("prediction", {})
    return {
        "input_id": record.get("input_id"),
        "source": record.get("source"),
        "language": record.get("language"),
        "category": record.get("category"),
        "source_text": record.get("source_text"),
        "label": ground_truth.get("label"),
        "is_injection": ground_truth.get("is_injection"),
        "expected_action": ground_truth.get("expected_action"),
        "predicted_is_injection": prediction.get("is_injection"),
        "predicted_action": prediction.get("action"),
        "score": prediction.get("score"),
        "matched_rules": prediction.get("matched_rules", []),
        "categories": prediction.get("categories", []),
        "evidence": prediction.get("evidence", []),
    }


def top_counts(items, key):
    counter = Counter()
    for item in items:
        value = key(item)
        if isinstance(value, list):
            if value:
                counter.update(value)
            else:
                counter["none"] += 1
        else:
            counter[value if value is not None else "none"] += 1
    return counter.most_common()


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


def render_text(item):
    text = item.get("source_text")
    if text is None:
        return ""
    return text.replace("\n", " ")[:240]


def write_markdown(path: Path, summary, *, top: int):
    fps = summary["false_positives"]
    fns = summary["false_negatives"]
    action_mismatches = summary["action_mismatches"]
    totals = summary["totals"]

    lines = [
        "# Prompt Injection Error Mining Report",
        "",
        f"Records: {summary['records']}",
        "",
        "## Totals",
        "",
        markdown_table(
            ["tp", "fp", "tn", "fn", "action_total", "action_correct", "action_mismatch"],
            [
                [
                    totals.get("tp", 0),
                    totals.get("fp", 0),
                    totals.get("tn", 0),
                    totals.get("fn", 0),
                    totals.get("action_total", 0),
                    totals.get("action_correct", 0),
                    totals.get("action_mismatch", 0),
                ]
            ],
        ),
        "",
        "## False Positives by Matched Rule",
        "",
        markdown_table(["rule", "count"], top_counts(fps, lambda item: item["matched_rules"])[:top]),
        "",
        "## False Positives by Category",
        "",
        markdown_table(["category", "count"], top_counts(fps, lambda item: item["categories"])[:top]),
        "",
        "## False Negatives by Ground Truth Category",
        "",
        markdown_table(["category", "count"], top_counts(fns, lambda item: item["category"])[:top]),
        "",
        "## Action Mismatches",
        "",
        markdown_table(
            ["input_id", "expected", "predicted", "score", "text"],
            [
                [
                    item["input_id"],
                    item["expected_action"],
                    item["predicted_action"],
                    item["score"],
                    render_text(item),
                ]
                for item in action_mismatches[:top]
            ],
        ),
        "",
        "## False Positive Examples",
        "",
    ]

    for item in fps[:top]:
        lines.extend(
            [
                f"- `{item['input_id']}` score `{item['score']}` action `{item['predicted_action']}` rules `{', '.join(item['matched_rules']) or 'none'}`",
                f"  Text: {render_text(item)}",
            ]
        )

    lines.extend(["", "## False Negative Examples", ""])
    for item in fns[:top]:
        lines.extend(
            [
                f"- `{item['input_id']}` expected `{item['expected_action']}` category `{item['category']}`",
                f"  Text: {render_text(item)}",
            ]
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    args = create_arg_parser().parse_args(argv)
    records = load_records(args.log_path)
    summary = mine_errors(records)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "summary.json", summary)
    write_markdown(args.out_dir / "summary.md", summary, top=args.top)
    print(json.dumps({"records": summary["records"], "totals": summary["totals"]}, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    main()
