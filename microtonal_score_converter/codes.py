"""The SymbTr ``Kod`` vocabulary.

Every row of a SymbTr-txt score carries a ``Kod``.  Most are notes (``9``), but
the column doubles as the score's entire event channel: ornaments, phrase
boundaries, usul changes, modulation markers and print-layout directives all
arrive as ``Kod`` values on rows that otherwise look like notes.

The table below is transcribed from ``code_explanations.xlsx`` shipped with
SymbTr (both the Turkish and English sheets).  ``KIND`` groups the codes by
what a *converter* has to do with them, which is the distinction the format
itself never makes explicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

# -- what a converter must do with a row -----------------------------------

#: A sounding note (or rest) that occupies time.
NOTE = "note"
#: A note whose duration is borrowed from a neighbour (grace/acciaccatura).
GRACE = "grace"
#: A sounding note carrying an ornament that expands into several onsets.
ORNAMENT = "ornament"
#: A zero-duration marker that carries structural information.
MARKER = "marker"
#: A zero-duration marker that only affects the printed page.
LAYOUT = "layout"
#: Score-level metadata rows (present in mu2, rare in txt).
METADATA = "metadata"


@dataclass(frozen=True)
class CodeInfo:
    code: int
    abbrev: str
    name: str
    kind: str
    note: str = ""


def _c(code, abbrev, name, kind, note=""):
    return CodeInfo(code, abbrev, name, kind, note)


#: The full ``Kod`` table.  Codes marked ``(-)`` in the spreadsheet are defined
#: by Mus2-Alpha but never occur in the published SymbTr-txt corpus; they are
#: retained so that scores exported from Mus2 do not silently lose rows.
CODES: Dict[int, CodeInfo] = {ci.code: ci for ci in [
    _c(0, "sus", "Rest", NOTE, "Pay/Payda set, LNS=100"),
    _c(1, "kcn", "Little note", NOTE,
       "Performance embellishment absent from the original; played softer"),
    _c(2, "", "Rest on first occurrence", NOTE,
       "Behaves as a note, but is a rest the first time through"),
    _c(3, "", "Rest on second occurrence", NOTE,
       "Behaves as a note, but is a rest the second time through"),
    _c(4, "gls", "Glissando", ORNAMENT, "Slides into the following note"),
    _c(5, "", "Attenuating tremolo", ORNAMENT),
    _c(6, "", "Amplifying tremolo", ORNAMENT),
    _c(7, "trm", "Tremolo", ORNAMENT,
       "Eight 32nds below quarter=90, else four 16ths"),
    _c(8, "crp", "Gracenote", GRACE,
       "Takes its duration from the following note"),
    _c(9, "nta", "Note or rest", NOTE, "The ordinary case"),
    _c(10, "acn", "Note followed by a gracenote", NOTE,
       "Gives part of its duration to the following grace note"),
    _c(11, "ssc", "Silent gracenote", ORNAMENT,
       "Gives part of its duration to an unwritten note one degree higher"),
    _c(12, "trl", "Trill", ORNAMENT,
       "Divided in four, played as silent gracenotes"),
    _c(13, "", "Natural trill", ORNAMENT),
    _c(14, "obk", "Beaming / usul-tempo grouping", LAYOUT),
    _c(15, "", "Amplifying-attenuating tremolo", ORNAMENT),
    _c(16, "", "Attenuating-amplifying tremolo", ORNAMENT),
    _c(17, "", "Normal post-gracenote", GRACE,
       "Takes its duration from the preceding note"),
    _c(18, "", "End staff at this point", LAYOUT),
    _c(19, "syb", "New page", LAYOUT),
    _c(20, "", "Forbid line/page break", LAYOUT),
    _c(21, "stb", "Line break", LAYOUT, "LNS=1 means break inside a measure"),
    _c(22, "", "Silent natural gracenote", ORNAMENT),
    _c(23, "mrd", "Mordent", ORNAMENT, "Upper auxiliary, first quarter of value"),
    _c(24, "mra", "Lower mordent", ORNAMENT,
       "Lower auxiliary, first quarter of value"),
    _c(25, "", "Natural mordent", ORNAMENT),
    _c(26, "", "Natural lower mordent", ORNAMENT),
    _c(27, "ptm", "Portamento", ORNAMENT,
       "Slides to the next note without connecting them"),
    _c(28, "grp", "Grupetto", ORNAMENT, "upper-self-lower triplet, then the note"),
    _c(29, "gra", "Lower grupetto", ORNAMENT,
       "lower-self-upper triplet, then the note"),
    _c(30, "", "Natural grupetto", ORNAMENT),
    _c(31, "", "Natural lower grupetto", ORNAMENT),
    _c(32, "tra", "Lower trill", ORNAMENT),
    _c(33, "", "Triole with gracenote", ORNAMENT),
    _c(34, "", "Triole with soft gracenote", ORNAMENT),
    _c(35, "oot", "Repeat previous measure", MARKER),
    _c(36, "", "Da capo", MARKER),
    _c(37, "", "Volta 1", MARKER),
    _c(38, "", "Volta 2", MARKER),
    _c(39, "", "Volta 3", MARKER),
    _c(40, "", "Volta 4", MARKER),
    _c(41, "", "Volta 5", MARKER),
    _c(42, "", "Volta 6", MARKER),
    _c(43, "mtr", "Inverted mordent", ORNAMENT),
    _c(44, "mta", "Inverted lower mordent", ORNAMENT),
    _c(45, "", "Inverted natural mordent", ORNAMENT),
    _c(46, "", "Inverted natural lower mordent", ORNAMENT),
    _c(47, "", "Vibrato", ORNAMENT),
    _c(48, "", "Free text below the staff", LAYOUT),
    _c(49, "", "Free text above the staff", LAYOUT),
    _c(50, "mkm", "Makam / makam change", METADATA,
       "Soz1 = makam name, Soz2 = key signature"),
    _c(51, "usl", "Usul / usul change", MARKER,
       "Pay/Payda = pulses/mertebe, LNS = SymbTr usul id, Soz1 = usul name"),
    _c(52, "tmd", "Tempo / tempo change", MARKER, "LNS carries the tempo"),
    _c(53, "cms", "Phrase boundary", MARKER),
    _c(54, "gcb", "Modulation / flavour start", MARKER,
       "Soz1 = degree, Soz2 = makam flavour"),
    _c(55, "gcs", "Modulation / flavour end", MARKER),
    _c(56, "trt", "Measure change without usul name", MARKER),
    _c(57, "frm", "Form", METADATA),
    _c(58, "bst", "Composer", METADATA),
    _c(59, "gfy", "Lyricist", METADATA),
    _c(60, "szb", "Starting lyrics", METADATA),
    _c(61, "", "Ahenk (transposition)", METADATA, "In Holdrian commas"),
    _c(62, "kol", "Folkloric", METADATA, "1 for folk music"),
    _c(63, "nts", "Notation style", METADATA, "THM / TSM / Karma"),
    _c(64, "gfa", "Lyrics title", METADATA),
    _c(65, "bsy", "Composition date", METADATA),
    _c(66, "esu", "Duration of the composition", METADATA),
    _c(71, "byt", "Paper size", LAYOUT),
    _c(72, "mrj", "Margins", LAYOUT),
    _c(73, "dzn", "Layout", LAYOUT),
    _c(89, "", "Gracenote promoted to note", NOTE,
       "Takes its duration from the next note"),
    _c(108, "", "Post-gracenote promoted to note", NOTE,
       "Gives part of its duration to the next note"),
]}

#: Codes that correspond to a sounding event (note, rest, grace or ornament).
SOUNDING_CODES = frozenset(
    c for c, ci in CODES.items() if ci.kind in (NOTE, GRACE, ORNAMENT)
)

#: Codes whose row carries no duration and no pitch.
NON_SOUNDING_CODES = frozenset(
    c for c, ci in CODES.items() if ci.kind in (MARKER, LAYOUT, METADATA)
)

#: Codes that attach an ornament to an otherwise ordinary note.  Mapped to the
#: ornament name used in the intermediate representation and by the writers.
ORNAMENT_NAMES = {
    4: "glissando",
    5: "tremolo-dim",
    6: "tremolo-cresc",
    7: "tremolo",
    11: "silent-gracenote",
    12: "trill",
    13: "trill-natural",
    15: "tremolo-cresc-dim",
    16: "tremolo-dim-cresc",
    22: "silent-gracenote-natural",
    23: "mordent",
    24: "mordent-lower",
    25: "mordent-natural",
    26: "mordent-lower-natural",
    27: "portamento",
    28: "turn",
    29: "turn-lower",
    30: "turn-natural",
    31: "turn-lower-natural",
    32: "trill-lower",
    33: "triplet-gracenote",
    34: "triplet-soft-gracenote",
    43: "mordent-inverted",
    44: "mordent-lower-inverted",
    45: "mordent-inverted-natural",
    46: "mordent-lower-inverted-natural",
    47: "vibrato",
}

#: Grace-note codes, mapped to where the borrowed duration comes from.
GRACE_CODES = {8: "next", 17: "previous"}


def describe(code: int) -> str:
    """Human-readable label for a ``Kod``, for diagnostics and audit reports."""
    info = CODES.get(code)
    return f"{code} ({info.name})" if info else f"{code} (unknown)"
