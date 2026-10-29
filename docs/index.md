# microtonal-score-converter

Convert **SymbTr-txt** — the gold 53-TET representation of Ottoman-Turkish
makam music — into MIDI, MusicXML, ABC, Humdrum, tokens and JSON, and measure
what each format loses.

| Doc | What it is |
|---|---|
| [Library guide](library.md) | How to use the package from Python |
| [API reference](api.md) | Generated from docstrings |
| README (repository root) | CLI, pitch model, corpus findings |

```python
from microtonal_score_converter import read_txt, write_abc, audit_score, format_report

score = read_txt("beyati--sarki--aksak--karsidan_yar--dede_efendi.txt")
print(write_abc(score, mode="53tet"))
print(format_report(audit_score(score)))
```

```bash
uv sync --group docs
uv run --group docs mkdocs serve
```
