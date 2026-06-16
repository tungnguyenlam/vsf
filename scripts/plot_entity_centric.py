import json
import os
import numpy as np
import matplotlib.pyplot as plt

def main():
    with open("results/metrics.json", "r") as f:
        data = json.load(f)

    pipelines = [
        "regex_only",
        "regex_recall",
        "underthesea_ner",
        "underthesea_regex",
        "underthesea_regex_recall"
    ]

    entities = set()
    for p in pipelines:
        if p in data and "per_entity" in data[p]:
            entities.update(data[p]["per_entity"].keys())
    entities = sorted(list(entities))
    metrics = ["precision", "recall", "f1"]

    os.makedirs("plot", exist_ok=True)

    # Determine grid size (e.g., 2 rows, 4 columns for 8 entities)
    n_entities = len(entities)
    cols = 3
    rows = (n_entities + cols - 1) // cols

    fig, axes = plt.subplots(rows, cols, figsize=(18, 6 * rows))
    axes = axes.flatten()

    x = np.arange(len(pipelines))  # the label locations for pipelines
    width = 0.25  # the width of the bars

    for i, entity in enumerate(entities):
        ax = axes[i]
        
        # Extract metrics for this entity across all pipelines
        entity_prec = [data.get(p, {}).get("per_entity", {}).get(entity, {}).get("precision", 0) for p in pipelines]
        entity_rec = [data.get(p, {}).get("per_entity", {}).get(entity, {}).get("recall", 0) for p in pipelines]
        entity_f1 = [data.get(p, {}).get("per_entity", {}).get(entity, {}).get("f1", 0) for p in pipelines]

        # Plot bars for Prec, Rec, F1
        rects1 = ax.bar(x - width, entity_prec, width, label='Precision', color='#1f77b4')
        rects2 = ax.bar(x, entity_rec, width, label='Recall', color='#ff7f0e')
        rects3 = ax.bar(x + width, entity_f1, width, label='F1', color='#2ca02c')

        # Add numbers on top
        ax.bar_label(rects1, fmt='%.2f', padding=3, rotation=90, fontsize=8)
        ax.bar_label(rects2, fmt='%.2f', padding=3, rotation=90, fontsize=8)
        ax.bar_label(rects3, fmt='%.2f', padding=3, rotation=90, fontsize=8)

        ax.set_title(f'Entity: {entity}', fontsize=14, pad=15)
        ax.set_xticks(x)
        # Use short names or rotate heavily
        short_pipelines = [p.replace("underthesea", "uts").replace("regex", "rx") for p in pipelines]
        ax.set_xticklabels(short_pipelines, rotation=30, ha="right", fontsize=9)
        ax.set_ylim(0, 1.35) 
        ax.grid(axis='y', linestyle='--', alpha=0.7)
        
        if i == 0:
            ax.legend(loc='upper right', ncol=3)

    # Hide any unused subplots
    for j in range(i + 1, len(axes)):
        fig.delaxes(axes[j])

    fig.tight_layout()
    output_path = "plot/entity_centric_bars.png"
    plt.savefig(output_path, dpi=300)
    print(f"Saved {output_path}")
    plt.close(fig)

if __name__ == "__main__":
    main()
