"""Restoring 53-TET tuning to a MuseScore file.

MuseScore ignores fractional MusicXML ``<alter>`` for playback and truncates it
toward zero, so a converted score looks right and sounds 12-TET.  These tests
cover the repair: matching notes to the gold score, handling the tie
continuations our MusicXML creates, and refusing to guess when the file does
not correspond to the score it is given.
"""

import re
import zipfile

import pytest

from microtonal_score_converter.musescore import (ACCIDENTAL_SUBTYPES, RetuneError,
                                  nominal_midi_for, retune_file, retune_mscx,
                                  tpc_for, tuning_cents)
from microtonal_score_converter.pitch import AE_ACCIDENTAL_GLYPHS, Pitch

#: A4 is the anchor, so expected cents are measured from it.
A4_MIDI_CENTS = 6900


def _mscx(notes):
    """A minimal MuseScore 2.06 score, shaped like what MuseScore itself writes."""
    chords = []
    for index, (pitch, tpc, tie) in enumerate(notes, start=1):
        tie_tag = f'<Tie id="{index}"></Tie>' if tie else ""
        chords.append(
            f"""        <Chord>
          <durationType>quarter</durationType>
          <Note>
            {tie_tag}
            <pitch>{pitch}</pitch>
            <tpc>{tpc}</tpc>
            </Note>
          </Chord>""")
    body = "\n".join(chords)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<museScore version="2.06">
  <Score>
    <Division>480</Division>
    <Staff id="1">
      <Measure>
        <voice>
{body}
          </voice>
        </Measure>
      </Staff>
    </Score>
  </museScore>
"""


def _tunings(text):
    return [float(v) for v in re.findall(r"<tuning>([^<]+)</tuning>", text)]


def _expected_cents(event):
    """Where the note should sound, in cents, with A4 at exactly 6900."""
    return (event.pitch53.koma - 305) * 1200 / 53 + A4_MIDI_CENTS


#: <tuning> is written to four decimals, so a ten-thousandth of a cent is the
#: most agreement anyone can ask for -- and is some nine orders of magnitude
#: below what is audible.
CENT_TOLERANCE = 1e-3


@pytest.fixture
def notes(synthetic_score):
    return [e for e in synthetic_score.events if e.is_note]


@pytest.fixture
def plain_mscx(notes):
    return _mscx([(nominal_midi_for(e.pitch53), tpc_for(e.pitch53), False)
                  for e in notes])


# -- the tuning arithmetic --------------------------------------------------


def test_tpc_is_the_line_of_fifths_with_f_at_13():
    # Confirmed against MuseScore 2.3.2's own import of every Arel-Ezgi glyph.
    assert tpc_for(Pitch.parse("F4")) == 13
    assert tpc_for(Pitch.parse("C4")) == 14
    assert tpc_for(Pitch.parse("B4")) == 19
    assert tpc_for(Pitch.parse("B4b4")) == 12      # a bakiyye flat is a flat
    assert tpc_for(Pitch.parse("B4#4")) == 26


def test_nominal_pitch_follows_the_written_spelling():
    assert nominal_midi_for(Pitch.parse("B4b1")) == 71   # koma flat stays on B
    assert nominal_midi_for(Pitch.parse("E5b4")) == 75   # bakiyye flat drops one
    assert nominal_midi_for(Pitch.parse("A4")) == 69


def test_anchor_keeps_a_at_concert_pitch():
    assert tuning_cents(Pitch.parse("A4")) == pytest.approx(0.0, abs=1e-9)
    assert tuning_cents(Pitch.parse("A5")) == pytest.approx(0.0, abs=1e-9)
    # C is then 5.66 cents flat of 12-TET, as the ISMIR paper's example says.
    assert tuning_cents(Pitch.parse("C5")) == pytest.approx(-5.66, abs=0.01)


def test_anchor_none_makes_c_exact_instead():
    assert tuning_cents(Pitch.parse("C5"), anchor=None) == pytest.approx(
        0.0, abs=1e-9)
    assert tuning_cents(Pitch.parse("A4"), anchor=None) == pytest.approx(
        5.66, abs=0.01)


def test_accidental_map_covers_every_arel_ezgi_glyph():
    for glyph in AE_ACCIDENTAL_GLYPHS.values():
        assert glyph in ACCIDENTAL_SUBTYPES


# -- the transformation -----------------------------------------------------


def test_retune_writes_one_tuning_per_note(synthetic_score, notes, plain_mscx):
    out, report = retune_mscx(plain_mscx, synthetic_score)
    assert report.complete
    assert len(_tunings(out)) == len(notes)
    assert report.notes_tuned == len(notes)


def test_retuned_pitch_is_exact(synthetic_score, notes, plain_mscx):
    out, _ = retune_mscx(plain_mscx, synthetic_score)
    pitches = [nominal_midi_for(e.pitch53) for e in notes]
    for cents, pitch, event in zip(_tunings(out), pitches, notes):
        assert pitch * 100 + cents == pytest.approx(_expected_cents(event),
                                                    abs=CENT_TOLERANCE)


def test_tuning_is_measured_from_musescores_own_pitch(synthetic_score, notes):
    # MuseScore truncates fractional <alter>, so it sometimes picks the wrong
    # semitone.  Correcting from where it actually landed still sounds right.
    wrong = [(nominal_midi_for(e.pitch53) + 1, 14, False) for e in notes]
    out, report = retune_mscx(_mscx(wrong), synthetic_score)
    assert report.complete
    for cents, (pitch, _, _), event in zip(_tunings(out), wrong, notes):
        assert pitch * 100 + cents == pytest.approx(_expected_cents(event),
                                                    abs=CENT_TOLERANCE)


def test_tie_continuations_consume_no_gold_event(synthetic_score, notes):
    rows = []
    for index, event in enumerate(notes):
        pitch = nominal_midi_for(event.pitch53)
        # Split the third note across a tie, as our MusicXML does for durations
        # no single symbol covers.
        rows.append((pitch, tpc_for(event.pitch53), index == 2))
        if index == 2:
            rows.append((pitch, tpc_for(event.pitch53), False))

    out, report = retune_mscx(_mscx(rows), synthetic_score)
    assert report.complete
    assert report.tie_continuations == 1
    assert report.events_consumed == len(notes)
    assert len(_tunings(out)) == len(notes) + 1
    # Both halves of the tie get the same tuning: it is one note.
    assert _tunings(out)[2] == _tunings(out)[3]


def test_existing_tuning_is_replaced_not_duplicated(synthetic_score, plain_mscx):
    once, _ = retune_mscx(plain_mscx, synthetic_score)
    twice, _ = retune_mscx(once, synthetic_score)
    assert _tunings(once) == _tunings(twice)
    assert once == twice


def test_a_mismatched_file_is_refused(synthetic_score, notes):
    too_few = _mscx([(nominal_midi_for(notes[0].pitch53), 14, False)])
    with pytest.raises(RetuneError, match="does not correspond"):
        retune_mscx(too_few, synthetic_score)


def test_a_wildly_wrong_pitch_is_refused(synthetic_score, notes):
    rows = [(nominal_midi_for(e.pitch53), 14, False) for e in notes]
    rows[1] = (rows[1][0] + 7, 14, False)      # a fifth out: not a rounding slip
    with pytest.raises(RetuneError, match="cents"):
        retune_mscx(_mscx(rows), synthetic_score)


def test_permissive_mode_reports_instead_of_raising(synthetic_score, notes):
    rows = [(nominal_midi_for(e.pitch53), 14, False) for e in notes]
    rows[1] = (rows[1][0] + 7, 14, False)
    out, report = retune_mscx(_mscx(rows), synthetic_score, strict=False)
    assert report.warnings
    assert not report.complete
    assert len(_tunings(out)) == len(notes) - 1


# -- files ------------------------------------------------------------------


def test_mscx_file_round_trip(tmp_path, synthetic_score, notes, plain_mscx):
    path = tmp_path / "score.mscx"
    path.write_text(plain_mscx, encoding="utf-8")
    report = retune_file(str(path), synthetic_score)
    assert report.complete
    assert len(_tunings(path.read_text(encoding="utf-8"))) == len(notes)


def test_mscz_keeps_everything_else_in_the_zip(tmp_path, synthetic_score,
                                               notes, plain_mscx):
    path = tmp_path / "score.mscz"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("META-INF/container.xml", "<container/>")
        archive.writestr("Thumbnails/thumbnail.png", b"\x89PNG not really")
        archive.writestr("score.mscx", plain_mscx)

    report = retune_file(str(path), synthetic_score)
    assert report.complete

    with zipfile.ZipFile(path) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {
            "META-INF/container.xml", "Thumbnails/thumbnail.png", "score.mscx"}
        assert archive.read("Thumbnails/thumbnail.png") == b"\x89PNG not really"
        assert len(_tunings(archive.read("score.mscx").decode())) == len(notes)


def test_output_path_leaves_the_original_alone(tmp_path, synthetic_score,
                                               plain_mscx):
    source = tmp_path / "in.mscx"
    source.write_text(plain_mscx, encoding="utf-8")
    destination = tmp_path / "out.mscx"
    destination.write_text(plain_mscx, encoding="utf-8")

    retune_file(str(destination), synthetic_score)
    assert source.read_text(encoding="utf-8") == plain_mscx
    assert _tunings(destination.read_text(encoding="utf-8"))


def test_cli_retune(tmp_path, synthetic_path, notes, plain_mscx):
    from microtonal_score_converter.cli import main
    path = tmp_path / "score.mscx"
    path.write_text(plain_mscx, encoding="utf-8")
    assert main(["retune", synthetic_path, str(path), "--no-mu2"]) == 0
    assert len(_tunings(path.read_text(encoding="utf-8"))) == len(notes)


def test_cli_retune_reports_a_mismatch(tmp_path, synthetic_path, capsys):
    from microtonal_score_converter.cli import main
    path = tmp_path / "score.mscx"
    path.write_text(_mscx([(60, 14, False)]), encoding="utf-8")
    assert main(["retune", synthetic_path, str(path), "--no-mu2"]) == 1
    assert "does not" in capsys.readouterr().err
