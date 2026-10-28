"""Minimal ABC reader, for round-trip verification.

Covers the subset this package emits: header fields, bar lines, rests, grace
notes in braces, decorations in exclamation marks, annotations in quotes, and
-- the part that matters -- fractional microtonal accidentals (``^12/53``,
``_/2``).  It is not a general ABC parser; it exists so the claim that ABC can
carry 53-TET is measured on real output rather than assumed from the spec.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, List, Optional

_STEP_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}

_TOKEN_RE = re.compile(
    r"""
    (?P<annotation>"[^"]*")
  | (?P<decoration>![^!]*!)
  | (?P<grace>\{[^}]*\})
  | (?P<accidental>(?:\^{1,2}|_{1,2}|=)(?:\d*/\d+|\d+)?)?
      (?P<letter>[A-Ga-g])(?P<octave>[',]*)
      (?P<length>\d*(?:/\d*)?)
  | (?P<rest>[zx])(?P<rest_length>\d*(?:/\d*)?)
  | (?P<bar>\|\]|\|\||:\||\|:|\|)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class AbcNote:
    step: str
    octave: int
    alter_semitones: Fraction
    duration: Fraction        # in whole notes
    is_rest: bool = False
    is_grace: bool = False

    @property
    def cents(self) -> Optional[float]:
        if self.is_rest:
            return None
        semitones = (self.octave + 1) * 12 + _STEP_SEMITONES[self.step.upper()]
        return semitones * 100.0 + float(self.alter_semitones) * 100.0


@dataclass
class AbcTune:
    notes: List[AbcNote] = field(default_factory=list)
    fields: Dict[str, str] = field(default_factory=dict)
    comments: List[str] = field(default_factory=list)
    lyrics: List[str] = field(default_factory=list)
    bars: int = 0
    annotations: List[str] = field(default_factory=list)
    unit: Fraction = Fraction(1, 8)


def read_abc(source) -> AbcTune:
    """Parse ABC from a path or a string."""
    text = source if "\n" in source or source.startswith("X:") \
        else open(source, encoding="utf-8").read()

    tune = AbcTune()
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("%%"):
            tune.comments.append(stripped[2:].strip())
            continue
        if len(stripped) > 1 and stripped[1] == ":":
            key, value = stripped[0], stripped[2:].strip()
            if key == "w":
                tune.lyrics.append(value)
            else:
                tune.fields[key] = value
                if key == "L":
                    tune.unit = Fraction(value)
            continue
        _parse_music(stripped, tune)
    return tune


def _parse_music(line: str, tune: AbcTune) -> None:
    # Accidentals persist to the end of the bar for the same letter and octave.
    in_force: Dict[tuple, Fraction] = {}
    for match in _TOKEN_RE.finditer(line):
        if match.group("annotation"):
            tune.annotations.append(match.group("annotation").strip('"'))
        elif match.group("bar"):
            tune.bars += 1
            in_force.clear()
        elif match.group("grace"):
            inner = match.group("grace")[1:-1]
            for note in _parse_notes(inner, tune.unit, dict(in_force)):
                tune.notes.append(
                    AbcNote(note.step, note.octave, note.alter_semitones,
                            Fraction(0), False, True))
        elif match.group("letter"):
            tune.notes.append(_build_note(match, tune.unit, in_force))
        elif match.group("rest"):
            tune.notes.append(AbcNote(
                "C", 4, Fraction(0),
                _length(match.group("rest_length"), tune.unit), is_rest=True))


def _parse_notes(fragment: str, unit: Fraction, in_force: dict) -> List[AbcNote]:
    return [_build_note(m, unit, in_force) for m in _TOKEN_RE.finditer(fragment)
            if m.group("letter")]


def _build_note(match, unit: Fraction, in_force: dict) -> AbcNote:
    letter = match.group("letter")
    octave = 5 if letter.islower() else 4
    marks = match.group("octave") or ""
    octave += marks.count("'") - marks.count(",")

    key = (letter.upper(), octave)
    token = match.group("accidental")
    if token:
        alteration = _alter(token)
        in_force[key] = alteration
    else:
        alteration = in_force.get(key, Fraction(0))

    return AbcNote(
        step=letter.upper(),
        octave=octave,
        alter_semitones=alteration,
        duration=_length(match.group("length"), unit),
    )


def _alter(token: Optional[str]) -> Fraction:
    """Decode ``^``/``_``/``=`` with an optional fractional magnitude."""
    if not token:
        return Fraction(0)
    sign_part = token[0]
    if sign_part == "=":
        return Fraction(0)
    signs = len(token) - len(token.lstrip("^_"))
    magnitude_text = token[signs:]
    if not magnitude_text:
        magnitude = Fraction(signs)
    elif magnitude_text.startswith("/"):
        magnitude = Fraction(1, int(magnitude_text[1:]))
    elif "/" in magnitude_text:
        numerator, denominator = magnitude_text.split("/")
        magnitude = Fraction(int(numerator), int(denominator))
    else:
        magnitude = Fraction(int(magnitude_text))
    return magnitude if sign_part == "^" else -magnitude


def _length(token: Optional[str], unit: Fraction) -> Fraction:
    if not token:
        return unit
    if token.startswith("/"):
        denominator = int(token[1:]) if len(token) > 1 else 2
        return unit / denominator
    if "/" in token:
        numerator, denominator = token.split("/")
        return unit * Fraction(int(numerator or 1), int(denominator or 2))
    return unit * int(token)
