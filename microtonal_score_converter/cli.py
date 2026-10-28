"""Command line interface.

::

    microtonal-score-converter convert SCORE... --to midi,abc -o out/
    microtonal-score-converter audit SCORE...
    microtonal-score-converter audit-published --root path/to/SymbTr
    microtonal-score-converter info SCORE
"""

from __future__ import annotations

import argparse
import glob
import os
import shutil
import sys
from typing import Dict, Iterable, List, Optional, Sequence

from . import __version__
from .audit import (audit_published_midi, audit_published_musicxml,
                    audit_score, format_report)
from .musescore import RetuneError, retune_file
from .readers.mu2 import find_sibling_mu2
from .readers.txt import read_txt
from .score import Score
from .writers import (write_abc, write_json, write_kern, write_midi,
                      write_musicxml, write_tokens)
from .writers.txt import write_txt

#: Target name -> (writer, extension, binary?).
TARGETS = {
    "midi": (write_midi, ".mid", True),
    "musicxml": (write_musicxml, ".xml", False),
    "abc": (write_abc, ".abc", False),
    "kern": (write_kern, ".krn", False),
    "tokens": (write_tokens, ".tokens.txt", False),
    "json": (write_json, ".json", False),
    "txt": (write_txt, ".symbtr.txt", False),
}

#: Options that only apply to one target, so ``--mode`` cannot be handed to a
#: writer that has no such parameter.
TARGET_OPTIONS = {
    "midi": ("convention", "timing", "anchor"),
    "musicxml": ("precision", "reference"),
    "abc": ("mode", "reference"),
    "kern": ("microtone_spine",),
    "tokens": ("preset",),
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 1
    return args.handler(args)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="microtonal-score-converter",
        description="Convert SymbTr-txt, the gold 53-TET representation of "
                    "Ottoman-Turkish makam music, into other symbolic formats.")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command")

    convert = subparsers.add_parser(
        "convert", help="convert scores to one or more target formats")
    convert.add_argument("inputs", nargs="+",
                         help="SymbTr-txt files, directories or globs")
    convert.add_argument("--to", default="musicxml",
                         help="comma-separated targets: "
                              + ", ".join(sorted(TARGETS)))
    convert.add_argument("-o", "--output", default=".", help="output directory")
    convert.add_argument("--no-mu2", action="store_true",
                         help="ignore sibling .mu2 metadata")
    convert.add_argument("--convention", default="symbtr",
                         help="MIDI tuning: symbtr, bend-nearest, 24tet, 12tet")
    convert.add_argument("--timing", default="symbolic",
                         help="MIDI timing: symbolic or ms")
    convert.add_argument("--anchor", type=int, default=305,
                         help="MIDI unbent reference pitch, in commas "
                              "(305 = A4, 327 = D5)")
    convert.add_argument("--precision", default="exact",
                         help="MusicXML tuning: exact, quartertone, 12tet")
    convert.add_argument("--reference", default="12tet",
                         help="alter measured from: 12tet or diatonic")
    convert.add_argument("--mode", default="53tet",
                         help="ABC tuning: 53tet, 24tet, 12tet")
    convert.add_argument("--microtone-spine", dest="microtone_spine",
                         default="koma", help="Humdrum spine: koma, cents, none")
    convert.add_argument("--preset", default="gold53",
                         help="token preset, see microtonal_score_converter.writers.tokens")
    convert.add_argument("-q", "--quiet", action="store_true")
    convert.set_defaults(handler=_run_convert)

    audit = subparsers.add_parser(
        "audit", help="round-trip scores through every format and report loss")
    audit.add_argument("inputs", nargs="+")
    audit.add_argument("--no-mu2", action="store_true")
    audit.set_defaults(handler=_run_audit)

    published = subparsers.add_parser(
        "audit-published",
        help="compare SymbTr's own MIDI and MusicXML exports against the gold txt")
    published.add_argument("--root", required=True,
                           help="a SymbTr checkout containing txt/, midi/, MusicXML/")
    published.add_argument("--limit", type=int, default=0,
                           help="only look at the first N scores")
    published.set_defaults(handler=_run_audit_published)

    retune = subparsers.add_parser(
        "retune",
        help="write exact 53-TET tuning into a MuseScore .mscz/.mscx",
        description="MuseScore 2.x ignores fractional MusicXML <alter> for "
                    "playback, so a converted score looks right and sounds "
                    "12-TET.  Open the MusicXML in MuseScore 2.x, save as .mscz, "
                    "then run this to set each note's tuning.  Converting with "
                    "--precision 12tet first keeps MuseScore on the right "
                    "semitone and halves the offsets it has to apply.  "
                    "MuseScore 4.x does not need this.")
    retune.add_argument("score", help="the gold SymbTr-txt the file came from")
    retune.add_argument("musescore", help="a .mscz or .mscx saved by MuseScore")
    retune.add_argument("-o", "--output",
                        help="write here instead of editing in place")
    retune.add_argument("--anchor", type=int, default=305,
                        help="comma value left untuned (305 = A4, so A stays "
                             "at concert pitch)")
    retune.add_argument("--permissive", action="store_true",
                        help="warn instead of failing when notes do not line up")
    retune.add_argument("--no-mu2", action="store_true")
    retune.set_defaults(handler=_run_retune)

    info = subparsers.add_parser("info", help="summarise a score")
    info.add_argument("inputs", nargs="+")
    info.add_argument("--no-mu2", action="store_true")
    info.set_defaults(handler=_run_info)

    return parser


# -- commands ---------------------------------------------------------------


def _run_convert(args) -> int:
    targets = [t.strip() for t in args.to.split(",") if t.strip()]
    unknown = [t for t in targets if t not in TARGETS]
    if unknown:
        print(f"unknown target(s): {', '.join(unknown)}; "
              f"choose from {', '.join(sorted(TARGETS))}", file=sys.stderr)
        return 2

    paths = _expand(args.inputs)
    if not paths:
        print("no input files matched", file=sys.stderr)
        return 2

    os.makedirs(args.output, exist_ok=True)
    failures = 0
    for path in paths:
        try:
            score = _load(path, args.no_mu2)
        except Exception as exc:  # noqa: BLE001 - keep going through a batch
            print(f"{path}: {exc}", file=sys.stderr)
            failures += 1
            continue

        stem = os.path.splitext(os.path.basename(path))[0]
        for target in targets:
            writer, extension, _ = TARGETS[target]
            destination = os.path.join(args.output, stem + extension)
            writer(score, destination, **_options_for(target, args))
            if not args.quiet:
                print(destination)
        for warning in score.warnings:
            print(f"warning: {warning}", file=sys.stderr)

    return 1 if failures else 0


def _options_for(target: str, args) -> Dict[str, object]:
    return {name: getattr(args, name)
            for name in TARGET_OPTIONS.get(target, ())
            if getattr(args, name, None) is not None}


def _run_audit(args) -> int:
    for path in _expand(args.inputs):
        score = _load(path, args.no_mu2)
        print(f"== {score.metadata.name} "
              f"({len(score.notes)} notes, {len(score.measures())} measures)")
        print(format_report(audit_score(score)))
        print()
    return 0


def _run_audit_published(args) -> int:
    root = args.root
    txts = sorted(glob.glob(os.path.join(root, "txt", "*.txt")))
    if args.limit:
        txts = txts[:args.limit]
    if not txts:
        print(f"no scores found under {root}/txt", file=sys.stderr)
        return 2

    xml_pairs = _existing_pairs(txts, root, "MusicXML", ".xml")
    midi_pairs = _existing_pairs(txts, root, "midi", ".mid")

    if xml_pairs:
        print("== published MusicXML vs gold SymbTr-txt ==")
        print(audit_published_musicxml(xml_pairs).summary())
        print()
    if midi_pairs:
        print("== published MIDI vs gold SymbTr-txt ==")
        print(audit_published_midi(midi_pairs).summary())
    return 0


def _existing_pairs(txts, root, directory, extension):
    pairs = []
    for txt in txts:
        stem = os.path.splitext(os.path.basename(txt))[0]
        candidate = os.path.join(root, directory, stem + extension)
        if os.path.exists(candidate):
            pairs.append((txt, candidate))
    return pairs


def _run_retune(args) -> int:
    score = _load(args.score, args.no_mu2)
    if args.output and args.output != args.musescore:
        shutil.copyfile(args.musescore, args.output)
    try:
        report = retune_file(
            args.output or args.musescore, score,
            anchor=args.anchor if args.anchor >= 0 else None,
            strict=not args.permissive)
    except RetuneError as exc:
        print(f"{args.musescore}: {exc}", file=sys.stderr)
        return 1
    print(report.summary())
    print(f"wrote {args.output or args.musescore}")
    return 0


def _run_info(args) -> int:
    for path in _expand(args.inputs):
        score = _load(path, args.no_mu2)
        meta = score.metadata
        usuls = score.usul_changes
        print(f"name       {meta.name}")
        print(f"title      {meta.title}")
        print(f"makam      {meta.makam}")
        print(f"form       {meta.form}")
        print(f"usul       {meta.usul}"
              + (f" ({usuls[0].time_signature})" if usuls else ""))
        print(f"composer   {meta.composer}")
        print(f"notes      {len(score.notes)} in {len(score.measures())} measures")
        print(f"tempo      {score.tempo:.1f} bpm"
              + (f" over {len(score.tempo_map())} segments"
                 if len(score.tempo_map()) > 1 else ""))
        print(f"duration   {score.duration_ms / 1000:.1f} s")
        print(f"range      {_range(score)}")
        print(f"structure  {len(score.phrase_boundaries)} phrase marks, "
              f"{len(score.sections)} section headings, "
              f"{len(score.modulations)} modulation markers")
        if meta.key_signature:
            print(f"key sig    {', '.join(meta.key_signature)}")
        for warning in score.warnings:
            print(f"warning    {warning}")
        print()
    return 0


def _range(score: Score) -> str:
    notes = score.notes
    if not notes:
        return "-"
    lowest = min(notes, key=lambda e: e.pitch53.koma).pitch53
    highest = max(notes, key=lambda e: e.pitch53.koma).pitch53
    span = highest.koma - lowest.koma
    return (f"{lowest.name} to {highest.name} "
            f"({span} commas, {span / 53:.2f} octaves)")


# -- helpers ----------------------------------------------------------------


def _expand(inputs: Iterable[str]) -> List[str]:
    """Accept files, directories and globs, in any mixture."""
    out: List[str] = []
    for item in inputs:
        if os.path.isdir(item):
            out.extend(sorted(glob.glob(os.path.join(item, "*.txt"))))
        elif any(ch in item for ch in "*?["):
            out.extend(sorted(glob.glob(item)))
        elif os.path.exists(item):
            out.append(item)
        else:
            print(f"not found: {item}", file=sys.stderr)
    return out


def _load(path: str, no_mu2: bool) -> Score:
    mu2 = None if no_mu2 else find_sibling_mu2(path)
    return read_txt(path, mu2_path=mu2, use_mu2=not no_mu2)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
