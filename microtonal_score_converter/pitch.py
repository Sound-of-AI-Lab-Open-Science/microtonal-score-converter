"""Pitch arithmetic for the SymbTr 53-TET (Holdrian comma) pitch space.

SymbTr encodes every pitch twice: once in 53-tone equal temperament (``Nota53``
/ ``Koma53``) and once in the 24-tone Arel-Ezgi theory (``NotaAE`` / ``KomaAE``).
Both use the *same* integer comma scale, so a single arithmetic model covers
them; only the spelling vocabulary differs.

The scale is exactly linear.  Verified against all 849,403 pitched rows of
SymbTr v2.4.3 with zero mismatches::

    koma = 265 + 53 * (octave - 4) + degree[letter] + alteration

``Do4``/``C4`` is comma 265, which is MIDI 60, so the whole comma scale is
anchored at ``koma 0 == MIDI 0 == C-1`` and::

    midi = koma * 12 / 53        (exact; 265 * 12 / 53 == 60)
    cents_above_C-1 = koma * 1200 / 53

That identity is the reason every other representation in this package can be
derived mechanically rather than by table lookup.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

#: Comma offsets of the natural degrees within an octave (53 commas).
DEGREE_COMMAS = {"C": 0, "D": 9, "E": 18, "F": 22, "G": 31, "A": 40, "B": 49}

#: Turkish solfege syllable -> Western letter name.
SOLFEGE_TO_LETTER = {
    "Do": "C", "Re": "D", "Mi": "E", "Fa": "F",
    "Sol": "G", "La": "A", "Si": "B",
}
LETTER_TO_SOLFEGE = {v: k for k, v in SOLFEGE_TO_LETTER.items()}

#: Comma value of C4 == MIDI 60.  Anchors the whole system.
C4_KOMA = 265

#: Commas per octave.
OCTAVE_COMMAS = 53

#: One Holdrian comma in cents.
COMMA_CENTS = Fraction(1200, 53)

#: Rest sentinel used in the ``Nota53``/``NotaAE`` columns.
REST_NAME = "Es"

#: Semitones above C for each letter name, i.e. the 12-TET reading of a natural.
#: Note that these are *not* the 53-TET naturals: 53-TET's D sits 3.8 cents
#: above 12-TET's and its B 9.4 cents above, which is why a letter-based
#: notation has to put that difference somewhere (see :func:`deviation_semitones`).
LETTER_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

_NOTE_RE = re.compile(
    r"^(Do|Re|Mi|Fa|Sol|La|Si|[A-G])(-?\d+)(?:([#b])(\d+))?$"
)

#: MusicXML accidental glyph names for the Arel-Ezgi accidentals, keyed by the
#: alteration in commas.  Taken from the SymbTr->MusicXML conventions used by
#: ``tomato`` so that scores we emit render identically to the official ones.
AE_ACCIDENTAL_GLYPHS = {
    -8: "double-slash-flat",   # buyuk mucennep
    -5: "flat",                # kucuk mucennep
    -4: "slash-flat",          # bakiyye
    -1: "quarter-flat",        # koma
    0: "natural",
    1: "quarter-sharp",        # koma
    4: "sharp",                # bakiyye
    5: "slash-quarter-sharp",  # kucuk mucennep
    8: "slash-sharp",          # buyuk mucennep
}


class PitchParseError(ValueError):
    """Raised when a SymbTr note name cannot be parsed."""


@dataclass(frozen=True)
class Pitch:
    """A spelled pitch in the SymbTr comma space.

    ``koma`` alone is not enough to round-trip a score: comma 278 is both
    ``Re4#4`` and ``Mi4b5``.  The spelling (letter/octave/alteration) is
    therefore carried alongside and treated as authoritative; ``koma`` is a
    derived convenience that we cross-check on construction.
    """

    letter: str          # Western letter name, "C".."B"
    octave: int          # scientific octave; C4 == middle C == MIDI 60
    alteration: int = 0  # alteration in commas, positive = sharp
    solfege: bool = True  # True if the source spelled it in Turkish solfege

    def __post_init__(self) -> None:
        if self.letter not in DEGREE_COMMAS:
            raise PitchParseError(f"unknown letter name {self.letter!r}")

    # -- construction ----------------------------------------------------

    @classmethod
    def parse(cls, name: str) -> "Pitch":
        """Parse a ``Nota53`` or ``NotaAE`` spelling, e.g. ``Mi5b3``/``E5b4``."""
        m = _NOTE_RE.match(name.strip())
        if not m:
            raise PitchParseError(f"cannot parse note name {name!r}")
        head, octave, sign, amount = m.groups()
        solfege = head in SOLFEGE_TO_LETTER
        letter = SOLFEGE_TO_LETTER[head] if solfege else head
        alteration = 0
        if sign:
            alteration = int(amount) * (1 if sign == "#" else -1)
        return cls(letter, int(octave), alteration, solfege)

    @classmethod
    def from_koma(cls, koma: int, *, solfege: bool = True) -> "Pitch":
        """Spell a comma value using the smallest alteration available.

        Used when a pitch arrives without a spelling (e.g. read back from MIDI).
        Prefers naturals, then the alteration of smallest magnitude, breaking
        ties towards flats, which matches SymbTr's own preference for makam
        scales (``b`` spellings outnumber ``#`` spellings roughly 2:1).
        """
        octave, within = divmod(koma - C4_KOMA + 4 * OCTAVE_COMMAS, OCTAVE_COMMAS)
        best = None
        for letter, base in DEGREE_COMMAS.items():
            for oct_shift in (-1, 0, 1):
                alteration = within - base - oct_shift * OCTAVE_COMMAS
                if abs(alteration) > 8:
                    continue
                key = (abs(alteration), alteration > 0, letter)
                if best is None or key < best[0]:
                    best = (key, letter, octave + oct_shift, alteration)
        if best is None:  # pragma: no cover - unreachable for any int koma
            raise PitchParseError(f"cannot spell comma value {koma}")
        _, letter, octave, alteration = best
        return cls(letter, octave, alteration, solfege)

    # -- derived values --------------------------------------------------

    @property
    def koma(self) -> int:
        """Absolute position in Holdrian commas, with C-1 == 0."""
        return (
            C4_KOMA
            + OCTAVE_COMMAS * (self.octave - 4)
            + DEGREE_COMMAS[self.letter]
            + self.alteration
        )

    @property
    def midi(self) -> Fraction:
        """Exact fractional MIDI note number."""
        return Fraction(self.koma * 12, 53)

    @property
    def cents(self) -> Fraction:
        """Exact cents above C-1 (MIDI 0)."""
        return Fraction(self.koma * 1200, 53)

    def hz(self, a4_hz: float = 440.0) -> float:
        """Frequency in Hz for a given concert-A reference."""
        return a4_hz * 2.0 ** ((float(self.midi) - 69.0) / 12.0)

    # -- spelling --------------------------------------------------------

    @property
    def name(self) -> str:
        """Re-emit the SymbTr spelling this pitch was parsed from."""
        head = LETTER_TO_SOLFEGE[self.letter] if self.solfege else self.letter
        if self.alteration == 0:
            return f"{head}{self.octave}"
        sign = "#" if self.alteration > 0 else "b"
        return f"{head}{self.octave}{sign}{abs(self.alteration)}"

    @property
    def accidental_glyph(self) -> Optional[str]:
        """Closest Arel-Ezgi accidental glyph name, for MusicXML/engraving.

        53-TET spellings use alterations (``b2``, ``b3``, ``#2`` ...) that have
        no Arel-Ezgi glyph.  We fall back to the nearest glyph; the exact value
        always travels in the numeric ``alter``, so nothing is lost.
        """
        if self.alteration == 0:
            return None
        if self.alteration in AE_ACCIDENTAL_GLYPHS:
            return AE_ACCIDENTAL_GLYPHS[self.alteration]
        same_direction = [
            k for k in AE_ACCIDENTAL_GLYPHS if (k > 0) == (self.alteration > 0)
        ]
        nearest = min(same_direction, key=lambda k: abs(k - self.alteration))
        return AE_ACCIDENTAL_GLYPHS[nearest]

    @property
    def alter_semitones(self) -> Fraction:
        """Alteration in (fractional) semitones, as MusicXML's ``alter`` wants."""
        return Fraction(self.alteration * 12, 53)

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.name


# -- tuning-grid quantisation ----------------------------------------------


def quantize(koma: int, edo: int) -> int:
    """Round a comma value to the nearest step of ``edo``-tone equal temperament.

    Returns the step index, where step 0 == C-1.  ``edo=12`` gives an integer
    MIDI note number; ``edo=24`` gives quarter-tone steps; ``edo=53`` is the
    identity in disguise.
    """
    # koma/53 octaves * edo steps per octave, rounded half away from zero so the
    # result is symmetric for sharps and flats.
    num = koma * edo
    q, rem = divmod(num, OCTAVE_COMMAS)
    if 2 * rem >= OCTAVE_COMMAS:
        q += 1
    return q


def quantization_error_cents(koma: int, edo: int) -> float:
    """Signed cents by which ``quantize(koma, edo)`` misses the true pitch.

    Positive means the quantised pitch is sharp of the original.  This is the
    per-note primitive behind the information-loss audit.
    """
    exact = koma * 1200.0 / OCTAVE_COMMAS
    approx = quantize(koma, edo) * 1200.0 / edo
    return approx - exact


def koma_to_midi(koma: int) -> float:
    """Fractional MIDI note number for a comma value."""
    return koma * 12.0 / OCTAVE_COMMAS


def midi_to_koma(midi: float) -> int:
    """Nearest comma value for a (possibly fractional) MIDI note number."""
    return int(round(midi * OCTAVE_COMMAS / 12.0))


def nominal_midi(pitch: "Pitch") -> int:
    """The 12-TET MIDI note a reader gets from the letter and octave alone."""
    return (pitch.octave + 1) * 12 + LETTER_SEMITONES[pitch.letter]


def deviation_semitones(pitch: "Pitch") -> Fraction:
    """Exact distance from the 12-TET note of this pitch's letter and octave.

    This is the value a letter-based format (MusicXML ``<alter>``, an ABC
    accidental) must carry if the sounding pitch is to survive, because every
    consumer reads the bare letter as 12-TET.  It differs from the *written*
    accidental: 53-TET's natural B is 9.4 cents above 12-TET's, so even an
    unaltered note needs a non-zero value to be exact.
    """
    return Fraction(pitch.koma * 12, OCTAVE_COMMAS) - nominal_midi(pitch)
