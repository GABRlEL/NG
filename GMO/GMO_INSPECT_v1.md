# `gmo_inspect.py`

`gmo_inspect.py` is a standalone GMO analyzer. It is separate from the KPD toolchain and works directly on loose `.gmo` files or directories containing them.

## What It Does

The script:

- verifies the fixed GMO file header
- parses the internal GMO chunk tree
- reports chunk IDs, names, offsets, and nesting
- extracts printable ASCII strings
- applies a coarse family classification to each file
- can emit either text output or JSON

It is meant for inspection and reverse engineering, not conversion.

## What It Assumes

The current parser is based on sample-backed findings from:

- checked GMO files in this workspace
- the reviewed 3ds Max GMO importer source in [GmoFunctions.ms](c:\Users\Gabriel\Downloads\KPD\GMOResearch\GMOImport3dsmax\include\GmoFunctions.ms) and [GmoStructs.ms](c:\Users\Gabriel\Downloads\KPD\GMOResearch\GMOImport3dsmax\include\GmoStructs.ms)

The working chunk header model is:

- `u16 chunk_id`
- `u16 args_offs`
- `u32 next_offs`
- full chunks then carry:
  - `u32 child_offs`
  - `u32 data_offs`

Current parser rules:

- `0x8000` in `chunk_id` means a half-chunk
- half-chunks use only the short header and inline payload
- full chunks may have a fixed-length ASCII name between `+0x10` and `args_offs`
- child parsing starts at `start + args_offs`
- `next_offs` is the span to the next sibling

## What It Reports

For each file, the script reports:

- path
- file size
- GMO magic
- whether the top-level GMO header is internally consistent
- chunk counts by base chunk ID
- a chunk tree, if requested
- extracted strings, if requested
- a coarse family label

## Family Labels

The family labels are intentionally broad:

- `mesh-bearing`
- `motion-only`
- `camera-helper`
- `locator-helper`
- `effect-helper`
- `bare-shell`
- `helper-or-unknown`

These labels are based on chunk families and string markers seen in the checked sample set. They are descriptive, not official format names.

## Current Strengths

- It distinguishes mesh-bearing comparison GMOs from the flagged helper/motion families in the current sample set.
- It uses the reviewed GMO chunk header model rather than a string-only heuristic.
- It is useful for checking whether a GMO actually contains mesh/material/image-side structures.

## Current Limits

- It does not fully decode payloads for `ARRAYS`, `DRAW_ARRAYS`, `FCURVE`, material parameters, or texture/image data.
- Some chunk semantics are still provisional beyond the chunk names taken from the reviewed importer source.
- The family classifier is conservative and sample-driven; it is not a universal validator for every GMO variant.

## Basic Usage

Text output:

```powershell
python gmo_inspect.py some_file.gmo
python gmo_inspect.py v2ComparisonFiles --tree
```

JSON output:

```powershell
python gmo_inspect.py v2FailedFiles --json --max-strings 0
```

Focused tree view:

```powershell
python gmo_inspect.py v2FailedFiles\\cam.gmo --tree --tree-depth 3
```
