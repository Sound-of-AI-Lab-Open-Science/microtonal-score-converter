"""Each writer, checked by reading its own output back."""

import json
from fractions import Fraction

import pytest

from conftest import corpus_available
from microtonal_score_converter import (read_txt, write_abc, write_json, write_kern,
                        write_midi, write_musicxml, write_tokens, write_txt)
from microtonal_score_converter.readers.abc import read_abc
from microtonal_score_converter.readers.midi import read_midi
from microtonal_score_converter.readers.musicxml import read_musicxml
from microtonal_score_converter.writers.jsonio import score_from_dict


def _gold_cents(event):
    return event.pitch53.koma * 1200.0 / 53.0


# -- SymbTr-txt -------------------------------------------------------------


def test_txt_round_trip_is_byte_identical(synthetic_path):
    from conftest import SYNTHETIC_TXT
    assert write_txt(read_txt(synthetic_path, use_mu2=False)) == SYNTHETIC_TXT


def test_txt_exact_offsets_are_rational(synthetic_score):
    out = write_txt(synthetic_score, offsets="exact")
    assert out.splitlines()[2].endswith("0.222222222222")


def test_txt_rejects_an_unknown_offset_mode(synthetic_score):
    with pytest.raises(ValueError):
        write_txt(synthetic_score, offsets="guess")


# -- JSON -------------------------------------------------------------------


def test_json_round_trip_reproduces_the_ir(synthetic_score):
    restored = score_from_dict(json.loads(write_json(synthetic_score)))
    assert restored.events == synthetic_score.events
    assert restored.metadata == synthetic_score.metadata


def test_json_rejects_a_future_schema(synthetic_score):
    payload = json.loads(write_json(synthetic_score))
    payload["schema"] = 99
    with pytest.raises(ValueError):
        score_from_dict(payload)


# -- MIDI -------------------------------------------------------------------


def test_midi_bend_preserves_53tet_exactly(synthetic_score):
    parsed = read_midi(write_midi(synthetic_score))
    notes = [e for e in synthetic_score.events if e.is_note]
    assert len(parsed.notes) == len(notes)
    offsets = [m.cents - _gold_cents(e) for m, e in zip(parsed.notes, notes)]
    anchor = offsets[0]
    assert max(abs(o - anchor) for o in offsets) < 0.05


def test_midi_anchor_leaves_a_unbent(synthetic_score):
    parsed = read_midi(write_midi(synthetic_score))
    notes = [e for e in synthetic_score.events if e.is_note]
    for midi_note, event in zip(parsed.notes, notes):
        if event.pitch53.name == "La4":
            assert midi_note.bend == 8192
            break
    else:  # pragma: no cover - the fixture contains an A
        pytest.fail("fixture has no A to check the anchor against")


def test_midi_12tet_drops_the_bends(synthetic_score):
    parsed = read_midi(write_midi(synthetic_score, convention="12tet"))
    assert {n.bend for n in parsed.notes} == {8192}


def test_midi_24tet_uses_half_semitone_bends(synthetic_score):
    parsed = read_midi(write_midi(synthetic_score, convention="24tet"))
    for note in parsed.notes:
        offset = (note.bend - 8192) / 8192 * note.bend_range * 100
        assert min(abs(offset - grid) for grid in (0.0, 50.0)) < 0.1


def test_midi_base_note_follows_the_written_spelling(synthetic_score):
    # B4b1 is a 1-comma flat, which stays on B rather than dropping to B-flat.
    parsed = read_midi(write_midi(synthetic_score))
    notes = [e for e in synthetic_score.events if e.is_note]
    pairs = {e.pitch53.name: m.note for m, e in zip(parsed.notes, notes)}
    assert pairs["Si4b2"] == 71      # B4, not 70
    assert pairs["Mi5b3"] == 75      # E-flat5, because the AE spelling is b4
    assert pairs["Fa5#3"] == 78


def test_midi_lns_shortens_the_note_not_the_bar(synthetic_score):
    # LNS is the percentage of the slot that sounds; the slot itself, and so
    # the position of every later note, must not move.
    parsed = read_midi(write_midi(synthetic_score))
    notes = [e for e in synthetic_score.events if e.is_note]
    # Pick the staccato note that is followed directly by another note, so the
    # gap between onsets is its slot and nothing else.
    index = next(i for i, e in enumerate(notes)
                 if e.lns == 50 and i + 1 < len(notes)
                 and not notes[i + 1].is_grace
                 and notes[i + 1].offset == e.offset_end)
    sounding = parsed.notes[index]
    slot = parsed.notes[index + 1].tick - sounding.tick
    assert sounding.duration == pytest.approx(slot * 0.5, abs=1)


def test_midi_keeps_grace_notes_by_borrowing_from_the_next_note(
        synthetic_score):
    parsed = read_midi(write_midi(synthetic_score))
    notes = [e for e in synthetic_score.events if e.is_note]
    assert len(parsed.notes) == len(notes), "a grace note went missing"

    grace_index = next(i for i, e in enumerate(notes) if e.is_grace)
    grace = parsed.notes[grace_index]
    assert 0 < grace.duration < parsed.division

    # The borrowed time comes out of the host note's front, so the host starts
    # later but nothing after it moves: with the grace removed, every note past
    # the host lands on exactly the same tick.
    import copy
    without = copy.deepcopy(synthetic_score)
    without.events = [e for e in without.events if not e.is_grace]
    plain = read_midi(write_midi(without))

    host = parsed.notes[grace_index + 1]
    assert host.tick > plain.notes[grace_index].tick
    assert [n.tick for n in plain.notes[grace_index + 1:]] == \
        [n.tick for n in parsed.notes[grace_index + 2:]]


def test_midi_tempo_and_time_signature(synthetic_score):
    parsed = read_midi(write_midi(synthetic_score))
    assert parsed.tempo_bpm == pytest.approx(108, abs=0.5)
    assert parsed.time_signatures[0][1:] == (9, 8)


def test_midi_rejects_unknown_options(synthetic_score):
    with pytest.raises(ValueError):
        write_midi(synthetic_score, convention="53tet")
    with pytest.raises(ValueError):
        write_midi(synthetic_score, timing="wall-clock")


# -- MusicXML ---------------------------------------------------------------


def test_musicxml_exact_is_lossless(synthetic_score):
    parsed = read_musicxml(write_musicxml(synthetic_score))
    heads = [n for n in parsed.notes if not n.is_rest and not n.tie_stop]
    notes = [e for e in synthetic_score.events if e.is_note]
    for xml_note, event in zip(heads, notes):
        assert xml_note.cents == pytest.approx(_gold_cents(event), abs=0.05)


def test_musicxml_always_writes_an_alter_for_an_accidental(synthetic_score):
    # The failure mode in SymbTr's own exports: a glyph with no value.
    for precision in ("exact", "quartertone", "12tet"):
        parsed = read_musicxml(
            write_musicxml(synthetic_score, precision=precision))
        assert not any(n.alter_missing for n in parsed.notes), precision


def test_musicxml_diatonic_reference_loses_the_natural_offset(synthetic_score):
    parsed = read_musicxml(
        write_musicxml(synthetic_score, reference="diatonic"))
    heads = [n for n in parsed.notes if not n.is_rest and not n.tie_stop]
    notes = [e for e in synthetic_score.events if e.is_note]
    errors = [abs(x.cents - _gold_cents(e)) for x, e in zip(heads, notes)]
    assert max(errors) > 1.0        # naturals are now wrong
    assert max(errors) < 10.0       # but only by the degree offset


def test_musicxml_ties_a_duration_no_symbol_covers(synthetic_score):
    parsed = read_musicxml(write_musicxml(synthetic_score))
    tied = [n for n in parsed.notes if n.tie_start]
    assert tied, "the 9/8 note should be written as a tie"
    folded = {}
    total = sum(n.duration for n in parsed.notes if n.tie_start or n.tie_stop)
    assert total == Fraction(9, 8)


def test_musicxml_rejects_unknown_options(synthetic_score):
    with pytest.raises(ValueError):
        write_musicxml(synthetic_score, precision="53tet")
    with pytest.raises(ValueError):
        write_musicxml(synthetic_score, reference="pythagorean")


# -- ABC --------------------------------------------------------------------


def test_abc_53tet_is_lossless(synthetic_score):
    parsed = read_abc(write_abc(synthetic_score))
    sounding = [e for e in synthetic_score.events if e.sounds]
    for abc_note, event in zip(parsed.notes, sounding):
        if event.is_note and not abc_note.is_rest:
            assert abc_note.cents == pytest.approx(_gold_cents(event), abs=0.01)


def test_abc_durations_need_no_ties(synthetic_score):
    parsed = read_abc(write_abc(synthetic_score))
    sounding = [e for e in synthetic_score.events if e.sounds]
    for abc_note, event in zip(parsed.notes, sounding):
        if not event.is_grace:
            assert abc_note.duration == event.duration


def test_abc_12tet_quantises(synthetic_score):
    parsed = read_abc(write_abc(synthetic_score, mode="12tet"))
    for note in parsed.notes:
        if not note.is_rest:
            assert note.alter_semitones.denominator == 1


def test_abc_header_carries_what_abc_has_no_field_for(synthetic_score):
    text = write_abc(synthetic_score)
    assert "M:9/8" in text
    assert "%%usul" in text or "%%makam" in text


def test_abc_rejects_unknown_options(synthetic_score):
    with pytest.raises(ValueError):
        write_abc(synthetic_score, mode="31tet")


# -- Humdrum ----------------------------------------------------------------


def test_kern_keeps_the_exact_comma_in_a_parallel_spine(synthetic_score):
    text = write_kern(synthetic_score)
    assert "**kern\t**koma" in text
    assert "\t312\t" in text or text.count("312") >= 1


def test_kern_cents_spine_is_relative_to_its_own_12tet_spelling(synthetic_score):
    text = write_kern(synthetic_score, microtone_spine="cents")
    assert "**cents" in text
    assert "+3.77" in text          # 53-TET D is 3.77 cents above 12-TET D


def test_kern_ties_what_one_symbol_cannot_hold(synthetic_score):
    text = write_kern(synthetic_score)
    assert "[1" in text and "]8" in text


def test_kern_rejects_unknown_options(synthetic_score):
    with pytest.raises(ValueError):
        write_kern(synthetic_score, microtone_spine="hertz")


# -- tokens -----------------------------------------------------------------


def test_token_presets_differ_only_where_intended(synthetic_score):
    gold = write_tokens(synthetic_score, preset="gold53").split()
    naive = write_tokens(synthetic_score, preset="naive12").split()
    gold_notes = [t for t in gold if not t.startswith("<") and t != "|"]
    naive_notes = [t for t in naive if not t.startswith("<") and t != "|"]
    assert len(gold_notes) == len(naive_notes)
    assert gold_notes != naive_notes


def test_token_koma_values_are_recoverable(synthetic_score):
    text = write_tokens(synthetic_score, preset="gold53_plain")
    assert "327_1/4" in text
    assert "312_1/8" in text


def test_token_intervals_start_with_a_sentinel(synthetic_score):
    text = write_tokens(synthetic_score, preset="contour53")
    assert text.split()[0].startswith("S_")


def test_token_degree_is_relative_to_the_final_note(synthetic_score):
    text = write_tokens(synthetic_score, preset="degree53")
    # The fixture ends on A4 (305), so the last pitched token is +0.
    assert [t for t in text.split() if not t.startswith("<")][-1].startswith("+0")


def test_token_separate_mode_splits_pitch_and_duration(synthetic_score):
    joined = write_tokens(synthetic_score, preset="gold53_plain")
    split = write_tokens(synthetic_score, pitch="koma53", duration="fraction",
                         markers=("bar", "rest"), combine=False)
    assert len(split.split()) > len(joined.split())


def test_tokens_reject_an_unknown_preset(synthetic_score):
    with pytest.raises(ValueError):
        write_tokens(synthetic_score, preset="gold99")


# -- against the real corpus ------------------------------------------------


@corpus_available
def test_published_midi_matches_our_midi_note_for_note(corpus_score,
                                                       corpus_midi):
    ours = read_midi(write_midi(corpus_score))
    theirs = read_midi(corpus_midi)
    assert len(ours.notes) == len(theirs.notes)
    for a, b in zip(ours.notes, theirs.notes):
        assert (a.note, a.bend, a.velocity) == (b.note, b.bend, b.velocity)


@corpus_available
def test_corpus_round_trips_byte_for_byte(corpus_files):
    for path in corpus_files[::97]:
        original = open(path, encoding="utf-8", newline="").read()
        rendered = write_txt(read_txt(path, use_mu2=False),
                             trailing_newline=original.endswith("\n"))
        assert rendered == original, path


@corpus_available
def test_every_writer_survives_a_sample_of_the_corpus(corpus_files):
    for path in corpus_files[::173]:
        score = read_txt(path, use_mu2=False)
        assert write_midi(score)
        assert write_musicxml(score)
        assert write_abc(score)
        assert write_kern(score)
        assert write_tokens(score, preset="gold53")
        assert write_json(score)
