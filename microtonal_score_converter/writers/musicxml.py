"""MusicXML writer with selectable tuning fidelity.

SymbTr ships MusicXML exports, but they are lossy in a way that is easy to
miss and hard to recover from.  Four of the eight Arel-Ezgi accidentals
(``slash-flat``, ``double-slash-flat``, ``slash-sharp``,
``slash-quarter-sharp``) are written with an ``<accidental>`` glyph and *no*
``<alter>`` element at all, because MusicXML 3.0 has no standard alter value
for them.  Any parser that reads ``<alter>`` -- music21 included -- therefore
reads those notes as naturals.  That affects 5.7% of all pitched notes in the
published corpus, and the error is not a microtonal nicety: a bakiyye flat read
as natural is wrong by 91 cents, a kucuk mucennep sharp by 113.

This writer always emits an ``<alter>``, and lets you choose how much of the
53-TET detail to keep:

``exact``
    ``alter`` is the true value, ``alteration * 12/53`` semitones.  Nothing is
    lost; the glyph is still the nearest Arel-Ezgi symbol so the score engraves
    correctly.
``quartertone``
    ``alter`` rounded to the nearest quarter tone.  This is what SymbTr's own
    exports *intend*, and what most MusicXML tooling can actually render.
``12tet``
    ``alter`` rounded to a whole semitone.  The deliberately flattened baseline.

A second, easily missed choice is what ``alter`` is measured *from*.  Readers
interpret a bare ``<step>D</step>`` as 12-TET D, but 53-TET's D sits 3.8 cents
higher and its B 9.4 cents higher, so writing only the notated accidental
leaves every natural slightly wrong.  ``reference="12tet"`` (the default) puts
the whole distance from the 12-TET note into ``alter``, which is exact;
``reference="diatonic"`` writes just the notated accidental, which engraves
conventionally and is what SymbTr's own exports intend, at the cost of up to
9.4 cents per note.
"""

from __future__ import annotations

from fractions import Fraction
from typing import List, Optional
from xml.sax.saxutils import escape

from ..duration import NoteValue, decompose, divisions_for
from ..pitch import OCTAVE_COMMAS, Pitch, deviation_semitones
from ..score import Event, Score

PRECISIONS = ("exact", "quartertone", "12tet")
REFERENCES = ("12tet", "diatonic")

#: MusicXML ornament elements keyed by the IR's ornament name.
_ORNAMENT_ELEMENTS = {
    "trill": "trill-mark",
    "trill-natural": "trill-mark",
    "trill-lower": "trill-mark",
    "mordent": "mordent",
    "mordent-natural": "mordent",
    "mordent-inverted": "inverted-mordent",
    "mordent-inverted-natural": "inverted-mordent",
    "mordent-lower": "inverted-mordent",
    "mordent-lower-natural": "inverted-mordent",
    "mordent-lower-inverted": "mordent",
    "mordent-lower-inverted-natural": "mordent",
    "turn": "turn",
    "turn-natural": "turn",
    "turn-lower": "inverted-turn",
    "turn-lower-natural": "inverted-turn",
    "tremolo": "tremolo",
    "tremolo-dim": "tremolo",
    "tremolo-cresc": "tremolo",
    "tremolo-cresc-dim": "tremolo",
    "tremolo-dim-cresc": "tremolo",
}


def write_musicxml(
    score: Score,
    path: Optional[str] = None,
    *,
    precision: str = "exact",
    reference: str = "12tet",
    include_lyrics: bool = True,
    include_ornaments: bool = True,
    include_structure: bool = True,
) -> str:
    """Render a score as MusicXML 3.1 partwise.

    ``include_structure`` adds the things SymbTr knows and MusicXML has no
    dedicated slot for -- section headings, phrase boundaries (``Kod 53``) and
    modulation markers (``Kod 54/55``) -- as ``<direction>`` text, so they
    survive a round trip instead of being silently dropped.
    """
    if precision not in PRECISIONS:
        raise ValueError(f"precision must be one of {PRECISIONS}")
    if reference not in REFERENCES:
        raise ValueError(f"reference must be one of {REFERENCES}")

    durations = [e.duration for e in score.events if e.sounds and e.duration > 0]
    divisions = divisions_for(durations)

    lines: List[str] = [
        "<?xml version='1.0' encoding='UTF-8' standalone='no'?>",
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 '
        'Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">',
        '<score-partwise version="3.1">',
    ]
    lines += _work_and_identification(score)
    lines += [
        "  <part-list>",
        '    <score-part id="P1">',
        "      <part-name>Music</part-name>",
        "    </score-part>",
        "  </part-list>",
        '  <part id="P1">',
    ]

    state = _WriterState(score, divisions, precision, reference, include_lyrics,
                         include_ornaments, include_structure)
    lines += state.render_measures()
    lines += ["  </part>", "</score-partwise>", ""]

    text = "\n".join(lines)
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
    return text


def _work_and_identification(score: Score) -> List[str]:
    meta = score.metadata
    out = []
    if meta.title:
        out += ["  <work>", f"    <work-title>{escape(meta.title)}</work-title>",
                "  </work>"]
    out.append("  <identification>")
    if meta.composer:
        out.append(
            f'    <creator type="composer">{escape(meta.composer)}</creator>')
    if meta.lyricist:
        out.append(f'    <creator type="poet">{escape(meta.lyricist)}</creator>')
    out += [
        "    <encoding>",
        "      <software>microtonal_score_converter</software>",
        "    </encoding>",
        f"    <miscellaneous>",
    ]
    for field in ("name", "makam", "form", "usul"):
        value = getattr(meta, field)
        if value:
            out.append(f'      <miscellaneous-field name="symbtr-{field}">'
                       f"{escape(value)}</miscellaneous-field>")
    out += ["    </miscellaneous>", "  </identification>"]
    return out


class _WriterState:
    """Walks the score once, emitting measure by measure."""

    def __init__(self, score, divisions, precision, reference, lyrics,
                 ornaments, structure):
        self.score = score
        self.divisions = divisions
        self.precision = precision
        self.reference = reference
        self.lyrics = lyrics
        self.ornaments = ornaments
        self.structure = structure
        self.pending_structure: List[str] = []

    # -- measures --------------------------------------------------------

    def render_measures(self) -> List[str]:
        out: List[str] = []
        first = True
        for number, bar in enumerate(self.score.measures(), start=1):
            out.append(f'    <measure number="{number}">')
            if first:
                out += self._opening_attributes()
                first = False
            for event in bar:
                out += self._render_event(event)
            out += self._flush_structure()
            out.append("    </measure>")
        return out

    def _opening_attributes(self) -> List[str]:
        usuls = self.score.usul_changes
        out = ["      <attributes>",
               f"        <divisions>{self.divisions}</divisions>"]
        out += self._key_signature()
        if usuls and usuls[0].mertebe > 0:
            out += ["        <time>",
                    f"          <beats>{usuls[0].pulses}</beats>",
                    f"          <beat-type>{usuls[0].mertebe}</beat-type>",
                    "        </time>"]
        out += ["        <clef>", "          <sign>G</sign>",
                "          <line>2</line>", "        </clef>", "      </attributes>"]
        out += self._tempo_direction()
        return out

    def _key_signature(self) -> List[str]:
        """Emit the makam key signature as MusicXML non-traditional key steps.

        A makam key signature is a list of altered *pitches*, not a number of
        fifths, so the ``<key-step>/<key-alter>/<key-accidental>`` form is the
        only honest encoding.  Falls back to an empty traditional key when the
        mu2 was not available to supply one.
        """
        signature = self.score.metadata.key_signature
        if not signature:
            return ["        <key>", "          <fifths>0</fifths>", "        </key>"]
        out = ["        <key>"]
        for name in signature:
            try:
                pitch = Pitch.parse(name)
            except ValueError:
                continue
            out += [f"          <key-step>{pitch.letter}</key-step>",
                    f"          <key-alter>{_alter(pitch, self.precision, self.reference)}</key-alter>"]
            glyph = pitch.accidental_glyph
            if glyph:
                out.append(f"          <key-accidental>{glyph}</key-accidental>")
        out.append("        </key>")
        return out

    def _tempo_direction(self) -> List[str]:
        bpm = round(self.score.tempo)
        meta = self.score.metadata
        label = ", ".join(
            f"{k}: {v}" for k, v in
            (("Makam", meta.makam), ("Form", meta.form), ("Usul", meta.usul))
            if v)
        out = ['      <direction placement="above">', "        <direction-type>",
               "          <metronome>",
               "            <beat-unit>quarter</beat-unit>",
               f"            <per-minute>{bpm}</per-minute>",
               "          </metronome>", "        </direction-type>"]
        if label:
            out += ["        <direction-type>",
                    f"          <words>{escape(label)}</words>",
                    "        </direction-type>"]
        out += [f'        <sound tempo="{bpm}"/>', "      </direction>"]
        return out

    # -- events ----------------------------------------------------------

    def _render_event(self, event: Event) -> List[str]:
        if not event.sounds:
            self._note_structure(event)
            return []
        if self.structure and event.is_section_heading:
            self.pending_structure.append(f"section {event.text.strip()}")
        out = self._flush_structure()
        if event.is_grace:
            out += self._note_element(event, NoteValue(Fraction(1, 16)), grace=True)
            return out
        values = decompose(event.duration)
        if not values:
            return out
        for position, value in enumerate(values):
            out += self._note_element(
                event, value,
                tie_start=position < len(values) - 1,
                tie_stop=position > 0,
                carry_text=position == 0,
            )
        return out

    def _note_element(
        self, event: Event, value: NoteValue, *,
        grace: bool = False, tie_start: bool = False,
        tie_stop: bool = False, carry_text: bool = True,
    ) -> List[str]:
        out = ["      <note>", f"        <!--symbtr-row {event.index}-->"]
        if grace:
            out.append("        <grace/>")

        if event.pitch53 is None:
            out.append("        <rest/>")
        else:
            pitch = event.pitch53
            out += ["        <pitch>", f"          <step>{pitch.letter}</step>"]
            alter = _alter(pitch, self.precision, self.reference)
            # Emit the alter whenever there is anything to say -- including a
            # written accidental that this precision rounds to zero.  Omitting
            # it is what makes SymbTr's own exports read as naturals.
            if alter != "0" or pitch.alteration:
                out.append(f"          <alter>{alter}</alter>")
            out += [f"          <octave>{pitch.octave}</octave>", "        </pitch>"]

        if not grace:
            duration = int(value.duration * 4 * self.divisions)
            out.append(f"        <duration>{duration}</duration>")
        if tie_stop:
            out.append('        <tie type="stop"/>')
        if tie_start:
            out.append('        <tie type="start"/>')
        out.append("        <voice>1</voice>")
        out.append(f"        <type>{value.type_name}</type>")
        out += ["        <dot/>"] * value.dots

        if event.pitch53 is not None and event.pitch53.accidental_glyph:
            out.append(
                f"        <accidental>{event.pitch53.accidental_glyph}</accidental>")
        if value.tuplet:
            actual, normal = value.tuplet
            out += ["        <time-modification>",
                    f"          <actual-notes>{actual}</actual-notes>",
                    f"          <normal-notes>{normal}</normal-notes>",
                    "        </time-modification>"]

        out += self._notations(event, tie_start, tie_stop)
        if carry_text:
            out += self._lyric(event)
        out.append("      </note>")
        return out

    def _notations(self, event: Event, tie_start: bool, tie_stop: bool) -> List[str]:
        inner: List[str] = []
        if tie_stop:
            inner.append('          <tied type="stop"/>')
        if tie_start:
            inner.append('          <tied type="start"/>')

        if self.ornaments and event.ornament:
            element = _ORNAMENT_ELEMENTS.get(event.ornament)
            if element:
                inner += ["          <ornaments>",
                          f"            <{element}/>", "          </ornaments>"]
        if event.articulation == "staccato":
            inner += ["          <articulations>", "            <staccato/>",
                      "          </articulations>"]
        if event.ornament in ("glissando", "portamento"):
            kind = "glissando" if event.ornament == "glissando" else "slide"
            inner.append(f'          <{kind} type="start" line-type="solid"/>')
        if not inner:
            return []
        return ["        <notations>"] + inner + ["        </notations>"]

    def _lyric(self, event: Event) -> List[str]:
        if not self.lyrics:
            return []
        text = event.text
        if not text.strip() or text.strip() == "." or event.is_section_heading:
            return []
        # SymbTr marks word ends with a trailing space and verse ends with two.
        trailing = len(text) - len(text.rstrip(" "))
        syllabic = "single" if trailing else "middle"
        out = ["        <lyric number=\"1\">",
               f"          <syllabic>{syllabic}</syllabic>",
               f"          <text>{escape(text.strip())}</text>"]
        if trailing >= 2:
            out.append("          <end-line/>")
        out.append("        </lyric>")
        return out

    # -- structural markers ----------------------------------------------

    def _note_structure(self, event: Event) -> None:
        if not self.structure:
            return
        if event.code == 53:
            self.pending_structure.append("phrase-boundary")
        elif event.code == 54:
            self.pending_structure.append(f"modulation-start {event.text.strip()}")
        elif event.code == 55:
            self.pending_structure.append(f"modulation-end {event.text.strip()}")
        elif event.code == 51 and event.text.strip():
            self.pending_structure.append(f"usul {event.text.strip()}")

    def _flush_structure(self) -> List[str]:
        if not self.pending_structure:
            return []
        out: List[str] = []
        for label in self.pending_structure:
            out += ['      <direction placement="above">',
                    "        <direction-type>",
                    f'          <other-direction>{escape(label)}</other-direction>',
                    "        </direction-type>", "      </direction>"]
        self.pending_structure = []
        return out


def _alter(pitch: Pitch, precision: str, reference: str) -> str:
    """The ``<alter>`` value at the requested fidelity.

    Always emitted when non-zero, including for the four Arel-Ezgi accidentals
    MusicXML has no standard alter value for -- which is exactly where SymbTr's
    own exports lose the pitch.
    """
    exact = (float(deviation_semitones(pitch)) if reference == "12tet"
             else pitch.alteration * 12.0 / OCTAVE_COMMAS)
    if precision == "12tet":
        return _trim(round(exact))
    if precision == "quartertone":
        return _trim(round(exact * 2) / 2)
    return _trim(exact)


def _trim(value) -> str:
    """Decimal with enough digits that the rounding is far below a cent.

    ``%g``'s default six significant digits leaves half a thousandth of a cent
    on the table, which is harmless but shows up as non-zero error in the
    audit and invites the question every time.
    """
    return f"{float(value):.10g}"
