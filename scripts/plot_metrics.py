import json
import os
import numpy as np
import matplotlib.pyplot as plt

def main():
    # Load metrics
    with open("results/metrics.json", "r") as f:
        data = json.load(f)

    pipelines = [
        "regex_only",
        "regex_recall",
        "underthesea_ner",
        "underthesea_regex",
        "underthesea_regex_recall"
    ]

    # Find all unique entities
    entities = set()
    for p in pipelines:
        if p in data and "per_entity" in data[p]:
            entities.update(data[p]["per_entity"].keys())
    
    entities = sorted(list(entities))
    metrics = ["precision", "recall", "f1"]

    os.makedirs("plot", exist_ok=True)

    x = np.arange(len(entities))  # the label locations
    width = 0.15  # the width of the bars

    for metric in metrics:
        fig, ax = plt.subplots(figsize=(14, 8))

        for i, pipeline in enumerate(pipelines):
            pipeline_data = data.get(pipeline, {}).get("per_entity", {})
            values = [pipeline_data.get(ent, {}).get(metric, 0) for ent in entities]
            
            # offset the bars
            offset = width * i - (width * len(pipelines) / 2) + width / 2
            bars = ax.bar(x + offset, values, width, label=pipeline)
            
            # Add labels on top of bars
            ax.bar_label(bars, fmt='%.2f', padding=3, rotation=90, fontsize=8)

        ax.set_ylabel(metric.capitalize(), fontsize=12)
        ax.set_title(f'Per-Entity {metric.capitalize()} Comparison', fontsize=14)
        ax.set_xticks(x)
        ax.set_xticklabels(entities, rotation=45, ha="right", fontsize=10)
        
        # Legend with some columns to make it wider rather than taller, reducing overlap
        ax.legend(title='Pipelines', loc='upper right', ncol=2)
        
        # Raise ylim so the legend and the bar numbers do not cover the bars
        ax.set_ylim(0, 1.35) 
        
        ax.grid(axis='y', linestyle='--', alpha=0.7)

        fig.tight_layout()
        output_path = f"plot/per_entity_{metric}.png"
        plt.savefig(output_path, dpi=300)
        print(f"Saved {output_path}")
        plt.close(fig)

if __name__ == "__main__":
    main()
