"""Turning SymbTr's ``Pay``/``Payda`` fractions into notated note values.

SymbTr states durations as a plain fraction of a whole note, which is a more
expressive encoding than conventional notation: ``1/24`` is a perfectly good
``Pay/Payda`` but needs a tuplet to write down, and a few values in the corpus
need more than one symbol tied together.  Every writer that produces notation
rather than timings has to solve the same problem, so it lives here.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Dict, List, Optional, Tuple

#: Power-of-two note value (in whole notes) -> MusicXML/Humdrum type name.
TYPE_NAMES: Dict[Fraction, str] = {
    Fraction(8): "maxima",
    Fraction(4): "long",
    Fraction(2): "breve",
    Fraction(1): "whole",
    Fraction(1, 2): "half",
    Fraction(1, 4): "quarter",
    Fraction(1, 8): "eighth",
    Fraction(1, 16): "16th",
    Fraction(1, 32): "32nd",
    Fraction(1, 64): "64th",
    Fraction(1, 128): "128th",
    Fraction(1, 256): "256th",
    Fraction(1, 512): "512th",
    Fraction(1, 1024): "1024th",
}

#: Tuplet ratios tried, in order of how common they are in makam notation.
#: ``(actual, normal)`` means ``actual`` notes in the time of ``normal``.
TUPLET_RATIOS = ((3, 2), (3, 1), (5, 4), (6, 4), (7, 4), (7, 8), (9, 8), (5, 2))

#: Dots allowed on a plain note value.  Triple dots exist in theory but not in
#: this corpus, and allowing them makes the search prefer absurd spellings
#: (5/8 as a triple-dotted half in a triplet) over the obvious tied pair.
MAX_DOTS = 2

#: Dots allowed *inside* a tuplet.  More than one is not real notation.
MAX_TUPLET_DOTS = 1


@dataclass(frozen=True)
class NoteValue:
    """A notatable duration: a base note value, dots and an optional tuplet."""

    base: Fraction                            # power-of-two value in whole notes
    dots: int = 0
    tuplet: Optional[Tuple[int, int]] = None  # (actual, normal)

    @property
    def type_name(self) -> str:
        return TYPE_NAMES[self.base]

    @property
    def duration(self) -> Fraction:
        """The actual sounding length in whole notes."""
        value = self.base * Fraction(2 ** (self.dots + 1) - 1, 2 ** self.dots)
        if self.tuplet:
            actual, normal = self.tuplet
            value *= Fraction(normal, actual)
        return value

    def __str__(self) -> str:  # pragma: no cover - diagnostics only
        out = self.type_name + "." * self.dots
        if self.tuplet:
            out += f" ({self.tuplet[0]}:{self.tuplet[1]})"
        return out


def _is_power_of_two(value: Fraction) -> bool:
    if value <= 0:
        return False
    n, d = value.numerator, value.denominator
    return (n & (n - 1)) == 0 and (d & (d - 1)) == 0


def notate(duration: Fraction) -> Optional[NoteValue]:
    """Express ``duration`` (in whole notes) as a single note value, or ``None``.

    Tries plain and dotted power-of-two values first, then the tuplet ratios.
    ``None`` means no single symbol covers it; :func:`decompose` then ties
    several together.
    """
    if duration <= 0:
        return None

    for dots in range(MAX_DOTS + 1):
        base = duration / Fraction(2 ** (dots + 1) - 1, 2 ** dots)
        if _is_power_of_two(base) and base in TYPE_NAMES:
            return NoteValue(base, dots)

    for actual, normal in TUPLET_RATIOS:
        scaled = duration * Fraction(actual, normal)
        for dots in range(MAX_TUPLET_DOTS + 1):
            base = scaled / Fraction(2 ** (dots + 1) - 1, 2 ** dots)
            if _is_power_of_two(base) and base in TYPE_NAMES:
                return NoteValue(base, dots, (actual, normal))

    return None


def decompose(duration: Fraction) -> List[NoteValue]:
    """Split a duration into tied note values, longest first.

    Needed for the rare ``Pay``/``Payda`` values no single symbol covers
    (``10/8`` and ``22/4`` both occur in SymbTr).  Greedy, which is also how an
    engraver would write them.
    """
    out: List[NoteValue] = []
    remaining = Fraction(duration)
    guard = 0
    while remaining > 0 and guard < 16:
        guard += 1
        value = notate(remaining)
        if value is not None:
            out.append(value)
            break
        candidate = _largest_value_below(remaining)
        if candidate is None:
            break
        out.append(candidate)
        remaining -= candidate.duration
    return out


def _largest_value_below(limit: Fraction) -> Optional[NoteValue]:
    best: Optional[NoteValue] = None
    for base in TYPE_NAMES:
        for dots in range(MAX_DOTS + 1):
            value = NoteValue(base, dots)
            if value.duration <= limit and (
                best is None or value.duration > best.duration
            ):
                best = value
    return best


def divisions_for(durations, minimum: int = 1, maximum: int = 10080) -> int:
    """Smallest MusicXML ``divisions`` per quarter note keeping all durations integral.

    MusicXML counts duration in whole divisions of a quarter note, so this is
    the least common multiple of the denominators once each duration is
    expressed in quarters.  Capped so a pathological score cannot produce an
    unusable value.
    """
    from math import gcd

    result = minimum
    for duration in durations:
        quarters = Fraction(duration) * 4
        if quarters <= 0:
            continue
        denominator = quarters.denominator
        result = result * denominator // gcd(result, denominator)
        if result > maximum:
            return maximum
    return result
