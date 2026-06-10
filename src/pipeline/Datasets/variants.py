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
