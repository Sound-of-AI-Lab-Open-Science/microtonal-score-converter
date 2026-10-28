"""The loss matrix: it must report loss where there is loss, and none where
there is not."""

import pytest

from conftest import corpus_available
from microtonal_score_converter.audit import audit_score, format_report


def _by_variant(reports):
    return {(r.fmt, r.variant): r for r in reports}


@pytest.fixture
def reports(synthetic_score):
    return _by_variant(audit_score(synthetic_score))


@pytest.mark.parametrize("key", [
    ("txt", "source"),
    ("json", "lossless"),
    ("midi", "symbtr-bend"),
    ("musicxml", "exact53"),
    ("abc", "53tet"),
    ("tokens", "gold53"),
])
def test_exact_configurations_lose_no_pitch(reports, key):
    report = reports[key]
    assert report.notes_compared > 0
    assert report.pitch_exact == report.notes_compared, report.pitch_cents_max


@pytest.mark.parametrize("key,floor", [
    (("midi", "12tet"), 20.0),
    (("musicxml", "12tet"), 20.0),
    (("abc", "12tet"), 20.0),
    (("tokens", "naive12"), 20.0),
    (("musicxml", "quartertone"), 5.0),
    (("abc", "24tet"), 5.0),
])
def test_quantised_configurations_report_the_loss(reports, key, floor):
    report = reports[key]
    assert report.pitch_cents_max >= floor
    assert report.pitch_exact < report.notes_compared


def test_diatonic_reference_is_lossy_but_only_slightly(reports):
    report = reports[("musicxml", "diatonic53")]
    assert 1.0 < report.pitch_cents_max < 10.0


def test_no_writer_of_ours_emits_an_accidental_without_a_value(reports):
    for (fmt, _), report in reports.items():
        if fmt == "musicxml":
            assert "no <alter>" not in report.note


def test_durations_survive_every_notated_format(reports):
    for key in (("txt", "source"), ("musicxml", "exact53"), ("abc", "53tet")):
        report = reports[key]
        assert report.duration_exact == report.durations_compared, key


def test_attributes_only_the_gold_format_carries_are_reported_lost(reports):
    # Both spellings of each pitch exist only in SymbTr-txt and our JSON.
    assert reports[("txt", "source")].attributes["ae_spelling"] != "lost"
    assert reports[("abc", "53tet")].attributes["ae_spelling"] == "lost"
    assert reports[("midi", "symbtr-bend")].attributes["ae_spelling"] == "lost"


def test_structural_annotations_survive_where_we_claim_they_do(reports):
    for key in (("musicxml", "exact53"), ("abc", "53tet"), ("tokens", "gold53")):
        assert reports[key].attributes["phrase_boundaries"] == "kept", key
        assert reports[key].attributes["usul_changes"] == "kept", key


def test_declared_formats_are_flagged_as_such(reports):
    kern = reports[("kern", "koma-spine")]
    assert kern.measured is False
    assert "declared" in kern.note


def test_report_table_marks_unmeasured_rows(synthetic_score):
    table = format_report(audit_score(synthetic_score))
    assert "(declared)" in table
    kern_line = next(l for l in table.splitlines() if l.startswith("kern"))
    assert "n/a" in kern_line
    assert "%" not in kern_line


@corpus_available
def test_audit_runs_on_a_real_score(corpus_score):
    reports = _by_variant(audit_score(corpus_score))
    assert reports[("midi", "symbtr-bend")].pitch_cents_max < 0.05
    assert reports[("musicxml", "12tet")].pitch_cents_max > 30
