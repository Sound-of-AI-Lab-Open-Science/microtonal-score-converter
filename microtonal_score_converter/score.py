"""The intermediate representation every reader produces and every writer consumes.

The design rule here is that the IR is a *superset* of SymbTr-txt, not a
lowest-common-denominator of the output formats.  Every column of the source
survives, including the ones no target format can express (``LNS``
articulation, ``Bas`` velocity, ornament codes, phrase boundaries, syllabified
lyrics).  Writers then drop what they cannot carry, and :mod:`microtonal_score_converter.audit`
measures exactly what each one dropped.

That is the whole point of the exercise: if the IR quietly normalised the gold
representation down to "pitch + duration", the loss would happen before any
writer ran and the comparison between representations would be meaningless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, Iterator, List, Optional

from .codes import (CODES, GRACE_CODES, NON_SOUNDING_CODES, NOTE,
                    ORNAMENT_NAMES)
from .pitch import Pitch

#: Section headings that appear in the ``Soz1`` column of instrumental pieces.
#: Transcribed from the SymbTr->MusicXML converter in ``tomato``.
SECTION_HEADINGS = frozenset([
    "1. HANE", "2. HANE", "3. HANE", "4. HANE", "TESLİM", "MÜLÂZİME",
    "SERHÂNE", "HÂNE-İ SÂNİ", "HÂNE-İ SÂLİS", "SERHANE", "ORTA HANE",
    "SON HANE", "1. HANEYE", "2. HANEYE", "3. HANEYE", "4. HANEYE", "KARAR",
    "1. HANE VE MÜLÂZİME", "2. HANE VE MÜLÂZİME", "3. HANE VE MÜLÂZİME",
    "4. HANE VE MÜLÂZİME", "1. HANE VE TESLİM", "2. HANE VE TESLİM",
    "3. HANE VE TESLİM", "4. HANE VE TESLİM", "ARANAĞME", "ZEMİN", "NAKARAT",
    "MEYAN", "SESLERLE NİNNİ", "OYUN KISMI", "ZEYBEK KISMI", "GİRİŞ SAZI",
    "GİRİŞ VE ARA SAZI", "GİRİŞ", "FİNAL", "SAZ", "ARA SAZI", "SUSTA", "KODA",
    "DAVUL", "RİTM", "BANDO", "MÜZİK", "SERBEST", "ARA TAKSİM",
    "GEÇİŞ TAKSİMİ", "KÜŞAT", "1. SELAM", "2. SELAM", "3. SELAM", "4. SELAM",
    "TERENNÜM",
])

#: ``LNS`` value that SymbTr uses for an ordinary (slightly detached) note.
DEFAULT_LNS = 95


@dataclass
class Event:
    """One row of a SymbTr score.

    Rows are kept in source order and never merged, so a reader/writer pair can
    reproduce the original file byte-for-byte.
    """

    index: int                      # Sira, 1-based
    code: int                       # Kod
    offset: Fraction                # start position, in measures from the top
    offset_end: Fraction            # end position, as literally stored in the file
    numerator: int = 0              # Pay
    denominator: int = 0            # Payda
    ms: int = 0                     # Ms, performed duration
    lns: int = DEFAULT_LNS          # LNS, legato/normal/staccato percentage
    velocity: int = 0               # Bas (VelOn in the ISMIR paper)
    text: str = ""                  # Soz1: lyric syllable, section name or usul name
    pitch53: Optional[Pitch] = None
    pitchAE: Optional[Pitch] = None

    # The pitch columns say more than the pitch.  A row with no pitch may still
    # carry the literal rest marker ``Es`` (some usul rows do), and the comma
    # columns hold 0 or -1 depending on how old the file is.  Both are kept
    # verbatim so writing SymbTr-txt back out is byte-exact.
    rest_marker: bool = False
    koma53_raw: Optional[int] = None
    komaAE_raw: Optional[int] = None
    #: The ``Offset`` cell exactly as it appeared.  Three of the 2200 published
    #: scores format integer offsets as ``3`` where the rest write ``3.0``, so
    #: round-tripping the number is not enough to round-trip the file.
    offset_text: str = ""

    # -- classification --------------------------------------------------

    @property
    def is_rest(self) -> bool:
        """True for a silence that occupies time.

        A ``Kod 51`` usul row also has no pitch and a non-zero ``Pay/Payda``
        (which there means the time signature, not a duration), so the code's
        *kind* has to be consulted as well.
        """
        if self.pitch53 is not None or self.duration <= 0:
            return False
        info = CODES.get(self.code)
        return info is not None and info.kind == NOTE

    @property
    def is_note(self) -> bool:
        return self.pitch53 is not None

    @property
    def is_grace(self) -> bool:
        return self.code in GRACE_CODES

    @property
    def grace_borrows_from(self) -> Optional[str]:
        """``"next"`` or ``"previous"`` for grace notes, else ``None``."""
        return GRACE_CODES.get(self.code)

    @property
    def ornament(self) -> Optional[str]:
        return ORNAMENT_NAMES.get(self.code)

    @property
    def sounds(self) -> bool:
        """True if the row produces audible output (note, rest or grace)."""
        return self.is_note or self.is_rest or self.is_grace

    @property
    def is_section_heading(self) -> bool:
        return self.text.strip() in SECTION_HEADINGS

    # -- duration --------------------------------------------------------

    @property
    def duration(self) -> Fraction:
        """Symbolic duration in whole notes.  Zero for grace notes and markers.

        ``Pay``/``Payda`` is overloaded: on a note it is the duration, but on a
        ``Kod 51`` usul row or a ``Kod 56`` metre change it is the *time
        signature*.  Reading 9/8 off a usul row as a duration silently adds a
        whole measure to the piece, so the code's kind has to be consulted.
        """
        if self.numerator <= 0 or self.denominator <= 0:
            return Fraction(0)
        if self.code in NON_SOUNDING_CODES:
            return Fraction(0)
        return Fraction(self.numerator, self.denominator)

    @property
    def quarters(self) -> Fraction:
        """Symbolic duration in quarter notes."""
        return self.duration * 4

    @property
    def tempo(self) -> Optional[float]:
        """Tempo implied by this row, in quarter-note BPM.

        SymbTr-txt has no explicit tempo column; the ISMIR paper gives
        ``ms = 240000/tempo * numerator/denominator``, which inverts to this.
        Rows without both a symbolic and a performed duration imply nothing.
        """
        if self.ms <= 0 or self.numerator <= 0 or self.denominator <= 0:
            return None
        return 240000.0 * self.numerator / (self.denominator * self.ms)

    @property
    def articulation(self) -> str:
        """``LNS`` bucketed into the three names the column is abbreviated from."""
        if self.lns >= 99:
            return "legato"
        if self.lns <= 60:
            return "staccato"
        return "normal"

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        what = self.pitch53.name if self.pitch53 else ("rest" if self.is_rest else "-")
        return (f"<Event {self.index} kod={self.code} {what} "
                f"{self.numerator}/{self.denominator} @{float(self.offset):.3f}>")


@dataclass
class UsulChange:
    """A ``Kod 51`` row: the metre in force from this point on."""

    index: int
    offset: Fraction
    name: str
    pulses: int        # Pay, the number of beats (zaman)
    mertebe: int       # Payda, the beat unit
    symbtr_id: int     # LNS, the SymbTr internal usul id

    @property
    def time_signature(self) -> str:
        return f"{self.pulses}/{self.mertebe}"

    @property
    def measure_length(self) -> Fraction:
        """Length of one measure in whole notes, or 0 for free rhythm."""
        if self.pulses <= 0 or self.mertebe <= 0:
            return Fraction(0)
        return Fraction(self.pulses, self.mertebe)


@dataclass
class TempoSegment:
    """A stretch of the score sharing one tempo, derived from the ``Ms`` column."""

    offset: Fraction
    bpm: float
    note_count: int


@dataclass
class Metadata:
    """Everything known about the piece that is not a note.

    ``makam``/``form``/``usul``/``title``/``composer`` come from the filename,
    which the ISMIR paper defines as the canonical place for them.  The rest is
    filled in opportunistically from a sibling ``.mu2`` file when one is given.
    """

    name: str = ""
    makam: str = ""
    form: str = ""
    usul: str = ""
    title: str = ""
    composer: str = ""
    lyricist: str = ""
    key_signature: List[str] = field(default_factory=list)
    karar_symbol: str = ""
    ahenk: Optional[int] = None
    notation: str = ""
    folkloric: Optional[bool] = None
    source: str = ""
    extra: Dict[str, str] = field(default_factory=dict)


@dataclass
class Score:
    """A parsed SymbTr score: events in source order plus derived structure."""

    events: List[Event] = field(default_factory=list)
    metadata: Metadata = field(default_factory=Metadata)
    warnings: List[str] = field(default_factory=list)

    # -- views over the events -------------------------------------------

    @property
    def notes(self) -> List[Event]:
        """Pitched events, grace notes included."""
        return [e for e in self.events if e.is_note]

    @property
    def sounding(self) -> List[Event]:
        """Everything that occupies or borrows time, in performance order."""
        return [e for e in self.events if e.sounds]

    @property
    def usul_changes(self) -> List[UsulChange]:
        out = []
        for e in self.events:
            if e.code == 51:
                out.append(UsulChange(
                    index=e.index, offset=e.offset, name=e.text.strip(),
                    pulses=e.numerator, mertebe=e.denominator, symbtr_id=e.lns,
                ))
        return out

    @property
    def phrase_boundaries(self) -> List[Fraction]:
        """Offsets of ``Kod 53`` rows -- Karaosmanoglu's own phrase annotation."""
        return [e.offset for e in self.events if e.code == 53]

    @property
    def modulations(self) -> List[Event]:
        """``Kod 54``/``55`` rows marking a gecki/cesni (modulation/flavour)."""
        return [e for e in self.events if e.code in (54, 55)]

    @property
    def sections(self) -> List[Event]:
        return [e for e in self.events if e.is_section_heading]

    @property
    def lyrics(self) -> str:
        """Lyrics reassembled from the syllable column.

        SymbTr marks word ends with one trailing space and verse ends with two,
        so the raw concatenation is already correctly spaced.
        """
        parts = [e.text for e in self.events
                 if e.sounds and e.text and not e.is_section_heading]
        return "".join(parts).strip()

    @property
    def is_instrumental(self) -> bool:
        return not any(
            e.text.strip() not in ("", ".") and not e.is_section_heading
            for e in self.events if e.sounds
        )

    # -- timing ----------------------------------------------------------

    def tempo_map(self, tolerance: float = 0.05) -> List[TempoSegment]:
        """Tempo segments recovered from the ``Ms`` column.

        Millisecond durations are stored as rounded integers, so the implied
        tempo wobbles by a fraction of a percent from note to note even when the
        tempo is constant.  ``tolerance`` is the relative change that counts as
        a real tempo change; 5% comfortably separates rounding noise from the
        genuine changes that SymbTr scores do contain (the fourth hane of a
        sazsemaisi, for instance).
        """
        segments: List[TempoSegment] = []
        for e in self.events:
            bpm = e.tempo
            if bpm is None:
                continue
            if segments and abs(bpm - segments[-1].bpm) <= tolerance * segments[-1].bpm:
                segments[-1].note_count += 1
                continue
            segments.append(TempoSegment(offset=e.offset, bpm=bpm, note_count=1))
        return self._merge_short_segments(segments)

    @staticmethod
    def _merge_short_segments(segments: List[TempoSegment]) -> List[TempoSegment]:
        """Drop one-note tempo blips, which are almost always rounding artefacts."""
        if len(segments) <= 1:
            return segments
        merged = [segments[0]]
        for seg in segments[1:]:
            if seg.note_count == 1:
                merged[-1].note_count += 1
            else:
                merged.append(seg)
        return merged

    @property
    def tempo(self) -> float:
        """A single representative tempo for the piece, in quarter-note BPM."""
        segs = self.tempo_map()
        if not segs:
            return 120.0
        return max(segs, key=lambda s: s.note_count).bpm

    @property
    def duration_ms(self) -> int:
        return sum(e.ms for e in self.events)

    # -- bar structure ---------------------------------------------------

    def measures(self) -> List[List[Event]]:
        """Group sounding events into measures using the ``Offset`` column.

        ``Offset`` counts measures from the top of the piece as a float, so a
        barline falls wherever the integer part increases.  This is more robust
        than re-deriving bars from the usul, because it survives the pickup
        measures and mid-piece metre changes that makam scores are full of.
        """
        bars: List[List[Event]] = []
        current: List[Event] = []
        pending: List[Event] = []
        current_bar = None
        for e in self.events:
            if not e.sounds:
                # Markers belong to the bar they precede, so hold them back
                # rather than attaching them to the bar that just ended.
                pending.append(e)
                continue
            bar_index = int(e.offset)
            if current_bar is None:
                current_bar = bar_index
            elif bar_index != current_bar:
                bars.append(current)
                current = []
                current_bar = bar_index
            current.extend(pending)
            pending = []
            current.append(e)
        current.extend(pending)
        if current:
            bars.append(current)
        return bars

    # -- convenience -----------------------------------------------------

    def __len__(self) -> int:
        return len(self.events)

    def __iter__(self) -> Iterator[Event]:
        return iter(self.events)

    def summary(self) -> str:  # pragma: no cover - diagnostics only
        return (
            f"{self.metadata.name or '<unnamed>'}: {len(self.notes)} notes, "
            f"{len(self.measures())} measures, makam={self.metadata.makam}, "
            f"usul={self.metadata.usul}, ~{self.tempo:.1f} bpm"
        )


def code_histogram(score: Score) -> Dict[str, int]:
    """Count of rows by ``Kod``, labelled -- used by the audit report."""
    out: Dict[str, int] = {}
    for e in score.events:
        info = CODES.get(e.code)
        label = f"{e.code}:{info.name}" if info else f"{e.code}:unknown"
        out[label] = out.get(label, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
