"""The pitch model, which everything else is built on."""

from fractions import Fraction

import pytest

from microtonal_score_converter.pitch import (C4_KOMA, OCTAVE_COMMAS, Pitch, PitchParseError,
                              deviation_semitones, nominal_midi, quantize,
                              quantization_error_cents)


@pytest.mark.parametrize("name,koma", [
    ("Do4", 265), ("C4", 265),          # the anchor: C4 is MIDI 60
    ("Re5", 327), ("D5", 327),
    ("Si4b2", 312), ("B4b1", 313),      # the two spellings of segah differ
    ("Mi5b3", 333), ("E5b4", 332),
    ("Fa5#3", 343), ("F5#4", 344),
    ("La4", 305), ("Sol3", 243),
    ("Do7", 424), ("Si4b6", 308),
])
def test_names_follow_the_linear_comma_formula(name, koma):
    assert Pitch.parse(name).koma == koma


def test_c4_is_midi_60_exactly():
    assert Pitch.parse("Do4").midi == 60
    assert Pitch.parse("Do4").midi.denominator == 1


def test_octave_is_53_commas():
    assert Pitch.parse("Do5").koma - Pitch.parse("Do4").koma == OCTAVE_COMMAS


def test_midi_is_exact_rational_not_float():
    assert Pitch.parse("Si4b2").midi == Fraction(312 * 12, 53)


def test_solfege_and_letter_spellings_round_trip():
    assert Pitch.parse("Mi5b3").name == "Mi5b3"
    assert Pitch.parse("E5b4").name == "E5b4"


def test_from_koma_prefers_the_smallest_alteration():
    # 312 is reachable as B4b2 (-2) or C5b6 (-6); the smaller wins.
    assert Pitch.from_koma(312).name == "Si4b2"
    assert Pitch.from_koma(C4_KOMA).name == "Do4"


def test_unparsable_names_raise():
    with pytest.raises(PitchParseError):
        Pitch.parse("H4")
    with pytest.raises(PitchParseError):
        Pitch.parse("Es")


def test_accidental_glyphs_match_arel_ezgi():
    assert Pitch.parse("B4b1").accidental_glyph == "quarter-flat"
    assert Pitch.parse("E5b4").accidental_glyph == "slash-flat"
    assert Pitch.parse("F5#4").accidental_glyph == "sharp"
    assert Pitch.parse("La4").accidental_glyph is None


def test_glyph_falls_back_to_the_nearest_in_the_same_direction():
    # b2 has no Arel-Ezgi glyph; it must not become a sharp.
    assert Pitch.parse("Si4b2").accidental_glyph == "quarter-flat"
    assert Pitch.parse("Do5#6").accidental_glyph.endswith("sharp")


@pytest.mark.parametrize("edo,maximum", [(12, 50.0), (24, 25.0), (53, 0.0)])
def test_quantisation_error_is_bounded_by_half_a_step(edo, maximum):
    worst = max(abs(quantization_error_cents(k, edo))
                for k in range(243, 425))
    assert worst <= maximum + 1e-9


def test_quantisation_to_53_is_lossless():
    for koma in range(243, 425):
        assert quantize(koma, 53) == koma


def test_deviation_absorbs_the_natural_degree_offset():
    # 53-TET's D is 3.77 cents above 12-TET's, so even a natural needs a value.
    assert Pitch.parse("Re5").alteration == 0
    assert float(deviation_semitones(Pitch.parse("Re5"))) == pytest.approx(
        0.0377, abs=1e-4)
    assert nominal_midi(Pitch.parse("Re5")) == 74


def test_deviation_is_zero_only_where_the_grids_coincide():
    assert deviation_semitones(Pitch.parse("Do5")) == 0
    assert deviation_semitones(Pitch.parse("Si4")) != 0
