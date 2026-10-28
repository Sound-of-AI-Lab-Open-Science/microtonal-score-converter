# microtonal-score-converter

Convert **SymbTr-txt** — the gold 53-TET representation of Ottoman-Turkish
makam music created by M. Kemal Karaosmanoğlu — into MIDI, MusicXML, ABC,
Humdrum, token streams and JSON, and **measure what each one loses**.

## Install

Managed with [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # create .venv and install the package + pytest
uv run microtonal-score-converter --version
```

To run it without cloning, straight from a checkout or a git URL:

```bash
uvx --from . microtonal-score-converter info SymbTr/txt/rast--sarki--duyek--omrumce_hep--irfan_ozbakir.txt
uv tool install .            # put `microtonal-score-converter` on your PATH for good
```

Plain pip also works:

```bash
pip install -e ".[dev]"
```

## Use

```bash
uv run microtonal-score-converter convert SymbTr/txt/*.txt --to midi,musicxml,abc,kern -o out/
uv run microtonal-score-converter audit   SymbTr/txt/beyati--sarki--aksak--karsidan_yar--dede_efendi.txt
uv run microtonal-score-converter audit-published --root SymbTr/
uv run microtonal-score-converter info    SymbTr/txt/rast--sarki--duyek--omrumce_hep--irfan_ozbakir.txt
```

### Opening a score in MuseScore

MuseScore 4.7 plays the exact MusicXML correctly with no extra steps:

```bash
uv run microtonal-score-converter convert score.txt --to musicxml -o out/
```

MuseScore 2.x plays everything in 12-TET. For that version, see
[MuseScore 2.x plays everything in 12-TET](#5-musescore-2x-plays-everything-in-12-tet):

```bash
uv run microtonal-score-converter convert score.txt --to musicxml --precision 12tet -o out/
#   open out/score.xml in MuseScore 2.x, save as score.mscz
uv run microtonal-score-converter retune score.txt score.mscz
```

```python
from microtonal_score_converter import read_txt, write_abc, audit_score, format_report

score = read_txt("beyati--sarki--aksak--karsidan_yar--dede_efendi.txt")
print(write_abc(score, mode="53tet"))
print(format_report(audit_score(score)))
```

---

## Why this exists

SymbTr-txt records each note *twice* — once in 53-tone equal temperament
(`Nota53`/`Koma53`) and once in 24-tone Arel-Ezgi theory (`NotaAE`/`KomaAE`) —
alongside the notated duration, the performed duration in milliseconds,
articulation, velocity, syllabified lyrics, ornament codes, phrase boundaries,
section headings and usul changes. No conventional symbolic format carries all
of that. Choosing a representation for makam MIR therefore means choosing what
to throw away, and until now there was no way to say precisely what.

This package converts out of the gold format and reports, per format and per
attribute, exactly what survived.

## The pitch model

The whole system turns on one identity, verified against **all 849,403 pitched
rows** of SymbTr v2.4.3 with zero mismatches:

```
koma = 265 + 53·(octave − 4) + degree[letter] + alteration
midi = koma · 12/53          (exact: 265 · 12/53 = 60)
```

`Do4`/`C4` is comma 265, which is MIDI 60, so the comma scale is anchored at
`koma 0 = MIDI 0 = C-1`. Every other representation here is derived
arithmetically from that rather than by table lookup.

A consequence that is easy to miss and costs real accuracy: **53-TET's natural
degrees are not 12-TET's**. 53-TET D sits 3.8 cents above 12-TET D and B sits
9.4 cents above. Any letter-based format (MusicXML `<alter>`, an ABC
accidental) must therefore put the *total* distance from the 12-TET letter into
the accidental, not just the notated alteration — otherwise every natural is
slightly wrong. That is the `reference="12tet"` default; `reference="diatonic"`
gives the conventional-looking alternative and costs up to 9.4 cents per note.

## Verification

Everything below is reproduced by `pytest` and by the corpus scripts; nothing
is asserted without being measured.

| Claim | Result |
|---|---|
| SymbTr-txt → IR → SymbTr-txt | **2200 / 2200 scores byte-identical** |
| `Offset` column recomputed from durations | identical on all rows checked (max difference 0) |
| ABC `53tet` round trip | **0.00000000 cents** error, all 849,403 notes |
| MusicXML `exact` round trip | 4 × 10⁻⁸ cents (decimal rounding) |
| MIDI `symbtr` round trip | 0.022 cents (the 14-bit pitch-bend limit) |
| MIDI vs SymbTr's own `.mid` | **note number and bend identical** wherever the note counts align |
| All 2200 scores → 7 formats | no failures, no alignment errors |
| Test suite on Python 3.8 – 3.14 | **130 passed** on every version |
| `retune`d score rendered by MuseScore 2.3.2 | within **1.4 cents** of 53-TET (was 65) |

### Reproducing SymbTr's MIDI exactly

Decoding the published `.mid` files pins down a convention the ISMIR paper only
sketches, and `write_midi(score)` reproduces it event for event:

* **Base note** is the 12-TET pitch of the *Arel-Ezgi* spelling: the letter and
  octave plus `round(alteration × 12/53)` semitones. A 1-comma flat (`B4b1`,
  segâh) stays on B; a bakiyye flat drops a semitone.
* **Bend** carries the remainder, *anchored on A* — the paper's "pitch-bend is
  unnecessary for any A in all octaves". C comes out 5.66 cents flat, which is
  the paper's worked `8192 − 5.7 × 40.96 ≈ 7960`.
* **Bend range** is set to ±2 semitones via RPN 0, giving 40.96 units per cent.
* **Timing** is symbolic at 480 ticks per quarter, and `LNS` is the note's
  gate: it sounds for `LNS` percent of its slot and rests for the remainder.

---

## Findings about the SymbTr corpus

These came out of building the converter and bear directly on any experiment
that trains on SymbTr's published derivatives.

### 1. The published MusicXML is badly out of tune

`microtonal-score-converter audit-published --root SymbTr/`, over **673,477 notes** in the 1,805
scores whose note counts align with the gold txt:

| | published MusicXML | published MIDI |
|---|---|---|
| notes with the exact pitch | **12.1%** | **99.5%** |
| mean error | 11.5 cents | 1.0 cents |
| notes off by **> 50 cents** | **6.0%** | 0.4% |
| max error | 186.8 cents | — |

Two causes compound:

* **7.3% of notes carry an `<accidental>` glyph with no `<alter>` element.**
  MusicXML 3.0 has no standard alter value for four of the eight Arel-Ezgi
  accidentals (`slash-flat`, `double-slash-flat`, `slash-sharp`,
  `slash-quarter-sharp`), and the official converter omits the element rather
  than approximating it. Every parser that reads `<alter>` — music21 included —
  therefore reads those notes as **naturals**. A bakiyye flat read as natural
  is wrong by 91 cents; a küçük mücennep sharp by 113.
* The remaining notes are quantised to quarter tones, and the `<alter>` is
  measured from the notated accidental rather than from the 12-TET letter, so
  even unaltered notes drift by up to 9.4 cents.

The practical consequence: **`xml_exp` is not "MusicXML at quarter-tone
resolution"**. It is MusicXML with roughly one note in sixteen placed in the
wrong semitone. Any pitch-sensitive result measured on it is confounded, and
the comparison against `gold53` is not measuring what it appears to.

### 2. Pitch-bend MIDI really does preserve 53-TET

At 99.5% exact and a 1.0-cent mean, the published MIDI is a faithful carrier of
the gold tuning — far better than its reputation as a "raw form … not for
listening". Where `midi_bend` underperforms in a representation comparison, the
cause is not tuning loss.

### 3. About 8% of the published MIDI files use a different anchor

Most are anchored on A, as the paper specifies. A minority are anchored on D,
leaving the whole file 1.89 cents sharp of the rest of the corpus — the exact
53-TET-vs-12-TET discrepancy of a perfect fourth. Inaudible, but it means the
MIDI corpus is not internally consistent. Pass `anchor=327` to reproduce those
files; `microtonal_score_converter`'s audit removes the per-score offset before comparing.

### 4. The published MIDI is not derived from the published txt

Note counts disagree for ~48% of scores. The `.txt` is linearised ("notes …
just as they are performed") while the `.mid` was rendered from the Mus2 source
with its own repeat handling, and `LNS` values occasionally differ between the
two. They are siblings, not a chain — so "the gold txt" and "the SymbTr MIDI"
are not two views of the same note sequence.

### 5. MuseScore 2.x plays everything in 12-TET

Not a SymbTr finding. Measured against MuseScore 2.3.2 by rendering to audio
and estimating each note's sounding f0. MuseScore 4.7 does not have this
problem: it plays the exact MusicXML correctly out of the box, and `retune` is
not needed for it.

| | max error |
|---|---|
| our MusicXML, opened in MuseScore | **65.2 cents** |
| the same score after `microtonal-score-converter retune` | **1.4 cents** (the estimator's own resolution) |

Two separate problems:

* **MuseScore ignores fractional `<alter>` for playback.** The value is read
  and used to pick a 12-TET pitch, and the microtone is dropped. There is
  nowhere in MusicXML to put a per-note tuning, so no MusicXML we could emit
  would fix this.
* **It truncates `<alter>` toward zero rather than rounding.** A 3-comma flat
  (`alter = -0.604`) is played as a *natural*, not a flat. So the lossless
  `precision="exact"` output is the *worst* choice for MuseScore — it misses by
  a semitone where `precision="12tet"` would at least pick the nearest one.

MuseScore's own answer to microtonality is `Note.tuning`, the per-note cent
offset in the Properties panel, stored natively as
`<Note><tuning>-35.85</tuning>`. `microtonal-score-converter retune` writes it into a `.mscz` or
`.mscx` that MuseScore 2.x saved:

```bash
microtonal-score-converter convert score.txt --to musicxml --precision 12tet -o out/
#   open out/score.xml in MuseScore 2.x, save as score.mscz
microtonal-score-converter retune score.txt score.mscz
```

```
notes retuned: 405 of 405 (18 tie continuations)
gold events matched: 387 of 387
largest tuning offset: 41.51 cents
```

Going through MuseScore's own importer rather than generating its native
format from scratch means tuplets, ties, lyrics, ornaments and layout are
handled by MuseScore; the only thing changed is the one thing it gets wrong.
The tuning is computed against **MuseScore's own `<pitch>`**, so even where it
truncated to the wrong semitone the sounding pitch comes out exact. Converting
with `--precision 12tet` first is still worth it: it puts MuseScore on the
right semitone, which halves the offsets (109 → 41.5 cents) and matters if you
later export MIDI from MuseScore 2.x, since **its MIDI export ignores
`tuning`** too.

Notes are matched to the gold score positionally, with the tie continuations
our MusicXML creates detected and folded back, and the result is checked: a
note needing more than 150 cents of correction means the file does not
correspond to the score, and `retune` refuses rather than quietly mis-tuning
it. Tested against MuseScore 2.3.2 end to end.

---

## The loss matrix

`microtonal-score-converter audit` round-trips a score through every configuration and reports
what came back. For the reference score (387 notes):

```
format     variant        pitch ok  mean c   max c  dur ok    bytes  lost
----------------------------------------------------------------------------
txt        source          100.0%    0.00    0.00 100.0%    19829  -
json       lossless        100.0%    0.00    0.00 100.0%   254491  -
midi       symbtr-bend     100.0%    0.00    0.01 100.0%     6226  performed_ms, ae_spelling, row_index
midi       24tet            14.0%    4.95   18.87 100.0%     5446  performed_ms, ae_spelling, row_index
midi       12tet            16.0%   10.36   37.74 100.0%     4978  performed_ms, ae_spelling, row_index
musicxml   exact53         100.0%    0.00    0.00 100.0%   133085  ae_spelling
musicxml   quartertone      15.5%    5.93   16.04 100.0%   122680  ae_spelling
musicxml   12tet            15.5%   10.60   39.62 100.0%   122465  ae_spelling
musicxml   diatonic53       15.5%    4.06    9.43 100.0%   123577  ae_spelling
abc        53tet           100.0%    0.00    0.00 100.0%     4099  performed_ms, ae_spelling, row_index
abc        24tet            15.5%    5.93   16.04 100.0%     2957  performed_ms, ae_spelling, row_index
abc        12tet            15.5%   10.60   39.62 100.0%     2789  performed_ms, ae_spelling, row_index
kern       koma-spine         n/a     n/a     n/a    n/a     5539  performed_ms, velocity, ae_spelling, row_index (declared)
tokens     gold53          100.0%    0.00    0.00 100.0%     3377  performed_ms, lyrics, ae_spelling, row_index
tokens     naive12          15.5%   10.60   39.62 100.0%     2893  performed_ms, lyrics, sections, usul_changes, ae_spelling, row_index
```

Two kinds of claim, kept apart on purpose:

* **Measured** — pitch and duration loss come from writing the score out,
  reading it back with the matching reader, and comparing note for note.
  Attribute retention is checked by looking for the attribute's content in the
  rendered output. No format is credited with preserving something that was not
  found.
* **Declared** — where there is no reader (Humdrum), the capability is stated
  in `DECLARED_SUPPORT` and the row is marked `(declared)` with `n/a` in the
  numeric columns, never mixed in with measured results.

Three representations are **exactly lossless for pitch**: ABC `53tet`,
MusicXML `exact`, and MIDI `symbtr` (to the 14-bit bend limit). ABC does it in
**4 KB where MusicXML needs 133 KB** — 32× smaller for identical pitch and
duration fidelity, which matters when the consumer is a language model paying
by the token.

---

## Targets

| Target | What it is | Options |
|---|---|---|
| `midi` | SMF with pitch bends | `convention` = `symbtr` / `bend-nearest` / `24tet` / `12tet`; `timing` = `symbolic` / `ms`; `anchor` |
| `musicxml` | MusicXML 3.1 partwise | `precision` = `exact` / `quartertone` / `12tet`; `reference` = `12tet` / `diatonic` |
| `abc` | ABC 2.2 with fractional accidentals | `mode` = `53tet` / `24tet` / `12tet`; `reference` |
| `kern` | Humdrum `**kern` + `**koma` + `**text` | `microtone_spine` = `koma` / `cents` / `none` |
| `tokens` | token streams for LM experiments | `preset`, or `pitch` × `duration` × `markers` |
| `json` | the full IR, lossless | `include_derived` |
| `txt` | SymbTr-txt itself | `offsets` = `source` / `exact` |

Plus `microtonal-score-converter retune`, which is not a target but a repair: it writes exact
per-note tuning into a `.mscz`/`.mscx` so MuseScore *plays* the microtones it
already *displays*.

### Notes on individual targets

**ABC.** The standard defines fractional accidentals — `^3/2c` raises C by one
and a half semitones, `^/2c` by a quarter tone — and both `abcm2ps` and
`abc2midi` implement them, so 53-TET survives as `^12/53`. The writer tracks
accidentals per bar (ABC carries them forward to the end of the measure) and
keeps a grace note's accidental out of that scope, as the standard requires.

**Humdrum.** `**kern` cannot spell a pitch between the twelve chromatic
degrees, and inventing an accidental would make the output unreadable to every
Humdrum tool. Humdrum's own answer is multi-spine: the conventional 12-TET
reading goes in `**kern`, the exact Holdrian comma in a parallel `**koma`
spine, the syllables in `**text`. Nothing is approximated away — the
approximation is confined to the spine where it belongs.

**Tokens.** A representation comparison needs its axes separated, or a
difference in accuracy cannot be attributed to anything. `pitch`
(`koma53`/`name53`/`nameAE`/`midi24`/`midi12`/`interval53`/`interval12`/`degree53`),
`duration` (`fraction`/`quarters`/`ms`/`none`) and `markers`
(`bar`/`phrase`/`section`/`usul`/`ornament`/`rest`) vary independently.
`PRESETS` pins down named points in that space so results stay comparable.

---

## What the IR keeps

Every column of the source survives, including the ones no target format can
express. Writers drop what they cannot carry and the audit measures it.

| | |
|---|---|
| `pitch53` / `pitchAE` | both spellings, with the exact comma value |
| `duration` | notated `Pay`/`Payda` as an exact rational |
| `ms` | performed duration, from which the tempo map is recovered |
| `lns` | legato/normal/staccato percentage |
| `velocity` | `Bas`, SymbTr's stand-in for the dynamics makam scores lack |
| `text` | syllabified lyrics, section headings, usul names — with significant trailing spaces |
| `code` | the full `Kod` vocabulary: ornaments, phrase marks, modulations, layout |
| `offset` | position in measures, exact |

### Things the format does not document

Working these out was most of the job, and they are the parts a reimplementation
gets wrong:

* **`Offset` is the position of the row's *end*, not its start,** and it counts
  *measures*, not whole notes. A 1/4 note at the top of a 9/8 measure carries
  `0.2222` = (1/4)/(9/8). Recomputing it from the durations reproduces the
  published values exactly.
* **`Pay`/`Payda` is overloaded.** On a note it is the duration; on a `Kod 51`
  usul row it is the *time signature*. Reading 9/8 off a usul row as a duration
  silently adds a whole measure to the piece.
* **There is no tempo column.** Tempo is recovered from `ms` via the paper's
  `ms = 240000/tempo × Pay/Payda`. Because `ms` is rounded to whole
  milliseconds the result wobbles by a fraction of a percent, so the tempo map
  needs a tolerance and one-note blips must be merged away. Rounding to the
  nearest integer BPM recovers the intended value (107.91 → 108).
* **Rests are identified by the `Es` spelling, not the comma,** which is `-1` in
  most files and `0` in older ones. A `Kod 51` row can also carry `Es`.
* **Grace notes have no duration at all** (`Pay`/`Payda` = 0/0). The code table
  says they take a 64th (below quarter = 90) or a 32nd from the following note;
  treating them as zero-length drops 12,588 notes from the corpus.
* **Three of the 2200 scores format integer offsets as `3` where the rest write
  `3.0`,** and one ends without a trailing newline. Round-tripping the *number*
  is not enough to round-trip the *file*.

---

## Layout

```
microtonal_score_converter/
  pitch.py       the 53-TET comma space; the one verified identity
  codes.py       the full SymbTr Kod vocabulary, from code_explanations.xlsx
  duration.py    Pay/Payda -> notated values, dots, tuplets, ties
  score.py       the IR: events in source order plus derived structure
  audit.py       the loss matrix, and the audit of SymbTr's own exports
  musescore.py   writing exact <tuning> into a MuseScore file
  cli.py         convert / audit / audit-published / info
  readers/       txt (gold), mu2 (metadata), filename, midi, musicxml, abc
  writers/       txt, midi, musicxml, abc, kern, tokens, jsonio
tests/           130 tests; corpus tests skip when SymbTr is not present
pyproject.toml   package metadata; dev deps in a PEP 735 dependency group
uv.lock          committed, so `uv sync` is reproducible
.python-version  3.12 for development; the package itself supports 3.8+
```

## Development

```bash
uv sync                      # .venv with the package installed editable
uv run pytest                # 130 tests, ~2 s
```

The `requires-python = ">=3.8"` claim is not a guess — uv makes checking it one
command per version, and all 130 tests pass on 3.8 through 3.14:

```bash
for v in 3.8 3.9 3.10 3.11 3.12 3.13 3.14; do
  echo -n "python $v: "; uv run --quiet --python "$v" pytest -q | tail -1
done
```

`uv.lock` is committed so the dev environment is reproducible; it pins only
pytest and its transitive dependencies, because the package itself has none.

The corpus tests look for a SymbTr checkout at `../SymbTr-master` and skip when
it is absent, so the suite runs anywhere without bundling the
dataset. Skips are reported (`-ra`) rather than hidden, so a green run against
no corpus is not mistaken for a full one.

## Credit

The SymbTr database and the `code_explanations.xlsx` code table are by
**M. Kemal Karaosmanoğlu**. The MIDI, MusicXML and Humdrum
conventions were worked out against the published corpus; the MusicXML
accidental glyph names follow the SymbTr→MusicXML converter in
[tomato](https://github.com/sertansenturk/tomato) by **Sertan Şentürk** so that
scores emitted here engrave like the official ones. The package has no runtime
dependencies, so it can also be embedded in tomato directly. No corpus data or
music-theory file is bundled — `microtonal_score_converter` loads them from whatever checkout
you point it at.

> Karaosmanoğlu, M. K. (2012). *A Turkish makam music symbolic database for
> music information retrieval: SymbTr.* ISMIR 2012, 223–228.
