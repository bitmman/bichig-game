// End-to-end check in headless Chromium: plays full games, checks feedback colours,
// hint, share text, stats, practice mode, offline reload and Mongolian shaping, and
// saves screenshots to docs/screenshots/.
//
//   npm run test:e2e        (needs the `playwright` package and a Chromium build)
import { createRequire } from "node:module";
import http from "node:http";
import { readFileSync, mkdirSync, existsSync, statSync } from "node:fs";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import * as core from "../../core.js";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const ROOT = fileURLToPath(new URL("../../", import.meta.url));
const SHOTS = join(ROOT, "docs", "screenshots");
const DAY = "2026-10-12";
const NOW = new Date(`${DAY}T10:00:00`);
const failures = [];
const notes = [];
const check = (cond, msg) => { if (!cond) failures.push(msg); return cond; };
const data = (n) => core.buildIndex(JSON.parse(readFileSync(join(ROOT, "data", `words-${n}.json`), "utf8")));

// ------------------------------------------------------------------ static server

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".json": "application/json",
  ".woff2": "font/woff2", ".svg": "image/svg+xml", ".webmanifest": "application/manifest+json", ".css": "text/css" };
function serve() {
  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
    if (p.endsWith("/")) p += "index.html";
    const file = normalize(join(ROOT, p));
    if (!file.startsWith(ROOT) || !existsSync(file) || statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { "content-type": TYPES[extname(file)] || "application/octet-stream", "cache-control": "no-cache" });
    res.end(readFileSync(file));
  });
  return new Promise((ok) => server.listen(0, "127.0.0.1", () => ok({ server, url: `http://127.0.0.1:${server.address().port}/` })));
}

// ------------------------------------------------------------------ helpers

const PHONE = { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true };
const DESKTOP = { viewport: { width: 1280, height: 860 }, deviceScaleFactor: 1 };

async function open(browser, url, { device = PHONE, settings, colorScheme = "light", seenHelp = true } = {}) {
  const ctx = await browser.newContext({ ...device, colorScheme, reducedMotion: "reduce" });
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: url.replace(/\/$/, "") });
  const page = await ctx.newPage();
  page.errors = [];
  page.on("pageerror", (e) => page.errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error") page.errors.push(m.text()); });
  await page.clock.setFixedTime(NOW);
  await page.addInitScript(([s, h]) => {
    if (sessionStorage.getItem("init")) return; // only on the first load of this context
    sessionStorage.setItem("init", "1");
    if (h) localStorage.setItem("bichig:v1:seenHelp", "true");
    if (s) localStorage.setItem("bichig:v1:settings", JSON.stringify(s));
  }, [settings, seenHelp]);
  await page.goto(url);
  await page.waitForSelector("#keyboard .key");
  await page.waitForSelector("#board .col");
  await page.evaluate(() => document.fonts.load('40px "Noto Sans Mongolian"', "ᠠ"));
  return { ctx, page };
}

async function type(page, word) {
  for (const ch of core.letters(word)) await page.click(`#keyboard .key[data-letter="${ch}"]`);
}

async function guess(page, word) {
  await type(page, word);
  await page.click('#keyboard .key[data-action="enter"]');
  await page.waitForTimeout(60);
}

/** Tile colour classes of every submitted column. */
const boardStates = (page) => page.$$eval("#board .col", (cols) => cols.map((c) =>
  [...c.querySelectorAll(".tile")].map((t) => ["correct", "present", "absent"].find((s) => t.classList.contains(s)) || null)));

/** Wrong guesses with a mix of green/yellow/grey against the answer (deterministic). */
function decoys(idx, answer, count) {
  const al = core.letters(answer).join("");
  const pool = [...idx.allowed.entries()].filter(([ls]) => ls !== al).map(([, w]) => {
    const s = core.score(w, answer);
    return { w, c: s.filter((x) => x === core.CORRECT).length, p: s.filter((x) => x === core.PRESENT).length };
  }).sort((x, y) => (x.w < y.w ? -1 : 1));
  const good = pool.filter((d) => d.c >= 1 && d.c + d.p >= 2 && d.c + d.p <= 4);
  const out = [];
  // take every k-th candidate so the decoys differ from each other
  const step = Math.max(1, Math.floor(good.length / count));
  for (let i = 0; i < good.length && out.length < count; i += step) out.push(good[i].w);
  for (const d of pool) if (out.length < count && !out.includes(d.w)) out.push(d.w);
  return out;
}

async function verifyColours(page, guesses, answer, label) {
  const states = await boardStates(page);
  guesses.forEach((g, i) => {
    const expected = core.score(g, answer);
    check(JSON.stringify(states[i]) === JSON.stringify(expected), `${label}: column ${i + 1} colours ${states[i]} != ${expected}`);
  });
}

async function shot(page, name) {
  await page.waitForTimeout(150);
  await page.screenshot({ path: join(SHOTS, name) });
  notes.push(`screenshot ${name}`);
}

// ------------------------------------------------------------------ shaping checks (in page)

async function shapingChecks(page, words) {
  const r = await page.evaluate(async (words) => {
    const { tileStrings, letters } = await import("./core.js");
    const out = { fontLoaded: document.fonts.check('40px "Noto Sans Mongolian"', "ᠠ"), joined: [], forms: {}, advance: { total: 0, match: 0, bad: [] } };
    const box = document.createElement("div");
    box.style.cssText = "position:absolute;left:-9999px;top:0;font-family:'Noto Sans Mongolian';font-size:40px;line-height:1";
    document.body.append(box);
    const vspan = (text) => {
      const s = document.createElement("span");
      s.style.cssText = "writing-mode:vertical-lr;display:inline-block;white-space:nowrap";
      s.textContent = text;
      box.append(s);
      return s;
    };
    // 1. joined words are shaped: shorter than the same letters forced apart with ZWNJ
    for (const w of words.slice(0, 40)) {
      const joined = vspan(w).getBoundingClientRect().height;
      const apart = vspan(letters(w).join("\u200c")).getBoundingClientRect().height;
      out.joined.push({ w, joined, apart });
    }
    // 2. positional forms: init / medi / fina / isol of each letter draw different pixels
    const cv = document.createElement("canvas");
    cv.width = 120; cv.height = 120;
    const cx = cv.getContext("2d", { willReadFrequently: true });
    const pix = (t) => {
      cx.clearRect(0, 0, 120, 120);
      cx.font = '60px "Noto Sans Mongolian"';
      cx.fillText(t, 20, 80);
      const d = cx.getImageData(0, 0, 120, 120).data;
      let h = 0;
      for (let i = 3; i < d.length; i += 4) h = (h * 31 + (d[i] > 127 ? 1 : 0) * (i + 1)) >>> 0;
      return h;
    };
    const Z = "\u200d";
    for (let cp = 0x1820; cp <= 0x1842; cp++) {
      const c = String.fromCodePoint(cp);
      const f = [pix(c), pix(c + Z), pix(Z + c + Z), pix(Z + c)];
      out.forms[c] = new Set(f).size;
    }
    // 3. tiles draw the same glyph as the letter inside the shaped word: compare each
    //    tile's advance with the advance of that letter's range in the joined word.
    //    Letters merged into one ligature glyph report the ligature's box, so they are
    //    counted separately.
    const data = await (await fetch("data/words-5.json")).json();
    const isFvs = (c) => /[\u180b-\u180d\u180f]/.test(c);
    const range = (node, a, b) => { const rg = document.createRange(); rg.setStart(node, a); rg.setEnd(node, b); return rg.getBoundingClientRect(); };
    out.advance.ligature = 0;
    for (const w of words) {
      const tn = vspan(w).firstChild;
      const tiles = tileStrings(w, data.tiles[w]);
      const spans = [];
      for (let i = 0; i < w.length; i++) {
        if (w[i] < "\u1820" || w[i] > "\u1842") continue;
        let e = i + 1;
        while (e < w.length && isFvs(w[e])) e++;
        spans.push([i, e]);
      }
      const rects = spans.map(([a, b]) => range(tn, a, b));
      rects.forEach((r, i) => {
        // Chromium splits a ligature's advance evenly between its letters
        const same = (j) => rects[j] && Math.abs(rects[j].height - r.height) < 0.02;
        if (same(i - 1) || same(i + 1)) { out.advance.ligature++; return; }
        const t = tiles[i];
        const li = [...t].findIndex((c) => c >= "\u1820" && c <= "\u1842");
        let te = li + 1;
        while (te < t.length && isFvs(t[te])) te++;
        const alone = range(vspan(t).firstChild, li, te).height;
        out.advance.total++;
        if (Math.abs(r.height - alone) < 0.6) out.advance.match++;
        else if (out.advance.bad.length < 8) out.advance.bad.push([w, i, +r.height.toFixed(1), +alone.toFixed(1)]);
      });
    }
    box.remove();
    return out;
  }, words);
  check(r.fontLoaded, "Noto Sans Mongolian is not loaded");
  const unjoined = r.joined.filter((j) => !(j.joined < j.apart * 0.97));
  check(unjoined.length === 0, `joined words not shorter than isolated letters: ${JSON.stringify(unjoined.slice(0, 3))}`);
  const flat = Object.entries(r.forms).filter(([, n]) => n < 2).map(([c]) => core.LATIN[c]);
  check(flat.length <= 3, `letters without distinct positional forms: ${flat}`);
  const rate = r.advance.match / r.advance.total;
  check(rate > 0.97, `tile advance match rate ${rate}`);
  notes.push(`shaping: font loaded=${r.fontLoaded}; ${r.joined.length} joined words all shorter than isolated letters ` +
    `(mean ratio ${(r.joined.reduce((s, j) => s + j.joined / j.apart, 0) / r.joined.length).toFixed(2)}); ` +
    `letters with >=2 distinct positional forms: ${35 - flat.length}/35 (single-form: ${flat.join(", ") || "none"}); ` +
    `tile advance equals in-word advance for ${r.advance.match}/${r.advance.total} letters ` +
    `(${r.advance.ligature} letters in adjacent equal-advance pairs, i.e. possible font ligatures, not measurable this way)` +
    (r.advance.bad.length ? `; e.g. mismatches ${JSON.stringify(r.advance.bad.slice(0, 4))}` : ""));
}

// ------------------------------------------------------------------ scenarios

async function dailyWin(browser, url) {
  const idx = data(5);
  const answer = idx.answers[core.dailyIndex(DAY, idx.answers.length)].word;
  const { ctx, page } = await open(browser, url);
  const [d1, d2] = decoys(idx, answer, 2);
  await guess(page, d1);
  await verifyColours(page, [d1], answer, "daily win");
  // keyboard colours follow the best state of each letter
  const ks = core.keyStates([d1], [core.score(d1, answer)]);
  for (const [ch, s] of Object.entries(ks)) {
    const cls = await page.$eval(`#keyboard .key[data-letter="${ch}"]`, (k) => k.className);
    check(cls.includes(s), `key ${core.LATIN[ch]} should be ${s}: ${cls}`);
  }
  await guess(page, d2);
  // mid-game screenshot with a partly typed third guess
  await type(page, core.letters(answer).slice(0, 3).join(""));
  await shot(page, "phone-daily-playing.png");
  for (let i = 0; i < 3; i++) await page.click('#keyboard .key[data-action="back"]');
  await guess(page, answer);
  await verifyColours(page, [d1, d2, answer], answer, "daily win");
  await page.waitForSelector("#dlg-stats[open]");
  const stats = await page.$$eval("#stats-body .stats-grid b", (b) => b.map((x) => x.textContent));
  check(JSON.stringify(stats) === JSON.stringify(["1", "100", "1", "1"]), `stats after a win: ${stats}`);
  await shot(page, "phone-daily-stats.png");
  await page.click("#dlg-stats [data-close]");
  const resultText = await page.textContent("#result");
  check(resultText.includes(core.translit(answer)), "result card shows the answer");
  await page.click("#share-btn");
  await page.waitForTimeout(100);
  const shared = await page.evaluate(() => document.body.dataset.lastShare);
  const expected = core.shareText({ scores: [d1, d2, answer].map((g) => core.score(g, answer)), won: true, length: 5, puzzle: 1, url });
  check(shared === expected, `share text:\n${shared}\n!=\n${expected}`);
  let clip = null;
  try { clip = await page.evaluate(() => navigator.clipboard.readText()); } catch { /* no clipboard in this mode */ }
  if (clip !== null) check(clip === expected, "clipboard holds the share text");
  check(!core.letters(shared.replace("ᠪᠢᠴᠢᠭ", "")).length, "share text contains no Mongolian letters (no spoilers)");
  notes.push(`daily #1 (5 letters) won in 3; share text:\n${shared}`);
  await shot(page, "phone-daily-won.png");

  // reload: the finished daily game is restored, not replayed
  await page.reload();
  await page.waitForSelector("#result");
  const restored = await boardStates(page);
  check(restored.filter((c) => c[0]).length === 3, "finished daily game restored after reload");

  // practice mode on the same page
  await page.click("#mode-practice");
  await page.waitForSelector('#mode-practice[aria-pressed="true"]');
  const practice = await page.evaluate(() => JSON.parse(localStorage.getItem("bichig:v1:practice:5")));
  check(practice && practice.status === "playing" && practice.guesses.length === 0, "practice game started");
  const [p1] = decoys(idx, practice.answer, 1);
  await guess(page, p1);
  await guess(page, practice.answer);
  await verifyColours(page, [p1, practice.answer], practice.answer, "practice");
  await page.waitForSelector("#next-btn");
  const pshare = await (await page.click("#share-btn"), page.evaluate(() => document.body.dataset.lastShare));
  check(pshare.startsWith("Bichig ᠪᠢᠴᠢᠭ practice · 5 · 2/6"), `practice share header: ${pshare.split("\n")[0]}`);
  await page.click("#next-btn");
  const after = await boardStates(page);
  check(after.every((c) => c.every((s) => s === null)), "new practice word starts with an empty board");
  const statsAfter = await page.evaluate(() => JSON.parse(localStorage.getItem("bichig:v1:stats:5")));
  check(statsAfter.played === 1, "practice games do not change daily stats");
  check(page.errors.length === 0, `page errors: ${page.errors}`);
  await ctx.close();
  return answer;
}

async function dailyLoseWithHint(browser, url) {
  const idx = data(6);
  const ans = idx.answers[core.dailyIndex(DAY, idx.answers.length)];
  const { ctx, page } = await open(browser, url, { settings: { length: 6, latin: true, theme: "dark", contrast: false }, colorScheme: "dark" });
  const wrong = decoys(idx, ans.word, 6);
  for (let i = 0; i < 4; i++) {
    check(!(await page.$("#hint-btn")), `no hint before guess 4 (after ${i})`);
    await guess(page, wrong[i]);
  }
  await page.waitForSelector("#hint-btn");
  await page.click("#hint-btn");
  const hint = await page.textContent(".hint");
  check(hint.includes(ans.meaning), `hint shows the Chinese meaning: ${hint}`);
  await shot(page, "phone-hint-latin-dark.png");
  await guess(page, wrong[4]);
  await guess(page, wrong[5]);
  await verifyColours(page, wrong, ans.word, "daily lose");
  await page.waitForSelector("#dlg-stats[open]");
  const stats = await page.$$eval("#stats-body .stats-grid b", (b) => b.map((x) => x.textContent));
  check(JSON.stringify(stats) === JSON.stringify(["1", "0", "0", "0"]), `stats after a loss: ${stats}`);
  await page.click("#dlg-stats [data-close]");
  const result = await page.textContent("#result");
  check(result.includes("The word was") && result.includes(core.translit(ans.word)), "loss reveals the answer");
  await page.click("#share-btn");
  const shared = await page.evaluate(() => document.body.dataset.lastShare);
  check(shared.split("\n")[0] === "Bichig ᠪᠢᠴᠢᠭ #1 · 6 · X/6 💡", `loss share header: ${shared.split("\n")[0]}`);
  check(shared.split("\n").length === 1 + 6 + 1, "loss share grid has one line per letter");
  notes.push(`daily #1 (6 letters) lost with hint; share text:\n${shared}`);
  await shot(page, "phone-lost-dark.png");
  check(page.errors.length === 0, `page errors: ${page.errors}`);
  await ctx.close();
}

async function inputChecks(browser, url) {
  const idx = data(5);
  const { ctx, page } = await open(browser, url, { device: DESKTOP });
  // not enough letters
  await type(page, "ᠬᠠᠭ");
  await page.click('#keyboard .key[data-action="enter"]');
  check((await page.textContent("#toast")).includes("Not enough letters"), "toast for a short guess");
  for (let i = 0; i < 3; i++) await page.keyboard.press("Backspace");
  // not a word
  await type(page, "ᠬᠬᠬᠬᠬ");
  await page.keyboard.press("Enter");
  check((await page.textContent("#toast")).includes("Not in word list"), "toast for a non-word");
  for (let i = 0; i < 5; i++) await page.keyboard.press("Backspace");
  // look-alike suggestion: an allowed word with o, typed with u instead
  let target = null;
  for (const [ls, w] of idx.allowed) {
    const swapped = ls.replace("ᠣ", "ᠤ");
    if (swapped !== ls && !idx.allowed.has(swapped) && core.suggest([...swapped], idx) === w) { target = { w, swapped }; break; }
  }
  if (check(target, "found a word to test look-alike suggestions")) {
    await type(page, target.swapped);
    await page.keyboard.press("Enter");
    const t = await page.textContent("#toast");
    check(t.includes("Did you mean") && t.includes(core.translit(target.w)), `suggestion toast: ${t}`);
    await page.click("#toast button");
    const typed = await page.$$eval("#board .col.current .tile .lat", (l) => l.map((x) => x.textContent).join(""));
    check(typed === core.translit(target.w), `suggestion fills in ${core.translit(target.w)}, got ${typed}`);
    await page.keyboard.press("Enter");
    await page.waitForTimeout(80);
    check((await boardStates(page))[0][0] !== null, "suggested word accepted as a guess");
  }
  // physical keyboard with Latin keys (Shift+O = ö etc.)
  const word = [...idx.allowed.values()].find((w) => core.letters(w).some((c) => c === "ᠥ") && core.letters(w).every((c) => "aeioungbphgmlstdjyr".includes(core.LATIN[c]) || ["ö", "ü", "ch", "sh", "ng"].includes(core.LATIN[c])));
  const keys = { "ö": "Shift+O", "ü": "Shift+U", "ng": "Shift+N", "sh": "Shift+S", "ch": "c" };
  for (const c of core.letters(word)) await page.keyboard.press(keys[core.LATIN[c]] || core.LATIN[c]);
  const typed = await page.$$eval("#board .col.current .tile .g", (g) => g.map((x) => x.textContent.replace(/[^ᠠ-ᡂ]/g, "")).join(""));
  check(typed === core.letters(word).join(""), `physical keyboard typed ${core.translit(word)}`);
  await page.keyboard.press("Enter");
  await page.waitForTimeout(80);
  await shot(page, "desktop.png");
  // positional tile forms and joined words, measured in the browser
  const sample = idx.answers.slice(0, 300).map((a) => a.word);
  await shapingChecks(page, sample);
  check(page.errors.length === 0, `page errors: ${page.errors}`);
  await ctx.close();
}

async function helpAndOffline(browser, url) {
  const { ctx, page } = await open(browser, url, { seenHelp: false });
  await page.waitForSelector("#dlg-help[open]");
  await shot(page, "phone-help.png");
  await page.click("#dlg-help [data-close]");
  // offline after the first load
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.waitForFunction(async () => (await (await caches.open("bichig-v1")).keys()).length >= 9, null, { timeout: 15000 });
  await page.reload(); // let the service worker control the page
  await page.waitForSelector("#keyboard .key");
  await ctx.setOffline(true);
  await page.reload();
  await page.waitForSelector("#board .col");
  const ok = await page.evaluate(() => document.fonts.check('40px "Noto Sans Mongolian"', "ᠠ") && document.querySelectorAll("#board .tile").length === 30);
  check(ok, "game loads offline after the first visit");
  await page.click("#btn-settings");
  await page.click('#set-length button[data-len="4"]');
  await page.waitForFunction(() => document.querySelectorAll("#board .tile").length === 24);
  notes.push("offline reload works, including switching to a not-yet-opened word length");
  await page.click("#dlg-settings [data-close]");
  await ctx.setOffline(false);
  check(page.errors.length === 0, `page errors: ${page.errors}`);
  await ctx.close();
}

// ------------------------------------------------------------------ main

mkdirSync(SHOTS, { recursive: true });
const { server, url } = await serve();
const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
try {
  await dailyWin(browser, url);
  await dailyLoseWithHint(browser, url);
  await inputChecks(browser, url);
  await helpAndOffline(browser, url);
} catch (e) {
  failures.push(`exception: ${e.stack || e}`);
} finally {
  await browser.close();
  server.close();
}
console.log(notes.join("\n"));
if (failures.length) {
  console.error(`\n${failures.length} FAILED:\n- ${failures.join("\n- ")}`);
  process.exit(1);
}
console.log("\nall end-to-end checks passed");
