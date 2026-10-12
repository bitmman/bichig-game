// Bichig game logic. Pure functions only (no DOM), shared by index.html and the tests.

export const ZWJ = "\u200d";
export const MVS = "\u180e";
export const FVS = ["", "\u180b", "\u180c", "\u180d", "\u180f"]; // index = FVS number

// Traditional alphabet order, with the Latin label shown on tiles and keys.
// Must match TRANSLIT in scripts/mongol_text.py.
export const ALPHABET = [
  ["\u1820", "a"], ["\u1821", "e"], ["\u1822", "i"], ["\u1823", "o"], ["\u1824", "u"],
  ["\u1825", "ö"], ["\u1826", "ü"], ["\u1827", "ē"], ["\u1828", "n"], ["\u1829", "ng"],
  ["\u182a", "b"], ["\u182b", "p"], ["\u182c", "h"], ["\u182d", "g"], ["\u182e", "m"],
  ["\u182f", "l"], ["\u1830", "s"], ["\u1831", "sh"], ["\u1832", "t"], ["\u1833", "d"],
  ["\u1834", "ch"], ["\u1835", "j"], ["\u1836", "y"], ["\u1837", "r"], ["\u1838", "w"],
  ["\u1839", "f"], ["\u183a", "k"], ["\u183b", "kh"], ["\u183c", "ts"], ["\u183d", "z"],
  ["\u183e", "hh"], ["\u183f", "zr"], ["\u1840", "lh"], ["\u1841", "zh"], ["\u1842", "chi"],
];
export const LATIN = Object.fromEntries(ALPHABET);
// Loanword letters: valid in guesses, never in answers. Must match LOAN_LETTERS.
export const LOAN = new Set(["\u1827", ..."\u1838\u1839\u183a\u183b\u183c\u183d\u183e\u183f\u1840\u1841\u1842"]);

export const isLetter = (ch) => ch >= "\u1820" && ch <= "\u1842";

/** Nominal letters of a word; FVS, MVS, NNBSP and ZWJ are not letters. */
export const letters = (word) => [...word].filter(isLetter);

export const translit = (word) => letters(word).map((c) => LATIN[c]).join("");

/** Letters with the FVS that follows each and whether an MVS precedes it. */
export function units(word) {
  const out = [];
  let mvs = false;
  for (const ch of word) {
    if (isLetter(ch)) {
      out.push({ letter: ch, fvs: 0, mvsBefore: mvs });
      mvs = false;
    } else if (FVS.indexOf(ch) > 0 && out.length) {
      out[out.length - 1].fvs = FVS.indexOf(ch);
    } else if (ch === MVS) {
      mvs = true;
    }
  }
  return out;
}

/**
 * Stand-alone string that draws letter i in its positional form: ZWJ on each side that
 * joins a neighbour, plus an optional FVS for the contextual variant. Must match
 * tile_string() in scripts/tile_forms.py.
 */
export function tileString(us, i, fvs) {
  const u = us[i];
  const joinsPrev = i > 0 && !u.mvsBefore;
  const nextMvs = i < us.length - 1 && us[i + 1].mvsBefore;
  const joinsNext = i < us.length - 1 && !nextMvs;
  // The letter before an MVS is drawn in final form without the MVS: with no a/e after
  // it the font would draw the MVS as a visible placeholder box.
  return (u.mvsBefore ? MVS : "") + (joinsPrev ? ZWJ : "") + u.letter + FVS[fvs] + (joinsNext ? ZWJ : "");
}

/** Tile strings for every letter. `codes` (from data.tiles) overrides the FVS per letter. */
export function tileStrings(word, codes) {
  const us = units(word);
  return us.map((u, i) => tileString(us, i, codes ? Number(codes[i]) : u.fvs));
}

export const CORRECT = "correct";
export const PRESENT = "present";
export const ABSENT = "absent";

/**
 * Colour feedback for one guess. Two passes so repeated letters are handled like the
 * original game: exact matches first, then a letter is "present" only as many times as
 * it still occurs unmatched in the answer.
 */
export function score(guess, answer) {
  const g = Array.isArray(guess) ? guess : letters(guess);
  const a = Array.isArray(answer) ? answer : letters(answer);
  if (g.length !== a.length) throw new Error("length mismatch");
  const result = new Array(g.length).fill(ABSENT);
  const left = new Map();
  for (let i = 0; i < a.length; i++) {
    if (g[i] === a[i]) result[i] = CORRECT;
    else left.set(a[i], (left.get(a[i]) || 0) + 1);
  }
  for (let i = 0; i < g.length; i++) {
    if (result[i] === CORRECT) continue;
    const n = left.get(g[i]) || 0;
    if (n > 0) {
      result[i] = PRESENT;
      left.set(g[i], n - 1);
    }
  }
  return result;
}

const RANK = { [ABSENT]: 1, [PRESENT]: 2, [CORRECT]: 3 };

/** Best-known state of every letter, for colouring the keyboard. */
export function keyStates(guesses, scores) {
  const st = {};
  guesses.forEach((g, gi) => {
    letters(g).forEach((c, i) => {
      const s = scores[gi][i];
      if (!st[c] || RANK[s] > RANK[st[c]]) st[c] = s;
    });
  });
  return st;
}

// ------------------------------------------------------------------ daily word

/** The first daily puzzle (#1). */
export const EPOCH = "2026-10-12";

/** Local calendar date as YYYY-MM-DD (the daily word changes at local midnight). */
export function dateKey(date = new Date()) {
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}`;
}

/** Whole days since 1970-01-01 for a YYYY-MM-DD key (calendar days, DST-proof). */
export function dayNumber(key) {
  const [y, m, d] = key.split("-").map(Number);
  return Math.round(Date.UTC(y, m - 1, d) / 86400000);
}

/** Puzzle number (1 on EPOCH) for a date key. */
export const puzzleNumber = (key) => dayNumber(key) - dayNumber(EPOCH) + 1;

/**
 * Index into the answer list for a date key. The list is stored in daily order, so
 * consecutive days take consecutive entries and nothing repeats until the list wraps.
 */
export function dailyIndex(key, n) {
  return (((puzzleNumber(key) - 1) % n) + n) % n;
}

// ------------------------------------------------------------------ word list

/** Index the JSON data: allowed letter strings -> spelling, plus tile codes. */
export function buildIndex(data) {
  const allowed = new Map();
  for (const w of data.allowed) allowed.set(letters(w).join(""), w);
  return {
    length: data.length,
    answers: data.answers.map(([word, meaning]) => ({ word, meaning })),
    allowed,
    tiles: data.tiles || {},
  };
}

// Letters that can look the same in some positions. Used only to suggest a word when
// a guess is not in the list ("did you mean ...").
const CONFUSABLE = [["ᠣ", "ᠤ"], ["ᠥ", "ᠦ"], ["ᠲ", "ᠳ"], ["ᠠ", "ᠡ"]];
const CONF_GROUP = new Map();
CONFUSABLE.forEach((grp, gi) => grp.forEach((c) => CONF_GROUP.set(c, gi)));

/** An allowed word that differs from `guessLetters` only in confusable letters. */
export function suggest(guessLetters, index) {
  for (const [ls, word] of index.allowed) {
    const a = [...ls];
    if (a.length !== guessLetters.length) continue;
    let ok = true;
    for (let i = 0; i < a.length && ok; i++) {
      const g = guessLetters[i];
      ok = a[i] === g || (CONF_GROUP.has(g) && CONF_GROUP.get(g) === CONF_GROUP.get(a[i]));
    }
    if (ok) return word;
  }
  return null;
}

// ------------------------------------------------------------------ sharing

const SQUARE = { [CORRECT]: "🟩", [PRESENT]: "🟨", [ABSENT]: "⬜" };
const SQUARE_HC = { [CORRECT]: "🟧", [PRESENT]: "🟦", [ABSENT]: "⬜" };

/**
 * Spoiler-free result. The grid mirrors the board: each column is a guess (left to
 * right) and each line a letter position (top to bottom), like vertical Mongolian.
 */
export function shareText({ scores, won, maxGuesses = 6, length, puzzle, practice, hint, highContrast, url }) {
  const sq = highContrast ? SQUARE_HC : SQUARE;
  const head = `Bichig ᠪᠢᠴᠢᠭ ${practice ? "practice" : "#" + puzzle} · ${length} · ${won ? scores.length : "X"}/${maxGuesses}${hint ? " 💡" : ""}`;
  const lines = [];
  for (let i = 0; i < length; i++) lines.push(scores.map((s) => sq[s[i]]).join(""));
  return [head, ...lines, ...(url ? [url] : [])].join("\n");
}
