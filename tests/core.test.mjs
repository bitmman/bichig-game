// Unit tests for core.js:  node --test tests/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  ABSENT, CORRECT, PRESENT, ZWJ, MVS, LATIN, LOAN,
  buildIndex, dailyIndex, dateKey, dayNumber, keyStates, letters, puzzleNumber,
  score, shareText, suggest, tileStrings, translit, units,
} from "../core.js";

const C = CORRECT, P = PRESENT, A = ABSENT;
const data = (n) => JSON.parse(readFileSync(new URL(`../data/words-${n}.json`, import.meta.url), "utf8"));

// ------------------------------------------------------------- letter extraction

test("letters skip FVS, MVS, NNBSP and ZWJ", () => {
  assert.deepEqual(letters("ᠲᠠᠲᠠᠯᠭ\u180eᠠ"), [..."ᠲᠠᠲᠠᠯᠭᠠ"]);
  assert.deepEqual(letters("ᠴᠢᠭ\u180c"), ["ᠴ", "ᠢ", "ᠭ"]);
  assert.deepEqual(letters("ᠤᠯᠤᠰ\u202fᠤᠨ"), [..."ᠤᠯᠤᠰᠤᠨ"]);
  assert.deepEqual(letters(ZWJ + "ᠤᠤ"), ["ᠤ", "ᠤ"]);
  assert.equal(translit("ᠬᠥᠮᠦᠨ"), "hömün");
});

test("alphabet covers U+1820..U+1842 and matches the Python table", () => {
  assert.equal(Object.keys(LATIN).length, 0x1842 - 0x1820 + 1);
  const py = readFileSync(new URL("../scripts/mongol_text.py", import.meta.url), "utf8");
  for (const [ch, lat] of Object.entries(LATIN)) {
    const esc = "\\u" + ch.codePointAt(0).toString(16).padStart(4, "0");
    assert.ok(py.includes(`"${esc}": "${lat}"`), `${esc} -> ${lat}`);
  }
  assert.equal(LOAN.size, 12);
});

test("units record FVS and MVS", () => {
  assert.deepEqual(units("ᠴᠢᠭ\u180c").map((u) => u.fvs), [0, 0, 2]);
  assert.deepEqual(units("ᠪᠠᠭ\u180eᠠ").map((u) => u.mvsBefore), [false, false, false, true]);
});

// ------------------------------------------------------------- tile forms

test("tile strings give positional forms with ZWJ", () => {
  assert.deepEqual(tileStrings("ᠬᠠᠭᠠᠨ"), ["ᠬ" + ZWJ, ZWJ + "ᠠ" + ZWJ, ZWJ + "ᠭ" + ZWJ, ZWJ + "ᠠ" + ZWJ, ZWJ + "ᠨ"]);
  assert.deepEqual(tileStrings("ᠠ"), ["ᠠ"]);
  // FVS codes from the data select the contextual variant (dotted masculine g)
  assert.equal(tileStrings("ᠬᠠᠭᠠᠨ", "00100")[2], ZWJ + "ᠭ\u180b" + ZWJ);
  // letter before MVS is final, the vowel after it follows an MVS
  const t = tileStrings("ᠪᠠᠭ\u180eᠠ");
  assert.equal(t[2], ZWJ + "ᠭ");
  assert.equal(t[3], MVS + "ᠠ");
});

// ------------------------------------------------------------- feedback

const L = (s) => [...s]; // latin test strings: one char = one letter

test("exact, present and absent", () => {
  assert.deepEqual(score(L("abcde"), L("abcde")), [C, C, C, C, C]);
  assert.deepEqual(score(L("edcba"), L("abcde")), [P, P, C, P, P]);
  assert.deepEqual(score(L("fghij"), L("abcde")), [A, A, A, A, A]);
});

test("repeated letter in guess, single in answer", () => {
  // answer has one 'a': only the first misplaced 'a' is yellow
  assert.deepEqual(score(L("aabbb"), L("cdaee")), [P, A, A, A, A]);
  // exact match takes priority over an earlier misplaced copy
  assert.deepEqual(score(L("aacda"), L("bbcda")), [A, A, C, C, C]);
  assert.deepEqual(score(L("xaxxa"), L("aqqqq")), [A, P, A, A, A]);
});

test("repeated letter in answer", () => {
  assert.deepEqual(score(L("aqqqq"), L("xaxxa")), [P, A, A, A, A]);
  assert.deepEqual(score(L("aaqqq"), L("xaxxa")), [P, C, A, A, A]);
  assert.deepEqual(score(L("aaaqq"), L("xaxxa")), [P, C, A, A, A]);
  assert.deepEqual(score(L("qaaaa"), L("xaxxa")), [A, C, A, A, C]);
});

test("feedback works on Mongolian letters and ignores FVS/MVS", () => {
  // ᠬᠠᠭᠠᠨ (hagan) vs ᠭᠠᠵᠠᠷ (gajar): a, a correct; g present once
  assert.deepEqual(score("ᠭᠠᠵᠠᠷ", "ᠬᠠᠭᠠᠨ"), [P, C, A, C, A]);
  assert.deepEqual(score("ᠪᠠᠭ\u180eᠠ", "ᠪᠠᠭᠠ"), [C, C, C, C]);
});

test("keyboard keeps the best state per letter", () => {
  const g = ["abc", "cab"];
  const st = keyStates(g.map((x) => x), [[A, P, A], [C, A, A]].map((s) => s));
  // letters() keeps only Mongolian letters, so use Mongolian words here instead
  const words = ["ᠭᠠᠵᠠᠷ", "ᠬᠠᠭᠠᠨ"];
  const s2 = keyStates(words, words.map((w) => score(w, "ᠬᠠᠭᠠᠨ")));
  assert.equal(s2["ᠭ"], C);
  assert.equal(s2["ᠵ"], A);
  assert.equal(s2["ᠬ"], C);
  assert.deepEqual(st, {});
});

// ------------------------------------------------------------- daily word

test("date keys use the local calendar date", () => {
  assert.equal(dateKey(new Date(2026, 9, 12, 0, 0, 1)), "2026-10-12");
  assert.equal(dateKey(new Date(2026, 9, 12, 23, 59, 59)), "2026-10-12");
  assert.equal(dayNumber("2026-10-13") - dayNumber("2026-10-12"), 1);
  // across a DST change (calendar math, not 24h arithmetic)
  assert.equal(dayNumber("2027-03-15") - dayNumber("2027-03-14"), 1);
  assert.equal(puzzleNumber("2026-10-12"), 1);
});

test("daily word is deterministic and does not repeat within the list", () => {
  const idx = buildIndex(data(5));
  const n = idx.answers.length;
  assert.equal(dailyIndex("2026-10-12", n), 0);
  assert.equal(dailyIndex("2026-10-12", n), dailyIndex("2026-10-12", n));
  const seen = new Set();
  const start = dayNumber("2026-10-12");
  for (let d = 0; d < n; d++) {
    const k = new Date(Date.UTC(1970, 0, 1 + start + d)).toISOString().slice(0, 10);
    seen.add(dailyIndex(k, n));
  }
  assert.equal(seen.size, n);
  // dates before launch still map into range
  const i = dailyIndex("2020-01-01", n);
  assert.ok(i >= 0 && i < n);
});

test("every length has a valid daily answer that is an allowed guess", () => {
  for (const n of [4, 5, 6]) {
    const idx = buildIndex(data(n));
    const { word } = idx.answers[dailyIndex(dateKey(), idx.answers.length)];
    assert.equal(letters(word).length, n);
    assert.equal(idx.allowed.get(letters(word).join("")), word);
  }
});

// ------------------------------------------------------------- suggestions and sharing

test("suggests a word differing only in look-alike letters", () => {
  const idx = buildIndex({ length: 4, answers: [], allowed: ["ᠬᠣᠲᠠ"], tiles: {} });
  assert.equal(suggest(letters("ᠬᠤᠲᠠ"), idx), "ᠬᠣᠲᠠ"); // u typed for o
  assert.equal(suggest(letters("ᠬᠤᠳᠠ"), idx), "ᠬᠣᠲᠠ"); // u/o and d/t
  assert.equal(suggest(letters("ᠬᠤᠯᠠ"), idx), null);
});

test("share text has no letters and mirrors the vertical board", () => {
  const scores = [[A, P, A, A, A], [C, C, C, C, C]];
  const txt = shareText({ scores, won: true, length: 5, puzzle: 3 });
  const lines = txt.split("\n");
  assert.equal(lines[0], "Bichig ᠪᠢᠴᠢᠭ #3 · 5 · 2/6");
  assert.deepEqual(lines.slice(1), ["⬜🟩", "🟨🟩", "⬜🟩", "⬜🟩", "⬜🟩"]);
  assert.ok(![...txt].some((c) => c >= "ᠠ" && c <= "ᡂ" && !"ᠪᠢᠴᠢᠭ".includes(c)));
  const lost = shareText({ scores: Array(6).fill([A, A, A, A]), won: false, length: 4, practice: true, hint: true });
  assert.match(lost.split("\n")[0], /practice · 4 · X\/6 💡$/);
});
