from src.pipeline.Datasets.base import BaseDataset


# Canonical label taxonomy -> Presidio entity types for the Vietnamese
# pii-masking-95k dataset. This is the single source of truth for the mapping;
# the evaluator imports it as its default. The dataset ships ~111 distinct
# fine-grained labels; only the 23 below map to our 8 target Presidio types.
# Everything else (currency, money amounts, health, crypto wallets, credentials,
# job/education, vehicle, etc.) is intentionally out of scope and dropped during
# mapped-type evaluation. See docs/datasets/pii-masking-95k.md.
VI_PII_LABEL_TO_PRESIDIO = {
    "HO_VA_TEN": "PERSON",
    "HO": "PERSON",
    "TEN": "PERSON",
    "TEN_DEM": "PERSON",
    "NGAY": "DATE_TIME",
    "NGAY_SINH": "DATE_TIME",
    "THANG": "DATE_TIME",
    "NAM": "DATE_TIME",
    "SO_DIEN_THOAI": "PHONE_NUMBER",
    "DIA_CHI_EMAIL": "EMAIL_ADDRESS",
    "THANH_PHO_TINH": "LOCATION",
    "QUAN_HUYEN": "LOCATION",
    "PHUONG_XA": "LOCATION",
    "DUONG_PHO": "LOCATION",
    "SO_NHA_TOA_NHA": "LOCATION",
    "QUOC_GIA": "LOCATION",
    "SO_TAI_KHOAN": "BANK_ACCOUNT",
    "TEN_TO_CHUC": "ORGANIZATION",
    "TEN_NGAN_HANG": "ORGANIZATION",
    "MA_NHAN_VIEN": "ID",
    "MA_GIAO_DICH": "ID",
    "MA_SO_THUE": "ID",
    "SO_CCCD_CMND": "ID",
    "SO_HO_CHIEU": "ID",
}


class PiiMasking95kDataset(BaseDataset):
    """Vietnamese synthetic PII dataset, ~95k rows, pre-tokenized.

    Synthetic Vietnamese documents (banking, healthcare, HR, government forms)
    with both placeholder-masked text and character-offset span annotations,
    plus a precomputed BIO token encoding. Private HF repo (needs HF_TOKEN).
    """

    name = "pii_masking_95k"
    hf_name = "nguyenlamtung/pii-masking-95k-preencoded"
    description = "Vietnamese synthetic PII dataset (~95k rows, pre-tokenized, 111 labels)."
    language = "vi"
    requires_token = True
    text_column = "source_text"
    mask_column = "privacy_mask"
    label_to_presidio = VI_PII_LABEL_TO_PRESIDIO


VIE_PII_LABEL_TO_PRESIDIO = {
    "human_name": "PERSON",
    "address": "LOCATION",
    "company_name": "ORGANIZATION",
    "phone_number": "PHONE_NUMBER",
    "email_address": "EMAIL_ADDRESS",
    "id_number": "ID",
    "date": "DATE_TIME",
}


class HoangHaViePiiDataset(BaseDataset):
    """Gated Hugging Face Vietnamese PII corpus with inline bracket labels.

    The source has a single `train` split and stores labeled spans in the
    translated `output` column as `[value]<label>`. This loader removes the
    inline markup, reconstructs character spans, and creates deterministic
    train_main/train_val/test partitions from the single source split.
    """

    name = "hoangha_vie_pii"
    hf_name = "HoangHa/vie-pii"
    description = "Gated Vietnamese PII dataset (10k rows, inline bracket labels)."
    language = "vi"
    requires_token = True
    text_column = "output"
    mask_column = "privacy_mask"
    label_to_presidio = VIE_PII_LABEL_TO_PRESIDIO

    def load(self, split: str = "train", limit: int = None, random_state: int = 42):
        import re

        import pandas as pd
        from datasets import load_dataset

        from src.pipeline.Utils import load_hf_token

        token = load_hf_token() if self.requires_token else None
        requested_split = "train_val" if split == "validation" else split
        dataset = load_dataset(self.hf_name, token=token)["train"].to_pandas()
        dataset = dataset.reset_index(drop=False).rename(columns={"index": "source_index"})
        dataset = self._partition(dataset, split=requested_split, random_state=random_state)
        if limit is not None and len(dataset) > limit:
            dataset = dataset.sample(n=limit, random_state=random_state).sort_index()

        parsed = dataset["output"].apply(self._parse_inline_markup)
        dataset["source_text"] = parsed.apply(lambda item: item[0])
        dataset["privacy_mask"] = parsed.apply(lambda item: item[1])
        dataset["split"] = (
            requested_split if requested_split in {"train_main", "train_val", "test"} else "train"
        )
        dataset["input_id"] = dataset["source_index"].apply(
            lambda index: f"{self.name}:{dataset['split'].iloc[0]}:{index}"
        )

        # Keep a compact label summary from the source column when it is valid
        # JSON, but do not rely on it for spans because repeated values need
        # sequential character offsets from the marked-up output text.
        label_re = re.compile(r"\[([^\]]+)\]<([A-Za-z_]+)>")
        dataset["inline_label_count"] = dataset["output"].apply(lambda text: len(label_re.findall(text)))
        return dataset

    def _partition(self, df, *, split: str, random_state: int):
        if split in {"train", "all"}:
            return df
        if split == "validation":
            split = "train_val"
        if split not in {"train_main", "train_val", "test"}:
            raise ValueError(
                f"{self.name}: split {split!r} not available. Use train, train_main, train_val, test, or all."
            )

        shuffled = df.sample(frac=1.0, random_state=random_state)
        val_size = max(1, int(round(len(shuffled) * 0.1)))
        test_size = max(1, int(round(len(shuffled) * 0.1)))
        val_indices = set(shuffled.iloc[:val_size].index)
        test_indices = set(shuffled.iloc[val_size : val_size + test_size].index)

        if split == "train_val":
            return df.loc[df.index.isin(val_indices)]
        if split == "test":
            return df.loc[df.index.isin(test_indices)]
        return df.loc[~df.index.isin(val_indices | test_indices)]

    def _parse_inline_markup(self, marked_text: str):
        import re

        label_re = re.compile(r"\[([^\]]+)\]<([A-Za-z_]+)>")
        spans = []
        chunks = []
        cursor = 0
        clean_offset = 0

        for match in label_re.finditer(marked_text):
            prefix = marked_text[cursor : match.start()]
            value = match.group(1)
            label = match.group(2)
            chunks.append(prefix)
            clean_offset += len(prefix)
            start = clean_offset
            chunks.append(value)
            clean_offset += len(value)
            spans.append(
                {
                    "start": start,
                    "end": clean_offset,
                    "value": value,
                    "label": label,
                }
            )
            cursor = match.end()

        suffix = marked_text[cursor:]
        chunks.append(suffix)
        return "".join(chunks), spans
