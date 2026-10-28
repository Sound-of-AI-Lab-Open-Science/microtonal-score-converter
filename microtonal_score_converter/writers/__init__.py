"""Writers that render the IR into target representations."""

from .abc import write_abc
from .jsonio import read_json, write_json
from .kern import write_kern
from .midi import write_midi
from .musicxml import write_musicxml
from .tokens import write_tokens

#: Format name -> (writer, default file extension).
WRITERS = {
    "midi": (write_midi, ".mid"),
    "musicxml": (write_musicxml, ".xml"),
    "abc": (write_abc, ".abc"),
    "kern": (write_kern, ".krn"),
    "tokens": (write_tokens, ".txt"),
    "json": (write_json, ".json"),
}

__all__ = [
    "write_abc", "write_json", "write_kern", "write_midi", "write_musicxml",
    "write_tokens", "read_json", "WRITERS",
]
