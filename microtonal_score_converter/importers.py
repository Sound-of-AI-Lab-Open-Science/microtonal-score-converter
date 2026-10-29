"""Rebuild a slim :class:`~microtonal_score_converter.score.Score` from formats
this package emits.

These importers assume *our* writers' subset (the same contract the audit
readers already parse).  They recover sounding pitch in 53-TET commas and
symbolic duration; they do **not** reconstruct Arel-Ezgi spelling, ``Kod``
structure, lyrics, ``Ms``, or other SymbTr columns the intermediate format
never carried.  The result is enough to convert microtonal MIDI/ABC/MusicXML
into any other writer target while keeping 53-TET pitch intact on the
lossless paths.
"""

from __future__ import annotations

import json
from fractions import Fraction
from typing import List, Optional, Tuple, Union

from .pitch import OCTAVE_COMMAS, Pitch
from .readers.abc import read_abc
from .readers.midi import read_midi
from .readers.musicxml import read_musicxml
from .readers.txt import read_txt
from .score import Event, Metadata, Score
from .writers.jsonio import score_from_dict
from .writers.midi import A4_KOMA

#: Ordinary note / rest row in SymbTr.
_NOTE_CODE = 9
#: Grace note that borrows from the following note.
_GRACE_CODE = 8

DEFAULT_LNS = 95
DEFAULT_VELOCITY = 96


def cents_to_koma(cents: float) -> int:
    """Nearest Holdrian comma for a pitch in cents above C-1."""
    return int(round(cents * OCTAVE_COMMAS / 1200.0))


def pitch_from_cents(cents: float) -> Pitch:
    """Spell the nearest 53-TET pitch for an absolute cents value."""
    return Pitch.from_koma(cents_to_koma(cents))


def _midi_anchor_offset(anchor_koma: int) -> float:
    """Cents to add back after reading a SymbTr-anchored MIDI file.

    ``write_midi`` subtracts the anchor's distance above its 12-TET note from
    every bend; undoing that restores absolute cents above C-1.
    """
    return (anchor_koma * 1200.0 / OCTAVE_COMMAS
            - round(anchor_koma * 12.0 / OCTAVE_COMMAS) * 100.0)


def _duration_parts(duration: Fraction) -> Tuple[int, int]:
    """``Pay``/``Payda`` for a duration in whole notes."""
    if duration <= 0:
        return 0, 0
    return duration.numerator, duration.denominator


def _event(
    index: int,
    *,
    pitch: Optional[Pitch],
    duration: Fraction,
    is_rest: bool = False,
    is_grace: bool = False,
    offset_end: Fraction = Fraction(0),
    velocity: int = DEFAULT_VELOCITY,
    text: str = "",
) -> Event:
    numerator, denominator = _duration_parts(duration)
    code = _GRACE_CODE if is_grace else _NOTE_CODE
    return Event(
        index=index,
        code=code,
        offset=offset_end - duration if duration > 0 else offset_end,
        offset_end=offset_end,
        numerator=numerator,
        denominator=denominator,
        ms=0,
        lns=DEFAULT_LNS if not is_rest else 100,
        velocity=0 if is_rest else velocity,
        text=text,
        pitch53=None if is_rest else pitch,
        pitchAE=None if is_rest else pitch,
        rest_marker=is_rest,
        koma53_raw=-1 if is_rest else None,
        komaAE_raw=-1 if is_rest else None,
        offset_text="",
    )


def _score_from_events(
    events: List[Event],
    *,
    metadata: Optional[Metadata] = None,
    warnings: Optional[List[str]] = None,
) -> Score:
    return Score(
        events=events,
        metadata=metadata or Metadata(),
        warnings=warnings or [
            "slim import: pitch and duration only; SymbTr structure not restored"
        ],
    )


def score_from_txt(
    path: str,
    *,
    mu2_path: Optional[str] = None,
    use_mu2: bool = True,
) -> Score:
    """Full SymbTr-txt import (delegates to :func:`read_txt`)."""
    return read_txt(path, mu2_path=mu2_path, use_mu2=use_mu2)


def score_from_json(source: Union[str, dict]) -> Score:
    """Full IR import from JSON text, a path, or a decoded dict."""
    if isinstance(source, dict):
        return score_from_dict(source)
    if isinstance(source, str) and not source.lstrip().startswith("{"):
        with open(source, encoding="utf-8") as handle:
            payload = json.load(handle)
    else:
        payload = json.loads(source)
    return score_from_dict(payload)


def score_from_midi(
    source,
    *,
    anchor: Optional[int] = A4_KOMA,
) -> Score:
    """Rebuild a slim score from MIDI this package (or SymbTr) wrote.

    Pitch bends are converted back to absolute cents.  When ``anchor`` is set
    (default A4 = 305, matching ``write_midi``), the SymbTr A-anchor offset is
    added back so recovered commas match the gold 53-TET values.  Pass
    ``anchor=None`` for files that bend in absolute cents (``bend-nearest``).
    """
    parsed = read_midi(source)
    division = parsed.division or 480
    offset = _midi_anchor_offset(anchor) if anchor is not None else 0.0

    notes = sorted(parsed.notes, key=lambda n: (n.tick, n.note))
    events: List[Event] = []
    running = Fraction(0)
    index = 1

    for i, note in enumerate(notes):
        if i + 1 < len(notes):
            slot_ticks = max(notes[i + 1].tick - note.tick, 1)
        else:
            # Last note: undo a default 95% LNS gate when the sounding length
            # is all we have.
            slot_ticks = max(int(round(note.duration / 0.95)), note.duration, 1)
        duration = Fraction(slot_ticks, division * 4)
        absolute_cents = note.cents + offset
        pitch = pitch_from_cents(absolute_cents)
        running += duration
        events.append(_event(
            index,
            pitch=pitch,
            duration=duration,
            offset_end=running,
            velocity=note.velocity if note.velocity else DEFAULT_VELOCITY,
        ))
        index += 1

    meta = Metadata()
    if parsed.tempo_bpm:
        meta.extra["mu2_tempo"] = str(round(parsed.tempo_bpm))
    return _score_from_events(events, metadata=meta)


def score_from_musicxml(source) -> Score:
    """Rebuild a slim score from MusicXML this package wrote."""
    parsed = read_musicxml(source)
    events: List[Event] = []
    running = Fraction(0)
    index = 1
    pending_tie: Optional[Event] = None

    for note in parsed.notes:
        if note.tie_stop and pending_tie is not None:
            # Fold the continuation into the tied head.
            head = pending_tie
            new_duration = head.duration + note.duration
            num, den = _duration_parts(new_duration)
            running += note.duration
            pending_tie = Event(
                index=head.index, code=head.code,
                offset=running - new_duration, offset_end=running,
                numerator=num, denominator=den, ms=0, lns=head.lns,
                velocity=head.velocity, text=head.text or note.lyric,
                pitch53=head.pitch53, pitchAE=head.pitchAE,
                rest_marker=head.rest_marker,
                koma53_raw=head.koma53_raw, komaAE_raw=head.komaAE_raw,
                offset_text="",
            )
            events[-1] = pending_tie
            if not note.tie_start:
                pending_tie = None
            continue

        if note.is_rest:
            duration = note.duration
            running += duration
            events.append(_event(
                index, pitch=None, duration=duration, is_rest=True,
                offset_end=running, text=note.lyric))
            index += 1
            pending_tie = None
            continue

        if note.cents is None:
            continue

        pitch = pitch_from_cents(note.cents)
        duration = note.duration
        running += duration if not note.is_grace else Fraction(0)
        event = _event(
            index, pitch=pitch, duration=duration,
            is_grace=note.is_grace, offset_end=running, text=note.lyric)
        events.append(event)
        index += 1
        pending_tie = event if note.tie_start else None

    meta = Metadata(title=parsed.title, composer=parsed.composer)
    return _score_from_events(events, metadata=meta)


def score_from_abc(source) -> Score:
    """Rebuild a slim score from ABC this package wrote."""
    parsed = read_abc(source)
    events: List[Event] = []
    running = Fraction(0)
    index = 1

    for note in parsed.notes:
        if note.is_rest:
            duration = note.duration
            running += duration
            events.append(_event(
                index, pitch=None, duration=duration, is_rest=True,
                offset_end=running))
            index += 1
            continue

        if note.cents is None:
            continue

        pitch = pitch_from_cents(note.cents)
        duration = note.duration
        if note.is_grace:
            events.append(_event(
                index, pitch=pitch, duration=Fraction(0), is_grace=True,
                offset_end=running))
        else:
            running += duration
            events.append(_event(
                index, pitch=pitch, duration=duration, offset_end=running))
        index += 1

    meta = Metadata(
        title=parsed.fields.get("T", ""),
        composer=parsed.fields.get("C", ""),
    )
    for comment in parsed.comments:
        if comment.startswith("makam "):
            meta.makam = comment[6:].strip()
        elif comment.startswith("usul "):
            meta.usul = comment[5:].strip()
        elif comment.startswith("form "):
            meta.form = comment[5:].strip()
        elif comment.startswith("symbtr-name "):
            meta.name = comment[len("symbtr-name "):].strip()
    return _score_from_events(events, metadata=meta)


#: Suffix (lowercase) -> format name for CLI auto-detect.
SUFFIX_FORMATS = {
    ".txt": "txt",
    ".symbtr.txt": "txt",
    ".json": "json",
    ".mid": "midi",
    ".midi": "midi",
    ".xml": "musicxml",
    ".musicxml": "musicxml",
    ".abc": "abc",
}

IMPORTABLE = frozenset(SUFFIX_FORMATS.values())


def detect_format(path: str) -> Optional[str]:
    """Guess an import format from a filename suffix."""
    lower = path.lower()
    # Prefer the longest matching suffix (``.symbtr.txt`` before ``.txt``).
    for suffix in sorted(SUFFIX_FORMATS, key=len, reverse=True):
        if lower.endswith(suffix):
            return SUFFIX_FORMATS[suffix]
    return None


def load_score(
    path: str,
    fmt: Optional[str] = None,
    *,
    no_mu2: bool = False,
) -> Score:
    """Load a score from ``path``, using ``fmt`` or suffix auto-detect."""
    resolved = fmt or detect_format(path)
    choices = ", ".join(sorted(IMPORTABLE))
    if resolved is None:
        raise ValueError(
            f"cannot detect format for {path!r}; pass --from {{{choices}}}")
    if resolved not in IMPORTABLE:
        raise ValueError(
            f"cannot import {resolved!r}; choose from {{{choices}}}")

    if resolved == "txt":
        mu2 = None
        if not no_mu2:
            from .readers.mu2 import find_sibling_mu2
            mu2 = find_sibling_mu2(path)
        return score_from_txt(path, mu2_path=mu2, use_mu2=not no_mu2)
    if resolved == "json":
        return score_from_json(path)
    if resolved == "midi":
        return score_from_midi(path)
    if resolved == "musicxml":
        return score_from_musicxml(path)
    if resolved == "abc":
        return score_from_abc(path)
    raise ValueError(f"unsupported import format {resolved!r}")
