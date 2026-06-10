from abc import ABC


class BaseDataset(ABC):
    """A PII evaluation dataset behind a uniform interface.

    Each dataset declares where it lives, its column schema, and — crucially —
    its own ``label_to_presidio`` mapping, because every dataset ships a
    different label taxonomy. Combining datasets is then just instantiating
    several and concatenating their loaded frames; the evaluator reads each
    dataset's mapping rather than relying on one global dict.

    Subclasses set the class attributes below. Override :meth:`load` only when a
    source needs handling the generic Hugging Face loader cannot express.

    Every dataset should be documented in ``docs/datasets/<name>.md`` (what it
    is, columns, span format, label taxonomy, and the mismatch vs our Presidio
    entity types).
    """

    # Registry key (short, snake_case).
    name: str = ""
    # Hugging Face repo id (or other source identifier).
    hf_name: str = ""
    # One-line human-readable description.
    description: str = ""
    # ISO language code of the text.
    language: str = "vi"
    # Whether the source is private and needs an HF token (from .env HF_TOKEN).
    requires_token: bool = False
    # Column holding the raw text. If absent, "text" is tried as a fallback.
    text_column: str = "source_text"
    # Column holding ground-truth spans (list of {start, end, label, ...}).
    mask_column: str = "privacy_mask"
    # Canonical label -> Presidio entity-type mapping for THIS dataset.
    # Labels not present here are out of scope and dropped by the evaluator.
    label_to_presidio: dict = {}

    @property
    def presidio_types(self) -> set:
        """Distinct Presidio entity types this dataset can be evaluated against."""
        return set(self.label_to_presidio.values())

    def load(self, split: str = "train", limit: int = None, random_state: int = 42):
        """Load the dataset into a normalized pandas DataFrame.

        Guarantees the columns the evaluator depends on: ``source_text``,
        ``privacy_mask`` (a list of span dicts), ``split``, and ``input_id``.
        Any extra source columns are passed through untouched.
        """
        import pandas as pd
        from datasets import load_dataset

        from src.pipeline.Utils import load_hf_token, normalize_privacy_mask

        token = load_hf_token() if self.requires_token else None
        dataset = load_dataset(self.hf_name, token=token)
        available = list(dataset.keys())

        if split == "all":
            selected = available
        else:
            mapped = split
            if split in {"val", "validation"} and "validation" in dataset:
                mapped = "validation"
            elif split in {"train_main", "train_val"}:
                mapped = "train"
            if mapped not in dataset:
                raise ValueError(
                    f"{self.name}: split {split!r} not available. Available: {available}"
                )
            selected = [mapped]

        frames = []
        for sp in selected:
            split_df = dataset[sp].to_pandas()
            if split in {"train_main", "train_val"} and sp == "train":
                from src.pipeline.Utils import split_train_validation_frame

                split_df = split_train_validation_frame(
                    split_df,
                    split=split,
                    random_state=random_state,
                )
            if limit is not None and len(split_df) > limit:
                split_df = split_df.sample(n=limit, random_state=random_state)
            split_df["split"] = split if split in {"train_main", "train_val"} else sp
            frames.append(split_df)

        df = pd.concat(frames, ignore_index=True)

        if self.text_column in df.columns and "source_text" not in df.columns:
            df["source_text"] = df[self.text_column]
        if "source_text" not in df.columns and "text" in df.columns:
            df["source_text"] = df["text"]
        if "source_text" not in df.columns:
            raise ValueError(
                f"{self.name}: text column {self.text_column!r} not found."
            )

        if self.mask_column not in df.columns:
            raise ValueError(
                f"{self.name}: mask column {self.mask_column!r} not found."
            )
        if self.mask_column != "privacy_mask":
            df["privacy_mask"] = df[self.mask_column]
        df["privacy_mask"] = df["privacy_mask"].apply(normalize_privacy_mask)

        if "input_id" not in df.columns:
            df["input_id"] = [
                f"{self.name}:{sp}:{i}" for i, sp in enumerate(df["split"].tolist())
            ]
        return df

    def unmapped_labels(self, df) -> dict:
        """Labels present in ``df`` but not in this dataset's mapping.

        These ground-truth spans are dropped during mapped-type evaluation, so
        this is the practical "what are we ignoring" view for a loaded frame.
        """
        from collections import Counter

        counts = Counter()
        for spans in df["privacy_mask"]:
            for span in spans:
                label = span.get("label")
                if label not in self.label_to_presidio:
                    counts[label] += 1
        return dict(counts)
