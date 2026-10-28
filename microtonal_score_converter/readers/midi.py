"""Minimal Standard MIDI File reader, for round-trip verification.

Only what the audit needs: note onsets, durations, note numbers and the pitch
bend in force at each onset, from which the sounding pitch in cents is
recoverable.  Deliberately dependency-free and deliberately not a general MIDI
library -- it exists so that "MIDI preserves the tuning" is a measured claim
rather than an asserted one.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

#: Default pitch-bend sensitivity in semitones, used until an RPN 0 says otherwise.
DEFAULT_BEND_RANGE = 2.0


@dataclass(frozen=True)
class MidiNote:
    tick: int
    duration: int
    note: int
    velocity: int
    bend: int          # raw 14-bit value, 8192 = centre
    channel: int
    bend_range: float  # semitones, as set by RPN 0

    @property
    def cents(self) -> float:
        """Sounding pitch in cents above C-1."""
        offset = (self.bend - 8192) / 8192.0 * self.bend_range * 100.0
        return self.note * 100.0 + offset


@dataclass
class MidiFile:
    division: int
    notes: List[MidiNote]
    tempos: List[Tuple[int, int]]       # (tick, microseconds per quarter)
    time_signatures: List[Tuple[int, int, int]]  # (tick, numerator, denominator)
    texts: List[Tuple[int, int, bytes]]  # (tick, meta type, payload)

    @property
    def tempo_bpm(self) -> Optional[float]:
        if not self.tempos:
            return None
        return 60000000.0 / self.tempos[0][1]


def read_midi(source) -> MidiFile:
    """Parse a MIDI file from a path or a ``bytes`` object."""
    data = source if isinstance(source, (bytes, bytearray)) else open(source, "rb").read()
    if data[:4] != b"MThd":
        raise ValueError("not a Standard MIDI File")

    header_length = struct.unpack(">I", data[4:8])[0]
    _, track_count, division = struct.unpack(">HHH", data[8:14])

    notes: List[MidiNote] = []
    tempos: List[Tuple[int, int]] = []
    signatures: List[Tuple[int, int, int]] = []
    texts: List[Tuple[int, int, bytes]] = []

    position = 8 + header_length
    for _ in range(track_count):
        if data[position:position + 4] != b"MTrk":
            break
        length = struct.unpack(">I", data[position + 4:position + 8])[0]
        _read_track(data, position + 8, position + 8 + length,
                    notes, tempos, signatures, texts)
        position += 8 + length

    notes.sort(key=lambda n: (n.tick, n.note))
    tempos.sort()
    return MidiFile(division, notes, tempos, signatures, texts)


def _read_track(data, start, end, notes, tempos, signatures, texts) -> None:
    position = start
    tick = 0
    running_status: Optional[int] = None
    bend: Dict[int, int] = {}
    bend_range: Dict[int, float] = {}
    rpn: Dict[int, Tuple[Optional[int], Optional[int]]] = {}
    sounding: Dict[Tuple[int, int], Tuple[int, int, int, float]] = {}

    while position < end:
        delta, position = _vlq(data, position)
        tick += delta

        status = data[position]
        if status & 0x80:
            running_status = status
            position += 1
        else:
            status = running_status
        if status is None:
            break

        if status == 0xFF:
            kind = data[position]
            position += 1
            length, position = _vlq(data, position)
            payload = data[position:position + length]
            position += length
            if kind == 0x51 and length == 3:
                tempos.append((tick, int.from_bytes(payload, "big")))
            elif kind == 0x58 and length >= 2:
                signatures.append((tick, payload[0], 2 ** payload[1]))
            elif kind in (0x01, 0x03, 0x05, 0x06):
                texts.append((tick, kind, bytes(payload)))
            continue

        if status in (0xF0, 0xF7):
            length, position = _vlq(data, position)
            position += length
            continue

        kind = status & 0xF0
        channel = status & 0x0F
        size = 1 if kind in (0xC0, 0xD0) else 2
        args = data[position:position + size]
        position += size

        if kind == 0xE0:
            bend[channel] = args[0] | (args[1] << 7)
        elif kind == 0xB0:
            _handle_controller(channel, args[0], args[1], rpn, bend_range)
        elif kind == 0x90 and args[1] > 0:
            sounding[(channel, args[0])] = (
                tick, args[1], bend.get(channel, 8192),
                bend_range.get(channel, DEFAULT_BEND_RANGE))
        elif kind == 0x80 or (kind == 0x90 and args[1] == 0):
            key = (channel, args[0])
            if key in sounding:
                onset, velocity, value, span = sounding.pop(key)
                notes.append(MidiNote(onset, tick - onset, args[0], velocity,
                                      value, channel, span))


def _handle_controller(channel, controller, value, rpn, bend_range) -> None:
    """Track RPN 0 so the bend range is read from the file, not assumed."""
    msb, lsb = rpn.get(channel, (None, None))
    if controller == 101:
        rpn[channel] = (value, lsb)
    elif controller == 100:
        rpn[channel] = (msb, value)
    elif controller == 6 and (msb, lsb) == (0, 0):
        bend_range[channel] = float(value)
    elif controller == 38 and (msb, lsb) == (0, 0):
        whole = bend_range.get(channel, DEFAULT_BEND_RANGE)
        bend_range[channel] = int(whole) + value / 100.0


def _vlq(data, position) -> Tuple[int, int]:
    value = 0
    while True:
        byte = data[position]
        position += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, position
