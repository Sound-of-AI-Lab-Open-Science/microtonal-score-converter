"""Optional metadata enrichment from a sibling ``.mu2`` file.

SymbTr-txt is the gold *musical* representation but it is deliberately stripped
of the header rows that Mus2-Alpha writes: the ``Kod 50/52/57/58/59/60/62/63``
rows carrying makam, tempo, form, composer, lyricist, title, folk flag and
notation style never appear in the published ``.txt`` files.  They do appear in
the matching ``.mu2``.

Reading the mu2 is therefore optional but worth doing when it is available: it
is the only place the *key signature* and an *explicit* tempo exist, and the
explicit tempo is more trustworthy than the one we back out of rounded
millisecond durations.

mu2 columns::

    Kod  Nota  Pay  Payda  Legato%  Bas  Cek  Soz-1  Soz-2  Offset
"""

from __future__ import annotations

import csv
import os
from typing import List, Optional, Tuple

from ..score import Metadata

#: ``Kod`` -> the :class:`~microtonal_score_converter.score.Metadata` field it populates from ``Soz-1``.
_SOZ1_FIELDS = {
    50: "makam",
    57: "form",
    58: "composer",
    59: "lyricist",
    60: "title",
    63: "notation",
}


def _rows(path: str) -> List[List[str]]:
    for encoding in ("utf-8-sig", "utf-8", "cp1254", "latin-1"):
        try:
            with open(path, encoding=encoding, newline="") as handle:
                return [r for r in csv.reader(handle, delimiter="\t") if r]
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError(  # pragma: no cover - all four failing is pathological
        "mu2", b"", 0, 1, f"could not decode {path}")


def read_mu2_metadata(path: str) -> Tuple[Metadata, Optional[float]]:
    """Return the header metadata of a mu2 file and its explicit tempo in BPM.

    The tempo row (``Kod 52``) states beats per minute *of the mertebe*, not of
    the quarter note: ``Pay/Payda = 1/8`` with ``Legato% = 216`` means 216
    eighth notes per minute, i.e. quarter = 108.  We normalise to quarter-note
    BPM so it is directly comparable with what the txt reader derives.
    """
    meta = Metadata(source=os.path.basename(path))
    tempo: Optional[float] = None

    for row in _rows(path):
        row = row + [""] * (10 - len(row))
        try:
            code = int(row[0])
        except ValueError:
            continue  # the header line

        soz1, soz2 = row[7].strip(), row[8].strip()

        field = _SOZ1_FIELDS.get(code)
        if field and soz1:
            setattr(meta, field, soz1)
        if code == 50 and soz2:
            meta.key_signature = [s.strip() for s in soz2.split(",") if s.strip()]
        elif code == 51 and soz1:
            meta.usul = soz1
        elif code == 52:
            tempo = _quarter_bpm(row)
        elif code == 61 and soz1:
            meta.ahenk = _maybe_int(soz1)
        elif code == 62 and soz1:
            meta.folkloric = soz1.strip().upper() in ("1", "H", "E", "EVET")
        elif code == 64 and soz1:
            meta.extra["lyrics_title"] = soz1
        elif code == 65 and soz1:
            meta.extra["composition_date"] = soz1
        elif code == 66 and soz1:
            meta.extra["stated_duration"] = soz1

    if meta.composer in ("?", "-"):
        meta.composer = ""
    if meta.lyricist in ("?", "-"):
        meta.lyricist = ""
    return meta, tempo


def _quarter_bpm(row: List[str]) -> Optional[float]:
    """Convert a ``Kod 52`` row into quarter-note BPM."""
    rate = _maybe_int(row[4])
    mertebe = _maybe_int(row[3])
    numerator = _maybe_int(row[2]) or 1
    if not rate or not mertebe:
        return None
    # `rate` counts units of `numerator/mertebe` whole notes per minute.
    return rate * (4.0 * numerator / mertebe)


def _maybe_int(value: str) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def find_sibling_mu2(txt_path: str) -> Optional[str]:
    """Locate the ``.mu2`` matching a ``.txt`` in a standard SymbTr checkout."""
    stem = os.path.splitext(os.path.basename(txt_path))[0]
    directory = os.path.dirname(os.path.abspath(txt_path))
    candidates = [
        os.path.join(directory, stem + ".mu2"),
        os.path.join(os.path.dirname(directory), "mu2", stem + ".mu2"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None
