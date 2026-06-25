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


def resolve_dataset_key(name: str) -> str:
    """Return the registered short key for ``name``.

    Accepts the registry key (``pii_masking_95k``) or the Hugging Face repo id
    (``nguyenlamtung/pii-masking-95k-preencoded``) used by the legacy
    ``load_evaluation_dataset`` default. Lets callers pass either form.
    """
    if name in DATASET_REGISTRY:
        return name
    for key, dataset_cls in DATASET_REGISTRY.items():
        if dataset_cls.hf_name == name:
            return key
    return name
