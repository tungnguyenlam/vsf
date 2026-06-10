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

`load(split="val")` is aliased to the `validation` split. `split="all"` concatenates all three.

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

## Label taxonomy & mismatch with our entity types

This is the important part. The dataset has **~111 distinct fine-grained labels**, but our pipeline
targets only **9 Presidio types** (`PERSON, LOCATION, ORGANIZATION, PHONE_NUMBER, EMAIL_ADDRESS,
BANK_ACCOUNT, ID, DATE_TIME, MISC`). The mapping is owned by the dataset class
(`VI_PII_LABEL_TO_PRESIDIO`) and consumed as the evaluator's default `label_to_presidio`.

### Mapped (23 labels → 8 types)

| Presidio type | Dataset labels |
|---------------|----------------|
| `PERSON` | `HO_VA_TEN`, `HO`, `TEN`, `TEN_DEM` |
| `DATE_TIME` | `NGAY`, `NGAY_SINH`, `THANG`, `NAM` |
| `LOCATION` | `THANH_PHO_TINH`, `QUAN_HUYEN`, `PHUONG_XA`, `DUONG_PHO`, `SO_NHA_TOA_NHA`, `QUOC_GIA` |
| `ORGANIZATION` | `TEN_TO_CHUC`, `TEN_NGAN_HANG` |
| `PHONE_NUMBER` | `SO_DIEN_THOAI` |
| `EMAIL_ADDRESS` | `DIA_CHI_EMAIL` |
| `BANK_ACCOUNT` | `SO_TAI_KHOAN` |
| `ID` | `MA_NHAN_VIEN`, `MA_GIAO_DICH`, `MA_SO_THUE`, `SO_CCCD_CMND`, `SO_HO_CHIEU` |

Notes:
- **`MISC`** is in our type set but **no dataset label maps to it** — the verifier may emit `MISC`,
  but there's no `MISC` ground truth here, so any `MISC` prediction counts as a false positive under
  mapped-type evaluation.
- **`TEN_DEM`** is mapped but does not appear in the data (0 occurrences observed) — harmless.

### Unmapped (88 labels — dropped during mapped-type evaluation)

These are real annotations the dataset provides but our 9-type pipeline does not target. They are
**ignored** by `evaluate_presidio(use_type_mapping=True)` — they neither help nor hurt mapped-type
metrics (they are not counted as FN for the mapped types). High-frequency examples:

`LOAI_TIEN_TE` (22.7k), `LINH_VUC_NGHE_NGHIEP` (19.1k), `CHUC_DANH_CONG_VIEC` (17.0k),
`SO_TIEN` (14.3k), `SO_TAI_LIEU` (9.2k), `CHAN_DOAN` (8.6k), `THOI_GIAN` (7.8k),
`LOAI_HINH_TO_CHUC` (7.8k), `MA_PIN` (7.7k), `DANH_XUNG` (7.5k), `KET_QUA_XET_NGHIEM` (6.8k),
`CO_QUAN_CAP` (6.8k), `TEN_TAI_SAN` (6.2k), `TAI_SAN` (5.8k), `NGAY_CAP` (5.7k),
`TOA_DO_DIA_LY` (5.6k) …

Broad categories of unmapped labels: **money/finance** (`SO_TIEN`, `LOAI_TIEN_TE`, `SO_DU`,
`MUC_LUONG_THU_NHAP`, `TY_GIA_HOI_DOAI`, `XEP_HANG_TIN_DUNG`), **payment cards**
(`SO_THE_TIN_DUNG`, `MA_BAO_MAT_THE_CVV`, `HAN_THE_TIN_DUNG`), **health/medical**
(`CHAN_DOAN`, `BENH_MAN_TINH`, `DON_THUOC`, `NHOM_MAU`, `MA_BENH_AN`, `KET_QUA_XET_NGHIEM`,
`TINH_TRANG_*`, `DI_UNG`, `THONG_TIN_DI_TRUYEN`), **credentials/digital** (`MAT_KHAU`, `MA_OTP`,
`MA_PIN`, `KHOA_API`, `DIA_CHI_IP*`, `DIA_CHI_MAC`, `DUONG_DAN_URL`, `DIA_CHI_VI_BITCOIN/ETHEREUM/LITECOIN`,
`MA_IMEI_DIEN_THOAI`), **job/education** (`CHUC_DANH_CONG_VIEC`, `LINH_VUC_NGHE_NGHIEP`,
`TRINH_DO_HOC_VAN`, `HOC_VI`), **vehicle** (`BIEN_SO_XE`, `SO_KHUNG_XE`, `HANG_XE`, `LOAI_PHUONG_TIEN`,
`SO_GIAY_PHEP_LAI_XE`), **demographics** (`GIOI_TINH`, `TUOI`, `QUOC_TICH`, `TON_GIAO`, `NGON_NGU`,
`CAN_NANG`, `CHIEU_CAO`), plus assorted IDs (`MA_KHACH_HANG`, `MA_SINH_VIEN`, `SO_THUA_DAT`,
`SO_AN_SINH_XA_HOI_MA_BHXH`, `MA_BUU_CHINH`, …).

> **Evaluation implication:** mapped-type recall is measured **only against mapped labels**, so the
> headline numbers describe coverage of the 8 target types — not the full PII surface of the dataset.
> If we later widen scope (e.g. add `CREDIT_CARD`, `IP_ADDRESS`, `MEDICAL`), extend
> `VI_PII_LABEL_TO_PRESIDIO` and this table together.

## Usage

```python
from src.pipeline.Datasets import get_dataset

ds = get_dataset("pii_masking_95k")
df = ds.load(split="val", limit=200)          # normalized: source_text, privacy_mask, split, input_id
print(ds.presidio_types)                        # the 8 evaluable types
print(ds.unmapped_labels(df))                   # what's being ignored in this slice

from src.pipeline.Evaluator import PIIEvaluator
evaluator = PIIEvaluator(ds.label_to_presidio)  # dataset owns the mapping
```

CLI evaluation is run through `scripts/evaluate_pipeline.py`, which delegates to the OOP runner in
`src/pipeline/Pipelines/evaluation.py`:

```bash
PYTHONPATH=. python3 scripts/evaluate_pipeline.py --pipeline regex_only --dataset nguyenlamtung/pii-masking-95k-preencoded --split test --limit 50
```

The runner loads local `.env` values before dataset setup, so this private dataset can use
`HF_TOKEN` from `.env`.
