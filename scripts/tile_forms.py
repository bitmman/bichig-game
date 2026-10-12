"""Pick, for every letter of a word, a stand-alone string that draws the same glyph.

The game shows each letter on its own tile. A tile is rendered as the letter with ZWJ on
the joining sides (initial ``c+ZWJ``, medial ``ZWJ+c+ZWJ``, final ``ZWJ+c``), which gives
the right *positional* form. Inside a real word, however, the font also applies
contextual rules (masculine/feminine g/h, dotted n before vowels, o/u after b, ...). We
reproduce those by adding a free variation selector (FVS1-4) to the tile string where
that yields the same glyph as in the shaped word.

The choice is made with HarfBuzz and the exact font file the game ships, so it does not
depend on any assumption about which FVS means what in a particular font version. The
JavaScript side rebuilds the same tile strings from the word and the per-letter FVS codes
(see ``tileString`` in core.js); ``tile_string`` below is the reference implementation.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from functools import lru_cache

import uharfbuzz as hb
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.ttLib import TTFont

from mongol_text import FVS, FVS_BY_INDEX, INDEX_BY_FVS, MVS, ZWJ, is_letter

# Glyphs that carry no ink and only mark invisible format characters.
_MARKER_PREFIXES = ("fvs", "mvs", "space", "zwj", "zwnj", "nnbsp", "uni200D", "uni180")


@dataclass
class Unit:
    letter: str
    fvs: int  # FVS index in the source spelling, 0 = none
    mvs_before: bool  # an MVS precedes this letter (final a/e after MVS)
    start: int  # code-unit index of the letter in the word
    end: int  # end of the letter + its FVS


def units(word: str) -> list[Unit]:
    out: list[Unit] = []
    pending_mvs = False
    for i, ch in enumerate(word):
        if is_letter(ch):
            out.append(Unit(ch, 0, pending_mvs, i, i + 1))
            pending_mvs = False
        elif ch in FVS and out:
            out[-1].fvs = INDEX_BY_FVS[ch]
            out[-1].end = i + 1
        elif ch == MVS:
            pending_mvs = True
    return out


def tile_string(us: list[Unit], i: int, fvs: int) -> str:
    """Stand-alone string for letter ``i``; must match ``tileString`` in core.js."""
    u = us[i]
    joins_prev = i > 0 and not u.mvs_before
    joins_next = i < len(us) - 1 and not us[i + 1].mvs_before
    s = MVS if u.mvs_before else ""
    s += ZWJ if joins_prev else ""
    s += u.letter + (FVS_BY_INDEX[fvs] if fvs else "")
    s += ZWJ if joins_next else ""
    s += MVS if i < len(us) - 1 and us[i + 1].mvs_before else ""
    return s


class TileFormFinder:
    def __init__(self, font_path: str):
        tt = TTFont(font_path)
        tt.flavor = None  # WOFF2 -> plain sfnt bytes for HarfBuzz
        buf = io.BytesIO()
        tt.save(buf)
        self.font = hb.Font(hb.Face(buf.getvalue()))
        self.glyph_order = tt.getGlyphOrder()
        self.ligatures = self._ligature_components(tt)
        self._glyph_set = tt.getGlyphSet()
        self._hmtx = tt["hmtx"]
        self._looks: dict[str, tuple] = {}

    def looks(self, name: str) -> tuple:
        """What a glyph looks like: its advance and decomposed outline.

        The font has several glyphs with different names but identical drawings (e.g.
        ``uni182C.G.medi`` and ``uni182D.G.medi``), so glyphs are compared by this key.
        """
        if name not in self._looks:
            pen = DecomposingRecordingPen(self._glyph_set)
            self._glyph_set[name].draw(pen)
            self._looks[name] = (self._hmtx[name][0], repr(pen.value))
        return self._looks[name]

    @staticmethod
    def _ligature_components(tt: TTFont) -> dict[str, list[list[str]]]:
        """ligature glyph -> possible component glyph sequences, from GSUB type 4."""
        comps: dict[str, list[list[str]]] = {}
        for lookup in tt["GSUB"].table.LookupList.Lookup:
            for st in lookup.SubTable:
                if lookup.LookupType == 7:
                    st = st.ExtSubTable
                if getattr(st, "LookupType", lookup.LookupType) != 4:
                    continue
                for first, ligs in st.ligatures.items():
                    for lig in ligs:
                        comps.setdefault(lig.LigGlyph, []).append([first, *lig.Component])
        return comps

    def _shape(self, text: str) -> list[tuple[str, int]]:
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        # Browsers lay Mongolian out in vertical-lr by shaping horizontally and rotating
        # the run, so shape left-to-right like they do.
        buf.direction = "ltr"
        hb.shape(self.font, buf, {})
        return [(self.glyph_order[g.codepoint], g.cluster) for g in buf.glyph_infos]

    @staticmethod
    def _inked(names: list[str]) -> list[str]:
        return [n for n in names if not n.startswith(_MARKER_PREFIXES)]

    @lru_cache(maxsize=None)
    def _tile_glyphs(self, text: str, letter_index: int) -> tuple[str, ...]:
        return tuple(self._inked([n for n, c in self._shape(text) if c == letter_index]))

    def word_glyphs(self, word: str) -> list[tuple[str, ...] | None]:
        """Per letter, the glyphs it is drawn with in ``word`` (None if undecidable)."""
        us = units(word)
        shaped = self._shape(word)
        starts = sorted({c for _, c in shaped})
        by_cluster: dict[int, list[str]] = {}
        for name, c in shaped:
            by_cluster.setdefault(c, []).append(name)
        result: list[tuple[str, ...] | None] = []
        for u in us:
            # cluster that contains this letter
            c = max(s for s in starts if s <= u.start)
            members = [v for v in us if c <= v.start and (v.start < min([s for s in starts if s > c] or [len(word)]))]
            glyphs = self._inked(by_cluster[c])
            if len(members) == 1:
                result.append(tuple(glyphs))
                continue
            # A ligature covering several letters: split it into its components.
            k = members.index(u)
            split = None
            if len(glyphs) == 1:
                for comp in self.ligatures.get(glyphs[0], []):
                    inked = self._inked(comp)
                    if len(inked) == len(members):
                        split = inked
                        break
            result.append((split[k],) if split else None)
        return result

    def codes(self, word: str) -> tuple[list[int], list[bool]]:
        """FVS code per letter for its tile, and whether that tile matches exactly."""
        us = units(word)
        targets = self.word_glyphs(word)
        codes, exact = [], []
        for i, u in enumerate(us):
            target = targets[i]
            chosen = None
            if target is not None:
                for fvs in dict.fromkeys([u.fvs, 0, 1, 2, 3, 4]):
                    text = tile_string(us, i, fvs)
                    li = text.index(u.letter)
                    got = self._tile_glyphs(text, li)
                    if [self.looks(g) for g in got] == [self.looks(g) for g in target]:
                        chosen = fvs
                        break
            codes.append(u.fvs if chosen is None else chosen)
            exact.append(chosen is not None)
        return codes, exact
