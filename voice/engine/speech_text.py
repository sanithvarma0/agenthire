"""Makes the agent's text safe to speak.

A model occasionally emits a character from an unrelated script (a Chinese
character in the middle of a Telugu sentence was seen in an eval run), which a
Telugu or Hindi voice cannot pronounce. `clean_for_speech` keeps only the
characters a voice in this app can say: English letters, digits, common
punctuation, the rupee sign, and the Devanagari and Telugu scripts.

This file stays plain ASCII: the allowed ranges are written as code points.
"""

from __future__ import annotations

import re

# Curly quotes, dashes, the ellipsis, the danda and double danda, as code points.
_PUNCTUATION_CODES = (0x2018, 0x2019, 0x201C, 0x201D, 0x2013, 0x2014, 0x2026, 0x0964, 0x0965)
_ALLOWED = (
    r"A-Za-z0-9 .,!?;:'()\-"
    + '"'
    + "".join(chr(code) for code in _PUNCTUATION_CODES)
    + chr(0x20B9)  # rupee sign
    + f"{chr(0x0900)}-{chr(0x097F)}"  # Devanagari
    + f"{chr(0x0C00)}-{chr(0x0C7F)}"  # Telugu
    + chr(0x200C) + chr(0x200D)  # zero-width joiners used in Indian scripts
    + chr(10)  # line break
)
_NOT_SPEAKABLE = re.compile(f"[^{_ALLOWED}]+")
_SPACES = re.compile(r"[ \t]{2,}")


_SCRIPT_RANGES = {
    "te": (0x0C00, 0x0C7F),  # Telugu
    "hi": (0x0900, 0x097F),  # Devanagari, used for Hindi
}
# Share of a line's letters that must be in one script to call it that language.
SCRIPT_SHARE = 0.5


def script_language(text: str) -> str | None:
    """The language code whose script most of the letters are in, or None when
    the line is mostly English letters or too short to tell."""
    letters = [c for c in text if c.isalpha() or 0x0900 <= ord(c) <= 0x0C7F]
    if len(letters) < 3:
        return None
    for code, (low, high) in _SCRIPT_RANGES.items():
        if sum(low <= ord(c) <= high for c in letters) / len(letters) >= SCRIPT_SHARE:
            return code
    return None


def indian_script(text: str) -> str | None:
    """Which Indian script the line is in, ignoring English words: a reply such as
    "haan ji, Al-Noor Electricals, boliye" is Hindi even though most of its letters
    are English. None when there are no Indian-script letters, or they are mixed."""
    counts = {code: sum(low <= ord(c) <= high for c in text) for code, (low, high) in _SCRIPT_RANGES.items()}
    code, most = max(counts.items(), key=lambda item: item[1])
    if most == 0 or most / sum(counts.values()) < SCRIPT_SHARE:
        return None
    return code


def words_in_script(text: str, code: str) -> int:
    """How many words have letters in that language's script. Unlike `script_language`,
    a short word counts too, so a brief real reply can be told from a stray one."""
    low, high = _SCRIPT_RANGES[code]
    return sum(any(low <= ord(c) <= high for c in word) for word in text.split())


# Kannada (U+0C80 to U+0CFF) is laid out in parallel with Telugu (U+0C00 to U+0C7F).
_KANNADA = (0x0C80, 0x0CFF)
_KANNADA_TO_TELUGU = -0x80


def normalise_transcript(text: str) -> str:
    """Fix a known speech-to-text slip before anything reads the transcript.

    In auto-detect mode, short colloquial Telugu is sometimes written in Kannada
    script (seen on a real call: Telugu came back as Kannada letters). This app
    only handles Telugu, Hindi and English, so Kannada letters are moved to the
    matching Telugu letters, which the parallel layout makes exact.
    """
    import unicodedata

    def convert(char: str) -> str:
        code = ord(char)
        if _KANNADA[0] <= code <= _KANNADA[1]:
            telugu = chr(code + _KANNADA_TO_TELUGU)
            if unicodedata.category(telugu) != "Cn":  # only where Telugu has that letter
                return telugu
        return char

    return "".join(convert(c) for c in text)


_SENTENCE_END = re.compile("[.!?" + chr(0x0964) + chr(0x0965) + "]")
SAME_QUESTION_SHARE = 0.6


def _words(text: str) -> list[str]:
    from backend.text_match import words

    return words(text)


def last_question(text: str) -> str:
    """The final sentence of `text` if it is a question, else an empty string."""
    stripped = text.rstrip()
    if not stripped.endswith("?"):
        return ""
    body = stripped[:-1]
    ends = [m.end() for m in _SENTENCE_END.finditer(body)]
    return stripped[(ends[-1] if ends else 0):].strip()


def same_question(first: str, second: str) -> bool:
    """Whether two questions ask the same thing: most of the shorter one's words are in the other."""
    a, b = set(_words(first)), set(_words(second))
    if min(len(a), len(b)) < 3:
        return False
    return len(a & b) / min(len(a), len(b)) >= SAME_QUESTION_SHARE


def keep_final_draft(reply: str) -> str:
    """When a reply holds a draft and then a rewrite of it, keep only the rewrite.

    Seen in an eval run: the model wrote a question with an English note to
    itself, then the same question again on a new line. Both would have been
    spoken. If a later paragraph asks a question an earlier one already asked,
    only the last paragraph is kept.
    """
    paragraphs = [p.strip() for p in reply.splitlines() if p.strip()]
    if len(paragraphs) < 2:
        return reply
    final = paragraphs[-1]
    final_questions = [q.strip() + "?" for q in final.split("?")[:-1]]
    for earlier in paragraphs[:-1]:
        for question in [q.strip() + "?" for q in earlier.split("?")[:-1]]:
            if any(same_question(question, other) for other in final_questions):
                return final
    return reply


def drop_repeated_question(reply: str, previous_reply: str) -> str:
    """Remove a closing question the agent already ended its previous turn with.

    On a real call the agent answered the provider's questions and tacked the
    same "can you come and check?" onto every answer. The answer is kept; the
    question is dropped. If the reply is nothing but that question, it is kept.
    """
    question = last_question(reply)
    if not question or not same_question(question, last_question(previous_reply)):
        return reply
    rest = reply.rstrip()[: len(reply.rstrip()) - len(question)].strip()
    if not rest or _restates(rest, previous_reply):
        # Asked to repeat, the agent says it all again; dropping the question then
        # left dead air on a real call, with both sides waiting.
        return reply
    return rest


def _restates(text: str, previous: str) -> bool:
    """Whether most of `text`'s words were already in `previous`, i.e. a repeat, not a new answer."""
    new, old = set(_words(text)), set(_words(previous))
    return bool(new) and len(new & old) / len(new) >= SAME_QUESTION_SHARE


# A JSON field such as "name":"available" or "said as": "...": a model writing
# its tool call into the reply instead of making it (seen on a real call).
_JSON_FIELD = re.compile(r'"[A-Za-z_ ]{1,30}"\s*:\s*(?:"[^"]*"|-?\d+(?:\.\d+)?|true|false|null)')
_JSON_LEFTOVERS = re.compile(r"^[\s{},\[\]]+|[\s{},\[\]]+$")


# A tool call written out as a function call, as one came out in an eval run:
# "functions.record fact( )" (the underscore was lost on the way).
_CALL_TEXT = re.compile(r"\bfunctions\s*\.\s*[a-z_ ]+\([^)]*\)?", re.IGNORECASE)


def has_leaked_tool_text(text: str) -> bool:
    return bool(_JSON_FIELD.search(text) or _CALL_TEXT.search(text))


def strip_leaked_tool_text(text: str) -> str:
    """Remove tool-call fields a model wrote into its reply, so they are never spoken."""
    if not has_leaked_tool_text(text):
        return text
    text = _CALL_TEXT.sub(" ", text)
    lines = []
    for line in text.splitlines():
        cleaned = _JSON_FIELD.sub(" ", line)
        cleaned = re.sub(r"[{}]", " ", cleaned)
        cleaned = re.sub(r"^[\s,]+|(?<=\s),(?=\s)|[\s,]+$", " ", cleaned)  # commas left between removed fields
        cleaned = _JSON_LEFTOVERS.sub("", cleaned).strip()
        if cleaned:
            lines.append(cleaned)
    return _SPACES.sub(" ", " ".join(lines)).strip()


_LATIN = (0x0041, 0x024F)
_SUPPORTED_SCRIPTS = [_LATIN, _SCRIPT_RANGES["te"], _SCRIPT_RANGES["hi"]]
MIN_LETTERS = 1  # a one-letter Telugu acknowledgement is clear speech


def is_unclear(text: str) -> bool:
    """Whether a transcript has no words at all to go on. Run after `normalise_transcript`.
    A line in the wrong script is not unclear: see `in_wrong_script`."""
    letters = [c for c in text if c.isalpha() or unicodedata_is_mark(c)]
    return len(letters) < MIN_LETTERS


def in_wrong_script(text: str) -> bool:
    """Whether speech-to-text wrote some of the line in a script this app does not use.
    In auto-detect mode, Hindi and Telugu speech came back in Gujarati, Punjabi, Odia,
    Bengali and Malayalam script on real calls. The line still goes to the model, which
    can read it by its sound; this only tells it what happened."""
    letters = [c for c in text if c.isalpha() and ord(c) >= 0x0900]
    return any(not any(low <= ord(c) <= high for low, high in _SUPPORTED_SCRIPTS) for c in letters)


def unicodedata_is_mark(char: str) -> bool:
    import unicodedata

    return unicodedata.category(char).startswith("M")


def clean_for_speech(text: str) -> str:
    """Remove characters a voice in this app cannot say, and tidy the spacing."""
    cleaned = _NOT_SPEAKABLE.sub(" ", text)
    return _SPACES.sub(" ", cleaned).strip()


def unspeakable_characters(text: str) -> str:
    """The characters `clean_for_speech` would remove, for reporting."""
    return "".join(_NOT_SPEAKABLE.findall(text)).strip()
