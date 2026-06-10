from src.pipeline.Datasets.variants import HoangHaViePiiDataset, PiiMasking95kDataset


DATASET_REGISTRY = {
    "hoangha_vie_pii": HoangHaViePiiDataset,
    "pii_masking_95k": PiiMasking95kDataset,
}


def list_dataset_names():
    return sorted(DATASET_REGISTRY)


def get_dataset_class(name: str):
    try:
        return DATASET_REGISTRY[name]
    except KeyError as exc:
        available = ", ".join(list_dataset_names())
        raise ValueError(
            f"Unknown dataset {name!r}. Available datasets: {available}"
        ) from exc


def get_dataset(name: str, **kwargs):
    return get_dataset_class(name)(**kwargs)
