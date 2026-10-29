# API reference

Generated from the package docstrings. Prefer the
[library guide](library.md) for a walkthrough; use this page for signatures
and parameter detail.

## Package exports

::: microtonal_score_converter
    options:
      members:
        - read_txt
        - parse_symbtr_name
        - Pitch
        - Score
        - Event
        - Metadata
        - notate
        - quantize
        - write_txt
        - write_json
        - write_midi
        - write_musicxml
        - write_abc
        - write_kern
        - write_tokens
        - audit_score
        - format_report
        - retune_file
        - retune_mscx
        - tuning_cents
      show_root_heading: false
      show_source: true

## Pitch model

::: microtonal_score_converter.pitch
    options:
      filters:
        - "!^_"
      show_source: false

## Intermediate representation

::: microtonal_score_converter.score
    options:
      members:
        - Event
        - Metadata
        - Score
        - UsulChange
        - TempoSegment
        - code_histogram
        - SECTION_HEADINGS
        - DEFAULT_LNS
      show_source: false

## Duration notation

::: microtonal_score_converter.duration
    options:
      filters:
        - "!^_"
      show_source: false

## Readers

::: microtonal_score_converter.readers.txt
    options:
      filters:
        - "!^_"
      show_source: false

::: microtonal_score_converter.readers.filename
    options:
      filters:
        - "!^_"
      show_source: false

::: microtonal_score_converter.readers.mu2
    options:
      filters:
        - "!^_"
      show_source: false

::: microtonal_score_converter.readers.midi
    options:
      filters:
        - "!^_"
      show_source: false

::: microtonal_score_converter.readers.musicxml
    options:
      filters:
        - "!^_"
      show_source: false

::: microtonal_score_converter.readers.abc
    options:
      filters:
        - "!^_"
      show_source: false

## Writers

::: microtonal_score_converter.writers.txt
    options:
      filters:
        - "!^_"
      show_source: false

::: microtonal_score_converter.writers.jsonio
    options:
      filters:
        - "!^_"
      show_source: false

::: microtonal_score_converter.writers.midi
    options:
      members:
        - write_midi
        - CONVENTIONS
        - TIMINGS
        - DEFAULT_TPQ
        - A4_KOMA
      show_source: false

::: microtonal_score_converter.writers.musicxml
    options:
      members:
        - write_musicxml
        - PRECISIONS
        - REFERENCES
      show_source: false

::: microtonal_score_converter.writers.abc
    options:
      members:
        - write_abc
        - MODES
        - REFERENCES
      show_source: false

::: microtonal_score_converter.writers.kern
    options:
      members:
        - write_kern
        - MICROTONE_SPINES
      show_source: false

::: microtonal_score_converter.writers.tokens
    options:
      members:
        - write_tokens
        - PRESETS
        - PITCH_ENCODINGS
        - DURATION_ENCODINGS
        - MARKERS
      show_source: false

## Audit

::: microtonal_score_converter.audit
    options:
      members:
        - audit_score
        - format_report
        - FormatReport
        - audit_published_midi
        - audit_published_musicxml
        - TOLERANCE_CENTS
        - ATTRIBUTES
        - DECLARED_SUPPORT
      show_source: false

## MuseScore retune

::: microtonal_score_converter.musescore
    options:
      members:
        - retune_file
        - retune_mscx
        - tuning_cents
        - RetuneReport
        - RetuneError
      show_source: false
