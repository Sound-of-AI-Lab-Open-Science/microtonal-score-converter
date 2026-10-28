"""Shared fixtures.

The tests run against the real SymbTr corpus when it is present next to this
checkout, and against a small hand-written score otherwise, so they stay useful
in CI without bundling the corpus.
"""

from __future__ import annotations

import os
import sys

import pytest

# `uv sync` installs the package, so this is only a fallback -- it keeps
# `python -m pytest` working in a bare checkout with nothing installed.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: Where a SymbTr checkout is expected, relative to this repository.
SYMBTR_ROOT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir, "SymbTr-master"))

#: A vocal score with microtonal accidentals, ties, sections and a known tempo.
REFERENCE_SCORE = "beyati--sarki--aksak--karsidan_yar--dede_efendi"

#: Minimal SymbTr-txt exercising rests, microtones, ties, grace notes and
#: a usul row.  Written out rather than copied from the corpus.
SYNTHETIC_TXT = "\t".join(
    ("Sira", "Kod", "Nota53", "NotaAE", "Koma53", "KomaAE",
     "Pay", "Payda", "Ms", "LNS", "Bas", "Soz1", "Offset")) + "\n" + "\n".join([
    "1\t51\t\t\t0\t0\t9\t8\t0\t20\t0\tAksak\t0.0",
    "2\t9\tRe5\tD5\t327\t327\t1\t4\t556\t95\t96\tKar\t0.222222222222",
    "3\t9\tMi5b3\tE5b4\t333\t332\t1\t8\t278\t99\t96\tşı\t0.333333333333",
    "4\t8\tFa5#3\tF5#4\t343\t344\t0\t0\t42\t99\t96\t\t0.333333333333",
    "5\t9\tSi4b2\tB4b1\t312\t313\t1\t8\t278\t50\t96\tdan \t0.444444444444",
    "6\t9\tEs\tEs\t-1\t-1\t1\t8\t278\t100\t0\t\t0.555555555556",
    "7\t53\t\t\t0\t0\t0\t0\t0\t0\t0\t\t0.555555555556",
    "8\t12\tLa4\tA4\t305\t305\t9\t8\t2500\t95\t96\tson  \t1.555555555556",
    "9\t9\tLa4\tA4\t305\t305\t1\t8\t278\t95\t96\t\t1.666666666667",
    # Two plain consecutive notes, so a test can read a note's slot straight
    # off the gap between onsets without a rest or grace in the way.
    "10\t9\tLa4\tA4\t305\t305\t1\t8\t278\t50\t96\t\t1.777777777778",
    "11\t9\tSol4\tG4\t296\t296\t1\t8\t278\t95\t96\t\t1.888888888889",
]) + "\n"


def _corpus_path(kind: str, extension: str) -> str:
    return os.path.join(SYMBTR_ROOT, kind, REFERENCE_SCORE + extension)


corpus_available = pytest.mark.skipif(
    not os.path.isdir(os.path.join(SYMBTR_ROOT, "txt")),
    reason="SymbTr corpus not found next to this checkout")


@pytest.fixture
def synthetic_path(tmp_path):
    path = tmp_path / f"{REFERENCE_SCORE}.txt"
    path.write_text(SYNTHETIC_TXT, encoding="utf-8")
    return str(path)


@pytest.fixture
def synthetic_score(synthetic_path):
    from microtonal_score_converter import read_txt
    return read_txt(synthetic_path, use_mu2=False)


@pytest.fixture
def corpus_txt():
    return _corpus_path("txt", ".txt")


@pytest.fixture
def corpus_mu2():
    return _corpus_path("mu2", ".mu2")


@pytest.fixture
def corpus_midi():
    return _corpus_path("midi", ".mid")


@pytest.fixture
def corpus_score(corpus_txt, corpus_mu2):
    from microtonal_score_converter import read_txt
    return read_txt(corpus_txt, mu2_path=corpus_mu2)


@pytest.fixture
def corpus_files():
    import glob
    return sorted(glob.glob(os.path.join(SYMBTR_ROOT, "txt", "*.txt")))
