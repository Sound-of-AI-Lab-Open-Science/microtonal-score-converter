"""Reader for SymbTr-txt -- the gold 53-TET representation.

This is the only reader whose fidelity matters, because every other
representation in this package is derived from its output.  It is deliberately
permissive about damage (it records warnings rather than raising) and strict
about meaning (it never guesses a pitch, and it preserves rows it does not
understand).

Two subtleties that are easy to get wrong and that the format does not document:

1. ``Offset`` is the position of the *end* of the row, not its start.  A 1/4
   note at the top of a 9/8 measure carries ``Offset = 0.2222`` = (1/4)/(9/8).
   Start offsets are therefore the previous row's value, which is what
   :class:`~microtonal_score_converter.score.Event.offset` holds.
2. Rests are spelled ``Es`` with ``Koma = -1`` in most files but ``Koma = 0`` in
   some older ones.  Both mean rest; only ``Nota53`` is authoritative.
"""

from __future__ import annotations

import csv
import os
from fractions import Fraction
from typing import List, Optional, Sequence

from ..pitch import REST_NAME, Pitch, PitchParseError
from ..score import Event, Metadata, Score
from .filename import humanize, parse_symbtr_name
from .mu2 import find_sibling_mu2, read_mu2_metadata

#: The canonical column order of SymbTr-txt v2.  All 2200 published scores use
#: exactly this header, but we index by name so variants still work.
REQUIRED_COLUMNS = (
    "Sira", "Kod", "Nota53", "NotaAE", "Koma53", "KomaAE",
    "Pay", "Payda", "Ms", "LNS", "Bas", "Soz1", "Offset",
)


class SymbTrTxtError(ValueError):
    """Raised when a file is not recognisable as SymbTr-txt at all."""


def read_txt(
    path: str,
    *,
    mu2_path: Optional[str] = None,
    use_mu2: bool = True,
) -> Score:
    """Parse a SymbTr-txt file into a :class:`~microtonal_score_converter.score.Score`.

    Parameters
    ----------
    path
        The ``.txt`` score.
    mu2_path
        Explicit path to the matching ``.mu2``.  When omitted and ``use_mu2``
        is set, a sibling file is looked for next to the score and in a
        ``../mu2`` directory, matching the layout of the SymbTr repository.
    use_mu2
        Set to ``False`` to parse the txt in isolation, which is the honest
        setting when measuring what the gold *txt* representation alone carries.
    """
    rows, header = _read_rows(path)
    columns = {name: i for i, name in enumerate(header)}
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        raise SymbTrTxtError(f"{path}: missing columns {missing}")

    score = Score(metadata=_metadata_from_filename(path))
    events: List[Event] = []
    previous_end = Fraction(0)

    for line_number, row in enumerate(rows, start=2):
        if not any(cell.strip() for cell in row):
            continue
        row = list(row) + [""] * (len(header) - len(row))
        event = _parse_row(row, columns, previous_end, score.warnings,
                           f"{os.path.basename(path)}:{line_number}")
        if event is None:
            continue
        events.append(event)
        previous_end = event.offset_end

    score.events = events
    _validate(score, os.path.basename(path))

    if use_mu2:
        found = mu2_path or find_sibling_mu2(path)
        if found:
            _merge_mu2(score, found)

    return score


# -- row parsing -----------------------------------------------------------


def _parse_row(
    row: Sequence[str],
    columns: dict,
    previous_end: Fraction,
    warnings: List[str],
    where: str,
) -> Optional[Event]:
    get = lambda name: row[columns[name]].strip()  # noqa: E731

    index = _int(get("Sira"), default=0)
    code = _int(get("Kod"), default=9)
    offset_end = _fraction(get("Offset"), default=previous_end)

    name53, name_ae = get("Nota53"), get("NotaAE")
    pitch53 = _parse_pitch(name53, get("Koma53"), warnings, where, "Nota53")
    pitch_ae = _parse_pitch(name_ae, get("KomaAE"), warnings, where, "NotaAE")

    return Event(
        index=index,
        code=code,
        offset=previous_end,
        offset_end=offset_end,
        numerator=max(_int(get("Pay"), default=0), 0),
        denominator=max(_int(get("Payda"), default=0), 0),
        ms=max(_int(get("Ms"), default=0), 0),
        lns=_int(get("LNS"), default=95),
        velocity=_int(get("Bas"), default=0),
        text=row[columns["Soz1"]],  # significant trailing spaces: do not strip
        pitch53=pitch53,
        pitchAE=pitch_ae,
        rest_marker=REST_NAME in (name53, name_ae),
        koma53_raw=_int(get("Koma53"), default=None),
        komaAE_raw=_int(get("KomaAE"), default=None),
        offset_text=row[columns["Offset"]],
    )


def _parse_pitch(
    name: str, koma: str, warnings: List[str], where: str, column: str
) -> Optional[Pitch]:
    """Parse one of the two pitch columns, cross-checking name against comma."""
    if not name or name == REST_NAME:
        return None
    try:
        pitch = Pitch.parse(name)
    except PitchParseError:
        warnings.append(f"{where}: unparsable {column} {name!r}")
        return None

    stated = _int(koma, default=None)
    if stated is not None and stated != pitch.koma:
        # The spelling is authoritative -- it is what the engraver entered --
        # but a disagreement means the file has been edited by hand, so say so.
        warnings.append(
            f"{where}: {column} {name!r} implies comma {pitch.koma} "
            f"but the file says {stated}"
        )
    return pitch


def _read_rows(path: str):
    for encoding in ("utf-8-sig", "utf-8", "cp1254", "latin-1"):
        try:
            with open(path, encoding=encoding, newline="") as handle:
                reader = csv.reader(handle, delimiter="\t")
                header = next(reader, None)
                if header is None:
                    raise SymbTrTxtError(f"{path}: empty file")
                return list(reader), [h.strip() for h in header]
        except UnicodeDecodeError:
            continue
    raise SymbTrTxtError(f"{path}: could not decode as text")


def _int(value: str, default=0):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _fraction(value: str, default: Fraction) -> Fraction:
    try:
        return Fraction(str(value).strip()).limit_denominator(1000000)
    except (TypeError, ValueError, ZeroDivisionError):
        return default


# -- metadata and validation ----------------------------------------------


def _metadata_from_filename(path: str) -> Metadata:
    fields = parse_symbtr_name(path)
    return Metadata(
        name=fields["name"],
        makam=fields["makam"],
        form=fields["form"],
        usul=fields["usul"],
        title=humanize(fields["title"]) if fields["title"] else "",
        composer=humanize(fields["composer"]) if fields["composer"] else "",
        source=os.path.basename(path),
    )


def _merge_mu2(score: Score, mu2_path: str) -> None:
    """Fill blank metadata fields from the mu2 without overwriting the filename.

    The filename fields are slugs and the mu2 fields are properly accented
    Turkish, so the mu2 wins wherever it has a value -- except for ``name``,
    which identifies the score in the corpus and must stay as the filename.
    """
    try:
        mu2_meta, mu2_tempo = read_mu2_metadata(mu2_path)
    except (OSError, UnicodeDecodeError) as exc:
        score.warnings.append(f"could not read {os.path.basename(mu2_path)}: {exc}")
        return

    target = score.metadata
    for field in ("makam", "form", "usul", "title", "composer", "lyricist",
                  "notation"):
        value = getattr(mu2_meta, field)
        if value:
            target.extra.setdefault(f"filename_{field}", getattr(target, field))
            setattr(target, field, value)
    if mu2_meta.key_signature:
        target.key_signature = mu2_meta.key_signature
    if mu2_meta.ahenk is not None:
        target.ahenk = mu2_meta.ahenk
    if mu2_meta.folkloric is not None:
        target.folkloric = mu2_meta.folkloric
    target.extra.update(mu2_meta.extra)
    if mu2_tempo:
        target.extra["mu2_tempo"] = f"{mu2_tempo:g}"


def _validate(score: Score, name: str) -> None:
    """Record structural problems as warnings.  Never raises.

    These are the same checks ``tomato``'s reader performs, kept because they
    catch real corpus damage, but demoted to warnings so that a damaged score
    still converts.
    """
    if not score.events:
        score.warnings.append(f"{name}: no rows")
        return

    if score.events[0].code != 51:
        score.warnings.append(f"{name}: does not start with a usul row (Kod 51)")

    expected = 0
    for event in score.events:
        expected += 1
        if event.index != expected:
            score.warnings.append(
                f"{name}: row index jumps to {event.index} (expected {expected})")
            expected = event.index

    for event in score.events:
        if event.is_rest and event.code not in (0, 9):
            score.warnings.append(
                f"{name}: row {event.index} is a rest with unexpected Kod {event.code}")
