# `gmo_inspect_v2.py`

`gmo_inspect_v2.py` is a standalone GMO analyzer. It is separate from the KPD tools and works directly on loose `.gmo` files or folders containing them.

## What It Does

The script:

- verifies the fixed GMO file header
- parses the internal GMO chunk tree
- labels chunks using the reviewed 3ds Max GMO importer source
- optionally decodes selected leaf payloads
- extracts printable ASCII strings
- assigns a coarse family classification
- emits either text output or JSON

It is an inspection tool, not a converter.

## Chunk Model

The current parser uses the chunk header model backed by the reviewed MaxScript source:

- `u16 chunk_id`
- `u16 args_offs`
- `u32 next_offs`
- full chunks then carry:
  - `u32 child_offs`
  - `u32 data_offs`

Working parser rules:

- `0x8000` in `chunk_id` marks a half-chunk
- half-chunks use the short header and inline payload
- full chunks may have an ASCII name between `+0x10` and `args_offs`
- container children are walked from `start + args_offs` to `start + next_offs`

## New In V2

Compared with the earlier version, `v2` adds payload decoding for a useful subset of chunk types.

Decoded payload families:

- `ARRAYS`
  - decodes `vertex_type`, `verts_count`, `morphs_count`, `format2`
  - interprets the vertex-format bitmask into texture/color/normal/position/weight formats
  - estimates record stride
  - previews a small number of decoded vertices
- `DRAW_ARRAYS`
  - decodes the referenced arrays triplet
  - decodes draw mode, sequential flag, vertex count, primitive count
  - shows either the sequential seed or a short primitive-index preview
- `FCURVE`
  - decodes curve type, value count, frame count
  - handles both float32 and float16 curves
  - previews a small number of frames
- `ANIMATE`
  - decodes block, type, index, and referenced fcurve
- `BOUNDING_BOX`
  - decodes min/max vectors
- `ARRAY_OFFSET`
  - decodes the observed offset payload variants
- `FILE_NAME`
  - decodes the embedded string
- `FILE_IMAGE`
  - reports declared size and embedded signature bytes
- selected transform/material/texture/helper leaves
  - examples: `TRANSLATE`, `ROTATE_Q`, `SET_MATERIAL`, `SET_TEXTURE`, `FRAME_LOOP`, `FRAME_RATE`, `BLIND_DATA`

When `--payloads` is enabled:

- text tree output appends short payload summaries to decoded leaves
- JSON output includes structured `payload` objects on decoded leaves

## Family Labels

The family labels are broad and descriptive:

- `mesh-bearing`
- `motion-only`
- `camera-helper`
- `locator-helper`
- `effect-helper`
- `bare-shell`
- `helper-or-unknown`

These are not official GMO type names. They are sample-backed inspection labels.

## Validation Summary

`v2` was checked against the current comparison and failed review sets:

- `102` total GMO files
- `4` `mesh-bearing`
- `49` `effect-helper`
- `45` `bare-shell`
- `2` `motion-only`
- `1` `camera-helper`
- `1` `locator-helper`

This matched the earlier working hypothesis: the comparison set contains ordinary mesh-bearing GMOs, while the flagged set is dominated by helper, shell, and motion-side variants.

## CLI Options

Core options:

- `--json`
- `--tree`
- `--tree-depth N`
- `--max-strings N`

New `v2` options:

- `--payloads`
  - decode selected leaf payloads and include them in the output
- `--preview-limit N`
  - limit preview items for variable-length payloads such as vertices, primitives, and fcurve frames

## Basic Usage

Text summary:

```powershell
python gmo_inspect_v2.py some_file.gmo
```

Tree with payload summaries:

```powershell
python gmo_inspect_v2.py ..\v2ComparisonFiles\b0090.gmo --tree --payloads --preview-limit 2 --max-strings 0
```

JSON for a whole directory:

```powershell
python gmo_inspect_v2.py ..\v2FailedFiles --json --payloads --preview-limit 1 --max-strings 0
```

## Current Limits

- It still does not fully reconstruct mesh topology or material semantics.
- Some decoded fields remain structural rather than fully semantic.
- `ARRAYS` decoding is based on the reviewed importer model and current sample validation; it should still be treated as a reverse-engineered interpretation.
- The family classifier is sample-driven and should not be treated as a universal validator for every GMO variant.
