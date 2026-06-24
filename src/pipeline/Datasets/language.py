"""Language detection + an English/Vietnamese keep-filter for dataset conversion.

Single source of truth for "which languages do we keep" in safety_v0. Several
sources are multilingual (e.g. ``deepset/prompt-injections`` mixes EN+DE,
``Meddies/meddies-pii`` is broadly multilingual) but the project only keeps
English and Vietnamese. Converters call :func:`is_allowed_language` to drop
everything else.

The detector backend is configuration: ``langdetect`` by default, but any
``Callable[[str], Optional[str]]`` returning an ISO 639-1 code (or ``None`` when
undetectable) can be injected, so call sites never hard-depend on the vendor and
tests need no model. ``langdetect`` is imported lazily on first real use.
"""

from __future__ import annotations

import unicodedata
from typing import Callable, Optional, Sequence

# Languages safety_v0 keeps. Everything else is dropped at conversion.
ALLOWED_LANGUAGES: tuple = ("en", "vi")

# langdetect is non-deterministic unless its factory seed is fixed; pin it so
# the same text always resolves the same way (reproducible conversions).
_LANGDETECT_SEED = 42

DetectorFn = Callable[[str], Optional[str]]


def _langdetect_detect(text: str) -> Optional[str]:
    """Default detector backed by ``langdetect``; ``None`` if undetectable."""
    from langdetect import DetectorFactory, detect
    from langdetect.lang_detect_exception import LangDetectException

    DetectorFactory.seed = _LANGDETECT_SEED
    try:
        return detect(text)
    except LangDetectException:
        return None


def detect_language(text: str, *, detector: Optional[DetectorFn] = None) -> Optional[str]:
    """Return the ISO 639-1 code for ``text``, or ``None`` if undetectable.

    Empty/whitespace text is undetectable (``None``). ``detector`` overrides the
    default ``langdetect`` backend (for tests or a different engine).
    """
    if not text or not text.strip():
        return None
    detect = detector or _langdetect_detect
    return detect(text)


def latin_letter_ratio(text: str) -> float:
    """Fraction of alphabetic characters that are Latin script (1.0 if no letters).

    English and Vietnamese are both Latin-script (Vietnamese diacritics are
    ``LATIN ... WITH ...`` code points), so both score ~1.0. CJK / Arabic /
    Cyrillic / Khmer / etc. score low. Use this instead of word-level language
    detection on adversarial or obfuscated text (e.g. prompt-injection payloads),
    where ``langdetect`` misfires and would drop legitimate English.
    """
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    latin = sum(1 for c in letters if unicodedata.name(c, "").startswith("LATIN"))
    return latin / len(letters)


def is_mostly_latin(text: str, *, threshold: float = 0.5) -> bool:
    """True if at least ``threshold`` of the text's letters are Latin script."""
    return latin_letter_ratio(text) >= threshold


def is_allowed_language(
    text: str,
    *,
    allowed: Sequence[str] = ALLOWED_LANGUAGES,
    detector: Optional[DetectorFn] = None,
    keep_undetectable: bool = False,
) -> bool:
    """True if ``text`` is detected as one of ``allowed`` languages.

    ``keep_undetectable`` controls the policy for text the detector cannot
    classify (empty, too short, no alpha features). Default ``False`` is strict:
    if we cannot confirm the language is allowed, we drop it. Set ``True`` to keep
    undetectable rows (e.g. when most are short allowed-language snippets).
    """
    lang = detect_language(text, detector=detector)
    if lang is None:
        return keep_undetectable
    return lang in allowed
