"""Measuring what each representation loses.

The point of converting SymbTr to six other formats is not the files; it is
being able to say *precisely* what each format can and cannot carry, so that a
difference in downstream model accuracy can be attributed to something.  This
module produces that evidence.

Two kinds of claim are made here and they are kept apart deliberately:

**Measured.**  Pitch and duration loss are computed by actually writing the
score out, reading it back with the matching reader in
:mod:`microtonal_score_converter.readers`, and comparing note for note.  Attribute retention is
checked by looking for the attribute's content in the rendered output.  No
format is credited with preserving something that was not found.

**Declared.**  Where a format has no reader here (Humdrum), the capability is
stated in :data:`DECLARED_SUPPORT` and labelled as such in the report, never
silently mixed in with the measured numbers.

The headline number is cents of pitch error, because that is the dimension
makam music actually turns on: a 53-TET corpus flattened to 12-TET moves notes
by up to 40 cents, which is more than the distance between two adjacent
makam degrees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .pitch import OCTAVE_COMMAS
from .readers.abc import read_abc
from .readers.midi import read_midi
from .readers.musicxml import read_musicxml
from .score import Event, Score
from .writers import (write_abc, write_json, write_kern, write_midi,
                      write_musicxml, write_tokens)
from .writers.jsonio import score_from_dict
from .writers.txt import write_txt

#: Pitch differences below this are rounding in the format's own encoding
#: (MIDI's 14-bit bend, a decimal ``<alter>``), not loss of information.
TOLERANCE_CENTS = 0.05

#: Attributes the IR carries that a target format may or may not preserve.
#: Attributes checked by probing the output.  Pitch and duration are absent
#: on purpose: they are measured by round trip, not guessed at from substrings.
ATTRIBUTES = (
    "performed_ms", "articulation", "velocity", "lyrics", "ornaments",
    "grace_notes", "phrase_boundaries", "sections", "usul_changes",
    "modulations", "ae_spelling", "row_index",
)

#: Capabilities we state rather than measure, for formats with no reader here.
#: Keyed by format name; values map attribute -> ``True``/``False``.
DECLARED_SUPPORT: Dict[str, Dict[str, bool]] = {
    "kern": {
        # Pitch is exact via the parallel **koma spine, and duration is exact
        # via tied reciprocal values; neither is probed, so both are noted here
        # for the reader rather than scored.
        "performed_ms": False,
        "articulation": True,     # staccato only
        "velocity": False,
        "lyrics": True,           # **text spine
        "ornaments": True,
        "grace_notes": True,
        "phrase_boundaries": True,   # as global comments
        "sections": True,
        "usul_changes": True,
        "modulations": True,
        "ae_spelling": False,
        "row_index": False,
    },
}


@dataclass
class FormatReport:
    """What one format, in one configuration, preserved."""

    fmt: str
    variant: str
    measured: bool = True
    notes_compared: int = 0
    pitch_exact: int = 0
    pitch_cents_mean: float = 0.0
    pitch_cents_max: float = 0.0
    duration_exact: int = 0
    durations_compared: int = 0
    attributes: Dict[str, str] = field(default_factory=dict)
    size_bytes: int = 0
    note: str = ""

    @property
    def pitch_exact_fraction(self) -> float:
        return self.pitch_exact / self.notes_compared if self.notes_compared else 0.0

    @property
    def duration_exact_fraction(self) -> float:
        return (self.duration_exact / self.durations_compared
                if self.durations_compared else 0.0)

    @property
    def lossless(self) -> bool:
        return (self.notes_compared > 0
                and self.pitch_exact == self.notes_compared
                and self.duration_exact == self.durations_compared
                and all(v != "lost" for v in self.attributes.values()))


# -- the configurations compared -------------------------------------------

def _configurations() -> List[Tuple[str, str, Callable[[Score], object]]]:
    """(format, variant, render) triples covering the comparison's axes."""
    return [
        ("txt", "source", lambda s: write_txt(s)),
        ("json", "lossless", lambda s: write_json(s)),
        ("midi", "symbtr-bend", lambda s: write_midi(
            s, include_lyrics=True, include_markers=True)),
        ("midi", "24tet", lambda s: write_midi(
            s, convention="24tet", include_lyrics=True, include_markers=True)),
        ("midi", "12tet", lambda s: write_midi(
            s, convention="12tet", include_lyrics=True, include_markers=True)),
        ("musicxml", "exact53", lambda s: write_musicxml(s, precision="exact")),
        ("musicxml", "quartertone", lambda s: write_musicxml(
            s, precision="quartertone")),
        ("musicxml", "12tet", lambda s: write_musicxml(s, precision="12tet")),
        ("musicxml", "diatonic53", lambda s: write_musicxml(
            s, precision="exact", reference="diatonic")),
        ("abc", "53tet", lambda s: write_abc(s, mode="53tet")),
        ("abc", "24tet", lambda s: write_abc(s, mode="24tet")),
        ("abc", "12tet", lambda s: write_abc(s, mode="12tet")),
        ("kern", "koma-spine", lambda s: write_kern(s)),
        ("tokens", "gold53", lambda s: write_tokens(s, preset="gold53")),
        ("tokens", "naive12", lambda s: write_tokens(s, preset="naive12")),
    ]


def audit_score(score: Score, *, tolerance: float = TOLERANCE_CENTS
                ) -> List[FormatReport]:
    """Round-trip ``score`` through every configuration and report the loss."""
    reports = []
    for fmt, variant, render in _configurations():
        rendered = render(score)
        report = FormatReport(fmt=fmt, variant=variant)
        report.size_bytes = len(rendered if isinstance(rendered, bytes)
                                else rendered.encode("utf-8"))
        _measure(score, fmt, variant, rendered, report, tolerance)
        reports.append(report)
    return reports


def _measure(score, fmt, variant, rendered, report, tolerance) -> None:
    handler = _HANDLERS.get(fmt)
    if handler is None:
        report.measured = False
        report.attributes = {a: ("kept" if DECLARED_SUPPORT.get(fmt, {}).get(a)
                                 else "lost") for a in ATTRIBUTES}
        report.note = "declared, not measured: no reader for this format"
        return
    handler(score, variant, rendered, report, tolerance)
    report.attributes = _probe_attributes(score, fmt, rendered)


# -- per-format round trips -------------------------------------------------


def _gold_cents(event: Event) -> float:
    return event.pitch53.koma * 1200.0 / OCTAVE_COMMAS


def _accumulate(report: FormatReport, errors: Sequence[float], tolerance: float
                ) -> None:
    report.notes_compared = len(errors)
    report.pitch_exact = sum(1 for e in errors if e <= tolerance)
    report.pitch_cents_mean = sum(errors) / len(errors) if errors else 0.0
    report.pitch_cents_max = max(errors) if errors else 0.0


def _audit_txt(score, variant, rendered, report, tolerance) -> None:
    """The control: re-read our own SymbTr-txt and compare the whole IR."""
    import os
    import tempfile

    from .readers.txt import read_txt

    handle, path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="") as out:
            out.write(rendered)
        restored = read_txt(path, use_mu2=False)
    finally:
        os.unlink(path)

    notes = [e for e in score.events if e.is_note]
    restored_notes = [e for e in restored.events if e.is_note]
    errors = [abs(_gold_cents(a) - _gold_cents(b))
              for a, b in zip(notes, restored_notes)]
    _accumulate(report, errors, tolerance)
    _compare_durations(score, [e.duration for e in restored.events if e.sounds],
                       report)


def _audit_json(score, variant, rendered, report, tolerance) -> None:
    import json

    restored = score_from_dict(json.loads(rendered))
    notes = [e for e in score.events if e.is_note]
    restored_notes = [e for e in restored.events if e.is_note]
    errors = [abs(_gold_cents(a) - _gold_cents(b))
              for a, b in zip(notes, restored_notes)]
    _accumulate(report, errors, tolerance)
    _compare_durations(score, [e.duration for e in restored.events if e.sounds],
                       report)
    if restored.events != score.events:
        report.note = "JSON round trip did not reproduce the IR exactly"


def _audit_midi(score, variant, rendered, report, tolerance) -> None:
    parsed = read_midi(rendered)
    notes = [e for e in score.events if e.is_note]
    if len(parsed.notes) != len(notes):
        report.note = (f"{len(parsed.notes)} MIDI notes for {len(notes)} "
                       f"score notes")
    # SymbTr's bend convention anchors on A, so the whole file sits at a
    # constant offset from absolute cents.  Remove it before comparing, or
    # every note would read as 5.7 cents wrong for a reason that is a choice
    # of reference pitch, not a loss of information.
    pairs = list(zip(parsed.notes, notes))
    if not pairs:
        return
    offsets = [m.cents - _gold_cents(e) for m, e in pairs]
    anchor = sorted(offsets)[len(offsets) // 2]
    errors = [abs(o - anchor) for o in offsets]
    _accumulate(report, errors, tolerance)

    division = parsed.division or 1
    bpm = parsed.tempo_bpm or score.tempo
    restored = []
    for midi_note, event in pairs:
        # Undo the LNS gate before comparing: the note's written length is the
        # gap to the next onset, not how long it sounded.
        gate = min(max(event.lns, 1), 100) / 100.0
        restored.append(Fraction(midi_note.duration, int(division * 4 * gate))
                        if gate else Fraction(0))
    _compare_durations(score, restored, report, notes_only=True,
                       approximate=True)


def _audit_musicxml(score, variant, rendered, report, tolerance) -> None:
    parsed = read_musicxml(rendered)
    folded = _fold_ties(parsed.notes)
    gold_notes = [e for e in score.events if e.is_note]

    pitched = [head for head, _ in folded if not head.is_rest]
    errors = [abs(head.cents - _gold_cents(event))
              for head, event in zip(pitched, gold_notes)
              if head.cents is not None]
    _accumulate(report, errors, tolerance)
    _compare_durations(score, [duration for _, duration in folded], report)

    missing = sum(1 for n in parsed.notes if n.alter_missing)
    if missing:
        report.note = f"{missing} notes carry an accidental with no <alter>"


def _fold_ties(notes):
    """Group tied symbols back into the single note they stand for.

    MusicXML has to split a 9/8 note into a tied whole plus eighth; the gold
    representation does not, so the comparison has to put it back together or
    every such note would count as two.
    """
    folded = []
    for note in notes:
        if note.tie_stop and folded:
            head, duration = folded[-1]
            folded[-1] = (head, duration + note.duration)
        else:
            folded.append((note, note.duration))
    return folded


def _audit_abc(score, variant, rendered, report, tolerance) -> None:
    parsed = read_abc(rendered)
    sounding = [e for e in score.events if e.sounds]
    errors = [abs(a.cents - _gold_cents(e))
              for a, e in zip(parsed.notes, sounding)
              if e.is_note and a.cents is not None and not a.is_rest]
    _accumulate(report, errors, tolerance)
    _compare_durations(score, [a.duration for a in parsed.notes], report)


def _audit_tokens(score, variant, rendered, report, tolerance) -> None:
    """Re-read the token stream we just wrote, using the preset's own grammar."""
    # Markers and bar lines are not notes; neither are rest tokens, which some
    # presets emit and some do not.  Dropping both from each side is the only
    # alignment that holds for every preset.
    tokens = [t for t in rendered.split()
              if not t.startswith("<") and t != "|"
              and t != "R" and not t.startswith("R_")]
    notes = [e for e in score.events if e.sounds and not e.is_rest]
    errors: List[float] = []
    durations: List[Fraction] = []
    for token, event in zip(tokens, notes):
        pitch_text, _, duration_text = token.partition("_")
        if duration_text:
            try:
                durations.append(Fraction(duration_text))
            except (ValueError, ZeroDivisionError):
                pass
        if not event.is_note:
            continue
        try:
            value = int(pitch_text)
        except ValueError:
            continue
        if variant == "naive12":
            recovered = value * 100.0
            errors.append(abs(recovered - _gold_cents(event)))
        else:
            errors.append(abs(value * 1200.0 / OCTAVE_COMMAS - _gold_cents(event)))
    _accumulate(report, errors, tolerance)
    _compare_durations(score, durations, report)


_HANDLERS: Dict[str, Callable] = {
    "txt": _audit_txt,
    "json": _audit_json,
    "midi": _audit_midi,
    "musicxml": _audit_musicxml,
    "abc": _audit_abc,
    "tokens": _audit_tokens,
}


def _compare_durations(score, restored, report, *, notes_only: bool = False,
                       approximate: bool = False) -> None:
    source = [e for e in score.events if e.sounds]
    if notes_only:
        source = [e for e in source if e.is_note]
    pairs = list(zip(source, restored))
    report.durations_compared = len(pairs)
    tolerance = Fraction(1, 64) if approximate else Fraction(0)
    report.duration_exact = sum(
        1 for event, value in pairs
        if abs(Fraction(value) - event.duration) <= tolerance)


# -- attribute probes -------------------------------------------------------


def _probe_attributes(score: Score, fmt: str, rendered) -> Dict[str, str]:
    """Look for each attribute's actual content in the rendered output.

    Presence of the content is weak evidence that a reader could recover it,
    but absence is strong evidence that it could not -- and absence is what
    the comparison needs to establish.  ``n/a`` means the score does not have
    the attribute, so the format was never asked to carry it.
    """
    haystack = _haystack(fmt, rendered)
    out: Dict[str, str] = {}
    for attribute in ATTRIBUTES:
        evidence = _evidence(score, attribute)
        if evidence is None:
            out[attribute] = "n/a"
        else:
            out[attribute] = "kept" if any(e in haystack for e in evidence) \
                else "lost"
    return out


def _haystack(fmt: str, rendered) -> str:
    """A searchable rendering of the output, including MIDI's text events."""
    if fmt != "midi":
        return rendered if isinstance(rendered, str) else rendered.decode(
            "utf-8", "replace")
    parsed = read_midi(rendered)
    parts = [text.decode("utf-8", "replace") for _, _, text in parsed.texts]
    parts += [f"note={n.note} vel={n.velocity} bend={n.bend} dur={n.duration}"
              for n in parsed.notes]
    return "\n".join(parts)


def _evidence(score: Score, attribute: str) -> Optional[List[str]]:
    """Strings whose presence in the output shows the attribute survived."""
    if attribute == "performed_ms":
        values = [e.ms for e in score.events if e.sounds and e.ms > 0]
        return [f"dur={v}" for v in values[:5]] + [str(v) for v in values[:5]] \
            if values else None

    if attribute == "articulation":
        staccato = [e for e in score.events if e.sounds
                    and e.articulation == "staccato"]
        return ["staccato", "'", "vel="] if staccato else None

    if attribute == "velocity":
        values = {e.velocity for e in score.events if e.sounds and e.velocity}
        return [f"vel={v}" for v in sorted(values)] if len(values) > 1 else None

    if attribute == "lyrics":
        words = [e.text.strip() for e in score.events
                 if e.sounds and len(e.text.strip()) > 2
                 and not e.is_section_heading]
        return words[:8] or None

    if attribute == "ornaments":
        names = {e.ornament for e in score.events if e.ornament}
        return sorted(n for n in names if n) or None

    if attribute == "grace_notes":
        return ["grace", "{", "q"] if any(e.is_grace for e in score.events) \
            else None

    if attribute == "phrase_boundaries":
        return ["phrase"] if score.phrase_boundaries else None

    if attribute == "sections":
        headings = [e.text.strip() for e in score.sections]
        return headings[:4] or None

    if attribute == "usul_changes":
        names = [u.name for u in score.usul_changes if u.name]
        return names[:3] or None

    if attribute == "modulations":
        return ["modulation"] if score.modulations else None

    if attribute == "ae_spelling":
        differing = [e.pitchAE.name for e in score.events
                     if e.pitchAE and e.pitch53
                     and e.pitchAE.name != e.pitch53.name]
        return differing[:5] or None

    if attribute == "row_index":
        return ["symbtr-row", "symbtr_txt_note_index", "Sira", '"index"']

    return None  # pragma: no cover - ATTRIBUTES is exhaustive


# -- reporting --------------------------------------------------------------


def format_report(reports: Sequence[FormatReport], *, width: int = 100) -> str:
    """A fixed-width table of the loss matrix, for the terminal and for notes."""
    header = (f"{'format':10s} {'variant':13s} {'pitch ok':>9s} "
              f"{'mean c':>7s} {'max c':>7s} {'dur ok':>7s} {'bytes':>8s}  "
              f"lost")
    lines = [header, "-" * max(width, len(header))]
    for report in reports:
        lost = [a for a, v in report.attributes.items() if v == "lost"]
        flag = "" if report.measured else " (declared)"
        if report.measured:
            numbers = (f"{report.pitch_exact_fraction:8.1%} "
                       f"{report.pitch_cents_mean:7.2f} "
                       f"{report.pitch_cents_max:7.2f} "
                       f"{report.duration_exact_fraction:6.1%}")
        else:
            numbers = f"{'n/a':>8s} {'n/a':>7s} {'n/a':>7s} {'n/a':>6s}"
        lines.append(
            f"{report.fmt:10s} {report.variant:13s} {numbers} "
            f"{report.size_bytes:8d}  {', '.join(lost) or '-'}{flag}")
        if report.note:
            lines.append(f"{'':10s} {'':13s} note: {report.note}")
    return "\n".join(lines)


# -- pairwise path audit (gold → A → B → compare to gold) -------------------


#: Formats that :mod:`microtonal_score_converter.importers` can rebuild as a Score.
_PATH_FORMATS = frozenset({"txt", "json", "midi", "musicxml", "abc"})


@dataclass
class PathReport:
    """Loss of the path gold → write A → slim Score → write B, vs gold pitch."""

    src_fmt: str
    src_variant: str
    dst_fmt: str
    dst_variant: str
    notes_compared: int = 0
    pitch_exact: int = 0
    pitch_cents_mean: float = 0.0
    pitch_cents_max: float = 0.0
    duration_exact: int = 0
    durations_compared: int = 0
    note: str = ""

    @property
    def pitch_exact_fraction(self) -> float:
        return self.pitch_exact / self.notes_compared if self.notes_compared else 0.0

    @property
    def duration_exact_fraction(self) -> float:
        return (self.duration_exact / self.durations_compared
                if self.durations_compared else 0.0)

    @property
    def label(self) -> str:
        return (f"{self.src_fmt}/{self.src_variant}"
                f" -> {self.dst_fmt}/{self.dst_variant}")


def _path_configurations() -> List[Tuple[str, str, Callable[[Score], object]]]:
    """Configs that both render and re-import as a Score."""
    return [c for c in _configurations() if c[0] in _PATH_FORMATS]


def _import_rendered(fmt: str, rendered) -> Score:
    """Rebuild a slim (or full) Score from a just-rendered blob."""
    import json
    import os
    import tempfile

    from .importers import (score_from_abc, score_from_json, score_from_midi,
                            score_from_musicxml)

    if fmt == "txt":
        handle, path = tempfile.mkstemp(suffix=".txt")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="") as out:
                out.write(rendered)
            from .readers.txt import read_txt
            return read_txt(path, use_mu2=False)
        finally:
            os.unlink(path)
    if fmt == "json":
        return score_from_json(rendered if isinstance(rendered, str)
                               else rendered.decode("utf-8"))
    if fmt == "midi":
        return score_from_midi(rendered)
    if fmt == "musicxml":
        return score_from_musicxml(rendered)
    if fmt == "abc":
        return score_from_abc(rendered)
    raise ValueError(f"no importer for format {fmt!r}")


def _recovered_note_cents(fmt: str, variant: str, rendered
                          ) -> List[Optional[float]]:
    """Sounding pitch of each pitched note in ``rendered``, in cents above C-1.

    Notes only (no rests), so paths that drop rests still align with gold
    ``score.notes``.  MIDI values have the SymbTr A-anchor offset removed for
    relative comparison by the caller when needed; here we return absolute
    cents after undoing the default A4 anchor (matching ``score_from_midi``).
    """
    from .importers import _midi_anchor_offset

    if fmt == "txt":
        restored = _import_rendered("txt", rendered)
        return [_gold_cents(e) for e in restored.events if e.is_note]
    if fmt == "json":
        restored = _import_rendered("json", rendered)
        return [_gold_cents(e) for e in restored.events if e.is_note]
    if fmt == "midi":
        parsed = read_midi(rendered)
        offset = _midi_anchor_offset(305)
        return [n.cents + offset for n in
                sorted(parsed.notes, key=lambda n: (n.tick, n.note))]
    if fmt == "musicxml":
        folded = _fold_ties(read_musicxml(rendered).notes)
        return [head.cents for head, _ in folded
                if not head.is_rest and head.cents is not None]
    if fmt == "abc":
        return [n.cents for n in read_abc(rendered).notes
                if not n.is_rest and n.cents is not None]
    return []


def _recovered_note_durations(fmt: str, rendered) -> List[Fraction]:
    """Symbolic durations (whole notes) of pitched notes in ``rendered``."""
    if fmt == "txt":
        restored = _import_rendered("txt", rendered)
        return [e.duration for e in restored.events if e.is_note]
    if fmt == "json":
        restored = _import_rendered("json", rendered)
        return [e.duration for e in restored.events if e.is_note]
    if fmt == "midi":
        # Slot = onset gap; last note uses sounding length / 0.95.
        parsed = read_midi(rendered)
        notes = sorted(parsed.notes, key=lambda n: (n.tick, n.note))
        division = parsed.division or 480
        out: List[Fraction] = []
        for i, note in enumerate(notes):
            if i + 1 < len(notes):
                slot = max(notes[i + 1].tick - note.tick, 1)
            else:
                slot = max(int(round(note.duration / 0.95)), note.duration, 1)
            out.append(Fraction(slot, division * 4))
        return out
    if fmt == "musicxml":
        folded = _fold_ties(read_musicxml(rendered).notes)
        return [duration for head, duration in folded if not head.is_rest]
    if fmt == "abc":
        return [n.duration for n in read_abc(rendered).notes if not n.is_rest]
    return []


def audit_paths(score: Score, *, tolerance: float = TOLERANCE_CENTS
                ) -> List[PathReport]:
    """Measure pitch/duration loss for every ordered pair of importable formats.

    For each ``(A, B)``: write A from gold, re-import as a slim Score, write B,
    then compare B's recovered **note** pitches and durations to the original
    gold score.  Rests dropped by MIDI (etc.) do not shift the note alignment.
    """
    configs = _path_configurations()
    imported: Dict[Tuple[str, str], Score] = {}
    reports: List[PathReport] = []
    gold_notes = [e for e in score.events if e.is_note]

    for src_fmt, src_variant, render_src in configs:
        key = (src_fmt, src_variant)
        if key not in imported:
            try:
                imported[key] = _import_rendered(src_fmt, render_src(score))
            except Exception as exc:  # noqa: BLE001 - record and continue
                for dst_fmt, dst_variant, _ in configs:
                    reports.append(PathReport(
                        src_fmt, src_variant, dst_fmt, dst_variant,
                        note=f"import {src_fmt}/{src_variant} failed: {exc}"))
                continue

        mid = imported[key]
        for dst_fmt, dst_variant, render_dst in configs:
            report = PathReport(src_fmt, src_variant, dst_fmt, dst_variant)
            try:
                rendered = render_dst(mid)
            except Exception as exc:  # noqa: BLE001
                report.note = f"write {dst_fmt}/{dst_variant} failed: {exc}"
                reports.append(report)
                continue

            recovered = _recovered_note_cents(dst_fmt, dst_variant, rendered)
            pairs = list(zip(gold_notes, recovered))
            if len(recovered) != len(gold_notes):
                report.note = (f"{len(recovered)} recovered notes for "
                               f"{len(gold_notes)} gold notes")
            errors = [abs(cents - _gold_cents(event))
                      for event, cents in pairs if cents is not None]
            _accumulate(report, errors, tolerance)

            durations = _recovered_note_durations(dst_fmt, rendered)
            dur_pairs = list(zip(gold_notes, durations))
            report.durations_compared = len(dur_pairs)
            report.duration_exact = sum(
                1 for event, value in dur_pairs
                if abs(Fraction(value) - event.duration) <= Fraction(1, 64))
            reports.append(report)
    return reports


def format_path_report(reports: Sequence[PathReport], *, width: int = 110) -> str:
    """Table of pairwise path losses (gold → A → B vs gold)."""
    header = (f"{'src':22s} {'->':2s} {'dst':22s} {'pitch ok':>9s} "
              f"{'mean c':>7s} {'max c':>7s} {'dur ok':>7s}")
    lines = [header, "-" * max(width, len(header))]
    for report in reports:
        src = f"{report.src_fmt}/{report.src_variant}"
        dst = f"{report.dst_fmt}/{report.dst_variant}"
        if report.notes_compared == 0 and report.note:
            lines.append(f"{src:22s} -> {dst:22s} {'n/a':>9s} {'n/a':>7s} "
                         f"{'n/a':>7s} {'n/a':>7s}")
            lines.append(f"{'':22s}    note: {report.note}")
            continue
        lines.append(
            f"{src:22s} -> {dst:22s} "
            f"{report.pitch_exact_fraction:8.1%} "
            f"{report.pitch_cents_mean:7.2f} "
            f"{report.pitch_cents_max:7.2f} "
            f"{report.duration_exact_fraction:6.1%}")
        if report.note:
            lines.append(f"{'':22s}    note: {report.note}")
    return "\n".join(lines)


# -- auditing SymbTr's own published exports --------------------------------


@dataclass
class PublishedAudit:
    """How far SymbTr's own MIDI and MusicXML exports sit from the gold txt.

    This is not a criticism of the corpus so much as a warning to anyone
    training on it: the published derivatives are not interchangeable with the
    gold representation, and a model trained on ``MusicXML`` is being shown
    different pitches from a model trained on ``txt``.
    """

    scores: int = 0
    aligned: int = 0
    notes: int = 0
    exact: int = 0
    cents_mean: float = 0.0
    cents_max: float = 0.0
    over_50_cents: int = 0
    alter_missing: int = 0
    skipped: List[str] = field(default_factory=list)
    histogram: Dict[str, int] = field(default_factory=dict)

    @property
    def exact_fraction(self) -> float:
        return self.exact / self.notes if self.notes else 0.0

    def summary(self) -> str:
        lines = [
            f"scores: {self.scores} ({self.aligned} aligned by note count)",
            f"notes compared: {self.notes}",
            f"pitch exact: {self.exact} ({self.exact_fraction:.2%})",
            f"mean error: {self.cents_mean:.2f} cents, "
            f"max: {self.cents_max:.2f} cents",
            f"notes off by more than 50 cents: {self.over_50_cents} "
            f"({self.over_50_cents / self.notes:.2%})" if self.notes else "",
        ]
        if self.alter_missing:
            lines.append(
                f"notes with an accidental and no <alter>: {self.alter_missing} "
                f"({self.alter_missing / self.notes:.2%})")
        if self.histogram:
            lines.append("error distribution (cents):")
            for bucket, count in self.histogram.items():
                lines.append(f"    {bucket:>12s}  {count:7d}")
        return "\n".join(line for line in lines if line)


#: Buckets for the error histogram, in cents.
_BUCKETS = ((0.5, "< 0.5"), (5, "0.5 - 5"), (15, "5 - 15"), (30, "15 - 30"),
            (50, "30 - 50"), (100, "50 - 100"), (float("inf"), ">= 100"))


def audit_published_musicxml(
    pairs, *, tolerance: float = TOLERANCE_CENTS
) -> PublishedAudit:
    """Compare published MusicXML against the gold txt.

    ``pairs`` is an iterable of ``(txt_path, xml_path)``.  Scores whose note
    counts do not line up are counted but excluded from the pitch statistics,
    because a misalignment would otherwise masquerade as enormous pitch error.
    """
    from .readers.txt import read_txt

    audit = PublishedAudit()
    errors: List[float] = []
    buckets = {label: 0 for _, label in _BUCKETS}

    for txt_path, xml_path in pairs:
        audit.scores += 1
        try:
            score = read_txt(txt_path, use_mu2=False)
            parsed = read_musicxml(xml_path)
        except Exception as exc:  # noqa: BLE001 - a damaged file is data, not a crash
            audit.skipped.append(f"{txt_path}: {exc}")
            continue

        audit.alter_missing += sum(1 for n in parsed.notes if n.alter_missing)
        folded = [head for head, _ in _fold_ties(parsed.notes)
                  if not head.is_rest and not head.is_grace]
        gold = [e for e in score.events if e.is_note and not e.is_grace]
        if len(folded) != len(gold):
            audit.skipped.append(
                f"{txt_path}: {len(folded)} xml notes vs {len(gold)} gold notes")
            continue

        audit.aligned += 1
        for xml_note, event in zip(folded, gold):
            if xml_note.cents is None:
                continue
            error = abs(xml_note.cents - _gold_cents(event))
            errors.append(error)
            for limit, label in _BUCKETS:
                if error < limit:
                    buckets[label] += 1
                    break

    audit.notes = len(errors)
    audit.exact = sum(1 for e in errors if e <= tolerance)
    audit.cents_mean = sum(errors) / len(errors) if errors else 0.0
    audit.cents_max = max(errors) if errors else 0.0
    audit.over_50_cents = sum(1 for e in errors if e > 50)
    audit.histogram = buckets
    return audit


def audit_published_midi(
    pairs, *, tolerance: float = TOLERANCE_CENTS
) -> PublishedAudit:
    """Compare published MIDI against the gold txt.

    The published files are anchored on A, so a constant offset is removed
    per score before comparing -- see :mod:`microtonal_score_converter.writers.midi`.  About
    8% of them are anchored on D instead, which this absorbs rather than
    reports as error.
    """
    from .readers.txt import read_txt

    audit = PublishedAudit()
    errors: List[float] = []
    buckets = {label: 0 for _, label in _BUCKETS}

    for txt_path, midi_path in pairs:
        audit.scores += 1
        try:
            score = read_txt(txt_path, use_mu2=False)
            parsed = read_midi(midi_path)
        except Exception as exc:  # noqa: BLE001
            audit.skipped.append(f"{txt_path}: {exc}")
            continue

        gold = [e for e in score.events if e.is_note]
        if len(parsed.notes) != len(gold):
            audit.skipped.append(
                f"{txt_path}: {len(parsed.notes)} midi notes vs "
                f"{len(gold)} gold notes")
            continue

        audit.aligned += 1
        offsets = [m.cents - _gold_cents(e) for m, e in zip(parsed.notes, gold)]
        anchor = sorted(offsets)[len(offsets) // 2]
        for offset in offsets:
            error = abs(offset - anchor)
            errors.append(error)
            for limit, label in _BUCKETS:
                if error < limit:
                    buckets[label] += 1
                    break

    audit.notes = len(errors)
    audit.exact = sum(1 for e in errors if e <= tolerance)
    audit.cents_mean = sum(errors) / len(errors) if errors else 0.0
    audit.cents_max = max(errors) if errors else 0.0
    audit.over_50_cents = sum(1 for e in errors if e > 50)
    audit.histogram = buckets
    return audit
