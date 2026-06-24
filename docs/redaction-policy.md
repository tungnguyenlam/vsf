# Redaction policy — what must be redacted, what can be missed

This is the decision rule for **which detections matter**. Use it when reviewing
rows in the Annotate tab to decide whether a missed span is worth adding, and
which false positives are safe to delete. It is organized by the project's
21 entity types (`ENTITY_TYPES` in `src/pipeline/Verifiers/LLMVerifier.py`) so it
maps 1:1 to the type dropdown you pick from when adding a span.

The pipeline is **Vietnamese-first**: examples and disambiguating context words
are Vietnamese. The same rules apply to the (stretch-goal) English data.

## What redaction protects against

We redact to prevent two harms, in priority order:

1. **Direct harm / re-identification of a specific living person** — fraud,
   account takeover, financial loss, doxxing, exposure of a sensitive attribute.
2. **Quasi-identification** — fields that are not identifying alone but pinpoint
   a person when combined (a birth date plus a city plus an employer).

A value is PII only when it is **about a specific person**. The same string can
be PII or not depending on context: "Hà Nội" as someone's home address is PII;
"Hà Nội" in "cửa hàng ở Hà Nội" (a shop location) is not. Redaction is
**span-level**, so judge the occurrence, not the word.

## The three tiers

| Tier | Rule | Cost of getting it wrong |
|---|---|---|
| **MUST** | Redact **every** instance. High recall is mandatory; a miss is a reportable error. | A single leaked card number / national ID / password is a serious breach. |
| **CONDITIONAL** | Redact **when the span refers to or singles out a specific person**. Skip generic/public uses. | Missing one is a moderate privacy issue; over-redacting hurts data utility. |
| **IGNORE** | Not PII. Do **not** add it; delete it if the pipeline fired. | Redacting it is noise / over-redaction; it lowers dataset quality. |

When unsure between MUST and CONDITIONAL, treat as MUST. When unsure between
CONDITIONAL and IGNORE, prefer redacting only if the span, by itself or with its
immediate neighbors, could identify a person.

## Per-entity decision table

### MUST redact — high-harm identifiers and secrets

These directly enable fraud, account takeover, or unambiguous identification.
Redact every instance regardless of surrounding context.

| Entity | What it is | Vietnamese cues / examples |
|---|---|---|
| `CREDIT_CARD` | Card number, last-4, CVV, security code | 16-digit PAN, `xxxx 2522`, CVV 3-4 digits |
| `CREDENTIAL` | Passwords, secret keys, OTP, API tokens | `mật khẩu`, `OTP`, `mã bí mật`, bearer tokens |
| `BANK_ACCOUNT` | Bank account number | `số tài khoản`, `STK`, `tài khoản ngân hàng` |
| `FINANCIAL` | Other financial account numbers (IBAN, e-wallet id, card-linked ids) | `IBAN`, ví Momo/ZaloPay id |
| `ID` | Government / identity numbers: national ID, passport, tax id, insurance | `CCCD`, `CMND`, `hộ chiếu`, `mã số thuế` (MST), `BHYT`, `BHXH` |
| `CRYPTO` | Wallet address / private key | `0x…`, `bc1…` |
| `MEDICAL` | Health conditions, diagnoses, records tied to a person | `chẩn đoán`, `bệnh án`, medication for a named patient |
| `PHONE_NUMBER` | Phone number | `số điện thoại`, `SĐT`, `0…`/`+84…` |
| `EMAIL_ADDRESS` | Email address | `…@…` |

Notes:
- `ID` is broad. The MUST part is **government / identity / insurance numbers**.
  Order ids, promo codes, job codes are *not* identity — see IGNORE.
- A bare number is only `CREDIT_CARD` / `BANK_ACCOUNT` / `ID` when context
  supports it (`STK`, `CCCD`, `MST`, "thẻ tín dụng"). A bare number that is a
  quantity, price, order id, or date is **not** these types — do not add it.

### CONDITIONAL — redact when it identifies a specific person

PII only when the span is about an identifiable individual. Skip generic, public,
or organizational uses.

| Entity | Redact when… | Skip when… |
|---|---|---|
| `PERSON` | A real person's name (full or partial), incl. a recipient/sender | Brand/product names, public figures *only* if the context is clearly non-personal; default to redacting names |
| `LOCATION` | A residential or precise address that locates a person (street, house no., full postcode, "địa chỉ nhà") | Store/branch locations, a bare country or large city used non-personally |
| `USERNAME` | A login handle / account name tied to a person | A public brand handle, a generic role account |
| `IP_ADDRESS` | An address tied to a user's session/device | Documentation/example IPs (`127.0.0.1`, `0.0.0.0`) |
| `VEHICLE` | License plate / VIN of a person's vehicle | Generic vehicle model names |
| `DATE_TIME` | **Date of birth**, or a date that pinpoints a person's event; card expiry (payment data) | Generic dates: delivery date, order date, "Dec 9 2023", business hours |
| `NRP` | Nationality / religion / political affiliation stated **about a person** (sensitive attribute) | The same words as general topic/news, not about an individual |
| `OCCUPATION` | A job/title that, with other fields, identifies someone | A job mentioned generically |
| `EDUCATION` | A school/degree tied to a person | A school named as an institution generally |
| `PROPERTY` | A specific owned asset that identifies/links a person | Generic property descriptions |

`DATE_TIME` is the most over-fired type. Default: **DOB and card expiry → redact;
everything else → skip** unless the date clearly singles out a person.

### IGNORE — not PII; do not add, delete if fired

| Entity / value | Why it is not PII |
|---|---|
| `ORGANIZATION` (company/brand names) | A company is not a person. Redact only the rare case where a one-person business name *is* the person's name (then it is `PERSON`). |
| `URL` | Not PII unless it embeds an identity (a personal profile/account URL); a plain link is IGNORE. |
| `MISC` (free-text fields) | Gift messages, delivery instructions, notes. The real PII inside (name, address, phone) is captured by its own typed span; the surrounding prose is not PII. **Do not redact the whole field.** See `docs/datasets/webpii.md`. |
| Order id / invoice no. / PO / promo / coupon / job code | Transaction identifiers, not identity. (`ID` is reserved for government/identity numbers.) |
| Quantity, price, amount, percentage, product code/SKU | Commercial data, not personal. |
| Generic dates (delivery, order, business hours) | See `DATE_TIME` above. |
| UI/boilerplate text, marketing copy, legal notices | Not about a person. |
| Public / example values (`example.com`, `127.0.0.1`, sample names in templates) | Not a real person's data. |

## Ambiguity rules (the cases that cause most mistakes)

1. **Bare numbers.** Decide by Vietnamese context words, not digit shape:
   - `STK` / `số tài khoản` → `BANK_ACCOUNT`; `CCCD`/`CMND` → `ID`;
     `MST`/`mã số thuế` → `ID`; `thẻ`/`ending in` → `CREDIT_CARD`;
     `SĐT`/`điện thoại` → `PHONE_NUMBER`.
   - No identity context (order #, qty, price, code) → **IGNORE**.
2. **Names vs brands.** Personal names → `PERSON`. Company/store/brand → IGNORE
   (`ORGANIZATION` is not redacted). A storefront that is a person's name is a
   judgment call; prefer `PERSON` if it identifies the individual.
3. **Addresses.** Precise/residential → `LOCATION` (redact). Coarse (country,
   province) used non-personally → IGNORE. Postcodes and street numbers that
   complete an address → redact.
4. **Dates.** DOB and card expiry → redact. Everything else → IGNORE.
5. **Free-text fields.** Never redact the whole message/instruction. Add typed
   spans only for the actual PII tokens inside it (the recipient name, a phone,
   an address) if they are not already boxed.

## How this maps to annotation work

When reviewing a row in the Annotate tab:

- **Add a missed span** if it is a **MUST** type, or a **CONDITIONAL** type whose
  occurrence identifies a person. Pick the entity type from the table above.
- **Leave it / delete it** if it is **IGNORE**, or a CONDITIONAL type used
  generically. Over-redaction lowers dataset quality and is itself an error.
- **Prioritize recall on MUST types** — these are the ones we cannot afford to
  miss. CONDITIONAL types are best-effort with judgment; IGNORE types should stay
  clean.

## Source-key reference (WebPII)

`scripts/safety_v0/convert/convert_webpii.py::map_webpii_key_to_presidio` maps
WebPII source keys to the taxonomy. Highlights relevant to this policy:

- `PII_CARD_NUMBER` / `PII_CARD_LAST4` / `PII_CARD_CVV` / `PII_SECURITY_CODE` →
  `CREDIT_CARD` (MUST). Card expiry → `DATE_TIME` (redact as payment data).
- `PII_LOGIN_PASSWORD*` → `CREDENTIAL` (MUST); `PII_LOGIN_USERNAME` → `USERNAME`.
- Name keys → `PERSON`; address family → `LOCATION`; `PII_PHONE*` →
  `PHONE_NUMBER`; email keys → `EMAIL_ADDRESS`.
- `PII_PO_NUMBER` / `PII_JOB_CODE` / `PII_PROMO_CODE` are **transaction
  identifiers, not identity**, so the converter no longer maps them (no source
  box, never redacted). Already-converted data drops them at alignment via
  `NON_REDACTABLE_SOURCE_KEYS` in `run_ocr.py`.
- `PII_GIFT_MESSAGE` / `PII_DELIVERY_INSTRUCTIONS` → `MISC` and are **not
  redacted** (free-text; embedded PII is boxed separately). `PII_CARD_IMAGE` /
  `PII_AVATAR` are unmapped (no text span).
