"""The command line, which is how anyone else will actually use this."""

import os

import pytest

from conftest import corpus_available
from microtonal_score_converter.cli import main


def test_convert_writes_every_requested_target(synthetic_path, tmp_path, capsys):
    out = tmp_path / "out"
    code = main(["convert", synthetic_path, "--to",
                 "midi,musicxml,abc,kern,tokens,json,txt",
                 "-o", str(out), "--no-mu2"])
    assert code == 0
    produced = {p.suffix for p in out.iterdir()}
    assert {".mid", ".xml", ".abc", ".krn", ".json"} <= produced
    assert any(p.name.endswith(".tokens.txt") for p in out.iterdir())


def test_convert_passes_options_only_to_the_writer_that_takes_them(
        synthetic_path, tmp_path):
    out = tmp_path / "out"
    # --mode belongs to ABC and --precision to MusicXML; asking for both
    # targets at once must not hand either option to the wrong writer.
    assert main(["convert", synthetic_path, "--to", "abc,musicxml,midi",
                 "--mode", "12tet", "--precision", "quartertone",
                 "--convention", "12tet", "-o", str(out), "--no-mu2"]) == 0
    assert (out / os.path.basename(synthetic_path).replace(
        ".txt", ".abc")).exists()


def test_convert_rejects_an_unknown_target(synthetic_path, tmp_path, capsys):
    code = main(["convert", synthetic_path, "--to", "lilypond",
                 "-o", str(tmp_path)])
    assert code == 2
    assert "unknown target" in capsys.readouterr().err


def test_convert_reports_no_matching_input(tmp_path, capsys):
    code = main(["convert", str(tmp_path / "nothing-here-*.txt"),
                 "-o", str(tmp_path)])
    assert code == 2
    assert "no input files matched" in capsys.readouterr().err


def test_info_summarises(synthetic_path, capsys):
    assert main(["info", synthetic_path, "--no-mu2"]) == 0
    out = capsys.readouterr().out
    assert "makam      beyati" in out
    assert "usul       aksak (9/8)" in out
    assert "commas" in out


def test_audit_prints_the_matrix(synthetic_path, capsys):
    assert main(["audit", synthetic_path, "--no-mu2"]) == 0
    out = capsys.readouterr().out
    assert "musicxml" in out and "abc" in out and "pitch ok" in out


def test_no_command_prints_help(capsys):
    assert main([]) == 1
    assert "usage" in capsys.readouterr().out


@corpus_available
def test_audit_published_against_the_real_corpus(capsys):
    from conftest import SYMBTR_ROOT
    assert main(["audit-published", "--root", SYMBTR_ROOT, "--limit", "12"]) == 0
    out = capsys.readouterr().out
    assert "published MusicXML vs gold" in out
    assert "published MIDI vs gold" in out
