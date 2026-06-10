import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from src.pipeline.Datasets.variants import VI_PII_LABEL_TO_PRESIDIO
from src.pipeline.Evaluator import PIIEvaluator


def create_arg_parser():
    parser = argparse.ArgumentParser(
        description="Mine false positives and false negatives from prediction JSONL logs."
    )
    parser.add_argument("log_path", type=Path, help="Prediction JSONL path with source_text included.")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("output/error_analysis/latest"),
        help="Directory for Markdown and JSON summaries.",
    )
    parser.add_argument("--top", type=int, default=25, help="Rows per summary section.")
    parser.add_argument(
        "--context-window",
        type=int,
        default=60,
        help="Characters to include before and after each error span.",
    )
    return parser


def load_records(path: Path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def context_for(text: str, start: int, end: int, window: int):
    return text[max(0, start - window): min(len(text), end + window)]


def mine_errors(records, *, context_window: int):
    evaluator = PIIEvaluator()
    mapped_types = set(VI_PII_LABEL_TO_PRESIDIO.values())
    false_positives = []
    false_negatives = []
    totals = Counter()

    for rec in records:
        text = rec.get("source_text")
        if text is None:
            raise ValueError("source_text is required. Re-run evaluation with --include-source-text.")

        gt_spans = []
        for item in rec.get("ground_truth", []):
            mapped = VI_PII_LABEL_TO_PRESIDIO.get(item.get("label"))
            if mapped:
                gt_spans.append((item["start"], item["end"], mapped, item.get("label")))

        pred_spans = []
        for result in rec.get("results", []):
            entity_type = result.get("entity_type")
            if entity_type in mapped_types:
                pred_spans.append(
                    (
                        result.get("start"),
                        result.get("end"),
                        entity_type,
                        result,
                    )
                )

        matched_gt = set()
        matched_pred = set()
        for pred_index, (pred_start, pred_end, pred_type, _result) in enumerate(pred_spans):
            for gt_index, (gt_start, gt_end, gt_type, _label) in enumerate(gt_spans):
                if gt_index in matched_gt or pred_type != gt_type:
                    continue
                if evaluator.spans_overlap(pred_start, pred_end, gt_start, gt_end):
                    matched_gt.add(gt_index)
                    matched_pred.add(pred_index)
                    break

        totals["tp"] += len(matched_pred)
        totals["fp"] += len(pred_spans) - len(matched_pred)
        totals["fn"] += len(gt_spans) - len(matched_gt)

        for pred_index, (start, end, entity_type, result) in enumerate(pred_spans):
            if pred_index in matched_pred:
                continue
            false_positives.append(
                {
                    "input_id": rec.get("input_id"),
                    "entity_type": entity_type,
                    "text": result.get("text") or text[start:end],
                    "start": start,
                    "end": end,
                    "score": result.get("score"),
                    "recognizer": result.get("recognizer"),
                    "pattern": result.get("pattern"),
                    "context": context_for(text, start, end, context_window),
                }
            )

        for gt_index, (start, end, entity_type, label) in enumerate(gt_spans):
            if gt_index in matched_gt:
                continue
            false_negatives.append(
                {
                    "input_id": rec.get("input_id"),
                    "entity_type": entity_type,
                    "label": label,
                    "text": text[start:end],
                    "start": start,
                    "end": end,
                    "context": context_for(text, start, end, context_window),
                }
            )

    return {
        "records": len(records),
        "totals": dict(totals),
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }


def top_counts(items, key):
    counter = Counter(key(item) for item in items)
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


def write_markdown(path: Path, summary, *, top: int):
    fps = summary["false_positives"]
    fns = summary["false_negatives"]
    totals = summary["totals"]

    lines = [
        "# Prediction Error Mining Report",
        "",
        f"Records: {summary['records']}",
        "",
        "## Totals",
        "",
        markdown_table(
            ["tp", "fp", "fn"],
            [[totals.get("tp", 0), totals.get("fp", 0), totals.get("fn", 0)]],
        ),
        "",
        "## False Positives by Entity",
        "",
        markdown_table(["entity_type", "count"], top_counts(fps, lambda item: item["entity_type"])[:top]),
        "",
        "## False Negatives by Entity",
        "",
        markdown_table(["entity_type", "count"], top_counts(fns, lambda item: item["entity_type"])[:top]),
        "",
        "## False Negatives by Dataset Label",
        "",
        markdown_table(["label", "count"], top_counts(fns, lambda item: item["label"])[:top]),
        "",
        "## False Positives by Recognizer",
        "",
        markdown_table(
            ["recognizer", "count"],
            top_counts(fps, lambda item: item.get("recognizer") or "unknown")[:top],
        ),
        "",
        "## False Positives by Pattern",
        "",
        markdown_table(
            ["pattern", "count"],
            top_counts(fps, lambda item: item.get("pattern") or "unknown")[:top],
        ),
        "",
        "## Frequent False Positive Text",
        "",
        markdown_table(["text", "count"], top_counts(fps, lambda item: item["text"])[:top]),
        "",
        "## Frequent False Negative Text",
        "",
        markdown_table(["text", "count"], top_counts(fns, lambda item: item["text"])[:top]),
        "",
        "## False Positive Examples",
        "",
    ]

    for item in fps[:top]:
        lines.extend(
            [
                f"- `{item['entity_type']}` `{item['text']}` "
                f"via `{item.get('recognizer') or 'unknown'}` / `{item.get('pattern') or 'unknown'}`",
                f"  Context: {item['context']}",
            ]
        )

    lines.extend(["", "## False Negative Examples", ""])
    for item in fns[:top]:
        lines.extend(
            [
                f"- `{item['entity_type']}` `{item['label']}` `{item['text']}`",
                f"  Context: {item['context']}",
            ]
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    args = create_arg_parser().parse_args(argv)
    records = load_records(args.log_path)
    summary = mine_errors(records, context_window=args.context_window)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    write_json(args.out_dir / "summary.json", summary)
    write_markdown(args.out_dir / "summary.md", summary, top=args.top)
    print(json.dumps({
        "records": summary["records"],
        "totals": summary["totals"],
        "out_dir": str(args.out_dir),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
