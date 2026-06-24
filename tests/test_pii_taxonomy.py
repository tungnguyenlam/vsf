"""Guards for the expanded Vietnamese PII entity taxonomy.

The mapping `VI_PII_LABEL_TO_PRESIDIO` is the single source of truth for which
dataset labels are treated as PII and what target type they get. These tests
pin the contract so the taxonomy can't silently drift.
"""

from src.pipeline.Datasets import (
    VI_PII_DROPPED_LABELS,
    VI_PII_LABEL_TO_PRESIDIO,
    VIE_PII_LABEL_TO_PRESIDIO,
)
from src.pipeline.Verifiers.LLMVerifier import ENTITY_TYPES

ORIGINAL_8 = {
    "PERSON",
    "DATE_TIME",
    "PHONE_NUMBER",
    "EMAIL_ADDRESS",
    "LOCATION",
    "BANK_ACCOUNT",
    "ORGANIZATION",
    "ID",
}
NEW_13 = {
    "CREDIT_CARD",
    "CRYPTO",
    "IP_ADDRESS",
    "URL",
    "CREDENTIAL",
    "FINANCIAL",
    "MEDICAL",
    "VEHICLE",
    "USERNAME",
    "NRP",
    "OCCUPATION",
    "EDUCATION",
    "PROPERTY",
}


def test_target_types_are_the_21_expected():
    assert set(VI_PII_LABEL_TO_PRESIDIO.values()) == ORIGINAL_8 | NEW_13


def test_all_new_types_are_used():
    used = set(VI_PII_LABEL_TO_PRESIDIO.values())
    assert NEW_13 <= used, NEW_13 - used


def test_dropped_labels_are_not_mapped():
    for label in VI_PII_DROPPED_LABELS:
        assert label not in VI_PII_LABEL_TO_PRESIDIO


def test_mapping_and_dropped_sets_are_disjoint():
    assert not (set(VI_PII_LABEL_TO_PRESIDIO) & VI_PII_DROPPED_LABELS)


def test_every_target_type_is_in_verifier_enum():
    """Ground-truth/verifier spans must never carry a type the LLM verifier's
    JSON-schema enum would reject."""
    enum = set(ENTITY_TYPES)
    assert set(VI_PII_LABEL_TO_PRESIDIO.values()) <= enum
    assert set(VIE_PII_LABEL_TO_PRESIDIO.values()) <= enum
    assert "MISC" in enum  # catch-all preserved


def test_id_folds_personal_identifier_numbers():
    for label in (
        "SO_CCCD_CMND",
        "SO_HO_CHIEU",
        "SO_GIAY_PHEP_LAI_XE",
        "SO_THE_BAO_HIEM_Y_TE",
        "MA_BENH_AN",
        "MA_SINH_VIEN",
    ):
        assert VI_PII_LABEL_TO_PRESIDIO[label] == "ID"
