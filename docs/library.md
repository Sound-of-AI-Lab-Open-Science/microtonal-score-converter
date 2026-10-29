# Library guide

Use `microtonal_score_converter` as a Python library: read SymbTr-txt into an
intermediate representation (IR), inspect it, write other formats, and measure
what each format loses.

Install editable (or use the existing `.venv`):

```bash
uv sync
# or: pip install -e .
```

```python
from microtonal_score_converter import read_txt, write_abc, Score
```

Everything below is exported from the package root unless noted. The full
public list is `__all__` in `microtonal_score_converter/__init__.py`.

---

## Pipeline

```
SymbTr-txt ──read_txt──► Score (IR) ──write_*──► midi / musicxml / abc / …
                              │
                              └──audit_score──► loss matrix
```

Writers never mutate the `Score`. Most return a `str` (or `bytes` for MIDI);
pass `path=` to also write a file.

---

## Reading

```python
from microtonal_score_converter import read_txt, parse_symbtr_name

score = read_txt("path/to/score.txt")                 # loads sibling .mu2 if found
score = read_txt("path/to/score.txt", use_mu2=False)  # txt only
score = read_txt("score.txt", mu2_path="other.mu2")   # explicit metadata
```

`parse_symbtr_name(path_or_name)` splits a SymbTr filename into
`makam` / `form` / `usul` / `title` / `composer` (and optional `variant`).

Round-trip *verification* readers for written output live under
`microtonal_score_converter.readers` (`read_midi`, `read_musicxml`, `read_abc`)
and are not re-exported at the package root — they return lightweight note
lists for audit, not a full `Score`.

---

## The IR: `Score`, `Event`, `Pitch`

### `Score`

| Attribute / method | Meaning |
|---|---|
| `events` | All rows in source order (never merged) |
| `metadata` | Filename + optional `.mu2` fields |
| `warnings` | Parse-time notes |
| `notes` | Pitched events (grace included) |
| `sounding` | Notes, rests, graces |
| `usul_changes` | `Kod 51` metre rows |
| `phrase_boundaries` | Offsets of `Kod 53` |
| `sections` / `modulations` | Headings and gecki markers |
| `lyrics` | Syllables reassembled (trailing spaces matter) |
| `tempo` / `tempo_map()` | Recovered from `Ms` |
| `duration_ms` | Sum of performed durations |
| `measures()` | Sounding events grouped by `Offset` bar index |
| `summary()` | One-line diagnostic |

```python
print(score.metadata.makam, score.metadata.usul)
print(len(score.notes), "notes in", len(score.measures()), "measures")
for event in score.notes[:3]:
    print(event.pitch53.name, event.pitch53.koma, event.duration)
```

### `Event` (one SymbTr row)

| Field | SymbTr column |
|---|---|
| `index` | `Sira` |
| `code` | `Kod` |
| `pitch53` / `pitchAE` | `Nota53` / `NotaAE` as `Pitch` |
| `numerator` / `denominator` | `Pay` / `Payda` |
| `ms`, `lns`, `velocity`, `text` | `Ms`, `LNS`, `Bas`, `Soz1` |
| `offset` / `offset_end` | start (derived) / end (file `Offset`) |

Useful flags: `is_note`, `is_rest`, `is_grace`, `sounds`, `ornament`,
`articulation` (`legato` / `normal` / `staccato` from `LNS`),
`duration` / `quarters` (whole notes / quarters; **0** on usul and grace rows).

### `Pitch`

Anchored at `Do4` / `C4` = comma **265** = MIDI **60**:

```
koma = 265 + 53·(octave − 4) + degree[letter] + alteration
midi = koma · 12/53
```

```python
from microtonal_score_converter import Pitch, quantize

p = Pitch.parse("Mi5b3")
assert p.koma == 333
assert float(p.midi) == 333 * 12 / 53
print(p.name, p.cents, p.hz())
print(quantize(p.koma, 12))   # nearest 12-TET MIDI step
```

Letter-based formats must carry the distance from the **12-TET letter**, not
only the written accidental — that is `reference="12tet"` on MusicXML/ABC.
See the README pitch model for why.

---

## Writing

Every writer: `write_*(score, path=None, **options) -> str | bytes`.

| Function | Returns | Key options (defaults) |
|---|---|---|
| `write_txt` | `str` | `offsets="source"` \| `"exact"` |
| `write_json` | `str` | `include_derived=False`, `indent=2` |
| `write_midi` | `bytes` | `convention="symbtr"`, `timing="symbolic"`, `anchor=305` |
| `write_musicxml` | `str` | `precision="exact"`, `reference="12tet"` |
| `write_abc` | `str` | `mode="53tet"`, `reference="12tet"` |
| `write_kern` | `str` | `microtone_spine="koma"` \| `"cents"` \| `"none"` |
| `write_tokens` | `str` | `preset=...` or `pitch` × `duration` × `markers` |

### MIDI (`convention`)

| Value | Behaviour |
|---|---|
| `symbtr` | Published SymbTr pitch-bend convention (A-anchored); default |
| `bend-nearest` | Exact pitch; base note = nearest semitone |
| `24tet` / `12tet` | Deliberately lossy baselines |

`timing="symbolic"` uses `Pay`/`Payda` at 480 TPQ; `timing="ms"` uses
performed milliseconds. `anchor=305` is A4 in commas; pass `327` for the
minority of published files anchored on D.

### MusicXML (`precision`, `reference`)

| `precision` | Tuning resolution |
|---|---|
| `exact` | Fractional `<alter>` in 53-TET (lossless) |
| `quartertone` | Quantised to 24-TET |
| `12tet` | Nearest semitone (needed before MuseScore 2.x `retune`) |

| `reference` | What `<alter>` measures from |
|---|---|
| `12tet` | Distance from the 12-TET letter (exact sounding pitch) |
| `diatonic` | Written accidental only (prettier, up to ~9.4¢ error on naturals) |

### ABC (`mode`)

`53tet` (lossless fractional accidentals), `24tet`, or `12tet`. Same
`reference` choice as MusicXML.

### Tokens

Axes are independent; `preset` overrides them:

| Preset | Pitch | Duration | Markers |
|---|---|---|---|
| `gold53` | `koma53` | `fraction` | bar, phrase, section, usul, ornament, rest |
| `gold53_plain` | `koma53` | `fraction` | bar, rest |
| `naive12` | `midi12` | `fraction` | bar, rest |
| `contour53` | `interval53` | `fraction` | bar, rest |
| … | see `writers.tokens.PRESETS` | | |

```python
from microtonal_score_converter import write_tokens

stream = write_tokens(score, preset="gold53")
stream = write_tokens(score, pitch="koma53", duration="ms", markers=("bar", "rest"))
```

### JSON

Lossless IR dump. `include_derived=True` adds tempo map / measure count / etc.
Reload with `microtonal_score_converter.writers.jsonio.read_json` /
`score_from_dict`.

---

## Audit

```python
from microtonal_score_converter import audit_score, format_report

reports = audit_score(score)          # write → read → compare per config
print(format_report(reports))
for r in reports:
    if r.format == "abc" and r.variant == "53tet":
        print(r.pitch_ok, r.mean_cents, r.lost)
```

Pitch/duration columns are **measured** (round-trip). Humdrum rows are
**declared** (no reader) and marked `(declared)` in the table. Attribute
retention is probed in the rendered text — formats are not credited for
content that was not found.

---

## MuseScore retune

MuseScore 4.7 plays exact MusicXML correctly. MuseScore 2.x ignores fractional
`<alter>` for playback; write 12-TET MusicXML, open/save as `.mscz`, then:

```python
from microtonal_score_converter import read_txt, retune_file, tuning_cents

score = read_txt("score.txt")
report = retune_file("score.mscz", score, output_path="score-retuned.mscz")
print(report)   # notes retuned, largest offset, …
```

`tuning_cents(pitch)` is the per-note offset written into `<tuning>`.
`strict=True` (default) refuses files that need more than 150¢ correction
(likely a mismatched score).

---

## Minimal end-to-end

```python
from pathlib import Path
from microtonal_score_converter import (
    read_txt, write_midi, write_musicxml, write_abc, write_json,
    audit_score, format_report,
)

src = Path("beyati--sarki--aksak--karsidan_yar--dede_efendi.txt")
score = read_txt(str(src), use_mu2=False)
out = Path("out")
out.mkdir(exist_ok=True)

write_midi(score, path=str(out / (src.stem + ".mid")))
write_musicxml(score, path=str(out / (src.stem + ".xml")))
write_abc(score, path=str(out / (src.stem + ".abc")), mode="53tet")
write_json(score, path=str(out / (src.stem + ".json")))

print(score.summary())
print(format_report(audit_score(score)))
```

---

## Related docs

- Repository root `README.md` — CLI, pitch model, corpus findings, loss matrix
- [API reference](api.md) — generated from docstrings (`uv sync --group docs`
  then `uv run --group docs mkdocs serve`)
