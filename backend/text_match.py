"""Matching quoted words against what someone said, in any of the app's scripts.

Used during a call (a fact must quote the person) and after it (the grounding
check). It compares words, not meaning, and needs no model call.

This file stays plain ASCII: Indian-script ranges are written as code points.
"""

from __future__ import annotations

import re

# Devanagari and Telugu, as code points. Their vowel signs are combining marks,
# which a plain word pattern would split words on.
_INDIC_RANGES = f"{chr(0x0900)}-{chr(0x097F)}{chr(0x0C00)}-{chr(0x0C7F)}"
# The danda and double danda (the Devanagari full stops) sit inside that range but are
# punctuation: counted as letters, "tak" followed by a danda did not match "tak", and every
# short Hindi quote was refused on a real call.
_DANDAS = f"{chr(0x0964)}{chr(0x0965)}"
_NON_WORD = re.compile(rf"[{_DANDAS}]+|[^\w{_INDIC_RANGES}]+")
_NUMBER = re.compile(r"\d[\d,]*")

# Share of the quoted words that must appear in the line they are quoted from.
QUOTE_MATCH = 0.6
# Quotes this short must appear word for word.
SHORT_QUOTE_WORDS = 3


def words(text: str) -> list[str]:
    """Lower-cased words, ignoring punctuation."""
    return [w for w in _NON_WORD.split(text.casefold()) if w]


def quote_in_line(quote: str, line: str, threshold: float = QUOTE_MATCH) -> bool:
    """Whether most of the quoted words appear in the line. A short quote (three words
    or fewer) must appear in full: on a real call, a made-up three-word "will look at
    the issue" passed because two of its words were in "what is the issue?"."""
    quoted = words(quote)
    if not quoted:
        return False
    said = set(words(line))
    found = sum(w in said for w in quoted)
    if len(quoted) <= SHORT_QUOTE_WORDS:
        return found == len(quoted)
    return found / len(quoted) >= threshold


def numbers(text: str) -> set[int]:
    """Numbers written with digits, in any script, ignoring thousands separators."""
    found = set()
    for match in _NUMBER.findall(text):
        digits = match.replace(",", "")
        if digits:
            found.add(int(digits))
    return found
