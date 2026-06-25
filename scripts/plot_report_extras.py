"""Generate additional figures for the writeup.

Reads on-disk metrics (results/metrics.json for PII; output/safety_v0/** for PI)
and writes PNGs into writeup/images/. Reuses the data the writeup cites
directly, so the figures stay in sync with the report tables.

Usage:
    PYTHONPATH=. python scripts/plot_report_extras.py
"""
import json
import os
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REPO_ROOT = PROJECT_ROOT
METRICS_PATH = REPO_ROOT / "results" / "metrics.json"
PII_PROFILE_PATH = REPO_ROOT / "output" / "dataset_profiles" / "pii_masking_95k" / "all" / "stats.json"
SAFETY_V0 = REPO_ROOT / "output" / "safety_v0"
OUT_DIR = REPO_ROOT / "writeup" / "images"


# --- Color palette used by every plot in this file (matches the existing
# per-entity plots so the new figures feel like part of the same set). ---
PALETTE = {
    "primary": "#1f77b4",
    "secondary": "#ff7f0e",
    "tertiary": "#2ca02c",
    "danger": "#d62728",
    "muted": "#7f7f7f",
    "soft_blue": "#9bc4e2",
    "soft_orange": "#ffbb78",
    "soft_green": "#98df8a",
    "soft_red": "#ff9896",
    "rule": "#9467bd",
    "nb": "#1f77b4",
    "good": "#2ca02c",
    "bad": "#d62728",
}


def _save(fig, name, dpi=300):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / name
    fig.savefig(out, dpi=dpi, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out}")


# ---------------------------------------------------------------------------
# PII figures
# ---------------------------------------------------------------------------

def plot_pii_entity_distribution():
    """Horizontal bar of span counts per target Presidio entity type, from
    the on-disk pii-masking-95k profile (95,122 rows, full corpus)."""
    with open(PII_PROFILE_PATH) as f:
        stats = json.load(f)
    counts = stats["presidio_type_counts"]
    entities = sorted(counts.keys(), key=lambda k: counts[k])
    values = [counts[e] for e in entities]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    bars = ax.barh(entities, values, color=PALETTE["primary"], edgecolor="white")
    for bar, v in zip(bars, values):
        ax.text(v, bar.get_y() + bar.get_height() / 2,
                f" {v:,}", va="center", fontsize=9, color="#222")
    ax.set_xscale("log")
    ax.set_xlabel("Span count (log scale)", fontsize=11)
    ax.set_title("PII span distribution in pii-masking-95k (95,122 docs)",
                 fontsize=13, pad=12)
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    _save(fig, "pii_entity_distribution.png")


def plot_pii_recall_gap():
    """For the best pipeline (regex_recall), show 1 - recall per entity to
    visualise how much PII is being missed. Sorted descending so the worst
    gaps appear at the top."""
    with open(METRICS_PATH) as f:
        data = json.load(f)
    pipeline = "regex_recall"
    per_entity = data[pipeline]["per_entity"]
    rows = sorted(
        ((ent, m["recall"], m["precision"], m["tp"], m["fn"])
         for ent, m in per_entity.items()),
        key=lambda r: (1 - r[1]),
        reverse=True,
    )
    entities = [r[0] for r in rows]
    recall = [r[1] for r in rows]
    gap = [1 - r for r in recall]
    tp = [r[3] for r in rows]
    fn = [r[4] for r in rows]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    bars = ax.barh(entities, gap, color=PALETTE["danger"], edgecolor="white",
                   alpha=0.85, label="Missed (1 - recall)")
    for bar, g, t, f_ in zip(bars, gap, tp, fn):
        ax.text(g + 0.01, bar.get_y() + bar.get_height() / 2,
                f" {g*100:.1f}%  ({f_:,} FN / {t:,} TP)",
                va="center", fontsize=9, color="#222")
    ax.set_xlim(0, max(0.6, max(gap) + 0.18))
    ax.set_xlabel("Missed share of ground-truth spans (1 - recall)", fontsize=11)
    ax.set_title(f"Recall gap by entity for `{pipeline}` (validation, 500 rows)",
                 fontsize=13, pad=12)
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    _save(fig, "pii_recall_gap.png")


def plot_pii_overall_compare():
    """Grouped bars of overall P/R/F1 for every pipeline on the 500-row
    validation slice. Sorts columns to match the table in the report
    (regex_recall, underthesea_ner, underthesea_regex,
    underthesea_regex_recall)."""
    with open(METRICS_PATH) as f:
        data = json.load(f)
    pipelines = [
        "regex_only",
        "regex_recall",
        "underthesea_ner",
        "underthesea_regex",
        "underthesea_regex_recall",
    ]
    short = {
        "regex_only": "regex_only",
        "regex_recall": "regex_recall",
        "underthesea_ner": "uts_ner",
        "underthesea_regex": "uts_regex",
        "underthesea_regex_recall": "uts_regex_recall",
    }
    metrics = ["precision", "recall", "f1"]
    x = np.arange(len(pipelines))
    width = 0.26

    fig, ax = plt.subplots(figsize=(10, 5.5))
    colors = [PALETTE["primary"], PALETTE["secondary"], PALETTE["tertiary"]]
    for i, metric in enumerate(metrics):
        values = [data[p]["overall"][metric] for p in pipelines]
        bars = ax.bar(x + (i - 1) * width, values, width, label=metric.capitalize(),
                      color=colors[i], edgecolor="white")
        ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=8)
    ax.set_xticks(x)
    ax.set_xticklabels([short[p] for p in pipelines], fontsize=10)
    ax.set_ylim(0, 1.18)
    ax.set_ylabel("Score", fontsize=11)
    ax.set_title("Overall P/R/F1 across pipelines (validation, 500 rows)",
                 fontsize=13, pad=12)
    ax.grid(axis="y", linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", ncol=3, frameon=False)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    _save(fig, "pii_overall_compare.png")


# ---------------------------------------------------------------------------
# Prompt-injection figures
# ---------------------------------------------------------------------------

def _load_safety_v0(name):
    with open(SAFETY_V0 / name) as f:
        return json.load(f)


def plot_pi_confusion_in_domain():
    """Side-by-side confusion matrices for rule-based vs char n-gram NB on
    the balanced pi_vi_eval (148 rows)."""
    in_domain = _load_safety_v0("pi_vi_eval/in_domain_results.json")
    runs = {r["detector"]: r for r in in_domain["runs"]}
    rule = runs["rule_based_prompt_injection"]
    nb = runs["char_ngram_prompt_injection"]

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5))
    for ax, run, title, cmap in [
        (axes[0], rule, "Rule-based (memorised)", "Greens"),
        (axes[1], nb, "Char n-gram NB (LOO)", "Blues"),
    ]:
        cm = np.array([[run["tn"], run["fp"]],
                       [run["fn"], run["tp"]]])
        im = ax.imshow(cm, cmap=cmap, vmin=0)
        ax.set_xticks([0, 1])
        ax.set_yticks([0, 1])
        ax.set_xticklabels(["Benign", "Attack"], fontsize=10)
        ax.set_yticklabels(["Benign", "Attack"], fontsize=10)
        ax.set_xlabel("Predicted", fontsize=10)
        ax.set_ylabel("Actual", fontsize=10)
        for i in range(2):
            for j in range(2):
                ax.text(j, i, f"{cm[i, j]}", ha="center", va="center",
                        color="white" if cm[i, j] > cm.max() / 2 else "#222",
                        fontsize=14, fontweight="bold")
        ax.set_title(f"{title}\nF1 = {run['f1']:.3f}", fontsize=11, pad=10)
    fig.suptitle("Confusion matrices on pi_vi_eval (148 rows, balanced)",
                 fontsize=13, y=1.02)
    fig.tight_layout()
    _save(fig, "pi_confusion_in_domain.png")


def plot_pi_heldout_f1():
    """F1 bar chart for the four held-out runs on deepset_vi (rule + 3 NB
    variants). Visually answers "can the data be learned?"."""
    held = _load_safety_v0("deepset_vi/heldout_results.json")
    labels = []
    f1s = []
    colors = []
    for r in held["runs"]:
        if r["detector"] == "rule_based_prompt_injection":
            labels.append("Rule-based\n(authored)")
            colors.append(PALETTE["rule"])
        else:
            train = r["train"].replace("external:", "").replace("leave-one-out (in-domain)", "LOO (in-domain)")
            labels.append(f"NB\n{train}")
            colors.append(PALETTE["nb"])
        f1s.append(r["f1"])

    fig, ax = plt.subplots(figsize=(9, 5.5))
    bars = ax.bar(range(len(labels)), f1s, color=colors, edgecolor="white")
    for bar, f, run in zip(bars, f1s, held["runs"]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.015,
                f"F1 = {f:.3f}\nP={run['precision']:.2f}, R={run['recall']:.2f}",
                ha="center", va="bottom", fontsize=9)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("F1-score", fontsize=11)
    ax.set_title("Held-out generalization on deepset_vi (351 rows, 154 attacks)",
                 fontsize=13, pad=12)
    ax.grid(axis="y", linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)

    rule_patch = mpatches.Patch(color=PALETTE["rule"], label="Rule-based")
    nb_patch = mpatches.Patch(color=PALETTE["nb"], label="Char n-gram NB")
    ax.legend(handles=[rule_patch, nb_patch], loc="upper left", frameon=False)
    fig.tight_layout()
    _save(fig, "pi_heldout_f1.png")


def plot_pi_recall_growth():
    """Line chart of recall on llmail_vi (500 attacks) as the training pool
    grows. Demonstrates the data-centric lever described in the report."""
    transfer = _load_safety_v0("llmail_vi/transfer_results.json")
    rule = next(r for r in transfer["runs"] if r["detector"].startswith("rule"))
    nb_runs = [r for r in transfer["runs"] if r["detector"].startswith("char")]

    nb_order = ["pi_vi_eval", "deepset_vi", "pi_vi_eval,local_vietnamese_seed,local_vietnamese_app_seed,local_vietnamese_mentor_seed,deepset_vi"]
    nb_runs_sorted = []
    for key in nb_order:
        for r in nb_runs:
            if r["train"].endswith(key):
                nb_runs_sorted.append(r)
                break
    labels = ["pi_vi_eval", "deepset_vi", "pi_vi_eval + local + deepset_vi"]
    recall = [r["recall"] for r in nb_runs_sorted]

    fig, ax = plt.subplots(figsize=(9, 5.5))
    ax.plot(range(len(labels)), recall, "-o", color=PALETTE["nb"],
            markersize=10, linewidth=2.2, label="Char n-gram NB")
    for x, y in zip(range(len(labels)), recall):
        ax.text(x, y + 0.025, f"{y:.3f}", ha="center", fontsize=10,
                color=PALETTE["nb"], fontweight="bold")
    ax.axhline(rule["recall"], color=PALETTE["rule"], linestyle="--",
               linewidth=2, label=f"Rule-based (recall = {rule['recall']:.3f})")

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(0, 0.55)
    ax.set_ylabel("Recall on llmail_vi (500 attacks)", fontsize=11)
    ax.set_title("Translation-augmentation lever: more diverse Vietnamese data "
                 "leads to higher recall",
                 fontsize=13, pad=12)
    ax.grid(axis="y", linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", frameon=False)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    _save(fig, "pi_recall_growth.png")


def plot_pi_threshold_sweep():
    """Two-bar comparison of the Naive Bayes default (0.5) vs best-F1 (0.999)
    threshold on pi_vi_eval. Shows the small but bounded gain from threshold
    tuning described in the report."""
    sweep = _load_safety_v0("pi_vi_eval/nb_threshold_sweep.json")
    rows = [
        ("Default\n(threshold = 0.5)", sweep["default_threshold"], PALETTE["soft_blue"]),
        ("Best-F1\n(threshold = 0.999)", sweep["best_f1_threshold"], PALETTE["soft_orange"]),
    ]
    metrics = ["precision", "recall", "f1"]
    x = np.arange(len(rows))
    width = 0.24
    colors = [PALETTE["primary"], PALETTE["secondary"], PALETTE["tertiary"]]

    fig, ax = plt.subplots(figsize=(8.5, 5))
    for i, metric in enumerate(metrics):
        values = [r[1][metric] for r in rows]
        bars = ax.bar(x + (i - 1) * width, values, width,
                      color=colors[i], label=metric.capitalize(),
                      edgecolor="white")
        ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=9)
    ax.set_xticks(x)
    ax.set_xticklabels([r[0] for r in rows], fontsize=10)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("Score", fontsize=11)
    ax.set_title("NB threshold sweep on pi_vi_eval (148 rows, LOO)",
                 fontsize=13, pad=12)
    ax.grid(axis="y", linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)
    ax.legend(loc="upper left", ncol=3, frameon=False)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    _save(fig, "pi_threshold_sweep.png")


def plot_pi_fpr_summary():
    """Horizontal bars summarising false-positive count for each detector
    on the real benign side: 197 deepset_vi benigns + 28 ViHSD negatives
    inside pi_vi_eval. Reads the same data the heldout and in_domain JSONs
    cite, so the figure matches the report narrative."""
    in_domain = _load_safety_v0("pi_vi_eval/in_domain_results.json")
    held = _load_safety_v0("deepset_vi/heldout_results.json")

    def fp_count(runs, detector_substring):
        for r in runs:
            if detector_substring in r["detector"]:
                return r.get("fp", 0)
        return 0

    nb_in = next(r for r in in_domain["runs"] if r["detector"].startswith("char"))
    nb_held = next(
        r for r in held["runs"]
        if r["detector"].startswith("char") and r["train"].endswith("pi_vi_eval")
    )

    rows = [
        ("Rule-based\npi_vi_eval benign (74)", fp_count(in_domain["runs"], "rule"), PALETTE["rule"]),
        ("Rule-based\ndeepset_vi benign (197)", fp_count(held["runs"], "rule"), PALETTE["rule"]),
        ("Char n-gram NB\npi_vi_eval benign (74) LOO", nb_in["fp"], PALETTE["nb"]),
        ("Char n-gram NB\ndeepset_vi benign (197) ext. train", nb_held["fp"], PALETTE["nb"]),
    ]
    labels = [r[0] for r in rows]
    fps = [r[1] for r in rows]
    colors = [r[2] for r in rows]

    fig, ax = plt.subplots(figsize=(9, 5))
    bars = ax.barh(labels, fps, color=colors, edgecolor="white")
    for bar, fp in zip(bars, fps):
        ax.text(fp + 0.5, bar.get_y() + bar.get_height() / 2,
                f"  {int(fp)} FP", va="center", fontsize=10, color="#222")
    ax.set_xlim(0, max(fps) * 1.25 + 5)
    ax.set_xlabel("False positives on real Vietnamese benigns", fontsize=11)
    ax.set_title("False-positive footprint of the two detectors",
                 fontsize=13, pad=12)
    ax.grid(axis="x", linestyle="--", alpha=0.5)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    rule_patch = mpatches.Patch(color=PALETTE["rule"], label="Rule-based")
    nb_patch = mpatches.Patch(color=PALETTE["nb"], label="Char n-gram NB")
    ax.legend(handles=[rule_patch, nb_patch], loc="lower right", frameon=False)
    fig.tight_layout()
    _save(fig, "pi_fpr_summary.png")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plot_pii_entity_distribution()
    plot_pii_recall_gap()
    plot_pii_overall_compare()
    plot_pi_confusion_in_domain()
    plot_pi_heldout_f1()
    plot_pi_recall_growth()
    plot_pi_threshold_sweep()
    plot_pi_fpr_summary()
    print(f"\nAll figures written to {OUT_DIR}")


if __name__ == "__main__":
    main()
