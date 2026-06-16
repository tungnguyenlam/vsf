"""Tests for the mechanical-format recognizers (URL, IP_ADDRESS, CRYPTO,
CREDIT_CARD) added to the high-precision Vietnamese regex recognizer.

These run the recognizer directly (no Presidio AnalyzerEngine needed): build the
patterns, call ``analyze`` on a string, and check the value spans and types.
"""

from src.pipeline.Recognizers.CustomPatternRecognizer import (
    CustomPatternRecognizer,
    luhn_check,
)


def _recognizer():
    # build_patterns() returns a list with one VietnameseContextRegexRecognizer.
    return CustomPatternRecognizer().build_patterns()[0]


def _detect(text):
    rec = _recognizer()
    results = rec.analyze(text, entities=None, nlp_artifacts=None)
    return [(r.entity_type, text[r.start : r.end]) for r in results]


def test_supported_entities_include_new_types():
    rec = _recognizer()
    for t in ("URL", "IP_ADDRESS", "CRYPTO", "CREDIT_CARD"):
        assert t in rec.supported_entities


def test_url_detected():
    found = _detect("Trang chủ: https://vidu.vn/path?a=1 và www.test.com.vn nhé")
    urls = {v for t, v in found if t == "URL"}
    assert "https://vidu.vn/path?a=1" in urls
    assert "www.test.com.vn" in urls


def test_url_drops_trailing_punctuation():
    found = _detect("Liên hệ www.shop.vn, hoặc https://a.vn/p?x=1.")
    urls = {v for t, v in found if t == "URL"}
    assert "www.shop.vn" in urls  # trailing comma trimmed
    assert "https://a.vn/p?x=1" in urls  # trailing period trimmed


def test_ipv4_detected_and_octet_validated():
    found = _detect("Máy chủ 192.168.10.255 kết nối; 999.1.1.1 không hợp lệ")
    ips = {v for t, v in found if t == "IP_ADDRESS"}
    assert "192.168.10.255" in ips
    # 999 is not a valid octet -> the leading 99 won't form a full valid IP here.
    assert "999.1.1.1" not in ips


def test_ipv6_and_mac_detected():
    found = _detect("IPv6 2001:0db8:85a3:0000:0000:8a2e:0370:7334 MAC 00:1A:2B:3C:4D:5E")
    ips = {v for t, v in found if t == "IP_ADDRESS"}
    assert "2001:0db8:85a3:0000:0000:8a2e:0370:7334" in ips
    assert "00:1A:2B:3C:4D:5E" in ips


def test_ipv6_compressed():
    found = _detect("Địa chỉ ::1 và fe80::1ff:fe23:4567:890a trong mạng")
    ips = {v for t, v in found if t == "IP_ADDRESS"}
    assert "fe80::1ff:fe23:4567:890a" in ips


def test_crypto_addresses():
    text = (
        "ETH 0x52908400098527886E0F7030069857D2E4169EE7 "
        "BTC 1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2 "
        "LTC Ld2nGJ1V8XfYJ8a7tQYdN4MoQ9k3pZ1xqe"
    )
    cryptos = {v for t, v in _detect(text) if t == "CRYPTO"}
    assert "0x52908400098527886E0F7030069857D2E4169EE7" in cryptos
    assert "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2" in cryptos
    assert any(v.startswith("Ld") for v in cryptos)


def test_credit_card_grouped_and_context():
    found = _detect("Số thẻ tín dụng: 4111 1111 1111 1111, CVV: 123")
    by_type = {}
    for t, v in found:
        by_type.setdefault(t, set()).add(v)
    assert "4111 1111 1111 1111" in by_type.get("CREDIT_CARD", set())
    assert "123" in by_type.get("CREDIT_CARD", set())  # CVV folds into CREDIT_CARD


def test_luhn_check():
    # Reusable validator hook (kept available even though no bare-card pattern
    # ships by default — see CustomPatternRecognizer for why).
    assert luhn_check("4111111111111111")  # valid Visa test number
    assert luhn_check("4111 1111 1111 1111")  # separators ignored
    assert luhn_check("378282246310005")  # valid 15-digit Amex test number
    assert not luhn_check("4111111111111112")  # one digit off -> fails
    assert not luhn_check("123")  # too short


def test_validator_hook_filters_matches():
    """A pattern's validator must drop matches it rejects."""
    from src.pipeline.Recognizers.CustomPatternRecognizer import (
        ContextRegexPattern,
        VietnameseContextRegexRecognizer,
    )

    pat = ContextRegexPattern(
        name="even_only",
        entity_type="ID",
        regex=r"(?<!\d)(?P<value>\d{3})(?!\d)",
        score=0.5,
        validator=lambda v: int(v) % 2 == 0,
    )
    rec = VietnameseContextRegexRecognizer([pat])
    text = "codes 100 and 101 and 102"
    got = [text[r.start : r.end] for r in rec.analyze(text, None, None)]
    assert got == ["100", "102"]  # 101 rejected by validator


def test_value_only_spans_no_label_leak():
    """Spans must cover the value, not the Vietnamese context label."""
    found = _detect("mã bảo mật thẻ: 4321")
    cvv = [v for t, v in found if t == "CREDIT_CARD"]
    assert cvv == ["4321"]
