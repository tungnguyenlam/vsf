def with_prefix(prefix: str, metrics: dict) -> dict:
    """Return metrics dictionary with keys prefixed by prefix."""
    return {f"{prefix}_{key}": value for key, value in metrics.items()}

def display_evaluation_results(overall_df, per_entity_df=None):
    """Display evaluation summary DataFrames with styled metrics cleanly in Jupyter Notebooks."""
    from IPython.display import display, HTML

    overall_df_copy = overall_df.copy()
    float_cols_overall = [col for col in overall_df_copy.columns if overall_df_copy[col].dtype in ['float64', 'float32']]
    overall_df_copy[float_cols_overall] = overall_df_copy[float_cols_overall].round(4)

    per_entity_df_copy = None
    if per_entity_df is not None and not per_entity_df.empty:
        per_entity_df_copy = per_entity_df.copy()
        float_cols_entity = [col for col in per_entity_df_copy.columns if per_entity_df_copy[col].dtype in ['float64', 'float32']]
        per_entity_df_copy[float_cols_entity] = per_entity_df_copy[float_cols_entity].round(4)

    display(HTML("<h2>Evaluation Summary</h2>"))
    display(HTML("<h3>Overall Performance Metrics</h3>"))
    display(overall_df_copy)

    if per_entity_df_copy is not None:
        display(HTML("<h3>Detailed Metrics per Entity Type</h3>"))
        display(per_entity_df_copy)
    else:
        display(HTML("<p><em>No mapped entities found for detailed analysis.</em></p>"))

def plot_step_progress(overall_df, figsize=(10, 6)):
    """Plot precision, recall, and F1-score across pipeline steps."""
    import matplotlib.pyplot as plt
    import numpy as np
    
    steps = overall_df["step_name"].tolist()
    
    precision = overall_df["mapped_types_precision"].tolist()
    recall = overall_df["mapped_types_recall"].tolist()
    f1 = overall_df["mapped_types_f1"].tolist()
    
    x = np.arange(len(steps))
    width = 0.25
    
    fig, ax = plt.subplots(figsize=figsize, dpi=120)
    
    color_precision = "#4a90e2" # Blue
    color_recall = "#50e3c2"    # Teal
    color_f1 = "#9013fe"        # Purple
    
    rects1 = ax.bar(x - width, precision, width, label="Precision", color=color_precision, alpha=0.85, edgecolor="#ffffff", linewidth=1)
    rects2 = ax.bar(x, recall, width, label="Recall", color=color_recall, alpha=0.85, edgecolor="#ffffff", linewidth=1)
    rects3 = ax.bar(x + width, f1, width, label="F1-Score", color=color_f1, alpha=0.9, edgecolor="#ffffff", linewidth=1.5)
    
    ax.set_title("PII Masking Pipeline Performance Improvement", fontsize=14, fontweight="bold", pad=20, color="#333333")
    ax.set_xlabel("Pipeline Evolution Stages", fontsize=12, fontweight="semibold", labelpad=10, color="#555555")
    ax.set_ylabel("Metric Value (0.0 - 1.0)", fontsize=12, fontweight="semibold", labelpad=10, color="#555555")
    ax.set_xticks(x)
    ax.set_xticklabels(steps, fontsize=10, fontweight="semibold")
    ax.set_ylim(0, 1.05)
    
    ax.grid(axis='y', linestyle='--', alpha=0.5)
    ax.set_axisbelow(True)
    
    ax.legend(loc="upper left", frameon=True, facecolor="#f8f9fa", edgecolor="#dddddd", fontsize=10)
    
    def autolabel(rects):
        for rect in rects:
            height = rect.get_height()
            ax.annotate(
                f"{height:.2%}",
                xy=(rect.get_x() + rect.get_width() / 2, height),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                va="bottom",
                fontsize=9,
                fontweight="bold",
                color="#444444"
            )
            
    autolabel(rects1)
    autolabel(rects2)
    autolabel(rects3)
    
    plt.tight_layout()
    plt.show()
