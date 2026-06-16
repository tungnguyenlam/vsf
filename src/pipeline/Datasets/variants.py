from src.pipeline.Datasets.base import BaseDataset


# Canonical label taxonomy -> Presidio entity types for the Vietnamese
# pii-masking-95k dataset. This is the single source of truth for the mapping;
# the evaluator imports it as its default. The dataset ships ~110 distinct
# fine-grained labels. We map every label that denotes personal data to one of
# 21 target types (the original 8 plus 13 added for full PII coverage), so the
# safety converter redacts all gold PII and `pii_visible` stays honest. Only
# genuinely non-identifying tokens (see VI_PII_DROPPED_LABELS) are dropped.
#
# NOTE on detection: the detection recognizers currently emit only the original
# 8 types (PERSON, DATE_TIME, PHONE_NUMBER, EMAIL_ADDRESS, LOCATION,
# BANK_ACCOUNT, ORGANIZATION, ID). The 13 new types have no recognizer yet, so
# detection recall on them is 0 until detectors are added; read headline
# detection quality on the recognizer-covered subset. See
# docs/datasets/pii-masking-95k.md.
VI_PII_LABEL_TO_PRESIDIO = {
    # --- Original 8 target types (recognizers exist) --------------------------
    # PERSON
    "HO_VA_TEN": "PERSON",
    "HO": "PERSON",
    "TEN": "PERSON",
    "TEN_DEM": "PERSON",
    "DANH_XUNG": "PERSON",
    # DATE_TIME
    "NGAY": "DATE_TIME",
    "NGAY_SINH": "DATE_TIME",
    "THANG": "DATE_TIME",
    "NAM": "DATE_TIME",
    "THOI_GIAN": "DATE_TIME",
    "NGAY_CAP": "DATE_TIME",
    "HAN_THE_TIN_DUNG": "DATE_TIME",
    # PHONE_NUMBER
    "SO_DIEN_THOAI": "PHONE_NUMBER",
    # EMAIL_ADDRESS
    "DIA_CHI_EMAIL": "EMAIL_ADDRESS",
    # LOCATION
    "THANH_PHO_TINH": "LOCATION",
    "QUAN_HUYEN": "LOCATION",
    "PHUONG_XA": "LOCATION",
    "DUONG_PHO": "LOCATION",
    "SO_NHA_TOA_NHA": "LOCATION",
    "QUOC_GIA": "LOCATION",
    "TOA_DO_DIA_LY": "LOCATION",
    "MA_BUU_CHINH": "LOCATION",
    "PHUONG_HUONG": "LOCATION",
    # ORGANIZATION
    "TEN_TO_CHUC": "ORGANIZATION",
    "TEN_NGAN_HANG": "ORGANIZATION",
    "LOAI_HINH_TO_CHUC": "ORGANIZATION",
    "TO_CHUC_CONG_TY_BAO_HIEM": "ORGANIZATION",
    "TO_CHUC_PHAT_HANH_THE": "ORGANIZATION",
    "TEN_BENH_VIEN": "ORGANIZATION",
    "NHA_MANG": "ORGANIZATION",
    "CO_QUAN_CAP": "ORGANIZATION",
    # BANK_ACCOUNT
    "SO_TAI_KHOAN": "BANK_ACCOUNT",
    "MA_BIC_SWIFT_NGAN_HANG": "BANK_ACCOUNT",
    # ID (all personal identifier numbers fold here)
    "MA_NHAN_VIEN": "ID",
    "MA_GIAO_DICH": "ID",
    "MA_SO_THUE": "ID",
    "SO_CCCD_CMND": "ID",
    "SO_HO_CHIEU": "ID",
    "SO_TAI_LIEU": "ID",
    "SO_HOP_DONG_MA_SO_CHINH_SACH": "ID",
    "MA_SINH_VIEN": "ID",
    "MA_BENH_AN": "ID",
    "MA_KHACH_HANG": "ID",
    "SO_GIAY_PHEP_LAI_XE": "ID",
    "SO_THE_BAO_HIEM_Y_TE": "ID",
    "SO_AN_SINH_XA_HOI_MA_BHXH": "ID",
    "MA_IMEI_DIEN_THOAI": "ID",
    # --- 13 new target types (no recognizer yet) ------------------------------
    # CREDIT_CARD
    "SO_THE_TIN_DUNG": "CREDIT_CARD",
    "SO_THE": "CREDIT_CARD",
    "MA_BAO_MAT_THE_CVV": "CREDIT_CARD",
    # CRYPTO
    "DIA_CHI_VI_ETHEREUM": "CRYPTO",
    "DIA_CHI_VI_BITCOIN": "CRYPTO",
    "DIA_CHI_VI_LITECOIN": "CRYPTO",
    # IP_ADDRESS (incl. MAC)
    "DIA_CHI_IP": "IP_ADDRESS",
    "DIA_CHI_IPV4": "IP_ADDRESS",
    "DIA_CHI_IPV6": "IP_ADDRESS",
    "DIA_CHI_MAC": "IP_ADDRESS",
    # URL
    "DUONG_DAN_URL": "URL",
    # CREDENTIAL (secrets)
    "MAT_KHAU": "CREDENTIAL",
    "MA_OTP": "CREDENTIAL",
    "MA_PIN": "CREDENTIAL",
    "KHOA_API": "CREDENTIAL",
    "CHUOI_DINH_DANH_TRINH_DUYET": "CREDENTIAL",
    # FINANCIAL (personal amounts / ratings)
    "SO_TIEN": "FINANCIAL",
    "MUC_LUONG_THU_NHAP": "FINANCIAL",
    "SO_DU": "FINANCIAL",
    "XEP_HANG_TIN_DUNG": "FINANCIAL",
    # MEDICAL
    "CHAN_DOAN": "MEDICAL",
    "KET_QUA_XET_NGHIEM": "MEDICAL",
    "QUA_TRINH_DIEU_TRI": "MEDICAL",
    "BENH_MAN_TINH": "MEDICAL",
    "DON_THUOC": "MEDICAL",
    "DUNG_THUOC": "MEDICAL",
    "DI_UNG": "MEDICAL",
    "THONG_TIN_DI_TRUYEN": "MEDICAL",
    "NHOM_MAU": "MEDICAL",
    "TINH_TRANG_TIEM_CHUNG": "MEDICAL",
    "TINH_TRANG_THAI_KY": "MEDICAL",
    "THONG_TIN_SUC_KHOE_TAM_THAN": "MEDICAL",
    "TINH_TRANG_KHUYET_TAT": "MEDICAL",
    "CAN_NANG": "MEDICAL",
    "CHIEU_CAO": "MEDICAL",
    "SO_DUOC_CHE_MOT_PHAN": "MEDICAL",
    # VEHICLE
    "BIEN_SO_XE": "VEHICLE",
    "SO_KHUNG_XE": "VEHICLE",
    "LOAI_PHUONG_TIEN": "VEHICLE",
    "HANG_XE": "VEHICLE",
    # USERNAME / account handle
    "TEN_NGUOI_DUNG_TAI_KHOAN": "USERNAME",
    "TEN_TAI_KHOAN": "USERNAME",
    # NRP (used broadly: sensitive demographic attributes)
    "TON_GIAO": "NRP",
    "QUOC_TICH": "NRP",
    "GIOI_TINH": "NRP",
    "GIOI_TINH_SINH_HOC": "NRP",
    "THANH_PHAN_XA_HOI": "NRP",
    "TUOI": "NRP",
    # OCCUPATION
    "LINH_VUC_NGHE_NGHIEP": "OCCUPATION",
    "CHUC_DANH_CONG_VIEC": "OCCUPATION",
    "LOAI_HINH_CONG_VIEC": "OCCUPATION",
    "MA_NGHE_NGHIEP": "OCCUPATION",
    # EDUCATION
    "TRINH_DO_HOC_VAN": "EDUCATION",
    "HOC_VI": "EDUCATION",
    # PROPERTY
    "TEN_TAI_SAN": "PROPERTY",
    "TAI_SAN": "PROPERTY",
    "SO_DO": "PROPERTY",
    "SO_THUA_DAT": "PROPERTY",
}

# Source labels that do NOT denote personal data and are intentionally dropped
# (never written to pii_spans, never redacted). Documented so the omission is a
# deliberate decision, not an oversight.
VI_PII_DROPPED_LABELS = {
    "LOAI_TIEN_TE",      # currency type, e.g. "VND" / "USD"
    "TY_GIA_HOI_DOAI",   # exchange rate
    "NGON_NGU",          # language
    "MUI_GIO",           # timezone
    "MA_SAN_BAY",        # airport code (IATA), not personal
    "MA_GA_TRAM",        # station code, not personal
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
