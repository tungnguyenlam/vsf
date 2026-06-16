# Dataset: `pii_masking_95k`

Vietnamese synthetic PII dataset, pre-tokenized. This is the **default** evaluation
dataset for the PII pipeline.

- **Registry key:** `pii_masking_95k` (`src/pipeline/Datasets/variants.py` → `PiiMasking95kDataset`)
- **HF repo:** `nguyenlamtung/pii-masking-95k-preencoded` (**private** — needs `HF_TOKEN` in `.env`)
- **Language / region / script:** Vietnamese only (`vi` / `VN` / `Latn`)
- **Nature:** synthetic documents (banking, healthcare, HR, government/identity forms)

## Size & splits

| Split | Rows |
|-------|-----:|
| train | 76,097 |
| test | 9,513 |
| validation | 9,512 |
| **total** | **95,122** |

`load(split="val")` is aliased to the `validation` split. `split="train_val"` and
`split="train_main"` create a deterministic 10%/90% partition from the train split
for routine inspection without touching test. `split="all"` concatenates all three.

## Columns

| Column | Type | Meaning |
|--------|------|---------|
| `source_text` | str | Raw Vietnamese document. **Pipeline input.** |
| `masked_text` | str | Same text with each PII span replaced by a `[LABEL_n]` placeholder (e.g. `[SO_TAI_KHOAN_1]`). |
| `privacy_mask` | list[dict] | **Ground truth.** Span list; see format below. |
| `language` / `region` / `script` | str | Always `vi` / `VN` / `Latn`. |
| `uid` | str | Stable per-row UUID from the source. |
| `tokens` | ndarray[str] | Pre-tokenized subwords (SentencePiece-style, `▁` word-boundary marker; large multilingual vocab). |
| `token_classes` | ndarray[str] | BIO tags aligned to `tokens` (`B-<LABEL>`, `I-<LABEL>`, `O`). |
| `input_ids` / `attention_mask` | ndarray[int] | Encoder inputs for the precomputed tokenizer. |
| `offset_mapping` | ndarray[[int,int]] | Char span per token — bridges token space back to `source_text`. |

Added by our loader (`BaseDataset.load`): `split` (str) and `input_id` (`"{name}:{split}:{i}"`).

> **"Pre-encoded" caveat:** `tokens`/`token_classes`/`input_ids`/`offset_mapping` were produced by a
> *specific* tokenizer baked into the dataset. They're convenient for training a transformer NER head
> **only if you use that same tokenizer**. The Presidio/regex/LLM pipeline ignores these entirely and
> works off `source_text` + `privacy_mask`.

## Span format (`privacy_mask`)

A list of dicts, character offsets into `source_text`:

```json
{"start": 121, "end": 131, "value": "7204684910", "label": "SO_TAI_KHOAN", "label_index": 1}
```

- `start`/`end` — Python-style char slice (`source_text[start:end] == value`).
- `label` — fine-grained Vietnamese label (see taxonomy below).
- `label_index` — 1-based occurrence counter for that label within the row (matches the `_n` in `masked_text`).

The loader coerces this through `normalize_privacy_mask` (handles JSON strings / numpy arrays).

## Label taxonomy & mapping to our entity types

The dataset has **~110 distinct fine-grained labels**. We map **every label that denotes personal
data** to one of **21 target types** — the original 8 (`PERSON, LOCATION, ORGANIZATION,
PHONE_NUMBER, EMAIL_ADDRESS, BANK_ACCOUNT, ID, DATE_TIME`) plus **13 added** for full PII coverage
(`CREDIT_CARD, CRYPTO, IP_ADDRESS, URL, CREDENTIAL, FINANCIAL, MEDICAL, VEHICLE, USERNAME, NRP,
OCCUPATION, EDUCATION, PROPERTY`). `MISC` remains a verifier-only catch-all (no label maps to it).
The mapping is owned by the dataset class (`VI_PII_LABEL_TO_PRESIDIO`) and consumed as the
evaluator's default `label_to_presidio`.

This expansion exists so the `safety_v0` converter redacts **all** gold PII: previously only 23
labels mapped and ~46% of gold spans were dropped, leaving real PII (PINs, license/insurance/medical
numbers, IPs, salaries, …) in the "sanitized" text while the row claimed `pii_visible: False`. Now
only the genuinely non-identifying tokens below are dropped (~1.8% of spans).

### Mapped (target type → dataset labels)

| Target type | Dataset labels |
|---------------|----------------|
| `PERSON` | `HO_VA_TEN`, `HO`, `TEN`, `TEN_DEM`, `DANH_XUNG` |
| `DATE_TIME` | `NGAY`, `NGAY_SINH`, `THANG`, `NAM`, `THOI_GIAN`, `NGAY_CAP`, `HAN_THE_TIN_DUNG` |
| `LOCATION` | `THANH_PHO_TINH`, `QUAN_HUYEN`, `PHUONG_XA`, `DUONG_PHO`, `SO_NHA_TOA_NHA`, `QUOC_GIA`, `TOA_DO_DIA_LY`, `MA_BUU_CHINH`, `PHUONG_HUONG` |
| `ORGANIZATION` | `TEN_TO_CHUC`, `TEN_NGAN_HANG`, `LOAI_HINH_TO_CHUC`, `TO_CHUC_CONG_TY_BAO_HIEM`, `TO_CHUC_PHAT_HANH_THE`, `TEN_BENH_VIEN`, `NHA_MANG`, `CO_QUAN_CAP` |
| `PHONE_NUMBER` | `SO_DIEN_THOAI` |
| `EMAIL_ADDRESS` | `DIA_CHI_EMAIL` |
| `BANK_ACCOUNT` | `SO_TAI_KHOAN`, `MA_BIC_SWIFT_NGAN_HANG` |
| `ID` | `MA_NHAN_VIEN`, `MA_GIAO_DICH`, `MA_SO_THUE`, `SO_CCCD_CMND`, `SO_HO_CHIEU`, `SO_TAI_LIEU`, `SO_HOP_DONG_MA_SO_CHINH_SACH`, `MA_SINH_VIEN`, `MA_BENH_AN`, `MA_KHACH_HANG`, `SO_GIAY_PHEP_LAI_XE`, `SO_THE_BAO_HIEM_Y_TE`, `SO_AN_SINH_XA_HOI_MA_BHXH`, `MA_IMEI_DIEN_THOAI` |
| `CREDIT_CARD` | `SO_THE_TIN_DUNG`, `SO_THE`, `MA_BAO_MAT_THE_CVV` |
| `CRYPTO` | `DIA_CHI_VI_ETHEREUM`, `DIA_CHI_VI_BITCOIN`, `DIA_CHI_VI_LITECOIN` |
| `IP_ADDRESS` | `DIA_CHI_IP`, `DIA_CHI_IPV4`, `DIA_CHI_IPV6`, `DIA_CHI_MAC` |
| `URL` | `DUONG_DAN_URL` |
| `CREDENTIAL` | `MAT_KHAU`, `MA_OTP`, `MA_PIN`, `KHOA_API`, `CHUOI_DINH_DANH_TRINH_DUYET` |
| `FINANCIAL` | `SO_TIEN`, `MUC_LUONG_THU_NHAP`, `SO_DU`, `XEP_HANG_TIN_DUNG` |
| `MEDICAL` | `CHAN_DOAN`, `KET_QUA_XET_NGHIEM`, `QUA_TRINH_DIEU_TRI`, `BENH_MAN_TINH`, `DON_THUOC`, `DUNG_THUOC`, `DI_UNG`, `THONG_TIN_DI_TRUYEN`, `NHOM_MAU`, `TINH_TRANG_TIEM_CHUNG`, `TINH_TRANG_THAI_KY`, `THONG_TIN_SUC_KHOE_TAM_THAN`, `TINH_TRANG_KHUYET_TAT`, `CAN_NANG`, `CHIEU_CAO`, `SO_DUOC_CHE_MOT_PHAN` |
| `VEHICLE` | `BIEN_SO_XE`, `SO_KHUNG_XE`, `LOAI_PHUONG_TIEN`, `HANG_XE` |
| `USERNAME` | `TEN_NGUOI_DUNG_TAI_KHOAN`, `TEN_TAI_KHOAN` |
| `NRP` | `TON_GIAO`, `QUOC_TICH`, `GIOI_TINH`, `GIOI_TINH_SINH_HOC`, `THANH_PHAN_XA_HOI`, `TUOI` |
| `OCCUPATION` | `LINH_VUC_NGHE_NGHIEP`, `CHUC_DANH_CONG_VIEC`, `LOAI_HINH_CONG_VIEC`, `MA_NGHE_NGHIEP` |
| `EDUCATION` | `TRINH_DO_HOC_VAN`, `HOC_VI` |
| `PROPERTY` | `TEN_TAI_SAN`, `TAI_SAN`, `SO_DO`, `SO_THUA_DAT` |

`NRP` is used broadly here as "sensitive demographic attribute" (nationality, religion, gender,
biological sex, social class, age).

### Intentionally dropped (not personal data)

These denote no individual and are kept out of `pii_spans` (so they are never redacted). The set
lives in `VI_PII_DROPPED_LABELS` so the omission is a documented decision, not an oversight:

`LOAI_TIEN_TE` (currency type), `TY_GIA_HOI_DOAI` (exchange rate), `NGON_NGU` (language),
`MUI_GIO` (timezone), `MA_SAN_BAY` (airport code), `MA_GA_TRAM` (station code).

### Detection coverage (important)

The **evaluator** derives its type set dynamically from this mapping. Recognizers currently cover
**12 of the 21 types**: the original 8 plus `URL`, `IP_ADDRESS` (IPv4/IPv6/MAC), `CRYPTO`
(BTC/ETH/LTC), and `CREDIT_CARD` (grouped number + context + CVV) — high-precision regex in
`CustomPatternRecognizer.build_patterns()`. The remaining **9 new types** (`CREDENTIAL`, `FINANCIAL`,
`MEDICAL`, `VEHICLE`, `USERNAME`, `NRP`, `OCCUPATION`, `EDUCATION`, `PROPERTY`) have **no detector
yet**, so detection recall on them is **0** until recognizers are added — read headline detection
quality on the recognizer-covered subset. The mapping change is primarily for the `safety_v0`
dataset's redaction completeness and `pii_visible` honesty.

## Usage

```python
from src.pipeline.Datasets import get_dataset

ds = get_dataset("pii_masking_95k")
df = ds.load(split="train_val", limit=200)    # normalized: source_text, privacy_mask, split, input_id
print(ds.presidio_types)                        # the 8 evaluable types
print(ds.unmapped_labels(df))                   # what's being ignored in this slice

from src.pipeline.Evaluator import PIIEvaluator
evaluator = PIIEvaluator(ds.label_to_presidio)  # dataset owns the mapping
```

CLI evaluation is run through `scripts/evaluate_pipeline.py`, which delegates to the OOP runner in
`src/pipeline/Pipelines/evaluation.py`:

```bash
PYTHONPATH=. python3 scripts/evaluate_pipeline.py --pipeline regex_only --dataset nguyenlamtung/pii-masking-95k-preencoded --split train_val --limit 50
```

The runner loads local `.env` values before dataset setup, so this private dataset can use
`HF_TOKEN` from `.env`.
