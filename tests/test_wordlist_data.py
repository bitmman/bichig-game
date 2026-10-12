"""Invariants of the generated game data (data/words-*.json)."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from mongol_text import LOAN_LETTERS, invalid_reason, letters, shape_key  # noqa: E402


@pytest.fixture(scope="module", params=[4, 5, 6])
def data(request):
    return request.param, json.loads((ROOT / "data" / f"words-{request.param}.json").read_text(encoding="utf-8"))


def test_answers_are_valid_single_words(data):
    n, d = data
    for word, meaning in d["answers"]:
        assert invalid_reason(word) is None, word
        assert len(letters(word)) == n, word
        assert not set(letters(word)) & LOAN_LETTERS, word
        assert meaning, word


def test_answers_are_allowed_and_unique(data):
    n, d = data
    allowed = set(d["allowed"])
    answers = [w for w, _ in d["answers"]]
    assert set(answers) <= allowed
    assert len(set(answers)) == len(answers)


def test_no_two_answers_look_identical(data):
    _, d = data
    keys = [shape_key(w) for w, _ in d["answers"]]
    assert len(set(keys)) == len(keys)


def test_allowed_letter_strings_are_unique(data):
    n, d = data
    seen = set()
    for w in d["allowed"]:
        assert invalid_reason(w) is None, w
        ls = "".join(letters(w))
        assert len(ls) == n
        assert ls not in seen, w
        seen.add(ls)


def test_tile_codes_match_word_length(data):
    _, d = data
    for w, code in d["tiles"].items():
        assert w in d["allowed"]
        assert len(code) == len(letters(w)) and set(code) <= set("01234")
