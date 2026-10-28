"""Minimal MusicXML reader, for round-trip verification.

Extracts what the audit compares: pitch (step, alter, octave), duration in
divisions, ties, lyrics and whether an ``<accidental>`` was written without a
matching ``<alter>`` -- the failure mode that costs SymbTr's own exports 5.7%
of their notes.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from fractions import Fraction
from typing import List, Optional

_STEP_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


@dataclass(frozen=True)
class XmlNote:
    step: Optional[str]
    octave: Optional[int]
    alter: float
    duration: Fraction           # in whole notes
    is_rest: bool
    is_grace: bool
    tie_start: bool
    tie_stop: bool
    lyric: str
    accidental: Optional[str]
    alter_missing: bool          # an accidental glyph with no <alter>

    @property
    def cents(self) -> Optional[float]:
        """Sounding pitch in cents above C-1, or ``None`` for a rest."""
        if self.is_rest or self.step is None or self.octave is None:
            return None
        semitones = (self.octave + 1) * 12 + _STEP_SEMITONES[self.step]
        return semitones * 100.0 + self.alter * 100.0


@dataclass
class XmlScore:
    notes: List[XmlNote] = field(default_factory=list)
    divisions: int = 1
    measures: int = 0
    directions: List[str] = field(default_factory=list)
    title: str = ""
    composer: str = ""


def read_musicxml(source) -> XmlScore:
    """Parse MusicXML from a path or a string."""
    if isinstance(source, str) and source.lstrip().startswith("<"):
        # Strip the DOCTYPE: ElementTree will not fetch the external DTD.
        root = ET.fromstring(_strip_doctype(source))
    else:
        root = ET.parse(source).getroot()

    out = XmlScore()
    out.title = _text(root, ".//work-title")
    out.composer = _text(root, './/creator[@type="composer"]')

    divisions = 1
    for measure in root.iter("measure"):
        out.measures += 1
        found = measure.find("./attributes/divisions")
        if found is not None and found.text:
            divisions = int(found.text)
            out.divisions = divisions
        for direction in measure.iter("other-direction"):
            if direction.text:
                out.directions.append(direction.text)
        for note in measure.findall("note"):
            out.notes.append(_parse_note(note, divisions))
    return out


def _parse_note(note: ET.Element, divisions: int) -> XmlNote:
    pitch = note.find("pitch")
    accidental = note.find("accidental")
    alter_element = pitch.find("alter") if pitch is not None else None

    alter = 0.0
    if alter_element is not None and alter_element.text:
        alter = float(alter_element.text)

    duration_element = note.find("duration")
    duration = Fraction(0)
    if duration_element is not None and duration_element.text:
        duration = Fraction(int(duration_element.text), divisions * 4)

    ties = {t.get("type") for t in note.findall("tie")}
    lyric = note.find("./lyric/text")

    return XmlNote(
        step=_text(pitch, "step") or None if pitch is not None else None,
        octave=int(_text(pitch, "octave") or 0) if pitch is not None else None,
        alter=alter,
        duration=duration,
        is_rest=note.find("rest") is not None,
        is_grace=note.find("grace") is not None,
        tie_start="start" in ties,
        tie_stop="stop" in ties,
        lyric=(lyric.text or "") if lyric is not None else "",
        accidental=accidental.text if accidental is not None else None,
        alter_missing=accidental is not None and alter_element is None,
    )


def _text(element: Optional[ET.Element], path: str) -> str:
    if element is None:
        return ""
    found = element.find(path)
    return (found.text or "") if found is not None else ""


def _strip_doctype(text: str) -> str:
    start = text.find("<!DOCTYPE")
    if start == -1:
        return text
    end = text.find(">", start)
    return text[:start] + text[end + 1:]
