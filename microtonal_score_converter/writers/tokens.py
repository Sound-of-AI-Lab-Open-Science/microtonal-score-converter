"""Token-stream writer for language-model experiments.

The representation comparison needs token streams, not files, and it needs them
to differ along *one* axis at a time.  Comparing "gold txt" against "MIDI"
against "ABC" confounds tuning resolution with duration encoding with how much
structural annotation survives, so a difference in downstream accuracy cannot
be attributed to any of them.

This writer makes each axis an explicit, independent choice:

* ``pitch`` -- how finely tuning is encoded, from exact 53-TET commas down to
  12-TET MIDI numbers, plus the transposition-invariant variants.
* ``duration`` -- the notated fraction, quarters, or performed milliseconds.
* ``markers`` -- which of the structural annotations SymbTr carries (bars,
  phrases, sections, usul, ornaments) appear in the stream.

A "representation" in the comparison is then a named point in that space, and
:data:`PRESETS` pins down the six that have already been run so they can be
reproduced exactly.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence

from ..pitch import quantize
from ..score import Event, Score

PITCH_ENCODINGS = (
    "koma53",     # absolute Holdrian comma: exact, 53 steps per octave
    "name53",     # SymbTr 53-TET spelling, e.g. Mi5b3
    "nameAE",     # Arel-Ezgi spelling, e.g. E5b4
    "midi24",     # quarter-tone step index
    "midi12",     # integer MIDI note number
    "interval53", # comma difference from the previous note
    "interval12", # semitone difference from the previous note
    "degree53",   # commas relative to the piece's final note (karar)
)

DURATION_ENCODINGS = (
    "fraction",   # the notated Pay/Payda
    "quarters",   # duration in quarter notes
    "ms",         # performed milliseconds, as written
    "none",       # pitch only
)

MARKERS = ("bar", "phrase", "section", "usul", "ornament", "rest")

#: Named configurations.  The first six reproduce the representations already
#: compared, so results stay commensurable when new ones are added.
PRESETS: Dict[str, dict] = {
    "gold53": dict(pitch="koma53", duration="fraction",
                   markers=("bar", "phrase", "section", "usul", "ornament",
                            "rest")),
    "gold53_plain": dict(pitch="koma53", duration="fraction",
                         markers=("bar", "rest")),
    "ae24": dict(pitch="nameAE", duration="fraction", markers=("bar", "rest")),
    "naive24": dict(pitch="midi24", duration="fraction", markers=("bar", "rest")),
    "naive12": dict(pitch="midi12", duration="fraction", markers=("bar", "rest")),
    "contour53": dict(pitch="interval53", duration="fraction",
                      markers=("bar", "rest")),
    "contour12": dict(pitch="interval12", duration="fraction",
                      markers=("bar", "rest")),
    "degree53": dict(pitch="degree53", duration="fraction",
                     markers=("bar", "rest")),
    "pitch_only53": dict(pitch="koma53", duration="none", markers=("rest",)),
    "pitch_only12": dict(pitch="midi12", duration="none", markers=("rest",)),
}


def write_tokens(
    score: Score,
    path: Optional[str] = None,
    *,
    preset: Optional[str] = None,
    pitch: str = "koma53",
    duration: str = "fraction",
    markers: Sequence[str] = ("bar", "rest"),
    combine: bool = True,
    separator: str = " ",
) -> str:
    """Render a score as a token stream.

    Parameters
    ----------
    preset
        Name from :data:`PRESETS`; overrides the individual axes.
    combine
        ``True`` emits one token per note (``318_1/8``), which keeps sequences
        short and makes pitch and duration inseparable.  ``False`` emits them
        as separate tokens, which lets a model share pitch statistics across
        durations.  Which is better is an open question -- hence the switch.
    """
    if preset:
        if preset not in PRESETS:
            raise ValueError(f"unknown preset {preset!r}; "
                             f"choose from {sorted(PRESETS)}")
        config = PRESETS[preset]
        pitch, duration = config["pitch"], config["duration"]
        markers = config["markers"]

    if pitch not in PITCH_ENCODINGS:
        raise ValueError(f"pitch must be one of {PITCH_ENCODINGS}")
    if duration not in DURATION_ENCODINGS:
        raise ValueError(f"duration must be one of {DURATION_ENCODINGS}")

    tokens = list(_tokens(score, pitch, duration, set(markers), combine))
    text = separator.join(tokens)
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return text


def _tokens(score, pitch_encoding, duration_encoding, markers, combine):
    reference = _reference_koma(score)
    previous: Optional[int] = None
    bar = None

    for event in score.events:
        if not event.sounds:
            marker = _marker_token(event, markers)
            if marker:
                yield marker
            continue

        if "section" in markers and event.is_section_heading:
            yield f"<section:{event.text.strip()}>"

        if "bar" in markers:
            index = int(event.offset)
            if bar is not None and index != bar:
                yield "|"
            bar = index

        if event.is_rest:
            if "rest" in markers:
                yield _join("R", _duration_token(event, duration_encoding),
                            combine)
            continue

        if not event.is_note:
            continue

        if "ornament" in markers and event.ornament:
            yield f"<{event.ornament}>"
        if event.is_grace:
            yield "<grace>"

        pitch_token = _pitch_token(event, pitch_encoding, previous, reference)
        previous = event.pitch53.koma
        yield _join(pitch_token, _duration_token(event, duration_encoding),
                    combine)


def _join(pitch_token: str, duration_token: str, combine: bool) -> str:
    if not duration_token:
        return pitch_token
    return f"{pitch_token}_{duration_token}" if combine \
        else f"{pitch_token} {duration_token}"


def _marker_token(event: Event, markers) -> str:
    if event.code == 53 and "phrase" in markers:
        return "<phrase>"
    if event.code == 51 and "usul" in markers and event.text.strip():
        return f"<usul:{event.text.strip()}>"
    if event.is_section_heading and "section" in markers:
        return f"<section:{event.text.strip()}>"
    return ""


def _pitch_token(event, encoding, previous, reference) -> str:
    koma = event.pitch53.koma
    if encoding == "koma53":
        return str(koma)
    if encoding == "name53":
        return event.pitch53.name
    if encoding == "nameAE":
        return event.pitchAE.name if event.pitchAE else event.pitch53.name
    if encoding == "midi24":
        return str(quantize(koma, 24))
    if encoding == "midi12":
        return str(quantize(koma, 12))
    if encoding == "interval53":
        return "S" if previous is None else f"{koma - previous:+d}"
    if encoding == "interval12":
        if previous is None:
            return "S"
        return f"{quantize(koma, 12) - quantize(previous, 12):+d}"
    if encoding == "degree53":
        return f"{koma - reference:+d}" if reference is not None else str(koma)
    raise ValueError(encoding)  # pragma: no cover - guarded by the caller


def _duration_token(event, encoding) -> str:
    if encoding == "none":
        return ""
    if encoding == "ms":
        return str(event.ms)
    if encoding == "quarters":
        quarters = event.quarters
        return str(quarters) if quarters.denominator != 1 else str(quarters.numerator)
    duration = event.duration
    if duration <= 0:
        return "0"
    return f"{duration.numerator}/{duration.denominator}"


def _reference_koma(score: Score) -> Optional[int]:
    """The piece's final sounding pitch, used as the karar for ``degree53``.

    Makam scores end on the karar by definition, so the last note is a reliable
    tonic estimate and needs no makam lookup table -- which matters because the
    table only covers a fraction of the 155 makams in SymbTr.
    """
    for event in reversed(score.events):
        if event.is_note and not event.is_grace:
            return event.pitch53.koma
    return None
