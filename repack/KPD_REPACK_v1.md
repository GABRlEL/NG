# KPD Repack v1

`kpd_repack_v1.py` is a conservative repacker for the supported PSP NG `0x50`-entry KPD flavor.

It is built on the `v4` parser model and is intentionally narrow:
- it preserves the metadata region up to `data_start`
- it only patches file entry `offset` and `size` fields
- it rebuilds the data region while preserving original segment order and original inter-segment gaps
- it writes a new archive file instead of patching in place

## Scope

Supported:
- flat KPDs
- hierarchical `ng-datapack` KPDs that parse cleanly under `pyKPDTool_rebuilt_v4.py`
- replacing existing files by name
- growing or shrinking file payloads
- built-in verification after rebuild

Not supported:
- adding new entries
- removing entries
- renaming entries
- archives that only work through normalized embedded-header extraction

If an entry has a normalization note, `kpd_repack_v1.py` refuses to repack it.

## Commands

List files:

```powershell
python kpd_repack_v1.py list some.kpd
```

Write the list to JSON:

```powershell
python kpd_repack_v1.py list some.kpd --json-out some_files.json
```

Repack with one replacement:

```powershell
python kpd_repack_v1.py repack some.kpd some_rebuilt.kpd --replace path/in/archive.ext=local_replacement.ext --verify
```

Repack with multiple replacements:

```powershell
python kpd_repack_v1.py repack some.kpd some_rebuilt.kpd ^
  --replace first.ext=mods\\first.ext ^
  --replace folder/second.ext=mods\\second.ext ^
  --verify ^
  --report-json rebuild_report.json
```

## Name Matching

`--replace` accepts the archive-side target as:
- the raw entry name
- the extracted output name
- a unique basename

If a basename is ambiguous, the tool refuses the replacement.

## Verification

With `--verify`, the tool:
- re-parses the rebuilt KPD
- checks that layout and entry set still match
- checks that every unchanged file payload is byte-identical
- checks that every replaced file payload matches the replacement bytes exactly
- checks that header `file_size` and `data_size` match the actual rebuilt file

## Notes

- `--allow-warnings` exists, but the safe default is to leave it off.
- `--overwrite` only controls whether an existing output KPD may be replaced.
- Replacement payload validity is not interpreted by format. The tool only guarantees archive-structure correctness within its supported scope.
