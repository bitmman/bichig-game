#!/usr/bin/env python3
"""Build the Bichig word lists from Lotus (dictionary) and TM-Bench (frequencies).

    pip install -r scripts/requirements.txt
    python scripts/build_wordlist.py            # downloads pinned sources into .cache/

Outputs (all deterministic for the pinned inputs):

    data/words-4.json, data/words-5.json, data/words-6.json   game data
    review/answers_for_review.csv                              answer list for native-speaker review
    review/wordlist_report.md                                  counts, drops and reasons

See README.md ("How the word list is built") for the rationale behind each step.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import random
import sys
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mongol_text import (  # noqa: E402
    FVS,
    LOAN_LETTERS,
    invalid_reason,
    letters,
    shape_key,
    shaper_version,
    split_stem,
    tokens,
    translit,
)

ROOT = Path(__file__).resolve().parent.parent

LOTUS_COMMIT = "165267736aa0e7777432984b2dd759abe0d6c5a0"
LOTUS_ZIP_URL = f"https://raw.githubusercontent.com/csdq777/Lotus/{LOTUS_COMMIT}/data.zip"
LOTUS_ZIP_SHA256 = "d0ee1b3088fa9327524e7b291acfac01ca81a6ae825a4181ef2e5d6866dff24a"
LOTUS_PASSWORD = b"Lotusdata"  # published in the Lotus README
TMBENCH_COMMIT = "9e151c6e3eabeda8cb07148e89ec6587ee0a9fe8"
TMBENCH_FILES = ["AG_News", "ARC", "CMMT", "HellaSwag", "MMLU", "MNLI", "MRPC", "QNLI", "RTE"]
TMBENCH_URL = f"https://raw.githubusercontent.com/gao1948083886/TM-Bench/{TMBENCH_COMMIT}/Data/{{}}.json"

LENGTHS = (4, 5, 6)
ANSWERS_PER_LENGTH = 1500
MIN_FREQUENCY = 2  # a single occurrence in TM-Bench is too weak a signal for an answer
DAILY_TIER = 200  # daily schedule: most common 200 words first (shuffled), then the next 200, ...
MAX_MEANINGS = 3
SHUFFLE_SEED = "bichig-daily-v1"
FONT = ROOT / "fonts" / "NotoSansMongolian-Regular.woff2"


# --------------------------------------------------------------------------- sources


def fetch(url: str, dest: Path) -> Path:
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"downloading {url}", file=sys.stderr)
        with urllib.request.urlopen(url) as r:  # noqa: S310 - pinned https URL
            data = r.read()
        dest.write_bytes(data)
    return dest


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_lotus(zip_path: Path) -> tuple[list[str], dict[str, list[str]], dict[str, list[str]], list[str]]:
    """Dictionary words (in file order), their Chinese meanings, the zh->mn dictionary,
    and the Chinese side of the Lotus training sentences.

    Everything is read in memory straight from the encrypted zip; nothing from the
    sentence files is written out. The Chinese sentences are only used to rank glosses.
    """
    words: list[str] = []
    meanings: dict[str, list[str]] = {}
    zh_to_mn: dict[str, list[str]] = {}
    with zipfile.ZipFile(zip_path) as z:
        for line in z.read("data/mn_zh_dict.jsonl", pwd=LOTUS_PASSWORD).decode("utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            w = entry["mn_word"]
            if w not in meanings:
                words.append(w)
                meanings[w] = []
            for zh in entry["zh_meanings"]:
                if zh not in meanings[w]:
                    meanings[w].append(zh)
        for line in z.read("data/zh_mn_dict.jsonl", pwd=LOTUS_PASSWORD).decode("utf-8").splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            zh_to_mn.setdefault(entry["zh_word"], []).extend(entry["mn_meanings"])
            for w in entry["mn_meanings"]:
                if w not in meanings:
                    words.append(w)
                    meanings[w] = []
                if entry["zh_word"] not in meanings[w]:
                    meanings[w].append(entry["zh_word"])
        train = json.loads(z.read("data/zh_mn_train.json", pwd=LOTUS_PASSWORD).decode("utf-8"))
    return words, meanings, zh_to_mn, [e["zh"] for e in train]


def iter_strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from iter_strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from iter_strings(v)


@dataclass
class FreqStats:
    strings: int = 0
    tokens: int = 0
    tokens_with_suffix: int = 0
    tokens_with_mvs_suffix: int = 0
    counted: int = 0
    rejected: collections.Counter = field(default_factory=collections.Counter)


def count_frequencies(paths: list[Path]) -> tuple[collections.Counter, FreqStats]:
    """Stem frequencies over all text fields of TM-Bench, keyed by mongol-norm shape key.

    TM-Bench separates suffixes with U+180E; those are rewritten to U+202F first so that
    the stem can be split off (``ᠤᠯᠤᠰ᠎ᠤᠨ`` counts for ``ᠤᠯᠤᠰ``). MVS before a final a/e
    stays part of the stem, as in Lotus.
    """
    counts: collections.Counter = collections.Counter()
    st = FreqStats()
    for path in paths:
        for s in iter_strings(json.loads(path.read_text(encoding="utf-8"))):
            st.strings += 1
            for tok in tokens(s):
                st.tokens += 1
                stem, suffixes = split_stem(tok)
                if suffixes:
                    st.tokens_with_suffix += 1
                    if "᠎" in tok and " " not in tok:
                        st.tokens_with_mvs_suffix += 1
                reason = invalid_reason(stem) if stem else "suffix written as a separate token"
                if reason:
                    st.rejected[reason] += 1
                    continue
                counts[shape_key(stem)] += 1
                st.counted += 1
    return counts, st


# --------------------------------------------------------------------------- analysis


@dataclass
class Word:
    word: str
    letters: str
    key: str
    freq: int
    meanings: list[str]
    order: int  # position in the dictionary file (stable tie-breaker)


def chinese_word_counts(texts: list[str], vocab: set[str]) -> collections.Counter:
    """Count Chinese words in ``texts`` by forward maximum matching against ``vocab``.

    Used only to rank the Lotus glosses of a word by how common they are (a dependency-free
    stand-in for a real segmenter). Characters outside the vocabulary count as themselves.
    """
    maxlen = min(8, max((len(v) for v in vocab), default=1))
    counts: collections.Counter = collections.Counter()
    for s in texts:
        i = 0
        while i < len(s):
            for n in range(min(maxlen, len(s) - i), 0, -1):
                if n == 1 or s[i : i + n] in vocab:
                    counts[s[i : i + n]] += 1
                    i += n
                    break
    return counts


def pick_meanings(word: str, meanings: list[str], zh_counts: collections.Counter, zh_to_mn: dict[str, list[str]]) -> str:
    """Up to MAX_MEANINGS Chinese glosses for the hint, most common first.

    Lotus lists glosses in no particular order. Rank them by how often the gloss occurs
    as a word in Chinese text, then prefer glosses for which this word is the first
    Mongolian translation, then shorter ones; glosses with "……" placeholders go last.
    """

    def rank(im):
        i, m = im
        back = zh_to_mn.get(m, [])
        pos = back.index(word) if word in back else 99
        return ("…" in m, -zh_counts[m], pos, len(m), i)

    return "；".join(m for _, m in sorted(enumerate(meanings), key=rank)[:MAX_MEANINGS])


def daily_order(answers: list[Word], length: int) -> list[Word]:
    """Daily schedule: frequency tiers of DAILY_TIER words, shuffled within each tier.

    ``answers`` is sorted by frequency, so early days use the most common words while the
    order inside a tier is not predictable from the frequency ranking.
    """
    rng = random.Random(f"{SHUFFLE_SEED}-{length}")
    out: list[Word] = []
    for i in range(0, len(answers), DAILY_TIER):
        tier = answers[i : i + DAILY_TIER]
        rng.shuffle(tier)
        out.extend(tier)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cache", type=Path, default=ROOT / ".cache", help="download directory")
    ap.add_argument("--lotus-zip", type=Path, help="local Lotus data.zip (skips download)")
    ap.add_argument("--tmbench-dir", type=Path, help="local TM-Bench Data/ directory (skips download)")
    ap.add_argument("--out", type=Path, default=ROOT / "data")
    ap.add_argument("--review", type=Path, default=ROOT / "review")
    ap.add_argument("--answers", type=int, default=ANSWERS_PER_LENGTH)
    args = ap.parse_args()

    lotus_zip = args.lotus_zip or fetch(LOTUS_ZIP_URL, args.cache / f"lotus-{LOTUS_COMMIT[:12]}" / "data.zip")
    if sha256(lotus_zip) != LOTUS_ZIP_SHA256:
        sys.exit(f"unexpected checksum for {lotus_zip}")
    if args.tmbench_dir:
        tm_paths = [args.tmbench_dir / f"{n}.json" for n in TMBENCH_FILES]
    else:
        tm_paths = [fetch(TMBENCH_URL.format(n), args.cache / f"tmbench-{TMBENCH_COMMIT[:12]}" / f"{n}.json") for n in TMBENCH_FILES]

    dict_words, meanings, zh_to_mn, zh_sentences = load_lotus(lotus_zip)
    freq, fst = count_frequencies(tm_paths)
    for path in tm_paths:  # TM-Bench CMMT has Chinese source sentences too
        zh_sentences.extend(iter_strings(json.loads(path.read_text(encoding="utf-8"))))
    zh_counts = chinese_word_counts(zh_sentences, set(zh_to_mn))

    # ---- validate dictionary entries
    dict_invalid: collections.Counter = collections.Counter()
    dict_invalid_examples: dict[str, list[str]] = collections.defaultdict(list)
    valid: list[Word] = []
    for i, w in enumerate(dict_words):
        reason = invalid_reason(w)
        if reason:
            dict_invalid[reason] += 1
            if len(dict_invalid_examples[reason]) < 3:
                dict_invalid_examples[reason].append(w)
            continue
        key = shape_key(w)
        valid.append(Word(w, "".join(letters(w)), key, freq.get(key, 0), meanings[w], i))

    by_key: dict[str, list[Word]] = collections.defaultdict(list)
    by_letters: dict[str, list[Word]] = collections.defaultdict(list)
    for w in valid:
        by_key[w.key].append(w)
        by_letters[w.letters].append(w)

    def collision_partners(w: Word) -> list[Word]:
        """Other dictionary words that render identically but are spelled differently."""
        return [o for o in by_key[w.key] if o.letters != w.letters]

    def ambiguous_encoding(w: Word) -> bool:
        """Same letters, but another spelling (FVS/MVS) that renders differently."""
        return any(o.key != w.key for o in by_letters[w.letters])

    from tile_forms import TileFormFinder, units  # needs uharfbuzz + fontTools

    tiles = TileFormFinder(str(FONT))

    args.out.mkdir(parents=True, exist_ok=True)
    args.review.mkdir(parents=True, exist_ok=True)
    report_rows = []
    review_rows = []
    collision_examples = []
    tile_stats = collections.Counter()

    for L in LENGTHS:
        same_len = [w for w in valid if len(w.letters) == L]
        # One spelling per letter string for guesses: the most frequent, then the simplest.
        allowed: dict[str, Word] = {}
        for w in sorted(same_len, key=lambda w: (-w.freq, sum(c in FVS for c in w.word), "᠎" in w.word, w.order)):
            allowed.setdefault(w.letters, w)

        drops: collections.Counter = collections.Counter()
        candidates: list[Word] = []
        seen_letters = set()
        for w in sorted(same_len, key=lambda w: (-w.freq, w.order)):
            if w.letters in seen_letters:
                drops["duplicate spelling of the same letters"] += 1
                continue
            seen_letters.add(w.letters)
            if set(w.letters) & LOAN_LETTERS:
                drops["loanword letter (ē, w, f, k, kh, ts, z, ...)"] += 1
            elif collision_partners(w):
                drops["glyph collision with another dictionary word"] += 1
                if len(collision_examples) < 40:
                    collision_examples.append((w, collision_partners(w)))
            elif ambiguous_encoding(w):
                drops["same letters spelled with different FVS/MVS"] += 1
            elif w.freq == 0:
                drops["not found in TM-Bench (frequency 0)"] += 1
            elif w.freq < MIN_FREQUENCY:
                drops[f"TM-Bench frequency below {MIN_FREQUENCY}"] += 1
            elif not w.meanings:
                drops["no Chinese meaning"] += 1
            else:
                candidates.append(w)
        answers = candidates[: args.answers]
        drops["below the top-N frequency cutoff"] += max(0, len(candidates) - args.answers)

        # ---- tile FVS codes for every allowed word (answers are always allowed words)
        codes: dict[str, str] = {}
        for w in allowed.values():
            cs, exact = tiles.codes(w.word)
            us = units(w.word)
            tile_stats["letters"] += len(cs)
            tile_stats["approximate"] += exact.count(False)
            if any(c != u.fvs for c, u in zip(cs, us)):
                codes[w.word] = "".join(map(str, cs))

        ordered = daily_order(answers, L)
        rank = {w.letters: i + 1 for i, w in enumerate(answers)}
        data = {
            "length": L,
            "source": {
                "lotus": LOTUS_COMMIT,
                "tmbench": TMBENCH_COMMIT,
                "mongol_norm": shaper_version(),
            },
            "answers": [[w.word, pick_meanings(w.word, w.meanings, zh_counts, zh_to_mn)] for w in ordered],
            "allowed": sorted(w.word for w in allowed.values()),
            "tiles": dict(sorted(codes.items())),
        }
        (args.out / f"words-{L}.json").write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        for w in answers:
            review_rows.append([L, rank[w.letters], w.word, translit(w.letters), pick_meanings(w.word, w.meanings, zh_counts, zh_to_mn), w.freq])
        report_rows.append((L, len(same_len), len(allowed), len(candidates), len(answers), drops,
                            answers[-1].freq if answers else 0, answers[0].freq if answers else 0))

    with (args.review / "answers_for_review.csv").open("w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["length", "rank", "word", "latin", "chinese_meaning", "frequency"])
        wr.writerows(review_rows)

    write_report(args.review / "wordlist_report.md", locals())
    print((args.review / "wordlist_report.md").read_text(encoding="utf-8"))


def write_report(path: Path, v: dict) -> None:
    fst: FreqStats = v["fst"]
    lines = [
        "# Word list build report",
        "",
        "Generated by `scripts/build_wordlist.py`; do not edit by hand.",
        "",
        "## Sources",
        "",
        f"- Lotus dictionary, commit `{LOTUS_COMMIT}` (`data.zip` sha256 `{LOTUS_ZIP_SHA256[:16]}…`): "
        f"{len(v['dict_words'])} distinct Mongolian entries in `mn_zh_dict.jsonl` + `zh_mn_dict.jsonl`.",
        f"- TM-Bench, commit `{TMBENCH_COMMIT}`: {fst.strings} text fields, {fst.tokens} Mongolian tokens, "
        f"{fst.tokens_with_suffix} with a suffix ({fst.tokens_with_mvs_suffix} written with U+180E instead of U+202F), "
        f"{fst.counted} stems counted, {len(v['freq'])} distinct shape keys.",
        f"- mongol-norm `{shaper_version()}` shape keys for counting and comparing.",
        "",
        "TM-Bench tokens not counted (stem is not a valid single word):",
        "",
    ]
    lines += [f"- {r}: {n}" for r, n in v["fst"].rejected.most_common()] or ["- none"]
    lines += [
        "",
        "## Dictionary entries",
        "",
        f"- valid single words: {len(v['valid'])}",
    ]
    for r, n in v["dict_invalid"].most_common():
        ex = ", ".join(f"`{e!r}`" for e in v["dict_invalid_examples"][r])
        lines.append(f"- dropped, {r}: {n} (e.g. {ex})")
    lines += ["", "## Per word length", ""]
    for L, n_dict, n_allowed, n_cand, n_ans, drops, fmin, fmax in v["report_rows"]:
        lines += [
            f"### {L} letters",
            "",
            f"- dictionary words with {L} letters: {n_dict}",
            f"- allowed guesses (distinct letter strings): {n_allowed}",
            f"- answer candidates after filtering: {n_cand}",
            f"- answers: **{n_ans}** (TM-Bench frequency {fmin}–{fmax})",
            "- dropped from the answer list (each word counted under the first reason that applies):",
        ]
        lines += [f"  - {r}: {n}" for r, n in drops.most_common()]
        lines.append("")
    ts = v["tile_stats"]
    lines += [
        "## Tile forms",
        "",
        f"{ts['letters']} letters in allowed words; {ts['letters'] - ts['approximate']} tiles reproduce the exact glyph of "
        f"the shaped word, {ts['approximate']} fall back to the plain positional form (mostly a letter right before MVS).",
        "",
        "## Glyph collisions (examples)",
        "",
        "Answer candidates dropped because another dictionary word renders identically:",
        "",
        "| word | latin | looks identical to |",
        "|---|---|---|",
    ]
    for w, partners in v["collision_examples"]:
        lines.append(f"| {w.word} | {translit(w.letters)} | " + ", ".join(f"{p.word} ({translit(p.letters)})" for p in partners[:4]) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
