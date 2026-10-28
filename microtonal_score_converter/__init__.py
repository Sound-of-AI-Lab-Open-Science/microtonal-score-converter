"""Convert SymbTr-txt, the gold 53-TET representation of Ottoman-Turkish makam
music, into other symbolic representations -- and measure what each one loses.

SymbTr-txt (Karaosmanoglu, ISMIR 2012) encodes each note twice, in 53-tone
equal temperament and in 24-tone Arel-Ezgi theory, alongside notated and
performed durations, articulation, velocity, syllabified lyrics, ornament
codes, phrase boundaries and usul changes.  No conventional format carries all
of that.  This package converts out of it and reports, per format and per
attribute, exactly what survived.

    >>> from microtonal_score_converter import read_txt, write_abc
    >>> score = read_txt("beyati--sarki--aksak--karsidan_yar--dede_efendi.txt")
    >>> abc = write_abc(score, mode="53tet")
"""

__version__ = "0.1.0"

from .audit import audit_score, format_report
from .duration import notate
from .musescore import retune_file, retune_mscx, tuning_cents
from .pitch import Pitch, quantize
from .readers.filename import parse_symbtr_name
from .readers.txt import read_txt
from .score import Event, Metadata, Score
from .writers import (write_abc, write_json, write_kern, write_midi,
                      write_musicxml, write_tokens)
from .writers.txt import write_txt

__all__ = [
    "__version__",
    "Event", "Metadata", "Pitch", "Score",
    "read_txt", "parse_symbtr_name", "notate", "quantize",
    "write_abc", "write_json", "write_kern", "write_midi", "write_musicxml",
    "write_tokens", "write_txt",
    "audit_score", "format_report",
    "retune_file", "retune_mscx", "tuning_cents",
]
