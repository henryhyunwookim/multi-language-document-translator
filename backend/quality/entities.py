"""Conservative, language-aware checks for numbers and protected identifiers."""
from collections import Counter
import re
import unicodedata


def numeric_tokens(text: str) -> Counter:
    """Normalize Unicode digits without guessing ambiguous decimal separators."""
    normalized = unicodedata.normalize('NFKC', text)
    return Counter(re.findall(r'\d+(?:[.,]\d+)*', normalized))


def numeric_conversion_candidate(source: str, target: str) -> bool:
    """Only send plausible localization differences to the entity specialist.

    A bare identifier changing from 42 to 43 is still a deterministic failure.
    Dates, spelled-out quantities, scales and decimal conventions require
    semantic evidence, never automatic acceptance based on this heuristic.
    """
    text = unicodedata.normalize('NFKC', source + '\n' + target).lower()
    # Spelled-out quantities may introduce/remove digit tokens in any language.
    # Route them for evidence rather than maintaining an English-only lexicon.
    if sum(numeric_tokens(source).values()) != sum(numeric_tokens(target).values()):
        return True
    units = r'万|萬|亿|億|千|百|年|月|日|時|时|년|월|일|시|만|억|천|백|\b(?:million|billion|thousand|hundred|january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec|once|twice|one|two|three|four|five|six|seven|eight|nine|ten|first|second|third|am|pm)\b'
    return bool(re.search(units, text) or re.search(r'\d[.,:/-]\d', text))
