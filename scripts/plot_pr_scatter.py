import json
import os
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors

def main():
    with open("results/metrics.json", "r") as f:
        data = json.load(f)

    # Maintain a logical order of pipelines to show the "progression"
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

    os.makedirs("plot", exist_ok=True)

    fig, ax = plt.subplots(figsize=(12, 10))

    # Define a distinct color for each entity
    colors = list(mcolors.TABLEAU_COLORS.values())
    
    # Define markers for pipelines to differentiate them easily
    markers = ['o', 's', '^', 'D', 'v']

    for i, entity in enumerate(entities):
        color = colors[i % len(colors)]
        
        entity_precisions = []
        entity_recalls = []
        valid_pipelines_for_entity = []
        valid_markers = []

        for j, pipeline in enumerate(pipelines):
            metrics = data.get(pipeline, {}).get("per_entity", {}).get(entity)
            if metrics:
                entity_precisions.append(metrics.get("precision", 0))
                entity_recalls.append(metrics.get("recall", 0))
                valid_pipelines_for_entity.append(pipeline)
                valid_markers.append(markers[j])

        # Plot the trajectory line
        ax.plot(entity_recalls, entity_precisions, color=color, alpha=0.4, linestyle='-', zorder=1)
        
        # Plot the points
        for r, p, m, pipe in zip(entity_recalls, entity_precisions, valid_markers, valid_pipelines_for_entity):
            ax.scatter(r, p, color=color, marker=m, s=100, zorder=2, 
                       label=entity if pipe == pipelines[0] else "") # Only label the entity once

    ax.set_xlabel('Recall', fontsize=12)
    ax.set_ylabel('Precision', fontsize=12)
    ax.set_title('Precision vs. Recall Trajectory per Entity', fontsize=14)
    ax.set_xlim(0, 1.05)
    ax.set_ylim(0, 1.05)
    ax.grid(True, linestyle='--', alpha=0.7)

    # Create a custom legend for Entities
    handles, labels = ax.get_legend_handles_labels()
    entity_legend = ax.legend(handles, labels, title="Entities", loc="lower left", bbox_to_anchor=(1.02, 0))

    # Create a secondary legend for Pipelines
    import matplotlib.lines as mlines
    pipeline_handles = [mlines.Line2D([], [], color='gray', marker=markers[i], linestyle='None',
                                      markersize=10, label=pipe) for i, pipe in enumerate(pipelines)]
    ax.add_artist(entity_legend) # Add back the first legend
    ax.legend(handles=pipeline_handles, title="Pipelines", loc="upper left", bbox_to_anchor=(1.02, 1))

    fig.tight_layout()
    output_path = "plot/precision_recall_scatter.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"Saved {output_path}")
    plt.close(fig)

if __name__ == "__main__":
    main()
