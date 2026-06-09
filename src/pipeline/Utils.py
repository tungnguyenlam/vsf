def with_prefix(prefix: str, metrics: dict) -> dict:
    """Return metrics dictionary with keys prefixed by prefix."""
    return {f"{prefix}_{key}": value for key, value in metrics.items()}


DEFAULT_DATASET_NAME = "nguyenlamtung/pii-masking-95k-preencoded"


def load_hf_token():
    """Load the nearest .env into the environment and return the HF token.

    The dataset is private, so the Hugging Face token from .env (HF_TOKEN) is
    required to download it. Returns None if no token is configured.
    """
    import os

    try:
        from dotenv import load_dotenv, find_dotenv

        load_dotenv(find_dotenv(usecwd=True))
    except ImportError:
        pass
    return os.environ.get("HF_TOKEN")


def normalize_privacy_mask(value):
    """Return privacy mask data as a list of span dictionaries."""
    import json

    if value is None:
        return []
    if isinstance(value, list):
        return value
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, str):
        if not value:
            return []
        return json.loads(value)
    return list(value)


def load_evaluation_dataset(
    dataset_name: str = DEFAULT_DATASET_NAME,
    split: str = "train",
    limit: int = None,
    random_state: int = 42,
):
    """Load a sampled Vietnamese PII evaluation dataframe."""
    import pandas as pd
    from datasets import load_dataset

    dataset = load_dataset(dataset_name, token=load_hf_token())
    available_splits = list(dataset.keys())

    if split == "all":
        selected_splits = available_splits
    else:
        mapped_split = "validation" if split == "val" and "validation" in dataset else split
        if mapped_split not in dataset:
            raise ValueError(
                f"Split {split!r} is not available. Available splits: {available_splits}"
            )
        selected_splits = [mapped_split]

    frames = []
    for selected_split in selected_splits:
        split_df = dataset[selected_split].to_pandas()
        if limit is not None and len(split_df) > limit:
            split_df = split_df.sample(n=limit, random_state=random_state)
        split_df["split"] = selected_split
        frames.append(split_df)

    df = pd.concat(frames, ignore_index=True)
    if "text" in df.columns and "source_text" not in df.columns:
        df["source_text"] = df["text"]
    if "source_text" not in df.columns:
        raise ValueError("Evaluation dataset must contain a source_text or text column.")
    if "privacy_mask" not in df.columns:
        raise ValueError("Evaluation dataset must contain a privacy_mask column.")

    df["privacy_mask"] = df["privacy_mask"].apply(normalize_privacy_mask)
    if "input_id" not in df.columns:
        df["input_id"] = [
            f"{row['split']}:{index}" for index, row in df[["split"]].iterrows()
        ]
    return df


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
    wrapped_steps = [s.replace(": ", ":\n") for s in steps]
    ax.set_xticklabels(wrapped_steps, fontsize=10, fontweight="semibold")
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


def plot_per_entity_comparison(per_entity_df, entity_types=None, metrics=("precision", "recall", "f1"), steps_order=None, figsize=(14, 8)):
    """Plot metric trends for each entity type across pipeline steps.

    Args:
        per_entity_df: DataFrame with columns ['entity_type', 'step_name', ...metrics...]
        entity_types: Optional list of entity types to plot. Defaults to all found.
        metrics: Iterable of metric names to plot per entity.
        steps_order: Optional list specifying the x-axis order for steps.
        figsize: Figure size.

    Returns:
        Matplotlib figure and axes array.
    """
    import matplotlib.pyplot as plt
    import math

    if per_entity_df is None or per_entity_df.empty:
        raise ValueError("per_entity_df is empty or None")

    df = per_entity_df.copy()
    if steps_order is None:
        # preserve appearance order from the data
        steps_order = list(df["step_name"].unique())

    if entity_types is None:
        entity_types = sorted(df["entity_type"].unique())

    n = len(entity_types)
    cols = 2 if n > 1 else 1
    rows = math.ceil(n / cols)

    # Scale figure height with row count so wrapped x-tick labels of one row
    # don't crowd the title of the row below.
    width, base_height = figsize
    auto_height = max(base_height, 2.6 * rows)
    fig, axes = plt.subplots(rows, cols, figsize=(width, auto_height), squeeze=False)
    axes_2d = axes
    axes = axes.flatten()

    colors = {"precision": "#4a90e2", "recall": "#50e3c2", "f1": "#9013fe"}

    wrapped_steps = [s.replace(": ", ":\n") for s in steps_order]

    for i, ent in enumerate(entity_types):
        ax = axes[i]
        ent_df = df[df["entity_type"] == ent]
        # Ensure step order
        ent_df = ent_df.set_index("step_name").reindex(steps_order).reset_index()

        x = list(range(len(steps_order)))
        for metric in metrics:
            if metric not in ent_df.columns:
                continue
            y = ent_df[metric].fillna(0).tolist()
            ax.plot(x, y, marker="o", label=metric.capitalize(), color=colors.get(metric, None))
        ax.set_title(f"{ent} Metrics", fontsize=12, fontweight="semibold")
        ax.set_xticks(x)
        ax.set_xticklabels(wrapped_steps, fontsize=9)
        ax.set_ylim(0, 1.05)
        ax.grid(axis="y", linestyle="--", alpha=0.5)
        ax.legend(fontsize=9, loc="best")

    # Hide unused subplots
    for j in range(n, len(axes)):
        fig.delaxes(axes[j])

    fig.tight_layout()
    fig.subplots_adjust(hspace=0.75, wspace=0.25)
    plt.show()
    return fig, axes_2d
