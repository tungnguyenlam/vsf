"""Descriptive statistics for a loaded PII dataset frame.

Pure, dependency-light functions (only the standard library + the dataframe the
caller already loaded). Plotting and file I/O live in
``scripts/profile_dataset.py`` so this module stays importable without
matplotlib and is easy to unit test or reuse from a notebook.

A "dataset" here means a :class:`~src.pipeline.Datasets.base.BaseDataset` plus a
normalized frame from ``dataset.load(...)`` — i.e. it has ``source_text`` and
``privacy_mask`` (a list of ``{start, end, label, ...}`` span dicts). The
``label_to_presidio`` mapping is read from the dataset so every number here is
reported the same way the evaluator sees it (mapped vs dropped).
"""

from collections import Counter


def _percentile(sorted_values, fraction):
    """Nearest-rank percentile of an already-sorted, non-empty list."""
    if not sorted_values:
        return 0
    index = max(0, min(len(sorted_values) - 1, round(fraction * (len(sorted_values) - 1))))
    return sorted_values[index]


def _number_summary(values):
    """Min/median/mean/max/p90/p99/total for a list of numbers."""
    if not values:
        return {"count": 0, "min": 0, "median": 0, "mean": 0.0, "max": 0, "p90": 0, "p99": 0, "total": 0}
    ordered = sorted(values)
    total = sum(ordered)
    return {
        "count": len(ordered),
        "min": ordered[0],
        "median": _percentile(ordered, 0.5),
        "mean": round(total / len(ordered), 2),
        "max": ordered[-1],
        "p90": _percentile(ordered, 0.90),
        "p99": _percentile(ordered, 0.99),
        "total": total,
    }


def label_counts(df):
    """Counter of every native span label across the frame."""
    counts = Counter()
    for spans in df["privacy_mask"]:
        for span in spans:
            counts[span.get("label")] += 1
    return counts


def presidio_type_counts(df, label_to_presidio):
    """Counter of mapped Presidio entity types (dropped labels excluded)."""
    counts = Counter()
    for spans in df["privacy_mask"]:
        for span in spans:
            mapped = label_to_presidio.get(span.get("label"))
            if mapped:
                counts[mapped] += 1
    return counts


def label_to_type_breakdown(label_to_presidio, native_counts):
    """For each Presidio type, the native labels feeding it and their counts.

    Includes mapped labels with zero observed occurrences so coverage gaps (a
    label that is mapped but never appears) are visible.
    """
    breakdown = {}
    for label, presidio_type in label_to_presidio.items():
        bucket = breakdown.setdefault(presidio_type, {})
        bucket[label] = native_counts.get(label, 0)
    return breakdown


def compute_dataset_stats(df, dataset):
    """Return a JSON-serializable statistics report for ``df``.

    ``dataset`` supplies ``name`` and ``label_to_presidio``. The frame is the
    output of ``dataset.load(...)``.
    """
    label_to_presidio = dataset.label_to_presidio
    native_counts = label_counts(df)
    type_counts = presidio_type_counts(df, label_to_presidio)

    spans_per_row = [len(spans) for spans in df["privacy_mask"]]
    mapped_per_row = [
        sum(1 for span in spans if label_to_presidio.get(span.get("label"))) for spans in df["privacy_mask"]
    ]
    text_lengths = [len(text) for text in df["source_text"]]

    total_spans = sum(native_counts.values())
    mapped_spans = sum(type_counts.values())
    unmapped = {label: count for label, count in native_counts.items() if label not in label_to_presidio}
    unmapped_total = sum(unmapped.values())

    mapped_labels_present = sorted(
        label for label in label_to_presidio if native_counts.get(label, 0) > 0
    )
    mapped_labels_absent = sorted(
        label for label in label_to_presidio if native_counts.get(label, 0) == 0
    )

    return {
        "dataset": dataset.name,
        "rows": len(df),
        "splits_present": sorted(set(df["split"])) if "split" in df.columns else [],
        "spans": {
            "total": total_spans,
            "mapped": mapped_spans,
            "unmapped": unmapped_total,
            "mapped_share": round(mapped_spans / total_spans, 4) if total_spans else 0.0,
        },
        "rows_without_mapped_span": sum(1 for n in mapped_per_row if n == 0),
        "spans_per_row": _number_summary(spans_per_row),
        "mapped_spans_per_row": _number_summary(mapped_per_row),
        "text_length_chars": _number_summary(text_lengths),
        "distinct_native_labels": len(native_counts),
        "presidio_type_counts": dict(type_counts.most_common()),
        "label_to_type_breakdown": label_to_type_breakdown(label_to_presidio, native_counts),
        "mapped_labels_present": mapped_labels_present,
        "mapped_labels_absent": mapped_labels_absent,
        "native_label_counts": dict(native_counts.most_common()),
        "unmapped_label_counts": dict(Counter(unmapped).most_common()),
    }
