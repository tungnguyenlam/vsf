# Vietnamese PII Research Notes

This note tracks Vietnam-specific PII knowledge that informs the current
Presidio recognizers. It is a working engineering note, not legal advice.

Use this document to decide which entity types, regex contexts, and validation
rules are worth implementing next. Any legal/regulatory claim or checksum claim
should be confirmed against official sources before it is used in a seminar or
production-facing document.

## Current Engineering Scope

The current pipeline evaluates these Presidio types:

| Type | Included now | Main evidence used by the recognizers |
|---|---|---|
| `PERSON` | Yes | Name labels, person-role context, Underthesea PERSON spans |
| `LOCATION` | Yes | Vietnamese address component words such as Tinh, TP., Quan, Huyen, Phuong, Xa, Duong, Pho, Thon |
| `ORGANIZATION` | Yes | Organization labels and words such as cong ty, ngan hang, benh vien, truong, don vi |
| `PHONE_NUMBER` | Yes | Vietnamese-like phone prefixes and digit length |
| `EMAIL_ADDRESS` | Yes | Standard email regex |
| `BANK_ACCOUNT` | Yes | STK / so tai khoan / bank-account context plus numeric span |
| `ID` | Yes | CCCD/CMND, passport, tax code, employee ID, transaction ID context |
| `DATE_TIME` | Yes | Ngay sinh, thang sinh, nam sinh, and selected date contexts |
| `MISC` | Reserved | No dataset label currently maps to `MISC` |

The current dataset contains many additional labels that are not yet targeted,
including medical, credential, payment-card, vehicle, IP/device, financial, and
demographic fields. Those are documented in `docs/datasets/pii-masking-95k.md`.

## Vietnam-Specific Entity Notes

### CCCD / CMND

Current support:

- Detected as `ID`.
- Regex requires strong context such as `cccd`, `cmnd`, `cmtnd`, `can cuoc`,
  `can cuoc cong dan`, `chung minh nhan dan`, or `the cccd`.
- Supports 12-digit and older 9-digit-looking values.

Current recognizer patterns:

- `vn_cccd_cmnd`
- `vn_cccd_loose_number`

Research still needed:

- Confirm official current personal identification number structure.
- Confirm whether there is a public checksum. Do not assume one.
- Confirm whether old CMND values should remain in scope for demo examples.

Implementation direction:

- Keep context required. Bare 9/12-digit numbers are too risky.
- If official structure is confirmed, add a validator as a small helper function
  instead of putting all logic inside the regex.

### Passport

Current support:

- Detected as `ID`.
- Requires `ho chieu` or `passport` context.
- Current value shape is one uppercase letter followed by 6 to 8 digits.

Current recognizer pattern:

- `vn_passport_id`

Research still needed:

- Confirm valid Vietnamese passport series formats.
- Check whether newer formats differ from older examples.

Implementation direction:

- Keep context required.
- Avoid broad alphanumeric matching without `ho chieu` / `passport` context.

### Tax Code

Current support:

- Detected as `ID`.
- Requires `ma so thue` context.
- Current value shape is 10 digits with optional branch suffix `-ddd`.

Current recognizer pattern:

- `vn_tax_id`

Research still needed:

- Confirm official 10-digit and 13-digit representation.
- Confirm whether checksum validation is stable and worth implementing.
- Confirm whether individual tax IDs and organization tax IDs should be separated
  for reporting, even if both map to `ID` in evaluation.

Implementation direction:

- Keep as `ID` for current mapped evaluation.
- If validation is added, keep it behind a helper such as
  `is_valid_vn_tax_id(value: str)`.

### Bank Account Number

Current support:

- Detected as `BANK_ACCOUNT`.
- Uses context such as `so tai khoan`, `stk`, `tai khoan nhan`, and related
  banking phrases.

Research still needed:

- Bank account lengths and formats are bank-specific.
- Do not claim a universal Vietnam bank-account checksum without per-bank
  confirmation.

Implementation direction:

- Continue using context-first detection.
- Avoid detecting bare long numbers as bank accounts unless surrounded by
  account-specific context.

### Phone Number

Current support:

- Detected as `PHONE_NUMBER`.
- Supports `+84` or leading `0`, then common mobile-prefix style digits.

Current recognizer pattern:

- `vn_mobile_phone`

Research still needed:

- Confirm active Vietnam mobile prefixes and landline patterns.
- Decide whether landline numbers are in scope for the checkpoint.
- Decide whether phone detection should require context or allow high-confidence
  bare values.

Implementation direction:

- Keep current mobile-like pattern for now.
- Add landline support only if mentor/demo scope requires it.

### Address / Location

Current support:

- Detected as `LOCATION`.
- Covers house number, street-like, ward, district, province, hamlet/village, and
  country contexts.

Current recognizer patterns include:

- `vn_house_number`
- `vn_street_like_location`
- `vn_ward_location`
- `vn_district_location`
- `vn_province_location`

Research still needed:

- Build a controlled list of Vietnamese administrative unit names only if it
  improves precision without adding too much maintenance.
- Check whether address components should be detected separately or merged into
  longer spans for anonymization UX.

Implementation direction:

- Continue avoiding form-label overmatches such as `Ma`, `Ngay`, `So`, `Ten`,
  and `Dia` as location starts.
- Prefer context and boundaries over one giant address regex.

### Person Names

Current support:

- Detected as `PERSON`.
- Regex covers some person-label contexts.
- Underthesea is used as a filtered PERSON-only NER source in combined pipelines.

Current issue:

- Regex is high precision but misses many names.
- Underthesea recovers recall but adds false positives, especially organization,
  product, document, and code-like contexts.

Implementation direction:

- Keep `regex_recall` as the default for now.
- Keep Underthesea variants as experimental.
- Add resolver decision logging before doing more resolver tuning.

### Organization Names

Current support:

- Detected as `ORGANIZATION`.
- Uses labels and organization trigger words such as company, bank, hospital,
  school, department, office, center, and unit.

Current issue:

- Organization recall remains weaker than easier structured fields.
- PERSON/ORGANIZATION confusion is a common NER and dataset-boundary problem.

Implementation direction:

- Mine targeted validation errors before adding more broad regex.
- Consider a stronger Vietnamese NER model later if organization recall becomes
  a priority.

### Date / Time

Current support:

- Detected as `DATE_TIME`.
- Focuses on PII-relevant contexts such as birth date/year/month and selected
  document or event date contexts.

Current issue:

- Broad date regex can easily over-detect non-PII dates.
- Some cleanup already removed noisy issue-date and generic-year matches.

Implementation direction:

- Keep date context-specific.
- Decide whether `ngay cap` should remain excluded or should become a separate
  supported entity later.

## Unmapped But Important Future PII

These labels exist in the dataset but are outside the current mapped target
types. They should be considered if the PII scope expands:

| Future category | Examples | Possible future type |
|---|---|---|
| Payment cards | Card number, CVV, card expiry | `CREDIT_CARD`, `PAYMENT_CARD` |
| Credentials | Password, OTP, PIN, API key | `CREDENTIAL`, `SECRET` |
| Network/device | IP, MAC, IMEI, URL, wallet address | `DIGITAL_IDENTIFIER` |
| Medical | Diagnosis, prescription, medical record, blood type, test result | `MEDICAL` |
| Vehicle | License plate, VIN/chassis number, driver license | `VEHICLE_ID` |
| Demographic | Gender, age, nationality, religion, language | `DEMOGRAPHIC` |
| Finance | Salary, balance, transaction amount, credit score | `FINANCIAL` |

For the current checkpoint, these remain documented as out of scope.

## Validation Rule Design

Use three levels of evidence:

1. Format only:
   - Example: email address shape.
   - Useful when the format is distinctive.

2. Context plus format:
   - Example: `ma so thue: 0312345678`.
   - Best default for numeric identifiers because bare numbers are ambiguous.

3. Context plus format plus checksum/official validation:
   - Best when official rules are stable and easy to implement.
   - Should be a helper function, not only regex.

Current recommendation: most Vietnamese numeric identifiers should use level 2
until official validation rules are confirmed.

## Presentation Guidance

For mentor review, present this as:

1. Current pipeline detects 8 evaluable PII types, mapped from 23 dataset labels.
2. The dataset contains many more labels, but those are intentionally out of
   current scope.
3. Regex works surprisingly well for structured identifiers and addresses.
4. NER helps names, but causes false positives and slower runtime.
5. The next high-value improvement is not more broad regex; it is decision
   logging, targeted error mining, and confirmed Vietnam-specific validation.

