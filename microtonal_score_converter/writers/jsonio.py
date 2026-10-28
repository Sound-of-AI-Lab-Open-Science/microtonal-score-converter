"""Lossless JSON serialisation of the IR.

Every other writer drops something.  This one drops nothing, which makes it
the control in the information-loss audit: if a round trip through JSON is not
bit-identical, the loss is in the reader or the IR, not in the target format.
It is also the convenient format for the downstream experiments, which want
the structural annotations as data rather than as notation.
"""

from __future__ import annotations

import json
from fractions import Fraction
from typing import Any, Dict, Optional

from ..pitch import Pitch
from ..score import Event, Metadata, Score

SCHEMA_VERSION = 1


def write_json(
    score: Score,
    path: Optional[str] = None,
    *,
    indent: Optional[int] = 2,
    include_derived: bool = False,
) -> str:
    """Serialise a score.

    ``include_derived`` adds values that can be recomputed from the events
    (tempo map, measure count, phrase offsets).  Off by default so the file
    stays a faithful record of the source rather than a cache of our opinions
    about it.
    """
    payload: Dict[str, Any] = {
        "schema": SCHEMA_VERSION,
        "metadata": _metadata_to_dict(score.metadata),
        "events": [_event_to_dict(e) for e in score.events],
        "warnings": list(score.warnings),
    }
    if include_derived:
        payload["derived"] = {
            "tempo_bpm": score.tempo,
            "tempo_map": [
                {"offset": str(s.offset), "bpm": s.bpm, "notes": s.note_count}
                for s in score.tempo_map()
            ],
            "measures": len(score.measures()),
            "phrase_boundaries": [str(o) for o in score.phrase_boundaries],
            "note_count": len(score.notes),
            "duration_ms": score.duration_ms,
            "instrumental": score.is_instrumental,
        }

    text = json.dumps(payload, ensure_ascii=False, indent=indent)
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    return text


def read_json(path: str) -> Score:
    """Rebuild a score from :func:`write_json` output."""
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    return score_from_dict(payload)


def score_from_dict(payload: Dict[str, Any]) -> Score:
    version = payload.get("schema")
    if version != SCHEMA_VERSION:
        raise ValueError(f"unsupported schema version {version!r}")
    return Score(
        events=[_event_from_dict(d) for d in payload["events"]],
        metadata=_metadata_from_dict(payload["metadata"]),
        warnings=list(payload.get("warnings", [])),
    )


# -- events ----------------------------------------------------------------


def _event_to_dict(event: Event) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "index": event.index,
        "code": event.code,
        "offset": str(event.offset),
        "offset_end": str(event.offset_end),
        "num": event.numerator,
        "den": event.denominator,
        "ms": event.ms,
        "lns": event.lns,
        "velocity": event.velocity,
        "text": event.text,
        "rest_marker": event.rest_marker,
        "koma53_raw": event.koma53_raw,
        "komaAE_raw": event.komaAE_raw,
        "offset_text": event.offset_text,
    }
    if event.pitch53 is not None:
        out["pitch53"] = _pitch_to_dict(event.pitch53)
    if event.pitchAE is not None:
        out["pitchAE"] = _pitch_to_dict(event.pitchAE)
    return out


def _event_from_dict(data: Dict[str, Any]) -> Event:
    return Event(
        index=data["index"],
        code=data["code"],
        offset=Fraction(data["offset"]),
        offset_end=Fraction(data["offset_end"]),
        numerator=data["num"],
        denominator=data["den"],
        ms=data["ms"],
        lns=data["lns"],
        velocity=data["velocity"],
        text=data["text"],
        pitch53=_pitch_from_dict(data.get("pitch53")),
        pitchAE=_pitch_from_dict(data.get("pitchAE")),
        rest_marker=data.get("rest_marker", False),
        koma53_raw=data.get("koma53_raw"),
        komaAE_raw=data.get("komaAE_raw"),
        offset_text=data.get("offset_text", ""),
    )


def _pitch_to_dict(pitch: Pitch) -> Dict[str, Any]:
    # The spelling is what must survive; ``koma`` is written for readability
    # and for consumers that do not want to do the arithmetic themselves.
    return {
        "name": pitch.name,
        "letter": pitch.letter,
        "octave": pitch.octave,
        "alteration": pitch.alteration,
        "solfege": pitch.solfege,
        "koma": pitch.koma,
    }


def _pitch_from_dict(data: Optional[Dict[str, Any]]) -> Optional[Pitch]:
    if not data:
        return None
    return Pitch(
        letter=data["letter"],
        octave=data["octave"],
        alteration=data["alteration"],
        solfege=data.get("solfege", True),
    )


# -- metadata --------------------------------------------------------------


def _metadata_to_dict(meta: Metadata) -> Dict[str, Any]:
    return {
        "name": meta.name, "makam": meta.makam, "form": meta.form,
        "usul": meta.usul, "title": meta.title, "composer": meta.composer,
        "lyricist": meta.lyricist, "key_signature": list(meta.key_signature),
        "karar_symbol": meta.karar_symbol, "ahenk": meta.ahenk,
        "notation": meta.notation, "folkloric": meta.folkloric,
        "source": meta.source, "extra": dict(meta.extra),
    }


def _metadata_from_dict(data: Dict[str, Any]) -> Metadata:
    return Metadata(
        name=data.get("name", ""), makam=data.get("makam", ""),
        form=data.get("form", ""), usul=data.get("usul", ""),
        title=data.get("title", ""), composer=data.get("composer", ""),
        lyricist=data.get("lyricist", ""),
        key_signature=list(data.get("key_signature") or []),
        karar_symbol=data.get("karar_symbol", ""), ahenk=data.get("ahenk"),
        notation=data.get("notation", ""), folkloric=data.get("folkloric"),
        source=data.get("source", ""), extra=dict(data.get("extra") or {}),
    )
