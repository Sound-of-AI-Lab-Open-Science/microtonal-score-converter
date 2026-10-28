"""ABC notation writer, including a genuinely microtonal variant.

ABC is the most compact of the targets and the one the representation
comparison treats as the "plain text" baseline, but its usual form (``abc12``)
cannot say anything about tuning at all.  The ABC 2.2 standard does define
fractional accidentals -- ``^3/2c`` raises C by one and a half semitones and
``^/2c`` by a quarter tone -- and both ``abcm2ps`` and ``abc2midi`` implement
them, so 53-TET survives the trip if the alteration is spelled as a fraction
of a semitone.

Three modes, matching the comparison's three tuning resolutions:

``53tet``
    ``^12/53`` style accidentals.  Exact, at the cost of being unreadable by
    hand and unsupported by some ABC tools.
``24tet``
    Quarter tones (``^/2``, ``_3/2``), the resolution of SymbTr's own MusicXML.
``12tet``
    Plain ``^``/``_``/``=``.  The lossy baseline.

As in MusicXML, the accidental has to be measured from the 12-TET letter
rather than from the notated accidental, because that is how every ABC reader
interprets a bare ``d``.  ``reference="12tet"`` (the default) is exact;
``reference="diatonic"`` writes the notated accidental and leaves naturals
bare, which is readable but up to 9.4 cents out.
"""

from __future__ import annotations

from fractions import Fraction
from typing import List, Optional

from ..pitch import OCTAVE_COMMAS, Pitch, deviation_semitones
from ..score import Event, Score

MODES = ("53tet", "24tet", "12tet")
REFERENCES = ("12tet", "diatonic")

#: Unit note length declared in the ``L:`` field.
DEFAULT_UNIT = Fraction(1, 8)

#: Bars per line of output.
BARS_PER_LINE = 4

_ORNAMENT_DECORATIONS = {
    "trill": "!trill!",
    "trill-natural": "!trill!",
    "trill-lower": "!trill!",
    "mordent": "!mordent!",
    "mordent-natural": "!mordent!",
    "mordent-inverted": "!pralltriller!",
    "mordent-lower": "!lowermordent!",
    "mordent-lower-natural": "!lowermordent!",
    "mordent-lower-inverted": "!lowermordent!",
    "turn": "!turn!",
    "turn-lower": "!invertedturn!",
    "turn-natural": "!turn!",
    "turn-lower-natural": "!invertedturn!",
    "tremolo": "!///!",
    "tremolo-dim": "!///!",
    "tremolo-cresc": "!///!",
    "vibrato": "!^vibrato!",
}


def write_abc(
    score: Score,
    path: Optional[str] = None,
    *,
    mode: str = "53tet",
    reference: str = "12tet",
    index: int = 1,
    include_lyrics: bool = True,
    include_ornaments: bool = True,
    include_structure: bool = True,
) -> str:
    """Render a score as ABC."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if reference not in REFERENCES:
        raise ValueError(f"reference must be one of {REFERENCES}")

    lines = _header(score, index)
    lines += _body(score, mode, reference, include_lyrics, include_ornaments,
                   include_structure)
    text = "\n".join(lines) + "\n"
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    return text


def _header(score: Score, index: int) -> List[str]:
    meta = score.metadata
    usuls = score.usul_changes
    metre = usuls[0].time_signature if usuls and usuls[0].mertebe else "none"

    lines = [f"X:{index}", f"T:{meta.title or meta.name}"]
    if meta.composer:
        lines.append(f"C:{meta.composer}")
    if meta.lyricist:
        lines.append(f"A:{meta.lyricist}")
    # ABC has no field for makam or usul, so they go in free-text and in the
    # informational fields a parser will at least preserve.
    for label, value in (("makam", meta.makam), ("usul", meta.usul),
                         ("form", meta.form), ("symbtr-name", meta.name)):
        if value:
            lines.append(f"%%{label} {value}")
    if meta.key_signature:
        lines.append(f"%%key-signature {', '.join(meta.key_signature)}")
    lines += [
        f"M:{metre}",
        f"L:{DEFAULT_UNIT}",
        f"Q:1/4={round(score.tempo)}",
        "K:C",  # makam is not a key; accidentals are written out on every note
    ]
    return lines


def _body(score, mode, reference, lyrics, ornaments, structure) -> List[str]:
    out: List[str] = []
    buffer: List[str] = []
    syllables: List[str] = []
    bars = score.measures()

    for position, bar in enumerate(bars):
        tokens, bar_syllables = _render_bar(bar, mode, reference, lyrics,
                                            ornaments, structure)
        buffer.append(" ".join(tokens))
        syllables.extend(bar_syllables)

        at_line_end = (position + 1) % BARS_PER_LINE == 0
        if at_line_end or position == len(bars) - 1:
            terminator = "|]" if position == len(bars) - 1 else "|"
            out.append(" | ".join(buffer) + terminator)
            if lyrics and any(s not in ("*", "") for s in syllables):
                out.append("w: " + " ".join(syllables))
            buffer, syllables = [], []
    return out


def _render_bar(bar, mode, reference, lyrics, ornaments, structure):
    tokens: List[str] = []
    syllables: List[str] = []
    # ABC carries an accidental forward to every later note of the same letter
    # and octave within the bar, so an unaltered note following an altered one
    # needs an explicit natural or it inherits the alteration.
    in_force: dict = {}
    for event in bar:
        if not event.sounds:
            if structure:
                marker = _structure_marker(event)
                if marker:
                    tokens.append(marker)
            continue
        if structure and event.is_section_heading:
            tokens.append(f'"^{event.text.strip()}"')
        token = ""
        if ornaments and event.ornament in _ORNAMENT_DECORATIONS:
            token += _ORNAMENT_DECORATIONS[event.ornament]
        # A grace note's accidental does not persist to the notes after it,
        # so it gets a throwaway copy of the bar's accidental state.
        scope = dict(in_force) if event.is_grace else in_force
        body = (_pitch_token(event.pitch53, mode, reference, scope)
                if event.is_note else "z")
        length = _length_token(event.duration)
        if event.is_grace:
            tokens.append("{" + body + "}")
            continue
        tokens.append(token + body + length)
        if lyrics:
            syllables.append(_syllable(event))
    return tokens, syllables


def _structure_marker(event: Event) -> str:
    """Structural markers as ABC annotations, which parsers keep as text.

    Annotations are used rather than decorations (``!breath!``) because the
    label has to survive as *text*: a converter's job here is to keep
    Karaosmanoglu's phrase and modulation annotations recoverable, not to
    engrave them tastefully.  Pass ``include_structure=False`` to omit them.
    """
    if event.code == 53:
        return '"^phrase"'
    if event.code == 54:
        label = event.text.strip()
        return f'"^modulation: {label}"' if label else '"^modulation"'
    if event.code == 55:
        return '"^modulation end"'
    if event.code == 51 and event.text.strip():
        return f'"^{event.text.strip()}"'
    if event.is_section_heading:
        return f'"^{event.text.strip()}"'
    return ""


def _syllable(event: Event) -> str:
    text = event.text.strip()
    if not text or text == "." or event.is_section_heading:
        return "*"
    # ABC joins syllables within a word with '-' and separates words by space.
    return text + ("" if event.text.endswith(" ") else "-")


# -- pitch -----------------------------------------------------------------

_ABC_LETTERS = "CDEFGAB"


def _pitch_token(pitch: Pitch, mode: str, reference: str, in_force: dict) -> str:
    accidental = _accidental_token(pitch, mode, reference)
    letter = pitch.letter
    octave = pitch.octave
    key = (letter, octave)
    if accidental:
        in_force[key] = accidental
    elif in_force.get(key):
        accidental = "="
        in_force[key] = ""
    if octave >= 5:
        body = letter.lower() + "'" * (octave - 5)
    else:
        body = letter + "," * (4 - octave)
    return accidental + body


def _accidental_token(pitch: Pitch, mode: str, reference: str) -> str:
    semitones = (deviation_semitones(pitch) if reference == "12tet"
                 else Fraction(pitch.alteration * 12, OCTAVE_COMMAS))
    if semitones == 0:
        return "=" if pitch.alteration else ""

    if mode == "12tet":
        semitones = Fraction(round(float(semitones)))
    elif mode == "24tet":
        semitones = Fraction(round(float(semitones) * 2), 2)

    if semitones == 0:
        return "="
    sign = "^" if semitones > 0 else "_"
    magnitude = abs(semitones)
    if magnitude.denominator == 1:
        return sign * magnitude.numerator
    if magnitude.numerator == 1:
        return f"{sign}/{magnitude.denominator}"
    return f"{sign}{magnitude.numerator}/{magnitude.denominator}"


# -- duration --------------------------------------------------------------


def _length_token(duration: Fraction) -> str:
    """Length relative to the ``L:`` unit.

    ABC takes an arbitrary rational multiplier, so unlike MusicXML and Humdrum
    no decomposition into tied symbols is needed -- ``9/8`` of a whole note is
    just nine unit-eighths.
    """
    if duration <= 0:
        return ""
    multiplier = duration / DEFAULT_UNIT
    if multiplier == 1:
        return ""
    if multiplier.denominator == 1:
        return str(multiplier.numerator)
    if multiplier.numerator == 1:
        return f"/{multiplier.denominator}"
    return f"{multiplier.numerator}/{multiplier.denominator}"
