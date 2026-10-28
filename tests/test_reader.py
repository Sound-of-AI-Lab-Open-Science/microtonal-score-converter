"""Reading SymbTr-txt, and the things the format does not document."""

from fractions import Fraction

import pytest

from conftest import corpus_available
from microtonal_score_converter import read_txt
from microtonal_score_converter.readers.filename import humanize, parse_symbtr_name


def test_rows_are_kept_in_source_order(synthetic_score):
    assert [e.index for e in synthetic_score.events] == list(range(1, 12))


def test_offset_column_is_an_end_position(synthetic_score):
    # The file stores where the row ends; the IR exposes where it starts.
    first_note = synthetic_score.events[1]
    assert first_note.offset == 0
    assert first_note.offset_end == Fraction(2, 9)      # (1/4) / (9/8)


def test_usul_row_is_not_a_rest(synthetic_score):
    usul_row = synthetic_score.events[0]
    assert usul_row.code == 51
    assert not usul_row.is_rest
    assert not usul_row.sounds
    # Pay/Payda on a usul row is the time signature, not a duration.
    usul = synthetic_score.usul_changes[0]
    assert usul.time_signature == "9/8"
    assert usul.symbtr_id == 20


def test_rest_is_detected_from_the_name_not_the_comma(synthetic_score):
    rest = synthetic_score.events[5]
    assert rest.is_rest and rest.pitch53 is None and rest.sounds


def test_grace_note_has_no_symbolic_duration(synthetic_score):
    grace = synthetic_score.events[3]
    assert grace.is_grace and grace.duration == 0 and grace.ms > 0
    assert grace.grace_borrows_from == "next"


def test_ornament_code_is_resolved(synthetic_score):
    assert synthetic_score.events[7].ornament == "trill"


def test_phrase_boundary_is_structural_not_sounding(synthetic_score):
    marker = synthetic_score.events[6]
    assert marker.code == 53 and not marker.sounds
    assert synthetic_score.phrase_boundaries == [Fraction(5, 9)]


def test_articulation_buckets_lns(synthetic_score):
    assert synthetic_score.events[1].articulation == "normal"    # 95
    assert synthetic_score.events[2].articulation == "legato"    # 99
    assert synthetic_score.events[4].articulation == "staccato"  # 50


def test_tempo_is_recovered_from_milliseconds(synthetic_score):
    # 1/4 note lasting 556 ms implies 240000/(4*556) = 107.9 bpm.
    assert synthetic_score.tempo == pytest.approx(107.9, abs=0.2)


def test_both_spellings_are_kept_where_they_disagree(synthetic_score):
    event = synthetic_score.events[4]
    assert event.pitch53.name == "Si4b2" and event.pitch53.koma == 312
    assert event.pitchAE.name == "B4b1" and event.pitchAE.koma == 313


def test_lyrics_reassemble_with_symbtr_spacing(synthetic_score):
    # One trailing space ends a word, two end a verse.
    assert synthetic_score.lyrics == "Karşıdan son"


def test_measures_come_from_the_offset_column(synthetic_score):
    bars = synthetic_score.measures()
    # The 9/8 note starting at 0.56 spans the barline, so it belongs to bar 1;
    # only the row after it opens bar 2.
    assert len(bars) == 2
    assert [e.index for e in bars[1]] == [9, 10, 11]


def test_a_clean_score_produces_no_warnings(synthetic_score):
    assert synthetic_score.warnings == []


def test_damage_is_reported_but_does_not_raise(tmp_path):
    path = tmp_path / "broken--sarki--aksak--x--y.txt"
    path.write_text(
        "Sira\tKod\tNota53\tNotaAE\tKoma53\tKomaAE\tPay\tPayda\tMs\tLNS\tBas\t"
        "Soz1\tOffset\n"
        "1\t9\tRe5\tD5\t999\t327\t1\t4\t556\t95\t96\t\t0.25\n"
        "5\t9\tQx9\tD5\t327\t327\t1\t4\t556\t95\t96\t\t0.5\n",
        encoding="utf-8")
    score = read_txt(str(path), use_mu2=False)
    assert len(score.events) == 2
    messages = " ".join(score.warnings)
    assert "implies comma 327" in messages      # name/comma disagreement
    assert "unparsable" in messages             # unreadable spelling
    assert "usul row" in messages               # missing Kod 51
    assert "index jumps" in messages


def test_filename_fields():
    fields = parse_symbtr_name(
        "beyati--sarki--aksak--karsidan_yar--dede_efendi.txt")
    assert fields["makam"] == "beyati"
    assert fields["form"] == "sarki"
    assert fields["usul"] == "aksak"
    assert fields["composer"] == "dede_efendi"


def test_filename_empty_fields_stay_empty():
    fields = parse_symbtr_name("yeni_cargah--pesrev--devrikebir----.txt")
    assert fields["title"] == "" and fields["composer"] == ""


def test_humanize():
    assert humanize("dede_efendi") == "Dede Efendi"


@corpus_available
def test_mu2_supplies_what_the_txt_omits(corpus_score):
    meta = corpus_score.metadata
    assert meta.makam == "Beyâtî"            # accented, from the mu2
    assert meta.key_signature == ["B4b2"]    # only the mu2 has this
    assert meta.extra["filename_makam"] == "beyati"


@corpus_available
def test_whole_corpus_parses_without_warnings(corpus_files):
    assert len(corpus_files) > 2000
    for path in corpus_files[::17]:
        score = read_txt(path, use_mu2=False)
        assert score.notes, path
        assert score.warnings == [], path
