"""Unit tests for the Mongolian text handling used by the word-list build."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_wordlist import chinese_word_counts, count_frequencies, daily_order, Word  # noqa: E402
from mongol_text import (  # noqa: E402
    MVS,
    NNBSP,
    ZWJ,
    canonicalize_suffix_separators,
    invalid_reason,
    letters,
    shape_key,
    split_stem,
    tokens,
    translit,
)

ULUS = "ᠤᠯᠤᠰ"  # ulus "country"
GEN_UN = "ᠤᠨ"  # genitive suffix
TATALGA = "ᠲᠠᠲᠠᠯᠭ" + MVS + "ᠠ"  # tatalga, standard MVS before final a


# --------------------------------------------------------------- normalization


def test_suffix_separator_forms_have_the_same_key():
    tm_bench = ULUS + MVS + GEN_UN  # TM-Bench: U+180E before the suffix
    lotus = ULUS + NNBSP + GEN_UN  # standard: U+202F before the suffix
    assert shape_key(tm_bench) == shape_key(lotus)


def test_suffix_separator_canonicalized_to_nnbsp():
    assert canonicalize_suffix_separators(ULUS + MVS + GEN_UN) == ULUS + NNBSP + GEN_UN
    assert split_stem(ULUS + MVS + GEN_UN) == (ULUS, [GEN_UN])
    assert split_stem(ULUS + NNBSP + GEN_UN) == (ULUS, [GEN_UN])


def test_mvs_before_final_a_is_kept():
    assert canonicalize_suffix_separators(TATALGA) == TATALGA
    # TM-Bench writes both the vowel separator and the suffix separator as U+180E
    tm_bench = TATALGA + MVS + "ᠶ\u180bᠢᠨ"
    stem, suffixes = split_stem(tm_bench)
    assert stem == TATALGA
    assert suffixes == ["ᠶ\u180bᠢᠨ"]
    assert shape_key(stem) == shape_key(TATALGA)


def test_mvs_before_final_a_with_fvs_is_kept():
    word = "ᠬᠡᠵᠢᠶ" + MVS + "ᠡ"
    assert canonicalize_suffix_separators(word) == word
    # a suffix starting with a/e is not a final vowel
    assert canonicalize_suffix_separators("ᠤᠭᠤᠲᠠ" + MVS + "ᠠ\u180bᠴᠠ") == "ᠤᠭᠤᠲᠠ" + NNBSP + "ᠠ\u180bᠴᠠ"


def test_stem_from_tm_bench_matches_dictionary_word():
    # The frequency of a suffixed TM-Bench token is credited to the dictionary stem.
    stem, _ = split_stem(ULUS + MVS + GEN_UN)
    assert shape_key(stem) == shape_key(ULUS)


def test_letters_sharing_a_glyph_collide():
    assert shape_key("ᠤᠯᠤᠰ") == shape_key("ᠣᠯᠣᠰ")  # o/u
    assert shape_key("ᠬᠣᠲᠠ") == shape_key("ᠬᠤᠳᠠ")  # o/u and t/d
    assert shape_key("ᠡᠨᠳᠡ") == shape_key("ᠠᠳᠠ")  # different letter counts, same glyphs
    assert shape_key("ᠭᠡᠷ") != shape_key("ᠭᠠᠷ")  # feminine/masculine g differ


def test_tokens_split_on_punctuation_and_spaces():
    text = "ᠡᠨᠡ ᠨᠢ ᠮᠢᠨᠦ᠂ ᠤᠯᠤᠰ\u180eᠤᠨ abc 中文 ᠃"
    assert tokens(text) == ["ᠡᠨᠡ", "ᠨᠢ", "ᠮᠢᠨᠦ", ULUS + MVS + GEN_UN]


# --------------------------------------------------------------- letter extraction


def test_letters_exclude_format_characters():
    assert letters(TATALGA) == list("ᠲᠠᠲᠠᠯᠭᠠ")
    assert letters("ᠴᠢᠭ\u180c") == ["ᠴ", "ᠢ", "ᠭ"]  # FVS2 is not a letter
    assert letters(ULUS + NNBSP + GEN_UN) == list("ᠤᠯᠤᠰᠤᠨ")
    assert letters(ZWJ + "ᠤᠤ") == ["ᠤ", "ᠤ"]


def test_translit():
    assert translit("ᠬᠥᠮᠦᠨ") == "hömün"
    assert translit("ᠮᠣᠩᠭᠣᠯ") == "monggol"
    assert translit(TATALGA) == "tatalga"


@pytest.mark.parametrize(
    "word, reason",
    [
        ("ᠬᠥᠮᠦᠨ", None),
        (TATALGA, None),
        ("ᠴᠢᠭ\u180c", None),
        ("", "empty"),
        ("ᠬᠥᠮᠦᠨ ᠪᠣᠯ", "space (multi-word entry)"),
        (ULUS + NNBSP + GEN_UN, "NNBSP suffix part"),
        (ULUS + MVS + GEN_UN, "MVS suffix part"),
        (ZWJ + "ᠤᠤ", "ZWJ/ZWNJ (suffix or fragment entry)"),
        ("ᠤᠯᠤᠰa", "Latin character"),
        ("ᠤᠯᠤᠰ1", "digit"),
        ("ᠤᠯᠤᠰ国", "Chinese character"),
        ("ᠤᠯ\ue25aᠰ", "private-use character"),
        ("\u180bᠤᠯᠤᠰ", "stray FVS"),
        (MVS + "ᠠ", "MVS suffix part"),
        ("ᠤᠯᡃᠰ", "Todo/Sibe/Manchu letter"),
        ("ᠤᠯᠤᠰ᠂", "Mongolian punctuation or digit"),
    ],
)
def test_invalid_reason(word, reason):
    assert invalid_reason(word) == reason


# --------------------------------------------------------------- frequency counting


def test_count_frequencies_merges_encodings(tmp_path):
    data = [
        {"text": f"{ULUS} {ULUS}{MVS}{GEN_UN} ᠣᠯᠣᠰ᠃", "label": 1},
        {"nested": {"choices": [f"{TATALGA}{MVS}ᠶ\u180bᠢᠨ", "国家", f"{MVS}ᠤ\u180b"]}},
    ]
    p = tmp_path / "x.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    counts, stats = count_frequencies([p])
    # ulus, ulus+gen and olos (same glyphs) all count for the same shape
    assert counts[shape_key(ULUS)] == 3
    assert counts[shape_key(TATALGA)] == 1
    assert stats.tokens_with_mvs_suffix == 3  # incl. the suffix written as its own token
    assert stats.rejected["suffix written as a separate token"] == 1


def test_chinese_word_counts_prefers_longest_match():
    counts = chinese_word_counts(["人民的人", "人员"], {"人民", "人", "人员"})
    assert counts["人民"] == 1 and counts["人"] == 1 and counts["人员"] == 1


def test_daily_order_is_deterministic_and_tiered():
    words = [Word(f"w{i}", f"l{i:04d}", f"k{i}", 1000 - i, ["x"], i) for i in range(450)]
    a = daily_order(list(words), 5)
    b = daily_order(list(words), 5)
    assert [w.word for w in a] == [w.word for w in b]
    assert sorted(w.word for w in a[:200]) == sorted(w.word for w in words[:200])
    assert [w.word for w in a[:200]] != [w.word for w in words[:200]]
