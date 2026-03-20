# Index Validator

`index_validate_v2.py` checks extracted output against the cleaned index tables in [Index/List](c:\Users\Gabriel\Downloads\KPD\Index\List).

It validates names only:

- expected names come from the `.txt` index files
- actual names come from the better-fitting view of an extracted folder:
  - direct child names
  - or recursive file basenames for containers that were exported into helper subfolders like `msg/` or `ana/`
- it reports missing names, unexpected names, and unresolved index-to-folder matches

It does not parse KPD data or verify file bytes.

## Input Format

The index files in [Index/List](c:\Users\Gabriel\Downloads\KPD\Index\List) follow the community leader's cleaned format from [indexwriteup.txt](c:\Users\Gabriel\Downloads\KPD\Index\indexwriteup.txt):

- one expected entry name per line
- blank lines are ignored
- leading `✅` / `❌` markers are ignored if present
- in the index filename, every double underscore `__` acts like a directory divider

Examples:

- `DATAPACK.KPD.txt`
- `DATAPACK.KPD__pkdata__dance.txt`
- `DATAPACK.KPD__pkdata__battleevent__00_01_004_01_p00pack.txt`

## Simple Usage

Validate one extracted folder against one index file:

```powershell
python index_validate_v2.py verify_v2_dance_raw --index DATAPACK.KPD__pkdata__dance.txt
```

Validate one extracted folder against one full path index file:

```powershell
python index_validate_v2.py review_battleevent_extract --index Index\List\DATAPACK.KPD__pkdata__battleevent__00_01_004_01_p00pack.txt
```

Validate an export tree against the whole index directory:

```powershell
python index_validate_v2.py path\to\export_root
```

By default the tool uses [Index/List](c:\Users\Gabriel\Downloads\KPD\Index\List) as the index root.

## Output

For each failing or unresolved entry, the tool prints:

- the index file name
- the matched extracted directory, if any
- missing count
- unexpected count

At the end it prints a summary line.

Exit code behavior:

- `0`: all checked index sets matched, with no missing names
- `1`: at least one set is unresolved or has missing names
- `2`: bad command usage, missing directories, or invalid input path

Unexpected names are reported but do not fail the exit code unless `--strict-unexpected` is used.

## Helpful Options

- `--index-root <dir>`: use a different index directory
- `--index <file>`: validate a single index file against the given extracted folder
- `--json-out <file>`: write a JSON report
- `--strict-unexpected`: make extra names fail validation
- `--skip-folder-entries`: ignore folder-style index entries, using only file-like lines with a dot
- `--show-ok`: print successful matches too
- `--verbose`: print full missing/unexpected name lists

Example with JSON output:

```powershell
python index_validate_v2.py verify_v2_dance_raw --index DATAPACK.KPD__pkdata__dance.txt --json-out dance_index_report.json --verbose
```

Example for older-style flattened exports:

```powershell
python index_validate_v2.py path\to\export_root --skip-folder-entries --json-out flattened_report.json
```

## Matching Rules

In full-tree mode, the tool tries to match each index file to an extracted folder automatically.

It does that by:

- splitting the index filename on `__`
- treating those pieces as a container path
- checking suffix matches against directories under the export root
- falling back to the export root itself only when needed

This is meant to handle layouts like:

- `DATAPACK.KPD/pkdata/dance`
- `pkdata/dance`
- `dance`

And once a folder is matched, it can validate either:

- the direct child names in that folder
- or the recursive file basenames under that folder, whichever fits the index better

In `--skip-folder-entries` mode, the validator ignores folder-style index lines using a simple heuristic:

- if a cleaned line has no `.` in its basename, it is treated as a folder entry and skipped

This is intended for temporary comparison against flatter extraction layouts, especially while verifying whether all files were exported at all.

The single-index mode is simpler and more reliable when you already know which extracted folder should match which index file.
