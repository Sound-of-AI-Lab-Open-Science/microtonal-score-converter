"""Writer for SymbTr-txt itself.

Converting *out of* the gold representation is only half a converter.  Being
able to write it back matters for three reasons: it closes the round trip, so
the reader can be proven lossless rather than asserted to be; it lets other
sources (a Mus2 export, a corrected score, a generated one) enter the SymbTr
ecosystem in its native format; and it gives the audit a control case.

Byte-identity with the published files is achievable for every column except
``Offset``, which the original generator wrote as a running floating-point sum
and which the IR holds as an exact rational.  ``offsets="source"`` reproduces
the original cell verbatim -- including the three published scores that format
integer offsets as ``3`` where the rest write ``3.0`` -- and ``offsets="exact"``
recomputes it from the durations, which is what a corrected or newly generated
score wants.
"""

from __future__ import annotations

from fractions import Fraction
from typing import List, Optional

from ..pitch import REST_NAME
from ..score import Event, Score

HEADER = ("Sira", "Kod", "Nota53", "NotaAE", "Koma53", "KomaAE",
          "Pay", "Payda", "Ms", "LNS", "Bas", "Soz1", "Offset")

OFFSET_MODES = ("source", "exact")


def write_txt(
    score: Score,
    path: Optional[str] = None,
    *,
    offsets: str = "source",
    line_ending: str = "\n",
    trailing_newline: bool = True,
) -> str:
    """Render a score back to SymbTr-txt.

    ``trailing_newline`` exists because exactly one published score
    (``muhayyer--bozlak--serbest--havayi_da--asaf_guven.txt``) ends without
    one; set it to ``False`` to reproduce that file byte for byte.
    """
    if offsets not in OFFSET_MODES:
        raise ValueError(f"offsets must be one of {OFFSET_MODES}")

    rows: List[str] = ["\t".join(HEADER)]
    running = Fraction(0)
    measure = Fraction(0)
    for event in score.events:
        if event.code == 51:
            measure = Fraction(event.numerator, event.denominator) \
                if event.numerator > 0 and event.denominator > 0 else Fraction(0)
        # Offset counts *measures*, not whole notes, so a 1/4 note advances by
        # 2/9 of a 9/8 measure.  Free-rhythm sections (no usul) have no measure
        # length, and there the column simply counts whole notes.
        running += event.duration / measure if measure else event.duration
        if offsets == "source" and event.offset_text:
            cell = event.offset_text
        else:
            cell = _format_offset(running if offsets == "exact"
                                  else event.offset_end)
        rows.append("\t".join(_row(event, cell)))

    text = line_ending.join(rows)
    if trailing_newline:
        text += line_ending
    if path:
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
    return text


def _row(event: Event, offset_cell: str) -> List[str]:
    blank = REST_NAME if (event.is_rest or event.rest_marker) else ""
    note53 = event.pitch53.name if event.pitch53 else blank
    note_ae = event.pitchAE.name if event.pitchAE else blank
    koma53 = _koma(event.pitch53, event.koma53_raw, event.is_rest)
    koma_ae = _koma(event.pitchAE, event.komaAE_raw, event.is_rest)

    return [
        str(event.index), str(event.code), note53, note_ae, koma53, koma_ae,
        str(event.numerator), str(event.denominator), str(event.ms),
        str(event.lns), str(event.velocity), event.text, offset_cell,
    ]


def _koma(pitch, raw: Optional[int], is_rest: bool) -> str:
    """The comma column: from the pitch when there is one, else as it was read."""
    if pitch is not None:
        return str(pitch.koma)
    if raw is not None:
        return str(raw)
    return "-1" if is_rest else "0"


def _format_offset(offset: Fraction) -> str:
    """Match SymbTr's own 12-significant-digit float formatting.

    The published files were written by formatting a Python float to twelve
    significant digits and then taking its ``str``, which is why ``1`` appears
    as ``1.0`` but ``2.111111111111111`` appears as ``2.11111111111``.
    """
    return str(float(f"{float(offset):.12g}"))
