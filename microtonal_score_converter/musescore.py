"""Restoring 53-TET tuning to a MuseScore file.

MuseScore reads our MusicXML's pitches and accidentals correctly and then
plays everything in 12-TET, because **MuseScore ignores fractional
``<alter>`` for playback**.  Measured here against MuseScore 2.3.2, rendering
to audio and estimating the sounding f0 of each note:

=========================================  ====================
our MusicXML, opened in MuseScore          up to 67 cents wrong
the same score with per-note ``<tuning>``  within 2 cents
=========================================  ====================

Worse, MuseScore *truncates* a fractional ``<alter>`` toward zero rather than
rounding it: a 3-comma flat (``alter = -0.604``) is played as a natural, not
as a flat.  So the lossless ``precision="exact"`` MusicXML is the *worst*
option for MuseScore playback -- it is a semitone out where
``precision="12tet"`` would at least pick the nearest semitone.

MuseScore's own answer to microtonality is ``Note.tuning``, the per-note cent
offset in the Properties panel, stored in its native format as
``<Note><tuning>-35.85</tuning>``.  That element has been there since
MuseScore 1.x and is still there in 4.x, so writing it is version-proof in a
way that guessing at MusicXML semantics is not.

This module therefore takes a ``.mscz``/``.mscx`` that MuseScore produced from
our MusicXML and writes the exact tuning into every note.  Going through
MuseScore's own importer rather than generating its native format from scratch
means tuplets, ties, lyrics, ornaments and layout are all handled by MuseScore
itself; the only thing we change is the one thing it gets wrong.
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .pitch import LETTER_SEMITONES, OCTAVE_COMMAS, Pitch
from .score import Event, Score
from .writers.midi import A4_KOMA, _anchor_offset

#: MuseScore's tonal pitch class is a position on the line of fifths with
#: F = 13; a sharp adds 7 and a flat subtracts 7.  Confirmed by round-tripping
#: every Arel-Ezgi accidental through MuseScore 2.3.2.
TPC_NATURALS = {"F": 13, "C": 14, "G": 15, "D": 16, "A": 17, "E": 18, "B": 19}

#: MusicXML accidental glyph -> MuseScore ``<Accidental><subtype>``, as
#: MuseScore itself maps them on import.  Kept here so a generated file can be
#: checked against what MuseScore would have produced.
ACCIDENTAL_SUBTYPES = {
    "quarter-flat": "mirrored-flat",
    "slash-flat": "flat-slash",
    "flat": "flat",
    "double-slash-flat": "flat-slash2",
    "quarter-sharp": "sharp-slash",
    "sharp": "sharp",
    "slash-quarter-sharp": "sharp-slash3",
    "slash-sharp": "sharp-slash2",
    "natural": "natural",
}

_NOTE_RE = re.compile(r"<Note>(?P<body>.*?)</Note>", re.S)
_PITCH_RE = re.compile(r"<pitch>(-?\d+)</pitch>")
_TUNING_RE = re.compile(r"\s*<tuning>[^<]*</tuning>")
_TIE_RE = re.compile(r"<Tie[ >]|<Spanner type=\"Tie\"")
_TIE_PREV_RE = re.compile(r"<Spanner type=\"Tie\">.*?<prev>", re.S)


class RetuneError(ValueError):
    """Raised when a MuseScore file cannot be matched against the gold score."""


@dataclass
class RetuneReport:
    """What :func:`retune` did, so the caller can check rather than trust."""

    notes_seen: int = 0
    notes_tuned: int = 0
    tie_continuations: int = 0
    events_consumed: int = 0
    events_total: int = 0
    max_cents: float = 0.0
    warnings: List[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return (self.events_consumed == self.events_total
                and self.notes_tuned == self.notes_seen)

    def summary(self) -> str:
        lines = [
            f"notes retuned: {self.notes_tuned} of {self.notes_seen} "
            f"({self.tie_continuations} tie continuations)",
            f"gold events matched: {self.events_consumed} of {self.events_total}",
            f"largest tuning offset: {self.max_cents:.2f} cents",
        ]
        lines += [f"warning: {w}" for w in self.warnings]
        return "\n".join(lines)


# -- tuning -----------------------------------------------------------------


def nominal_midi_for(pitch: Pitch) -> int:
    """The 12-TET note MuseScore will have assigned to this spelling.

    Identical to the MIDI writer's ``symbtr`` convention: the letter and octave
    plus ``round(alteration x 12/53)`` semitones, which is what MuseScore
    derives from ``<step>``, ``<octave>`` and a rounded ``<alter>``.
    """
    natural = (pitch.octave + 1) * 12 + LETTER_SEMITONES[pitch.letter]
    return natural + round(pitch.alteration * 12.0 / OCTAVE_COMMAS)


def tuning_cents(pitch: Pitch, anchor: Optional[int] = A4_KOMA) -> float:
    """Cents to add to the 12-TET note to sound the exact 53-TET pitch.

    Anchored on A by default so that A4 is concert pitch and the rest of the
    scale sits where SymbTr's own MIDI puts it, rather than making C exact and
    leaving A 5.7 cents sharp.
    """
    cents = pitch.koma * 1200.0 / OCTAVE_COMMAS - nominal_midi_for(pitch) * 100.0
    if anchor is not None:
        cents -= _anchor_offset(anchor)
    return cents


def tpc_for(pitch: Pitch) -> int:
    """MuseScore tonal pitch class for a spelling."""
    return TPC_NATURALS[pitch.letter] + 7 * round(
        pitch.alteration * 12.0 / OCTAVE_COMMAS)


# -- the transformation -----------------------------------------------------


def retune_mscx(
    text: str,
    score: Score,
    *,
    anchor: Optional[int] = A4_KOMA,
    strict: bool = True,
    max_offset: float = 150.0,
) -> Tuple[str, RetuneReport]:
    """Write exact per-note ``<tuning>`` into MuseScore native XML.

    The tuning is computed against **MuseScore's own** ``<pitch>``, not against
    the pitch we would have chosen.  That matters because MuseScore truncates
    a fractional ``<alter>`` toward zero, so it sometimes lands a semitone away
    from the written accidental -- and correcting from where it actually is
    makes the sounding pitch exact either way.

    Notes are matched to the gold score positionally, with tie continuations
    (which our MusicXML creates for any duration no single symbol covers)
    detected from MuseScore's tie markup and consuming no new gold event.  The
    match is then checked: a tuning further than ``max_offset`` cents from the
    note means the file does not correspond to this score, and that raises
    rather than quietly mis-tuning it.
    """
    gold = [e for e in score.events if e.is_note]
    report = RetuneReport(events_total=len(gold))
    state = {"index": 0, "previous": None, "tie_open": False, "previous_midi": None}

    def replace(match: re.Match) -> str:
        body = match.group("body")
        report.notes_seen += 1

        pitch_match = _PITCH_RE.search(body)
        if pitch_match is None:
            report.warnings.append(
                f"note {report.notes_seen} has no <pitch>; left untouched")
            return match.group(0)
        midi_pitch = int(pitch_match.group(1))

        event = _next_event(state, gold, midi_pitch, report, strict)
        tie_open = bool(_TIE_RE.search(body)) and not bool(_TIE_PREV_RE.search(body))
        state["tie_open"] = tie_open
        state["previous_midi"] = midi_pitch
        if event is None:
            return match.group(0)

        cents = (event.pitch53.koma * 1200.0 / OCTAVE_COMMAS
                 - midi_pitch * 100.0)
        if anchor is not None:
            cents -= _anchor_offset(anchor)

        if abs(cents) > max_offset:
            message = (f"note {report.notes_seen} would need {cents:+.0f} cents "
                       f"to reach {event.pitch53.name}; the file does not look "
                       f"like this score")
            if strict:
                raise RetuneError(message)
            report.warnings.append(message)
            return match.group(0)

        report.max_cents = max(report.max_cents, abs(cents))
        report.notes_tuned += 1

        cleaned = _TUNING_RE.sub("", body)
        indent = _indent_of(cleaned)
        tuned = _PITCH_RE.sub(
            lambda m: f"{m.group(0)}\n{indent}<tuning>{cents:.4f}</tuning>",
            cleaned, count=1)
        return f"<Note>{tuned}</Note>"

    out = _NOTE_RE.sub(replace, text)
    report.events_consumed = state["index"]

    if strict and not report.complete:
        raise RetuneError(
            f"matched {report.events_consumed} of {report.events_total} gold "
            f"notes against {report.notes_seen} MuseScore notes; the file does "
            f"not correspond to this score")
    return out, report


def _next_event(state, gold, midi_pitch, report, strict) -> Optional[Event]:
    """Pick the gold event this MuseScore note stands for.

    A tie continuation repeats the previous note at the same pitch and belongs
    to the same gold event, so it must not advance the pointer.
    """
    if (state["tie_open"] and state["previous"] is not None
            and state["previous_midi"] == midi_pitch):
        report.tie_continuations += 1
        return state["previous"]

    index = state["index"]
    if index < len(gold):
        event = gold[index]
        state["index"] = index + 1
        state["previous"] = event
        return event

    message = (f"MuseScore has more notes than the score: note "
               f"{report.notes_seen} is past gold note {len(gold)}")
    if strict:
        raise RetuneError(message)
    report.warnings.append(message)
    return None


def _indent_of(body: str) -> str:
    match = re.search(r"\n(\s*)<pitch>", body)
    return match.group(1) if match else "            "


# -- file handling ----------------------------------------------------------


def retune_file(
    musescore_path: str,
    score: Score,
    output_path: Optional[str] = None,
    *,
    anchor: Optional[int] = A4_KOMA,
    strict: bool = True,
) -> RetuneReport:
    """Retune a ``.mscx`` or ``.mscz`` in place, or to ``output_path``.

    ``.mscz`` is a zip; only the score XML inside it is rewritten, so
    thumbnails, audio settings and anything else MuseScore stored survive.
    """
    destination = output_path or musescore_path
    if musescore_path.lower().endswith(".mscz"):
        return _retune_mscz(musescore_path, destination, score, anchor, strict)

    with open(musescore_path, encoding="utf-8") as handle:
        text = handle.read()
    out, report = retune_mscx(text, score, anchor=anchor, strict=strict)
    with open(destination, "w", encoding="utf-8") as handle:
        handle.write(out)
    return report


def _retune_mscz(source, destination, score, anchor, strict) -> RetuneReport:
    with zipfile.ZipFile(source) as archive:
        entries = [(item, archive.read(item.filename))
                   for item in archive.infolist()]

    inner = [name for name, _ in
             ((item.filename, data) for item, data in entries)
             if name.lower().endswith(".mscx")]
    if not inner:
        raise RetuneError(f"{source}: no .mscx inside the .mscz")

    report: Optional[RetuneReport] = None
    rewritten = []
    for item, data in entries:
        if item.filename == inner[0]:
            text = data.decode("utf-8")
            out, report = retune_mscx(text, score, anchor=anchor, strict=strict)
            data = out.encode("utf-8")
        rewritten.append((item, data))

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for item, data in rewritten:
            archive.writestr(item, data)
    with open(destination, "wb") as handle:
        handle.write(buffer.getvalue())

    assert report is not None  # the inner .mscx was found above
    return report
