"""Tile strings: positional forms via ZWJ, contextual forms via FVS chosen with HarfBuzz."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from mongol_text import MVS, ZWJ  # noqa: E402
from tile_forms import TileFormFinder, tile_string, units  # noqa: E402

FONT = ROOT / "fonts" / "NotoSansMongolian-Regular.woff2"


@pytest.fixture(scope="module")
def finder():
    return TileFormFinder(str(FONT))


def test_positional_tile_strings():
    us = units("ᠬᠠᠭᠠᠨ")
    assert [tile_string(us, i, 0) for i in range(5)] == [
        "ᠬ" + ZWJ,  # initial
        ZWJ + "ᠠ" + ZWJ,  # medial
        ZWJ + "ᠭ" + ZWJ,
        ZWJ + "ᠠ" + ZWJ,
        ZWJ + "ᠨ",  # final
    ]
    assert tile_string(units("ᠠ"), 0, 0) == "ᠠ"  # isolated


def test_mvs_tile_strings():
    us = units("ᠲᠠᠲᠠᠯᠭ" + MVS + "ᠠ")
    # the letter before MVS is final; the vowel after it is drawn after an MVS
    assert tile_string(us, 5, 0) == ZWJ + "ᠭ"
    assert tile_string(us, 6, 0) == MVS + "ᠠ"


def test_fvs_from_spelling_is_kept():
    us = units("ᠴᠢᠭ\u180c")
    assert us[2].fvs == 2
    assert tile_string(us, 2, 2) == ZWJ + "ᠭ\u180c"


def test_masculine_g_gets_dotted_tile(finder):
    # In ᠬᠠᠭᠠᠨ the medial g is the dotted (masculine) form; plain ZWJ context would give
    # the undotted default, FVS1 reproduces the in-word glyph.
    codes, exact = finder.codes("ᠬᠠᠭᠠᠨ")
    assert codes == [0, 0, 1, 0, 0]
    assert all(exact)


def test_feminine_initial_g_inside_ligature(finder):
    # ᠭᠡ is a ligature in the font; its components are recovered from GSUB.
    glyphs = finder.word_glyphs("ᠭᠡᠷ")
    assert all(g is not None for g in glyphs)
    codes, exact = finder.codes("ᠭᠡᠷ")
    assert all(exact)


def test_unsupported_fvs_is_a_visible_placeholder(finder):
    # This is why tiles are compared by ink: an FVS the font does not apply is drawn.
    assert finder.placeholders(ZWJ + "\u1820\u180f" + ZWJ)
    assert not finder.placeholders(ZWJ + "\u182d\u180b" + ZWJ)
    assert not finder.placeholders(MVS + "\u1820")


def test_no_tile_in_the_data_draws_a_placeholder(finder):
    import json

    for n in (4, 5, 6):
        d = json.loads((ROOT / "data" / f"words-{n}.json").read_text(encoding="utf-8"))
        for w in d["allowed"]:
            us = units(w)
            code = d["tiles"].get(w) or "".join(str(u.fvs) for u in us)
            for i in range(len(us)):
                t = tile_string(us, i, int(code[i]))
                assert not finder.placeholders(t), (w, i, t)
