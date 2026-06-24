"""Tests for the reusable English/Vietnamese language keep-filter.

Uses an injected detector so the tests need neither langdetect nor a model. One
optional test exercises the real langdetect backend when it is installed.
"""

import pytest

from src.pipeline.Datasets.language import (
    ALLOWED_LANGUAGES,
    detect_language,
    is_allowed_language,
    is_mostly_latin,
    latin_letter_ratio,
)


def fake_detector(mapping, default=None):
    """Build a detector that returns a fixed code per exact text."""
    return lambda text: mapping.get(text, default)


def test_detect_language_uses_injected_detector():
    det = fake_detector({"hello": "en", "xin chao": "vi"})
    assert detect_language("hello", detector=det) == "en"
    assert detect_language("xin chao", detector=det) == "vi"


def test_detect_language_empty_is_none_without_calling_detector():
    def boom(_text):
        raise AssertionError("detector should not be called for empty text")

    assert detect_language("", detector=boom) is None
    assert detect_language("   ", detector=boom) is None


def test_is_allowed_keeps_en_and_vi_drops_others():
    det = fake_detector({"a": "en", "b": "vi", "c": "de", "d": "fr"})
    assert is_allowed_language("a", detector=det) is True
    assert is_allowed_language("b", detector=det) is True
    assert is_allowed_language("c", detector=det) is False
    assert is_allowed_language("d", detector=det) is False


def test_undetectable_policy_default_strict_drops():
    det = fake_detector({}, default=None)  # everything undetectable
    assert is_allowed_language("???", detector=det) is False
    assert is_allowed_language("???", detector=det, keep_undetectable=True) is True


def test_allowed_languages_is_en_vi():
    assert ALLOWED_LANGUAGES == ("en", "vi")


def test_custom_allowed_set():
    det = fake_detector({"x": "de"})
    assert is_allowed_language("x", allowed=("de",), detector=det) is True
    assert is_allowed_language("x", allowed=("en",), detector=det) is False


def test_is_mostly_latin_keeps_english_and_vietnamese():
    assert is_mostly_latin("Please send an email now.")
    # Vietnamese diacritics are LATIN code points -> kept.
    assert is_mostly_latin("Xin chào, đây là tiếng Việt với dấu.")
    # Obfuscated/adversarial English stays Latin -> kept (langdetect would not).
    assert is_mostly_latin("yes Please yes issue yes an yes api_call yes")


def test_is_mostly_latin_drops_non_latin_scripts():
    assert not is_mostly_latin("メールを送信してください。これは重要です。")  # Japanese
    assert not is_mostly_latin("请立即发送电子邮件，这很重要。")  # Chinese


def test_latin_ratio_no_letters_is_one():
    # Punctuation/digits only -> no letters -> treated as Latin (kept).
    assert latin_letter_ratio("12345 !!! ???") == 1.0


def test_real_langdetect_backend_if_available():
    pytest.importorskip("langdetect")
    assert detect_language("This is a clear English sentence about books.") == "en"
    assert is_allowed_language("Ich brauche dringend Ihre Hilfe mit dieser Frage.") is False
