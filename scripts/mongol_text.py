"""Traditional Mongolian (Hudum) text helpers shared by the word-list build and its tests.

Terminology used throughout the project:

* letter      -- a nominal Mongolian letter, U+1820..U+1842. This is the unit of the game.
* FVS         -- free variation selectors U+180B..U+180D and U+180F. They pick a glyph
                 variant of the preceding letter; they are part of the spelling but not letters.
* MVS         -- U+180E MONGOLIAN VOWEL SEPARATOR. Standard orthography uses it only
                 before a word-final a/e (e.g. ᠲᠠᠲᠠᠯᠭ᠎ᠠ). TM-Bench also uses it before
                 every suffix, where the standard character is U+202F (NNBSP).
* NNBSP       -- U+202F, the standard separator between a stem and a suffix.
* shape key   -- mongol-norm's ``MongolianShaper.normalize`` output. Two strings with the
                 same shape key render identically (UTN #57 shaping), so it is used to
                 compare and count words across differently-encoded sources.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

LETTER_FIRST = 0x1820
LETTER_LAST = 0x1842

FVS = frozenset("᠋᠌᠍᠏")
FVS_BY_INDEX = {1: "᠋", 2: "᠌", 3: "᠍", 4: "᠏"}
INDEX_BY_FVS = {v: k for k, v in FVS_BY_INDEX.items()}
MVS = "᠎"
NNBSP = " "
ZWJ = "‍"
ZWNJ = "‌"
A, E = "ᠠ", "ᠡ"

# Latin transliteration shown on tiles and keys. A simple, readable scheme close to the
# common Inner Mongolian / MNS romanisation: one Latin label per Unicode letter, so the
# labels disambiguate letters that share a glyph (o/u, ö/ü, t/d, ...).
TRANSLIT = {
    "ᠠ": "a", "ᠡ": "e", "ᠢ": "i", "ᠣ": "o", "ᠤ": "u",
    "ᠥ": "ö", "ᠦ": "ü", "ᠧ": "ē", "ᠨ": "n", "ᠩ": "ng",
    "ᠪ": "b", "ᠫ": "p", "ᠬ": "h", "ᠭ": "g", "ᠮ": "m",
    "ᠯ": "l", "ᠰ": "s", "ᠱ": "sh", "ᠲ": "t", "ᠳ": "d",
    "ᠴ": "ch", "ᠵ": "j", "ᠶ": "y", "ᠷ": "r", "ᠸ": "w",
    "ᠹ": "f", "ᠺ": "k", "ᠻ": "kh", "ᠼ": "ts", "ᠽ": "z",
    "ᠾ": "hh", "ᠿ": "zr", "ᡀ": "lh", "ᡁ": "zh", "ᡂ": "chi",
}
assert len(TRANSLIT) == LETTER_LAST - LETTER_FIRST + 1

# Letters used (almost) only in loanwords from Tibetan, Sanskrit, Chinese or Russian.
# Words containing them are valid guesses but are not picked as answers.
LOAN_LETTERS = frozenset("ᠧ") | frozenset(chr(c) for c in range(0x1838, LETTER_LAST + 1))

# A run of characters that can belong to one Mongolian word in running text. Private-use
# characters are included on purpose so a token containing them is rejected as a whole
# instead of being split into plausible-looking fragments.
TOKEN_RE = re.compile("[ᠠ-ᢪ᠋-᠏ ‌‍-]+")


def is_letter(ch: str) -> bool:
    return LETTER_FIRST <= ord(ch) <= LETTER_LAST


def letters(word: str) -> list[str]:
    """The nominal letters of ``word``; FVS, MVS, NNBSP, ZWJ/ZWNJ are not letters."""
    return [ch for ch in word if is_letter(ch)]


def translit(word_or_letters) -> str:
    return "".join(TRANSLIT[ch] for ch in word_or_letters if is_letter(ch))


def _mvs_is_vowel_separator(text: str, i: int) -> bool:
    """True if the MVS at ``text[i]`` is the standard one before a final a/e.

    That is: MVS, then a or e, then optional FVS, then end of word (end of text, an
    NNBSP or another MVS that starts a suffix).
    """
    j = i + 1
    if j >= len(text) or text[j] not in (A, E):
        return False
    j += 1
    while j < len(text) and text[j] in FVS:
        j += 1
    return j == len(text) or text[j] in (NNBSP, MVS)


def canonicalize_suffix_separators(token: str) -> str:
    """Rewrite TM-Bench style suffix separators (U+180E) to the standard U+202F.

    MVS before a word-final a/e is kept, so ``ᠲᠠᠲᠠᠯᠭ᠎ᠠ᠎ᠶ᠋ᠢᠨ`` becomes
    ``ᠲᠠᠲᠠᠯᠭ᠎ᠠ`` + NNBSP + ``ᠶ᠋ᠢᠨ``. Text already using NNBSP is returned unchanged.
    """
    if MVS not in token:
        return token
    out = []
    for i, ch in enumerate(token):
        if ch == MVS and not _mvs_is_vowel_separator(token, i):
            out.append(NNBSP)
        else:
            out.append(ch)
    return "".join(out)


def split_stem(token: str) -> tuple[str, list[str]]:
    """Split a running-text token into its stem and NNBSP-separated suffixes."""
    parts = canonicalize_suffix_separators(token).split(NNBSP)
    return parts[0], parts[1:]


def invalid_reason(word: str) -> str | None:
    """Why ``word`` cannot be a game word, or None if it is a valid single word.

    A valid word is one or more nominal letters, optionally with FVS after a letter and
    with MVS only in the standard position before a final a/e.
    """
    if not word:
        return "empty"
    if any(0xE000 <= ord(ch) <= 0xF8FF for ch in word):
        return "private-use character"
    if NNBSP in word:
        return "NNBSP suffix part"
    if any(ch.isspace() for ch in word):
        return "space (multi-word entry)"
    if ZWJ in word or ZWNJ in word:
        return "ZWJ/ZWNJ (suffix or fragment entry)"
    for ch in word:
        cp = ord(ch)
        if 0x1800 <= cp <= 0x18AF:
            continue
        if ch.isdigit():
            return "digit"
        if "CJK" in unicodedata.name(ch, ""):
            return "Chinese character"
        if "LATIN" in unicodedata.name(ch, ""):
            return "Latin character"
        return "other non-Mongolian character"
    for i, ch in enumerate(word):
        if is_letter(ch):
            continue
        if ch in FVS:
            if i == 0 or not (is_letter(word[i - 1]) or word[i - 1] in FVS):
                return "stray FVS"
            continue
        if ch == MVS:
            if i == 0 or not _mvs_is_vowel_separator(word, i):
                return "MVS suffix part"
            continue
        if 0x1843 <= ord(ch) <= 0x18AA:
            return "Todo/Sibe/Manchu letter"
        return "Mongolian punctuation or digit"
    return None


@lru_cache(maxsize=1)
def _shaper():
    from mongol_norm import MongolianShaper

    return MongolianShaper(locale="MNG")


def shaper_version() -> str:
    return _shaper().canonical_version


@lru_cache(maxsize=200_000)
def shape_key(word: str) -> str:
    """mongol-norm's normalized (glyph-shape) key for ``word``.

    U+180E and U+202F suffix separators produce the same key, as do encodings that only
    differ in letters sharing a glyph (o/u, ö/ü, t/d, ...). If mongol-norm cannot encode
    the shape it raises; we then fall back to the written-unit shape string, which is
    what normalize() would have encoded.
    """
    shaper = _shaper()
    try:
        return shaper.normalize(word)
    except ValueError:
        return "shape:" + shaper.shape_str(word)


def tokens(text: str) -> list[str]:
    """Mongolian word tokens of running text (punctuation, spaces and other scripts split)."""
    return TOKEN_RE.findall(text)
