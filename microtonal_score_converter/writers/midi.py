"""MIDI writer, including an exact reimplementation of SymbTr's own convention.

Standard MIDI cannot express 53-TET, so SymbTr's published ``.mid`` files use
pitch bend, with a convention the ISMIR paper only sketches.  Decoding the
shipped files pins it down completely:

* **Base note** is the 12-TET pitch of the *Arel-Ezgi* spelling, i.e. the
  letter and octave plus ``round(alteration_commas * 12/53)`` semitones.  So a
  1-comma flat (``B4b1``, segah) stays on B, a 4-comma flat (bakiyye) drops a
  semitone, and an 8-comma flat drops two.
* **Bend** carries the remainder, *anchored on A*: the paper's "the anchor note
  is A (La), therefore pitch-bend is unnecessary for any A in all octaves".
  Concretely, A sits at exactly 12-TET A and everything else is bent by its
  53-TET distance from A minus the 12-TET distance.  C comes out 5.66 cents
  flat, which is the "8192 - 5.7 * 40.96 = 7960" worked example in the paper.
* **Bend range** is set explicitly to +/-2 semitones via RPN 0, giving the
  40.96 units-per-cent the paper quotes.
* **Timing** is symbolic (``Pay``/``Payda`` at 480 ticks per quarter) with a
  single tempo meta event, and ``LNS`` becomes the note's gate: a note sounds
  for ``LNS`` percent of its written length and rests for the remainder.

Writing with ``convention="symbtr"`` reproduces those files event for event,
which is how this writer is tested.  The other conventions exist because
"MIDI with pitch bends" is one of the representations under comparison and a
fair comparison needs its variants spelled out rather than assumed.
"""

from __future__ import annotations

import struct
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

from ..pitch import OCTAVE_COMMAS, Pitch, quantize
from ..score import Event, Score

#: Ticks per quarter note used by the published SymbTr MIDI files.
DEFAULT_TPQ = 480

#: Comma value of A4 -- the pitch SymbTr's MIDI leaves unbent.
A4_KOMA = 305

#: Pitch-bend units per cent at the +/-2 semitone range SymbTr requests.
UNITS_PER_CENT = 4096 / 100.0

#: Note-off velocity used by SymbTr.
RELEASE_VELOCITY = 64

#: Channels available for round-robin allocation (9 is the drum channel).
MELODIC_CHANNELS = tuple(c for c in range(16) if c != 9)

CONVENTIONS = ("symbtr", "bend-nearest", "24tet", "12tet")
TIMINGS = ("symbolic", "ms")


# -- SMF primitives ---------------------------------------------------------


def _vlq(value: int) -> bytes:
    """MIDI variable-length quantity."""
    if value < 0:
        raise ValueError("negative delta time")
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(out))


class _Track:
    """Collects absolute-time events and serialises them as an MTrk chunk."""

    def __init__(self) -> None:
        # (tick, priority, sequence) keeps simultaneous events in a stable and
        # musically correct order: controllers and bends before note-offs
        # before note-ons, so a bend never lands after the note it belongs to.
        self._events: List[Tuple[int, int, int, bytes]] = []
        self._sequence = 0

    def add(self, tick: int, payload: bytes, priority: int = 1) -> None:
        self._events.append((tick, priority, self._sequence, payload))
        self._sequence += 1

    def meta(self, tick: int, kind: int, data: bytes, priority: int = 0) -> None:
        self.add(tick, bytes([0xFF, kind]) + _vlq(len(data)) + data, priority)

    def serialise(self) -> bytes:
        body = bytearray()
        previous = 0
        for tick, _, _, payload in sorted(self._events):
            body += _vlq(tick - previous) + payload
            previous = tick
        body += _vlq(0) + b"\xFF\x2F\x00"  # end of track
        return b"MTrk" + struct.pack(">I", len(body)) + bytes(body)


# -- tuning -----------------------------------------------------------------


def _base_note_and_cents(
    pitch: Pitch, convention: str, anchor: Optional[int]
) -> Tuple[int, float]:
    """Split a pitch into a MIDI note number and a bend in cents."""
    if convention == "12tet":
        return quantize(pitch.koma, 12), 0.0

    if convention == "24tet":
        # Nearest quarter tone: an integer note plus either 0 or +50 cents.
        step = quantize(pitch.koma, 24)
        return step // 2, 50.0 * (step % 2)

    if convention == "symbtr":
        # Base note follows the written spelling, not the nearest semitone, so
        # a 1-comma flat stays on its letter and a bakiyye flat drops a
        # semitone -- which is what the published MIDI files do.
        base = (_letter_midi(pitch.letter, pitch.octave)
                + round(pitch.alteration * 12.0 / OCTAVE_COMMAS))
    elif convention == "bend-nearest":
        base = quantize(pitch.koma, 12)
    else:  # pragma: no cover - guarded by the caller
        raise ValueError(f"unknown convention {convention!r}")

    cents = pitch.koma * 1200.0 / OCTAVE_COMMAS - base * 100.0
    if anchor is not None:
        cents -= _anchor_offset(anchor)
    return base, cents


def _anchor_offset(anchor_koma: int) -> float:
    """How far the anchor pitch sits above its own 12-TET note, in cents.

    Subtracting this from every bend puts the anchor exactly on the 12-TET
    grid, which is the paper's "pitch-bend is unnecessary for any A".
    """
    return (anchor_koma * 1200.0 / OCTAVE_COMMAS
            - round(anchor_koma * 12.0 / OCTAVE_COMMAS) * 100.0)


_LETTER_SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _letter_midi(letter: str, octave: int) -> int:
    """MIDI note of an unaltered letter name, with C4 == 60."""
    return (octave + 1) * 12 + _LETTER_SEMITONES[letter]


def _bend_value(cents: float) -> int:
    return max(0, min(16383, int(round(8192 + cents * UNITS_PER_CENT))))


# -- writer -----------------------------------------------------------------


def write_midi(
    score: Score,
    path: Optional[str] = None,
    *,
    convention: str = "symbtr",
    timing: str = "symbolic",
    tpq: int = DEFAULT_TPQ,
    tempo: Optional[float] = None,
    program: Optional[int] = None,
    anchor: Optional[int] = A4_KOMA,
    include_lyrics: bool = False,
    include_markers: bool = False,
) -> bytes:
    """Render a score as a Standard MIDI File.

    Parameters
    ----------
    convention
        ``"symbtr"`` reproduces the published SymbTr MIDI exactly.
        ``"bend-nearest"`` keeps the pitch exact but puts the base note on the
        nearest semitone, which survives re-quantisation by other tools better.
        ``"24tet"`` and ``"12tet"`` deliberately throw tuning away; they are the
        lossy baselines the representation comparison needs.
    timing
        ``"symbolic"`` uses the notated ``Pay``/``Payda``.  ``"ms"`` uses the
        performed ``Ms`` column, which is what SymbTr's own files do and which
        preserves ornament expansion and tempo nuance at the cost of the
        notated rhythm.  Both are scaled by ``tpq`` and the score tempo, so a
        tick means the same thing either way.
    anchor
        Comma value of the pitch left unbent.  Defaults to A4, which is what
        the paper specifies and what most published SymbTr MIDI files do.
        About 8% of them are instead anchored on D, leaving the whole file
        1.9 cents sharp of the rest of the corpus -- pass ``anchor=327`` to
        reproduce those.  ``None`` anchors on C, making MIDI note numbers
        exact multiples of the comma scale.
    include_lyrics, include_markers
        Off by default so the output matches SymbTr's deliberately bare files.
        Turning them on keeps the syllables and section/phrase structure, which
        is the point of having a converter at all.
    """
    if convention not in CONVENTIONS:
        raise ValueError(f"convention must be one of {CONVENTIONS}")
    if timing not in TIMINGS:
        raise ValueError(f"timing must be one of {TIMINGS}")

    bpm = tempo if tempo is not None else _score_tempo(score)
    if convention not in ("symbtr", "bend-nearest"):
        anchor = None

    header = _header_track(score, bpm, timing)
    notes = _note_track(
        score, convention, timing, tpq, bpm, anchor, program,
        include_lyrics, include_markers,
    )

    data = (
        b"MThd" + struct.pack(">IHHH", 6, 1, 2, tpq)
        + header.serialise() + notes.serialise()
    )
    if path:
        with open(path, "wb") as handle:
            handle.write(data)
    return data


def _score_tempo(score: Score) -> float:
    """Prefer the mu2's stated tempo; fall back to the one implied by ``Ms``.

    The ``Ms`` column is rounded to whole milliseconds, so the implied tempo is
    a hair off (107.91 where the score says 108).  Rounding to the nearest
    integer BPM recovers the intended value for essentially every score.
    """
    stated = score.metadata.extra.get("mu2_tempo")
    if stated:
        try:
            return float(stated)
        except ValueError:
            pass
    return round(score.tempo)


def _header_track(score: Score, bpm: float, timing: str) -> _Track:
    track = _Track()
    track.meta(0, 0x02, b"Converted from SymbTr-txt by microtonal_score_converter")
    name = score.metadata.title or score.metadata.name
    if name:
        track.meta(0, 0x03, name.encode("utf-8"))

    usuls = score.usul_changes
    if usuls and usuls[0].mertebe > 0:
        track.meta(0, 0x58, _time_signature(usuls[0].pulses, usuls[0].mertebe))

    track.meta(0, 0x51, struct.pack(">I", int(round(60000000.0 / bpm)))[1:])
    return track


def _time_signature(pulses: int, mertebe: int) -> bytes:
    denominator_power = max(0, (mertebe.bit_length() - 1))
    return bytes([pulses, denominator_power, 24, 8])


def _note_track(
    score: Score,
    convention: str,
    timing: str,
    tpq: int,
    bpm: float,
    anchor: Optional[int],
    program: Optional[int],
    include_lyrics: bool,
    include_markers: bool,
) -> _Track:
    track = _Track()
    channel = 0

    if convention != "12tet":
        # RPN 0: pitch bend sensitivity = 2 semitones, 0 cents.
        for controller, value in ((101, 0), (100, 0), (6, 2), (38, 0)):
            track.add(0, bytes([0xB0 | channel, controller, value]), priority=0)
    if program is not None:
        track.add(0, bytes([0xC0 | channel, program & 0x7F]), priority=0)

    # Positions accumulate exactly and are rounded only at emission, so a
    # score does not drift by a tick per note over several thousand notes.
    position = 0.0
    borrowed = 0.0
    current_bend: Dict[int, int] = {}
    tempo_at = _tempo_lookup(score, bpm) if timing == "symbolic" else None
    last_tempo: Optional[int] = None

    for event in score.events:
        tick = int(round(position))

        if include_markers:
            _emit_marker(track, tick, event)

        if not event.sounds:
            continue

        if tempo_at is not None:
            new_tempo = tempo_at(event)
            if new_tempo is not None and new_tempo != last_tempo:
                track.meta(tick, 0x51, struct.pack(">I", new_tempo)[1:], priority=0)
                last_tempo = new_tempo

        length = _event_length(event, timing, tpq, bpm)
        if event.is_grace and timing == "symbolic":
            # A grace note has no written length; it takes one from its
            # neighbour.  Dropping it instead (which a zero length would do)
            # silently removes 12,588 notes from the corpus.
            length = _grace_ticks(bpm, tpq)
            borrowed = length
        if length <= 0:
            continue
        if borrowed and not event.is_grace:
            length = max(length - borrowed, 1.0)
            borrowed = 0.0
        position += length

        if not event.is_note:
            continue

        gate = _gate_ticks(length, event.lns)
        base, cents = _base_note_and_cents(event.pitch53, convention, anchor)
        base = max(0, min(127, base))

        if convention != "12tet":
            bend = _bend_value(cents)
            if current_bend.get(channel) != bend:
                track.add(tick, bytes([0xE0 | channel, bend & 0x7F, bend >> 7]),
                          priority=1)
                current_bend[channel] = bend

        velocity = event.velocity if 0 < event.velocity < 128 else 96
        track.add(tick, bytes([0x90 | channel, base, velocity]), priority=3)
        track.add(tick + gate, bytes([0x80 | channel, base, RELEASE_VELOCITY]),
                  priority=2)

        if include_lyrics and event.text.strip() and not event.is_section_heading:
            track.meta(tick, 0x05, event.text.encode("utf-8"), priority=0)

    return track


def _emit_marker(track: _Track, tick: int, event: Event) -> None:
    if event.code == 53:
        track.meta(tick, 0x06, b"phrase", priority=0)
    elif event.code == 51 and event.text.strip():
        track.meta(tick, 0x06, f"usul: {event.text.strip()}".encode("utf-8"),
                   priority=0)
    elif event.is_section_heading:
        track.meta(tick, 0x06, event.text.strip().encode("utf-8"), priority=0)


def _tempo_lookup(score: Score, fallback: float):
    """Map events to microseconds-per-quarter, honouring mid-piece changes."""
    segments = score.tempo_map()
    if len(segments) <= 1:
        single = int(round(60000000.0 / fallback))
        return lambda event: single

    boundaries = [(seg.offset, int(round(60000000.0 / round(seg.bpm))))
                  for seg in segments]

    def lookup(event: Event) -> Optional[int]:
        value = boundaries[0][1]
        for offset, tempo in boundaries:
            if event.offset >= offset:
                value = tempo
            else:
                break
        return value

    return lookup


def _event_length(event: Event, timing: str, tpq: int, bpm: float) -> float:
    """Length of an event in (fractional) ticks."""
    ms_ticks = event.ms * bpm * tpq / 60000.0
    if timing == "ms":
        return ms_ticks
    if event.duration > 0:
        return float(event.quarters * tpq)
    # A grace note has no written duration; fall back to its performed length.
    return ms_ticks


def _grace_ticks(bpm: float, tpq: int) -> float:
    """Written length of a grace note, per the SymbTr code table.

    "For pieces slower than quarter = 90 bpm it is a 64th note, for faster
    pieces a 32nd."  The length is taken out of the following note, so the bar
    still adds up.
    """
    value = Fraction(1, 64) if bpm < 90 else Fraction(1, 32)
    return float(value * 4 * tpq)


def _gate_ticks(length: float, lns: int) -> int:
    """How long the note actually sounds, from the ``LNS`` percentage.

    ``LNS`` is the percentage of the written length that is voiced; the
    remainder is the silence that makes a note detached.  The default 95 gives
    the "last 5% completed with silence" the ISMIR paper describes.
    """
    whole = int(round(length))
    if lns <= 0:
        return max(1, whole)
    gate = int(round(length * min(lns, 100) / 100.0))
    return max(1, min(gate, max(1, whole)))
