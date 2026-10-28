"""Metadata carried by the SymbTr filename.

The ISMIR 2012 paper makes the filename part of the format::

    beyati--sarki--aksak--karsidan_yar--dede_efendi.txt
    makam   form   usul    title         composer

So the four classification labels used in the downstream task suite (makam,
form, usul, composer) are recoverable without opening the file -- which is why
"four tasks from one filename" works at all.  Empty fields are written as a
single ``-`` or left blank; both occur in the corpus.
"""

from __future__ import annotations

import os
import re
from typing import Dict

FIELDS = ("makam", "form", "usul", "title", "composer")

_SEPARATOR = "--"


def parse_symbtr_name(path_or_name: str) -> Dict[str, str]:
    """Split a SymbTr name into its five fields.

    Extra fields (some corrected files carry a sixth ``--corrected`` suffix) are
    collected under ``variant`` rather than silently shifting the other fields.
    Unknown shapes return whatever could be matched plus the raw name, instead
    of raising: a converter should still convert a badly named file.
    """
    name = os.path.basename(path_or_name)
    name = re.sub(r"\.(txt|mu2|xml|mid|midi|abc|krn|json)$", "", name, flags=re.I)

    parts = name.split(_SEPARATOR)
    out: Dict[str, str] = {"name": name}
    for field, value in zip(FIELDS, parts):
        value = value.strip()
        out[field] = "" if value in ("", "-", "?") else value
    for field in FIELDS:
        out.setdefault(field, "")
    if len(parts) > len(FIELDS):
        out["variant"] = _SEPARATOR.join(parts[len(FIELDS):])
    return out


def humanize(slug: str) -> str:
    """``dede_efendi`` -> ``Dede Efendi``, for titles in exported scores."""
    return " ".join(w.capitalize() for w in slug.replace("_", " ").split())
