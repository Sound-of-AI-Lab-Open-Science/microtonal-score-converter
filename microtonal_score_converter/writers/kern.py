"""Humdrum ``**kern`` writer with an exact microtonal companion spine.

``**kern`` has no way to spell a pitch between the twelve chromatic degrees,
and bolting one on with a non-standard accidental would make the output
unreadable to every Humdrum tool.  Humdrum's own answer to this is
multi-spine: put the conventional notation in ``**kern`` and the exact value in
a parallel spine that tools can ignore or consume.

So a score becomes ``**kern`` (the 12-TET reading, which is what rhythm and
contour tools want) beside ``**koma`` (the raw Holdrian comma, which is exact
and from which the true pitch is ``koma * 12/53`` in MIDI terms), optionally
beside ``**text`` for the syllables.  Nothing is approximated away; the
approximation is simply confined to the spine where it belongs.

This also makes Humdrum the only target here that is simultaneously honest and
usable by off-the-shelf tooling -- worth knowing when choosing a representation
for rhythmic analysis of makam music.
"""

from __future__ import annotations

from fractions import Fraction
from typing import List, Optional

from ..duration import NoteValue, decompose
from ..pitch import Pitch
from ..score import Event, Score

MICROTONE_SPINES = ("koma", "cents", "none")


def write_kern(
    score: Score,
    path: Optional[str] = None,
    *,
    microtone_spine: str = "koma",
    include_lyrics: bool = True,
    include_structure: bool = True,
) -> str:
    """Render a score as a Humdrum file."""
    if microtone_spine not in MICROTONE_SPINES:
        raise ValueError(f"microtone_spine must be one of {MICROTONE_SPINES}")

    has_lyrics = include_lyrics and not score.is_instrumental
    spines = ["**kern"]
    if microtone_spine != "none":
        spines.append(f"**{microtone_spine}")
    if has_lyrics:
        spines.append("**text")

    lines = _reference_records(score)
    lines.append("\t".join(spines))
    lines += _tandem_interpretations(score, len(spines))
    lines += _body(score, len(spines), microtone_spine, has_lyrics,
                   include_structure)
    lines.append("\t".join(["*-"] * len(spines)))

    text = "\n".join(lines) + "\n"
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    return text


def _reference_records(score: Score) -> List[str]:
    meta = score.metadata
    out = []
    for key, value in (
        ("COM", meta.composer), ("OTL", meta.title), ("LYR", meta.lyricist),
        ("AGN", meta.form), ("AMD", meta.makam), ("AMT", meta.usul),
        ("ONM", meta.name),
    ):
        if value:
            out.append(f"!!!{key}: {value}")
    if meta.key_signature:
        out.append("!!!key-signature: " + ", ".join(meta.key_signature))
    out.append("!!!ONB: tuning is 53-TET; the **kern spine is a 12-TET reading")
    return out


def _tandem_interpretations(score: Score, width: int) -> List[str]:
    out = ["\t".join(["*Ipiano"] + ["*"] * (width - 1))]
    usuls = score.usul_changes
    if usuls and usuls[0].mertebe:
        out.append("\t".join([f"*M{usuls[0].time_signature}"] + ["*"] * (width - 1)))
    out.append("\t".join([f"*MM{round(score.tempo)}"] + ["*"] * (width - 1)))
    return out


def _body(score, width, microtone_spine, has_lyrics, structure) -> List[str]:
    out: List[str] = []
    for number, bar in enumerate(score.measures(), start=1):
        out.append("\t".join([f"={number}"] * width))
        for event in bar:
            if structure:
                comment = _structure_comment(event)
                if comment:
                    out.append(comment)
            if not event.sounds:
                continue
            out += _event_records(event, width, microtone_spine, has_lyrics)
    return out


def _structure_comment(event: Event) -> str:
    if event.code == 53:
        return "!! phrase boundary"
    if event.code == 54:
        return f"!! modulation start: {event.text.strip()}"
    if event.code == 55:
        return f"!! modulation end: {event.text.strip()}"
    if event.code == 51 and event.text.strip():
        return f"!! usul: {event.text.strip()}"
    if event.is_section_heading:
        return f"!! section: {event.text.strip()}"
    return ""


def _event_records(event, width, microtone_spine, has_lyrics) -> List[str]:
    if event.is_grace:
        # Humdrum spells a grace note with a 'q' and no duration.
        kern = ("q" + _kern_pitch(event.pitch53)) if event.is_note else "."
        return ["\t".join(_columns(kern, event, width, microtone_spine,
                                   has_lyrics, first=True))]

    values = decompose(event.duration)
    if not values:
        return []

    out = []
    for position, value in enumerate(values):
        kern = _kern_token(event, value, position, len(values))
        out.append("\t".join(_columns(
            kern, event, width, microtone_spine, has_lyrics,
            first=position == 0)))
    return out


def _columns(kern, event, width, microtone_spine, has_lyrics, first) -> List[str]:
    columns = [kern]
    if microtone_spine == "koma":
        columns.append(str(event.pitch53.koma) if event.is_note else ".")
    elif microtone_spine == "cents":
        columns.append(f"{_cents_offset(event.pitch53):+.2f}"
                       if event.is_note else ".")
    if has_lyrics:
        text = event.text.strip()
        columns.append(text if first and text and text != "." else ".")
    return columns[:width]


def _kern_token(event: Event, value: NoteValue, position: int, total: int) -> str:
    recip = _kern_recip(value)
    body = _kern_pitch(event.pitch53) if event.is_note else "r"
    token = recip + body
    if event.articulation == "staccato" and event.is_note:
        token += "'"
    if event.ornament in ("trill", "trill-natural", "trill-lower"):
        token += "t"
    elif event.ornament in ("mordent", "mordent-natural"):
        token += "M"
    elif event.ornament in ("mordent-lower", "mordent-lower-natural"):
        token += "m"
    elif event.ornament in ("turn", "turn-natural"):
        token += "S"
    if total > 1 and event.is_note:
        token = ("[" if position == 0 else
                 "]" if position == total - 1 else "_") + token
    return token


def _kern_recip(value: NoteValue) -> str:
    """Humdrum reciprocal duration for a note value.

    ``**kern`` writes the reciprocal of the duration in whole notes: an eighth
    is ``8``, a breve is ``0``, a longa ``00``.  Dots multiply as usual, and a
    tuplet simply produces a non-power-of-two reciprocal (a triplet sixteenth
    is ``24``), which is exactly what Humdrum expects.
    """
    # A dotted value's reciprocal is taken from the undotted base, with the
    # dots written out; everything else uses the sounding duration directly.
    reciprocal = Fraction(1) / (value.base if value.dots else value.duration)
    if reciprocal >= 1 and reciprocal.denominator == 1:
        text = str(reciprocal.numerator)
    elif reciprocal == Fraction(1, 2):
        text = "0"
    elif reciprocal == Fraction(1, 4):
        text = "00"
    elif reciprocal == Fraction(1, 8):
        text = "000"
    else:
        text = f"{reciprocal.numerator}%{reciprocal.denominator}"
    return text + "." * value.dots


_KERN_SEMITONE_ALTER = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _kern_pitch(pitch: Pitch) -> str:
    """Letter plus 12-TET accidentals, in Humdrum's repeated-letter octaves."""
    semitones = round(pitch.alteration * 12.0 / 53.0)
    letter = pitch.letter
    if pitch.octave >= 4:
        body = letter.lower() * (pitch.octave - 3)
    else:
        body = letter.upper() * (4 - pitch.octave)
    return body + ("#" * semitones if semitones > 0 else "-" * -semitones)


def _cents_offset(pitch: Pitch) -> float:
    """Cents between the exact pitch and the 12-TET note the kern spine spells."""
    semitones = round(pitch.alteration * 12.0 / 53.0)
    nominal = ((pitch.octave + 1) * 12 + _KERN_SEMITONE_ALTER[pitch.letter]
               + semitones)
    return pitch.koma * 1200.0 / 53.0 - nominal * 100.0
