"""Slim Score importers and pairwise path audit."""

from microtonal_score_converter import (
    audit_paths, format_path_report, score_from_abc, score_from_midi,
    score_from_musicxml, write_abc, write_midi, write_musicxml,
)
from microtonal_score_converter.cli import main
from microtonal_score_converter.importers import (
    cents_to_koma, detect_format, load_score, pitch_from_cents,
)
from microtonal_score_converter.pitch import Pitch


def _gold_komas(score):
    return [e.pitch53.koma for e in score.events if e.is_note]


def _max_cents_error(gold, restored):
    pairs = list(zip(
        [e for e in gold.events if e.is_note],
        [e for e in restored.events if e.is_note],
    ))
    assert len(pairs) == len([e for e in gold.events if e.is_note])
    return max(abs(a.pitch53.koma - b.pitch53.koma) * 1200.0 / 53.0
               for a, b in pairs)


# -- primitives -------------------------------------------------------------


def test_cents_to_koma_round_trips_the_anchor():
    assert cents_to_koma(Pitch.parse("Do4").cents) == 265
    assert pitch_from_cents(float(Pitch.parse("Si4b2").cents)).koma == 312


def test_detect_format_from_suffix():
    assert detect_format("x.mid") == "midi"
    assert detect_format("x.ABC") == "abc"
    assert detect_format("x.symbtr.txt") == "txt"
    assert detect_format("x.json") == "json"
    assert detect_format("x.musicxml") == "musicxml"


# -- write → import pitch fidelity ------------------------------------------


def test_midi_symbtr_import_keeps_53tet_pitch(synthetic_score):
    restored = score_from_midi(write_midi(synthetic_score))
    assert _gold_komas(restored) == _gold_komas(synthetic_score)
    assert _max_cents_error(synthetic_score, restored) < 0.05


def test_abc_53tet_import_keeps_53tet_pitch(synthetic_score):
    restored = score_from_abc(write_abc(synthetic_score, mode="53tet"))
    notes_gold = [e for e in synthetic_score.events if e.is_note]
    notes_rest = [e for e in restored.events if e.is_note]
    assert len(notes_rest) == len(notes_gold)
    assert _max_cents_error(synthetic_score, restored) < 0.05


def test_musicxml_exact_import_keeps_53tet_pitch(synthetic_score):
    restored = score_from_musicxml(
        write_musicxml(synthetic_score, precision="exact"))
    assert len([e for e in restored.events if e.is_note]) == \
        len([e for e in synthetic_score.events if e.is_note])
    assert _max_cents_error(synthetic_score, restored) < 0.05


def test_midi_to_abc_preserves_pitch(synthetic_score):
    mid = write_midi(synthetic_score)
    slim = score_from_midi(mid)
    restored = score_from_abc(write_abc(slim, mode="53tet"))
    assert _max_cents_error(synthetic_score, restored) < 0.05


def test_abc_to_midi_preserves_pitch(synthetic_score):
    abc = write_abc(synthetic_score, mode="53tet")
    slim = score_from_abc(abc)
    restored = score_from_midi(write_midi(slim))
    assert _max_cents_error(synthetic_score, restored) < 0.05


# -- pairwise audit ---------------------------------------------------------


def test_audit_paths_lossless_cells_are_exact(synthetic_score):
    reports = {r.label: r for r in audit_paths(synthetic_score)}
    for label in (
        "midi/symbtr-bend -> abc/53tet",
        "abc/53tet -> midi/symbtr-bend",
        "musicxml/exact53 -> abc/53tet",
        "json/lossless -> midi/symbtr-bend",
        "txt/source -> abc/53tet",
    ):
        report = reports[label]
        assert report.notes_compared > 0, label
        assert report.pitch_cents_max < 0.05, (label, report.pitch_cents_max)
        assert report.pitch_exact_fraction == 1.0, label


def test_audit_paths_lossy_midi12_damages_pitch(synthetic_score):
    reports = {r.label: r for r in audit_paths(synthetic_score)}
    report = reports["midi/12tet -> abc/53tet"]
    assert report.notes_compared > 0
    assert report.pitch_cents_mean > 0.5


def test_format_path_report_mentions_arrows(synthetic_score):
    text = format_path_report(audit_paths(synthetic_score))
    assert "->" in text
    assert "pitch ok" in text


# -- CLI --------------------------------------------------------------------


def test_cli_convert_from_midi_to_abc(synthetic_score, tmp_path):
    mid = tmp_path / "score.mid"
    mid.write_bytes(write_midi(synthetic_score))
    out = tmp_path / "out"
    assert main(["convert", str(mid), "--from", "midi", "--to", "abc",
                 "-o", str(out), "-q"]) == 0
    abc_path = out / "score.abc"
    assert abc_path.exists()
    restored = score_from_abc(abc_path.read_text(encoding="utf-8"))
    assert _max_cents_error(synthetic_score, restored) < 0.05


def test_cli_audit_paths(synthetic_path, capsys):
    assert main(["audit", synthetic_path, "--paths", "--no-mu2"]) == 0
    out = capsys.readouterr().out
    assert "midi/symbtr-bend" in out
    assert "->" in out


def test_load_score_auto_detects_midi(synthetic_score, tmp_path):
    path = tmp_path / "piece.mid"
    path.write_bytes(write_midi(synthetic_score))
    restored = load_score(str(path))
    assert _max_cents_error(synthetic_score, restored) < 0.05
