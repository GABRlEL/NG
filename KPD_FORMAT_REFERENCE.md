# KPD Format Reference

This document records sample-backed facts about the `DPLK` / `KPD` archive format seen in `psp_ng_DATAPACK.KPD`.

Sources used:

- direct binary inspection of `psp_ng_DATAPACK.KPD`
- static analysis of `pyKPDTool.pysrc.txt`
- validation against the rebuilt manifest and extracted sample files

This note avoids tool-to-tool comparison and focuses on format facts, parser rules, and embedded-format observations.

## Scope

The statements below are high-confidence for the provided PSP NG sample:

- archive magic `DPLK`
- version `0x00000100`
- entry size `0x50`
- sector alignment `0x800`
- hierarchical child-pool alignment is not globally fixed across all checked nested KPDs

Other KPD variants may exist and should be rechecked separately.

## Archive-Level Layout

For `psp_ng_DATAPACK.KPD`:

- file size: `0x11EE8000` (`300,843,008`)
- data region start: `0x76800`
- data region size: `0x11E71800`
- `data_start + data_size = file_size`

Observed top-level layout:

| Range | Meaning |
| --- | --- |
| `0x0000-0x07FF` | main archive header |
| `0x0800-0x0FFF` | secondary structured block |
| `0x1000-0x1AEF` | root entry table |
| `0x1AF0-0x767FF` | additional entry runs and structured metadata |
| `0x76800-EOF` | file data region |

## Main Header

The sample reads cleanly as a header with `u64`-spaced fields:

| Offset | Type | Value in sample | Notes |
| --- | --- | --- | --- |
| `0x00` | `char[4]` | `DPLK` | archive magic |
| `0x04` | `u32` | `0x00000100` | version |
| `0x08` | `u32` | `0x11EE8000` | file size low 32 bits |
| `0x10` | `u64` | `0x800` | alignment-related |
| `0x18` | `u64` | `0x800` | alignment-related |
| `0x20` | `u64` | `0x76000` | exact meaning unresolved |
| `0x28` | `u64` | `0x76800` | data region start |
| `0x30` | `u64` | `0x11E71800` | data region size |

Notes:

- valid entry records continue past `0x76000` and still end before `0x76800`
- `0x20` is therefore not a strict "last populated index byte" marker in this sample

## Entry Record

Each entry record is `0x50` bytes.

| Offset | Type | Meaning |
| --- | --- | --- |
| `0x00` | `u32` | entry type |
| `0x04` | `u32` | always `0` in this sample |
| `0x08` | `u64` | stored offset |
| `0x10` | `u64` | stored size |
| `0x18` | `u16` | `0xFFFF` in this sample |
| `0x1A` | `char[0x36]` | ASCII name/path, NUL-padded |

Observed entry types:

- `0`: directory or storage-pool entry
- `1`: file entry

Observed name behavior:

- names are ASCII
- names may be plain basenames such as `emotion.ana`
- names may also contain slashes such as `battleevent/00_00_000_01_p00pack.kpd`

Alignment facts:

- all observed stored offsets are `0x800` aligned
- all observed directory sizes are `0x800` aligned
- file sizes are not generally `0x800` aligned

These three alignment facts hold for the outer `psp_ng_DATAPACK.KPD` sample.

Checked nested hierarchical KPDs can use smaller child-pool spacing and smaller stored offsets, commonly `0x10` aligned rather than `0x800` aligned.

## Index Organization

The sample index is fragmented into many short runs of contiguous `0x50`-byte entries.

Confirmed properties:

- each entry begins on a `0x10` boundary
- contiguous entries form runs
- the root run begins at `0x1000`

Observed counts in this sample:

- directory entries: `39`
- file entries: `2369`
- total entries: `2408`
- total runs before the data area: `439`
- singleton runs: `189`

Singleton runs are normal metadata, not noise.

## Root Table and Metadata Pools

The first run at `0x1000` is a root table of `35` directory/storage-pool entries.

Its `offset/size` pairs map onto later metadata ranges rather than directly to file data. Example mappings:

- `ana`: `offset=0x0`, `size=0x1000` -> metadata `0x2800-0x37FF`
- `battle`: `offset=0x1000`, `size=0x8000` -> metadata `0x3800-0xB7FF`
- `bgm`: `offset=0x9800`, `size=0x1800` -> metadata `0xC000-0xD7FF`

In this sample, the root table is best understood as a table of metadata pools or storage buckets.

Practical consequences:

- root entry names are not a direct visible path tree
- visible path prefixes do not always correspond to root buckets
- for example, many `battleevent/*.kpd` and `script/*.kpd` files live inside the `pkdata` pool

## Data-Pool Resolution

For this sample, file stored offsets are relative to pool bases, not absolute file positions.

Resolved physical location rule:

- `physical_offset = pool_base + offset_stored`

When the correct pool base is used, stored offsets land directly on valid file headers.

### Verified top-level pool bases

| Pool | Metadata Range | Verified Data Base | Files |
| --- | --- | --- | --- |
| `ana` | `0x2800-0x3800` | `0x76800` | `7` |
| `battle` | `0x3800-0xB800` | `0x110800` | `322` |
| `bgm` | `0xC000-0xD800` | `0x76F800` | `27` |
| `cam` | `0xD800-0xE800` | `0x195E800` | `1` |
| `char` | `0xE800-0x22800` | `0x195F000` | `713` |
| `chardata` | `0x22800-0x23800` | `0x35D1000` | `4` |
| `dance` | `0x23800-0x24800` | `0x35D5800` | `21` |
| `dlc` | `0x25000-0x27000` | `0x37C3000` | `1` file plus `1` nested dir |
| `im` | `0x28000-0x29000` | `0x37D9800` | `5` |
| `install` | `0x29000-0x2A000` | `0x398C800` | `1` |
| `mapdata` | `0x2B000-0x2D000` | `0x39B0000` | `65` |
| `menucommon` | `0x2D800-0x2E800` | `0x3B16000` | `1` |
| `msg` | `0x2F000-0x31000` | `0x3B1F000` | `54` |
| `pkdata` | `0x32000-0x3B800` | `0x3B3B800` | `349` |
| `save` | `0x3B800-0x3C800` | `0xFBC4000` | `8` |
| `se` | `0x3D000-0x3E000` | `0xFC7B800` | `6` |
| `voice` | `0x45000-0x77000` | `0xFDB5000` | `774` |

### `voice`

The `voice` pool resolves cleanly with base `0xFDB5000`.

With that base:

- all `774` `voice` `.at3` files validate as `RIFF ... WAVEfmt `
- the pool layout closes cleanly near the end of the archive

### `staffroll`

`staffroll` is internally split into sub-pools rather than behaving as one flat pool.

Observed working sub-bases:

- `root/staffroll/2d` -> `en_logo.ana` at `0xFDA2800`
- `root/staffroll/bin` -> `staffroll_00.bin` at `0xFDAB000`
- `root/staffroll/msg` -> `msg_staffroll*.mwm` at `0xFDAF000`

## Hierarchical Child-Pool Alignment

Hierarchical KPDs do not all space sibling child pools with the same alignment.

For the checked sample set, the working rule is:

- compute child-pool spans from the node contents
- sequence sibling child pools using a child-pool alignment that matches the archive header's `data_size`

Observed working child-pool alignments:

- `0x800`: outer `psp_ng_DATAPACK.KPD`, plus checked nested archives such as `submission13.kpd` through `submission66.kpd`
- `0x10`: checked nested hierarchical archives such as `menu.kpd`, `staffroll.kpd`, `ndch.kpd`, `dance.kpd`, `mapcommon.kpd`, `first_read_00.kpd`, checked `battleevent/*.kpd`, checked `st09_*.kpd`, and checked `tansaku_00_st*.kpd`

For the four main previously suspicious nested archives:

| Archive | Working child-pool alignment | Result |
| --- | --- | --- |
| `menu.kpd` | `0x10` | `msg_mainmenu_00.mwm`, `msg_missionmenu_00.mwm`, and `msg_talent_00.mwm` start at `MWMS` |
| `staffroll.kpd` | `0x10` | `msg_staffroll*.mwm` and nested `staffroll_00.bin` start at their expected headers |
| `ndch.kpd` | `0x10` | `fl001.gmo`, `fl002.gmo`, `msg_ndchdialog*.mwm`, `nendochi.pbd`, and `nendochi.phd` start at expected headers |
| `dance.kpd` | `0x10` | `da000.gmo`, `da001.gmo`, `da002.gmo`, `msg_*.mwm`, `dance.pbd`, and `dance.phd` start at expected headers |

Practical consequence:

- late embedded `MWMS` or `OMG.00.1PSP` headers inside extracted nested files are not, by themselves, evidence that the file format is layered or that an extra normalization pass is required
- in the checked `menu`, `staffroll`, `ndch`, `dance`, `mapcommon`, and `first_read_00` cases, those late headers were caused by using the wrong child-pool alignment

This alignment rule also explains the reviewed `FailedFiles` set cleanly:

- `202` flagged review files were checked against the corrected model
- `0` remained unresolved as KPD offset-model problems

## Tree and Path Observations

Observed path facts:

- nested `.kpd` files are common: `349` confirmed entries
- file paths may be stored directly in entry names
- some top-level buckets are empty in practice, while other buckets contain many nested subtrees

## Verified File Signatures

These signatures were validated against the resolved physical offsets in the sample:

| Extension | Verified Count | Header |
| --- | --- | --- |
| `.ana` | `30/30` | `@ANA ` |
| `.gmo` | `710/710` | `OMG.00.1PSP` |
| `.gim` | `68/68` | `MIG.00.1PSP` |
| `.at3` | `801/801` | `RIFF .... WAVEfmt ` |
| `.lbn` | `69/69` | `1B 4C 75 61 51 00 01 04 04 04 08 00 00 00 00 00` |
| `.mwm` | `65/65` | `MWMS 00 00 01 00 14 00 00 00` |
| `.png` | `8/8` | standard PNG header |
| `.phd` | `4/4` | `PPHD8 00 00 00 00 00 01 00` |
| `.kpd` | `349/349` | `DPLK 00 01 00 00` |
| `.efa` | `31/31` | `45 46 41 00` (`EFA\\0`) |
| `.bin` | `1/1` | `53 54 46 52 00 00 01 00 14 00 00 00` (`STFR`) |

## BIN Format Observations

The `.bin` extension is not one uniform format.

Observed `.bin` families:

- `STFR`: top-level `staffroll_00.bin`
- `MOTC`: nested `eventmotionconvtable_00.bin` and `eventseconvtable_00.bin` inside `tansaku_00_st02.kpd`
- additional `0x14`-header `.bin` families inside `first_read_00.kpd`

Shared observed prefix across the checked magic-bearing `.bin` families:

| Offset | Type | Observed value |
| --- | --- | --- |
| `0x00` | `char[4]` | family-specific magic (`STFR` or `MOTC`) |
| `0x04` | `u32` | `0x00000100` |
| `0x08` | `u32` | `0x14` |

### `STFR`

Observed header for `staffroll_00.bin`:

| Offset | Type | Value |
| --- | --- | --- |
| `0x00` | `char[4]` | `STFR` |
| `0x04` | `u32` | `0x00000100` |
| `0x08` | `u32` | `0x14` |
| `0x0C` | `u32` | `0x16C` |
| `0x10` | `u32` | `0x2C` |

Observed size relation:

- `0x14 + 0x16C * 0x2C = 0x3EA4`
- that exactly matches the file size

This strongly indicates:

- `u32` at `0x0C` is a record count in this sample
- `u32` at `0x10` is a record stride in this sample
- the file is a `0x14`-byte header followed by `364` fixed-size records of `0x2C` bytes each

Observed record-table facts:

- record `i` starts at `0x14 + i * 0x2C`
- the `u32` at record offset `+0x00` equals the record index in `364/364` records
- record offset `+0x04` is `0` in `364/364` records
- record offsets `+0x08` and `+0x20` only take values `0` or `1`
- `0xFFFFFFFF` is universal at record offset `+0x28`
- `0xFFFFFFFF` appears at record offset `+0x14` in `363/364` records
- record offsets `+0x18` and `+0x1C` behave like floats and draw from small value sets

Observed ordering pattern:

- record offset `+0x0C` behaves like a section ID
- section IDs are almost entirely `0, 1, 2, 3, 4, 5, 6`, with one sentinel record using `0xFFFFFFFF`
- these section IDs appear in ascending contiguous bands through the file
- record offset `+0x10` behaves like a per-section sequence index
- within each normal section band, the sequence runs from `0` up to `count - 1`

Observed section bands:

| Section ID | Record Count | Record Index Range | Sequence Range |
| --- | --- | --- | --- |
| `0` | `70` | `0-69` | `0-69` |
| `1` | `44` | `70-114` | `0-43` |
| `2` | `28` | `115-142` | `0-27` |
| `3` | `46` | `143-188` | `0-45` |
| `4` | `76` | `189-264` | `0-75` |
| `5` | `38` | `265-302` | `0-37` |
| `6` | `61` | `303-363` | `0-60` |

The one sentinel record appears at record index `71` and uses `0xFFFFFFFF` for both the section-like and sequence-like fields.

Observed linkage to numbered `staffroll` message files:

- the numbered message files are `msg_staffroll00_00.mwm` through `msg_staffroll06_00.mwm`
- for those seven files, `u32` at `0x0C` matches the `STFR` section count exactly
- the `STFR` sequence field at record offset `+0x10` spans the same `0..count-1` range as the entry indices in the corresponding `.mwm`
- the best current model is that `STFR` references staffroll message entries by `(section_id, sequence_index)`

Exact sample-backed section mapping:

| STFR section ID | Numbered message file | `.mwm` count at `0x0C` |
| --- | --- | --- |
| `0` | `msg_staffroll00_00.mwm` | `70` |
| `1` | `msg_staffroll01_00.mwm` | `44` |
| `2` | `msg_staffroll02_00.mwm` | `28` |
| `3` | `msg_staffroll03_00.mwm` | `46` |
| `4` | `msg_staffroll04_00.mwm` | `76` |
| `5` | `msg_staffroll05_00.mwm` | `38` |
| `6` | `msg_staffroll06_00.mwm` | `61` |

Observed staffroll `.mwm` structure:

| Offset | Type | Meaning |
| --- | --- | --- |
| `0x00` | `char[4]` | `MWMS` |
| `0x04` | `u32` | `0x00000100` |
| `0x08` | `u32` | `0x14` |
| `0x0C` | `u32` | entry count |
| `0x14` | `count * 0x10` bytes | entry table |
| after table | variable | UTF-16LE text payload |

Observed numbered-`MWM` entry layout:

| Relative Offset | Type | Meaning |
| --- | --- | --- |
| `+0x00` | `u32` | entry index |
| `+0x04` | `u32` | `0` in checked staffroll samples |
| `+0x08` | `u32` | UTF-16LE byte length |
| `+0x0C` | `u32` | payload-relative text offset |

Observed numbered-`MWM` facts:

- entry indices are consecutive `0..count-1`
- the text area begins at `0x14 + count * 0x10`
- the stored text offsets are relative to that text-area base
- the decoded payload is UTF-16LE staff-roll text

Separate observed file:

- `msg_staffroll_system_00.mwm` uses the same `MWMS` family header but has count `1`
- a direct field-level link between that file and the lone `STFR` sentinel record is not yet proven

Other repeated field behavior:

- most records use `240.0` at record offset `+0x1C`
- ten near-terminal records in section `6` use `16.0` at record offset `+0x1C`, `0` at record offset `+0x20`, and group `3` at record offset `+0x24`
- most records use `1` at record offset `+0x20`

This suggests `STFR` is an ordered layout table with sectioned entries rather than a free-form binary blob.

The file appears to be a structured table rather than an arbitrary binary blob.

### `MOTC`

Observed nested `MOTC` samples:

- `eventmotionconvtable_00.bin`
- `eventseconvtable_00.bin`

Both checked samples share the same header layout:

| Offset | Type | Value in both samples |
| --- | --- | --- |
| `0x00` | `char[4]` | `MOTC` |
| `0x04` | `u32` | `0x00000100` |
| `0x08` | `u32` | `0x14` |
| `0x0C` | `u32` | `0x1` |
| `0x10` | `u32` | `0x308` |
| total size | `u32` | `0x340` |

Observed structural facts:

- both files use `u32` at `0x10 = 0x308`
- in both checked samples, `0x14 + 0x308 + 0x24 = file_size`
- the trailing `0x24` bytes are all zero padding
- the declared body is exactly `194` little-endian `u32` words
- in both samples, the first two body words are `0`

Checked body patterns:

- `eventmotionconvtable_00.bin`: `2` zero words followed by `192` words of `0xFFFFFFFF`
- `eventseconvtable_00.bin`: `2` zero words, then `128` words of `0x00FF00FF`, then `64` words of `0xFFFFFFFF`

This makes `MOTC` look like a small fixed-length word-table format rather than generic packed binary.

So far, `.bin` is best treated as a family of magic-bearing table formats rather than a single generic container.

### Additional `0x14`-Header `.bin` Families

Corrected extraction of nested `first_read_00.kpd` reveals a broader family of structured `.bin` files.

Across `52/52` checked `.bin` files in that archive:

- bytes `0x04-0x07` are `0x00000100`
- bytes `0x08-0x0B` are `0x14`
- bytes `0x00-0x03` are four ASCII uppercase/digit/underscore characters

Observed example magics:

- `BGMC`
- `CHRT`
- `ENMY`
- `EQST`
- `BVFT`
- `ASKL`

Observed example headers:

| File | Magic | `u32@0x0C` | `u32@0x10` |
| --- | --- | --- | --- |
| `bgm_00.bin` | `BGMC` | `0x21` | `0x2C` |
| `character_00.bin` | `CHRT` | `0x16` | `0x128` |
| `enemy_00.bin` | `ENMY` | `0x2D7` | `0x114` |
| `equipset_00.bin` | `EQST` | `0x13E` | `0x1C` |
| `battlevoice_00.bin` | `BVFT` | `0x1D` | `0x10` |
| `attackergun_00.bin` | `ASKL` | `0x4` | `0xB0` |

The field semantics are not yet pinned down, but these files are clearly part of the same broad `magic + 0x100 + 0x14` binary-table family rather than generic opaque blobs.

## DAT Format Observations

The `228` sample `.dat` files split into three clear families.

### `BTTK`

`208/228` `.dat` files begin with `BTTK`.

Observed version counts:

- version `1`: `97`
- version `2`: `75`
- version `3`: `34`
- version `4`: `2`

Observed common facts:

- bytes `0x00-0x03` are `42 54 54 4B` (`BTTK`)
- `u32` at `0x04` is a small version number
- `u32` at `0x08` follows `0x08 + 4 * version` in `208/208` checked files
- the body is compact binary data, not text

Observed versioned block pattern:

- version `1` files use header size `0x0C`
- version `2` files use header size `0x10`
- version `3` files use header size `0x14`
- version `4` files use header size `0x18`
- bytes from `0x0C` up to `header_size` act as an in-file offset table
- the number of payload blocks matches the version number
- all checked offset values are sorted, inside the file, and at or after the header

This strongly suggests a versioned format where newer versions add more payload sections through extra in-header block offsets.

Confirmed container rule across all `208` checked `BTTK` files:

- file header = `magic` + `version` + `header_size`
- `header_size = 0x08 + 4 * version`
- the `version - 1` `u32` values from `0x0C` up to `header_size` are block-start offsets for later payload blocks
- payload block boundaries are:
  - block `0` start = `header_size`
  - block `1..n-1` starts = stored offsets
  - final block end = EOF

Observed block-local record structure:

- every checked block can be decomposed into a small block-local header plus `0x10`-byte records
- the final block always fits `0x04 + n * 0x10`
- non-final blocks almost always fit `0x0C + n * 0x10`
- one checked outlier, `think/battlethink001.dat` block `0`, also fits `0x04 + n * 0x10`

Observed block-local header rules across all `357` checked blocks:

- `209` blocks use a `0x04`-byte local header
- `148` blocks use a `0x0C`-byte local header
- all version `1` files consist of one `0x04`-header block
- in versions `2-4`, the final block still uses a `0x04`-byte header and the added earlier blocks normally use `0x0C`

Observed `0x04`-byte local header pattern:

- in `208/209` checked blocks, the four header bytes are `[0x00, record_count, block_kind, 0x00]`
- in those same `208/209` blocks, the second byte matches the actual number of `0x10`-byte records exactly
- the one observed outlier is `think/battlethink001.dat` block `0`, which uses header bytes `[0x02, 0x04, 0x01, 0x00]` while still containing `5` records

Observed `0x0C`-byte local header pattern:

- in `148/148` checked blocks, header word `0` packs as bytes `[0x01, record_count, block_kind, 0x00]`
- in `148/148` checked blocks, the second byte again matches the actual record count exactly
- header word `2` is `0` in `146/148` checked blocks
- the only checked exceptions are `think/battlethink192.dat` block `0` and `think/battlethink193.dat` block `0`, where header word `2 = 0x01000289`

Observed block-kind distribution across all `357` checked blocks:

- kind `1`: `99` blocks
- kind `4`: `96` blocks
- kind `5`: `62` blocks
- kind `3`: `55` blocks
- kind `6`: `35` blocks
- kind `2`: `5` blocks
- kind `7`: `5` blocks

Observed `0x0C`-header middle-word vocabulary:

- the middle header word is highly constrained rather than random
- the most common byte patterns are:
  - `[0x00, 0x00, N, 0x00]` with `N = 10, 20, 30, 40, 50, 60`
  - `[0x04, 0x06, 0x01, 0x00]`
  - `[0x04, 0x06, 0x02, 0x00]`
  - `[0x01, 0x00, 0xC7, 0x00]`
  - `[0x01, 0x00, 0xF3, 0x00]`
  - `[0x01, 0x05, 0x90, 0x00]`
  - `[0x06, 0x08, 0x00, 0x00]`

Observed record packing:

- the checked sample contains `1486` `BTTK` records total
- every record is exactly `0x10` bytes
- the records fit more naturally as `8` little-endian `u16` fields than as four unrelated `u32` values

Observed record view as `u16[8]`:

- `u16[0]` is usually a small selector-like value:
  - overall top values are `0, 1, 2, 3, 4, 5`
  - in the dominant kind-`1` family, `u16[0] = 0` in `135/136` checked records
- `u16[1]` is a constrained command/value field:
  - most common values are `0x0100`, `0x0200`, `0x0300`, `0x0146`, `0x013C`, `0x0132`, `0x0128`
- `u16[2]` is another constrained packed field:
  - most common values are `0x0000`, `0x0602`, `0x0402`, `0x0401`, `0x0101`, `0x0102`
- `u16[3] = 0xFFFF` in `1482/1486` checked records
- `u16[4]` is a small integer field:
  - most common values are `0, 1, 2, 3, 4`
- `u16[5]` is almost always one of:
  - `0x0000`, `0x0100`, `0x0200`, `0x0300`, `0x0400`
  - these five values cover `1484/1486` checked records
- `u16[6] = 0` in `1478/1486` checked records
- `u16[7] = 0` in `1480/1486` checked records

Observed family-level split:

- kinds `4`, `5`, and `6` account for `193/357` checked blocks and `1101/1486` checked records
- those three kinds share the same broad `u16` field ranges and dominate the larger multi-record blocks
- kind `1` is structurally distinct because its records almost always pin `u16[0]` to `0`

Observed kind-`1` setup-block profile:

- kind `1` accounts for `99/357` checked blocks
- `82/99` kind-`1` blocks are non-final blocks, so this family is primarily used as a setup/intermediate block class
- kind-`1` block sizes are strongly skewed toward very small payloads:
  - `67` blocks contain `1` record
  - `29` blocks contain `2` records
  - `2` blocks contain `3` records
  - `1` outlier block contains `5` records

Observed kind-`1` record-library behavior:

- across `99` kind-`1` blocks, there are `71` distinct logical record sequences
- `14` logical record sequences are reused, covering `42/99` kind-`1` blocks
- this reuse is broader than exact full-payload reuse because the same logical record sequence often appears under different local-header metadata
- among the repeated kind-`1` sequences:
  - `6` appear under multiple `0x0C`-header middle-word values
  - `6` appear across multiple `BTTK` versions
  - `1` appears in both `0x0C`-header intermediate form and `0x04`-header final form

Observed dominant one-record kind-`1` form:

- `67` kind-`1` blocks contain exactly one record
- `59/67` of those one-record blocks fit the same core shape:
  - `(0, 0x0100, X, 0xFFFF, Y, Z, 0, 0)` when viewed as `u16[8]`
- in those dominant one-record setups:
  - variability is concentrated in `X = u16[2]`, `Y = u16[4]`, and `Z = u16[5]`
  - common `X` values include `0x0402`, `0x0602`, `0x0603`, `0x0401`, and `0x0403`
  - `Y` is usually `0`
  - `Z` is usually one of `0x0000`, `0x0200`, `0x0300`, or `0x0400`

Observed separation between setup row and header metadata:

- the same repeated kind-`1` record sequence can appear with different `0x0C`-header middle words
- sample-backed examples include:
  - `(0, 0x0100, 0x0402, 0xFFFF, 0, 0x0400, 0, 0)` reused `6` times under four different middle-word patterns
  - `(0, 0x0100, 0x0602, 0xFFFF, 0, 0x0300, 0, 0)` reused `5` times under three different middle-word patterns
- this indicates that the kind-`1` local header carries per-use metadata on top of a reusable setup-record library rather than fully defining the setup payload by itself

Observed kinds `4`/`5`/`6` terminal-family profile:

- kinds `4`, `5`, and `6` account for `193/357` checked blocks and `1101/1486` checked records
- outside one small outlier subgroup described below, these dominant families are best described by the `u16[0]` field forming a short nondecreasing selector ladder
- across the `174` clean kind-`4/5/6` blocks whose `u16[0]` values stay in the small range `0..5`, `173/174` use only step `0` or step `+1` between adjacent records

Observed kind-`4` profile:

- kind `4` accounts for `96/357` checked blocks
- `77/96` kind-`4` blocks are final blocks
- kind-`4` block sizes are tightly clustered:
  - `71` blocks contain `5` records
  - `13` blocks contain `4` records
  - `8` blocks contain `6` records
  - `4` blocks contain `7` records
- in the `92` clean kind-`4` blocks, the selector ladder always tops out at `3`
- the three most common clean `u16[0]` selector sequences are:
  - `(0, 1, 2, 2, 3)` in `30` blocks
  - `(0, 1, 2, 3, 3)` in `18` blocks
  - `(0, 1, 1, 2, 3)` in `16` blocks
- those three selector ladders cover `64/92` clean kind-`4` blocks
- exact duplication is almost absent:
  - only `1` repeated logical record sequence was observed, covering `2` blocks
  - no exact full-payload duplicate was observed in this family

Observed kind-`5` profile:

- kind `5` accounts for `62/357` checked blocks
- `49/62` kind-`5` blocks are final blocks
- kind-`5` block sizes are also tightly clustered:
  - `27` blocks contain `6` records
  - `20` blocks contain `5` records
  - `14` blocks contain `7` records
  - `1` block contains `8` records
- in the `58` clean kind-`5` blocks, the selector ladder tops out at `4`
- the three most common clean `u16[0]` selector sequences are:
  - `(0, 1, 2, 3, 4)` in `20` blocks
  - `(0, 1, 2, 3, 3, 4)` in `12` blocks
  - `(0, 0, 1, 2, 2, 3, 4)` in `8` blocks
- those three selector ladders cover `40/58` clean kind-`5` blocks
- kind `5` is the only dominant terminal family where exact full-payload reuse is still visible:
  - `2` repeated logical record sequences were observed, covering `4` blocks
  - those same `4` blocks also form `2` exact full-payload duplicate pairs

Observed kind-`6` profile:

- kind `6` accounts for `35/357` checked blocks
- unlike kinds `4` and `5`, kind `6` skews earlier rather than later:
  - `22/35` kind-`6` blocks are non-final blocks
  - `13/35` kind-`6` blocks are final blocks
- kind-`6` blocks are longer than the other dominant families:
  - `17` blocks contain `6` records
  - `7` blocks contain `8` records
  - `5` blocks contain `7` records
  - `3` blocks contain `9` records
  - `3` blocks contain `10` records
- in the `24` clean kind-`6` blocks, the selector ladder usually tops out at `5`
- the three most common clean `u16[0]` selector sequences are:
  - `(0, 1, 2, 3, 4, 5)` in `16` blocks
  - `(0, 1, 2, 2, 3, 3, 4, 5)` in `3` blocks
  - `(0, 1, 2, 3, 4, 4, 5)` in `2` blocks
- those three selector ladders cover `21/24` clean kind-`6` blocks
- exact duplication is again rare:
  - only `1` repeated logical record sequence was observed, covering `2` blocks
  - no exact full-payload duplicate was observed in this family

Observed version-`3` selector outlier subgroup:

- `19/193` checked kind-`4/5/6` blocks break the small-selector ladder pattern by introducing high-byte selector variants in `u16[0]`
- every one of those outlier blocks is confined to the same small version-`3` file cluster:
  - `think/battlethink119.dat`
  - `think/battlethink120.dat`
  - `think/battlethink121.dat`
  - `think/battlethink204.dat`
  - `think/battlethink205.dat`
  - `think/battlethink206.dat`
  - `think/battlethink207.dat`
- the observed outlier selector values are:
  - `0x0100`, `0x0101`, `0x0102`, `0x0103`, `0x0104`, and `0x0204`
- outside that confined subgroup, the dominant terminal families are much more regular and stay within the simple `0..5` selector-ladder model

Observed composition and reuse behavior:

- exact block payload reuse is limited:
  - `339` unique block payloads across `357` checked blocks
  - only `14` distinct payloads are reused at all
  - only `32/357` checked blocks participate in an exact duplicate
- the reused payloads are concentrated in small setup blocks:
  - `24/32` reused blocks are kind-`1` blocks with `0x0C`-byte local headers
  - `4/32` reused blocks are kind-`1` blocks with `0x04`-byte local headers
  - `4/32` reused blocks are kind-`5` final blocks with `0x04`-byte local headers
- full-file duplication is extremely rare:
  - only one exact whole-file composition repeat was observed in the sample, `battlethink055.dat` and `battlethink056.dat`

Observed block-kind template families:

- repeated kind sequences are common even when the block payloads themselves are unique
- dominant versioned kind-sequence families in the sample are:
  - version `1`: `(4)` `42`, `(3)` `23`, `(5)` `20`, `(1)` `6`
  - version `2`: `(1,3)` `14`, `(1,4)` `13`, `(1,1)` `7`, `(6,5)` `7`
  - version `3`: `(1,1,4)` `11`, `(1,1,1)` `3`, `(1,1,5)` `3`, `(6,6,5)` `3`, `(7,4,5)` `3`, `(6,6,6)` `3`
  - version `4`: `(1,1,1,3)` `1`, `(1,1,1,4)` `1`

Observed non-`1` backbone grammar:

- if kind `1` is treated as a setup/intermediate family and removed from the block sequence, the remaining non-setup backbone is much smaller and more regular
- observed non-`1` backbone counts across all `208` checked `BTTK` files are:
  - `(4)` in `67` files
  - `(3)` in `39` files
  - `(5)` in `27` files
  - `()` in `16` files
  - `(6,5)` in `7` files
  - `(3,3)`, `(4,5)`, `(5,4)`, and `(4,6)` in `5` files each
- the empty backbone `()` means the file contains only kind-`1` blocks and no non-setup terminal family at all
- the most common non-`1` block-to-block transitions are:
  - `6 -> 5` in `10` places
  - `6 -> 6` in `9` places
  - `4 -> 5` in `8` places
  - `3 -> 3` in `5` places
  - `5 -> 4` in `5` places
  - `4 -> 6` in `5` places

Observed repeated backbone motifs with stable selector ladders:

- backbone `(6,6,5)` occurs in exactly three version-`3` files:
  - `think/battlethink117.dat`
  - `think/battlethink198.dat`
  - `think/battlethink202.dat`
- all three `(6,6,5)` files use the same clean selector-ladder trio:
  - first kind `6`: `(0, 1, 2, 3, 4, 5)`
  - second kind `6`: `(0, 1, 2, 3, 4, 5)`
  - final kind `5`: `(0, 1, 2, 3, 4)`
- backbone `(7,4,5)` also occurs in exactly three version-`3` files:
  - `think/battlethink118.dat`
  - `think/battlethink199.dat`
  - `think/battlethink203.dat`
- all three `(7,4,5)` files again use the same selector-ladder trio:
  - kind `7`: `(0, 1, 2, 3, 4, 5, 6)`
  - kind `4`: `(0, 1, 1, 2, 3)`
  - kind `5`: `(0, 1, 2, 3, 4)`
- backbone `(6,6,6)` is the contrasting outlier case:
  - it occurs in `think/battlethink121.dat`, `think/battlethink206.dat`, and `think/battlethink207.dat`
  - unlike `(6,6,5)` and `(7,4,5)`, it is the one repeated multi-block backbone whose selector ladders stay inside the version-`3` high-byte outlier subgroup documented above

Observed field-role signals inside the clean repeated families:

- `u16[2]` is highly structured rather than arbitrary:
  - `1476/1486` checked `BTTK` records use a `u16[2]` value from one of these dense bands:
    - `0x000-0x005`
    - `0x100-0x106`
    - `0x200-0x205`
    - `0x302-0x303`
    - `0x400-0x406`
    - `0x501-0x505`
    - `0x600-0x606`
    - `0x701-0x706`
  - only `10/1486` checked records fall outside those bands
  - those band exceptions are confined to the known oddball files:
    - `think/battlethink001.dat`
    - `think/battlethink002.dat`
    - `think/battlethink014.dat`
    - `think/battlethink023.dat`
    - `think/battlethink074.dat`
    - `think/battlethink106.dat`
    - `think/battlethink192.dat`
    - `think/battlethink193.dat`
- across the four clean sibling-family groups
  - `think/battlethink115.dat`, `think/battlethink196.dat`, `think/battlethink200.dat`
  - `think/battlethink116.dat`, `think/battlethink197.dat`, `think/battlethink201.dat`
  - `think/battlethink117.dat`, `think/battlethink198.dat`, `think/battlethink202.dat`
  - `think/battlethink118.dat`, `think/battlethink199.dat`, `think/battlethink203.dat`
  every row-aligned difference is confined to `u16[2]`, with only two aligned rows also varying `u16[4]`
- more specifically, across `59` aligned rows in those four groups:
  - `11` rows are byte-identical across all compared siblings
  - `46` rows vary only in `u16[2]`
  - `2` rows vary only in `u16[2]` and `u16[4]`
  - no aligned row varies in any other field
- this makes `u16[2]` the strongest current candidate for the main per-file reference/index operand inside otherwise stable row classes, while `u16[1]`, `u16[5]`, and usually `u16[4]` behave more like row-type metadata

Observed band-to-row-class split:

- exact `u16[2] = 0` rows behave more like structural/control rows than general operand rows:
  - there are `217` exact-zero `u16[2]` records in the checked sample
  - `151/217` of those exact-zero rows use `u16[1]` in the small set `{0x300, 0x500, 0x51E, 0x528, 0x532, 0x53C}` with `u16[5] = 0`
  - representative exact-zero row classes include:
    - kind `4`, `(u16[1], u16[4], u16[5]) = (0x528, 0, 0)`
    - kind `6`, `(u16[1], u16[4], u16[5]) = (0x300, 37, 0)`
    - kind `7`, `(u16[1], u16[4], u16[5]) = (0x300, 31, 0)`
- the dominant operand-like bands are `0x400` and `0x600`:
  - together they cover `801/1486` checked records
  - they recur across many of the same row classes rather than defining completely separate row shapes
  - sample-backed row classes that stay within the `0x400/0x600` pair include:
    - kind `6`, `(u16[1], u16[4], u16[5]) = (0x100, 0, 0x200)` with `12` records
    - kind `6`, `(u16[1], u16[4], u16[5]) = (0x100, 1, 0x300)` with `12` records
- the `0x700` band is much narrower and is skewed toward the later kind-`5`/kind-`6` families:
  - `48/62` `0x700`-band records belong to kinds `5` or `6`
  - the strongest pure `0x700` row class is kind `6`, `(u16[1], u16[4], u16[5]) = (0x200, 6, 0)`, with `12` records
  - the closely related kind `5` class `(0x200, 6, 0)` appears `8` times and only uses the neighboring `0x600/0x700` pair

Observed `u16[1]` family split:

- `u16[1] = 0x100` is the main operand-row family:
  - it covers `799/1486` checked `BTTK` records
  - `782/799` of those rows use a non-zero `u16[2]` band
  - the dominant bands inside this family are `0x400` (`306` rows) and `0x600` (`252` rows)
- `u16[1] = 0x200` behaves like a secondary/terminal operand family rather than the main one:
  - it covers `126` checked rows
  - it is skewed toward the later bands `0x600` (`28` rows) and `0x700` (`26` rows), with smaller populations in `0x500` (`16`) and exact zero (`15`)
- `u16[1] = 0x300` is mostly a marker/control family:
  - `40/57` rows with `u16[1] = 0x300` use exact `u16[2] = 0`
  - the remaining non-zero cases are mostly `0x600`-band rows
- `u16[1] = 0x500`, `0x51E`, `0x528`, `0x532`, and `0x53C` are pure structural/control families in this sample:
  - all `111` rows using those `u16[1]` values have exact `u16[2] = 0`

Observed banked-versus-bankless role split:

- `u16[1] = 0x100` and the paired `0x1xx` families
  - `0x11E`, `0x128`, `0x132`, `0x13C`, `0x146`
  form one large banked operand/reference side of the language
- combined, that banked side covers `990/1486` checked `BTTK` rows
- all `990/990` of those rows use only the small `u16[4]` range `0..3`
- `818/990` of those rows also use a non-zero `u16[5]` bank selector
- this is the strongest sample-backed reason to treat `u16[4]` as a local slot/subindex field in the banked families and `u16[5]` as a bank/namespace selector rather than arbitrary padding
- the low-byte-paired `0x1xx` families are especially regular:
  - they cover `191` rows total
  - all `191/191` use `u16[4] <= 3`
  - `154/191` use a non-zero `u16[5]`

- the linked `0x2xx` partner families
  - `0x21E`, `0x228`, `0x232`, `0x23C`, `0x246`
  behave like bankless control/operator-side variants rather than more banked operand rows
- combined, those `0x2xx` families cover `106` checked rows
- all `106/106` use `u16[5] = 0`
- only `40/106` stay in the small `u16[4]` range `0..3`, while the rest spread across the broader control-like range `4, 5, 6, 10, 11, 12, 13, 14, 15, 16, 18, 19`
- this matches the visible low-byte pairing:
  - `0x11E/0x21E`
  - `0x128/0x228`
  - `0x132/0x232`
  - `0x13C/0x23C`
  - `0x146/0x246`
- the cleanest current interpretation is that the `0x1xx` member of each pair is the banked operand/reference variant and the `0x2xx` member is a linked bankless control/operator variant

Observed non-zero `u16[5]` bank profiles:

- the non-zero banks `0x100`, `0x200`, `0x300`, and `0x400` all stay inside the same banked operand/reference side:
  - they are all dominated by `u16[1] = 0x100`
  - they all keep `u16[4]` in the small range `0..3`
  - this reinforces the interpretation of `u16[5]` as a bank/namespace selector rather than a free-form numeric field
- `u16[5] = 0x100` is the smallest observed bank:
  - it covers `105` rows total
  - it is concentrated in kinds `3` and `4` (`86/105` rows)
  - its `u16[2]` bands are relatively balanced across `0x100` (`28`), `0x400` (`27`), `0x500` (`17`), and `0x600` (`33`)
  - the best current model is an earlier or lighter bank rather than the default one
- `u16[5] = 0x200` is the broadest observed bank:
  - it covers `337` rows total
  - it appears across kinds `1`, `3`, `4`, `5`, `6`, and `7`
  - `272/337` rows still use the main `u16[1] = 0x100` family
  - its `u16[2]` space is dominated by the `0x400` (`127`) and `0x600` (`101`) bands
  - this is the strongest current candidate for the default banked operand namespace in the checked sample
- `u16[5] = 0x300` behaves like a later or more specialized bank:
  - it covers `189` rows total
  - it is heavily skewed toward kinds `5` (`71`) and `4` (`51`)
  - its `u16[2]` values are strongly concentrated in `0x600` (`95/189`)
  - it does not appear in kind `7`
- `u16[5] = 0x400` is a fourth substantial bank with a mixed terminal-family profile:
  - it covers `200` rows total
  - it is concentrated in kinds `4`, `5`, and `6` (`159/200` rows)
  - its `u16[2]` distribution is centered on `0x400` (`91`) and `0x600` (`60`), with a real `0x500` presence (`25`)
  - like the `0x300` bank, it does not appear in kind `7`
- these bank labels are still structural, not gameplay-semantic:
  - the checked sample supports “small/early bank”, “broad default bank”, and “later/specialized bank” style role labels
  - it does not yet prove what in-game subsystem each bank corresponds to

Observed file-level bank scoping:

- across all `208` checked `BTTK` files, the banked operand/reference rows use at most one non-zero `u16[5]` bank per file
- `157/208` files use exactly one non-zero bank from `{0x100, 0x200, 0x300, 0x400}`
- the remaining `51/208` files use no non-zero bank at all
- no checked file mixes multiple non-zero banks on the banked `0x100/0x1xx` side
- this is the strongest current reason to treat `u16[5]` as a file-scoped or motif-scoped bank selector rather than a row-local free variable

Observed file-level `u16[4]` slot-set structure on the banked side:

- the checked sample uses only seven file-level slot sets for banked operand/reference rows:
  - no banked rows: `51` files
  - `{0}`: `73` files
  - `{0, 1}`: `47` files
  - `{0, 1, 2}`: `19` files
  - `{0, 1, 2, 3}`: `10` files
  - `{1, 2, 3}`: `6` files
  - `{1}`: `2` files
- `200/208` checked files therefore use either no banked slots or a prefix-closed slot set `0..n`
- this is the strongest current sample-backed reason to treat `u16[4]` as a local slot/subindex field rather than another unconstrained parameter
- the eight non-prefix outliers are:
  - `think/battlethink005.dat`
  - `think/battlethink051.dat`
  - `think/battlethink119.dat`
  - `think/battlethink121.dat`
  - `think/battlethink195.dat`
  - `think/battlethink204.dat`
  - `think/battlethink206.dat`
  - `think/battlethink207.dat`
- those outliers are confined to a small set of unusual backbones:
  - `(2,)`
  - `(5,)`
  - `(6, 4, 4)`
  - `(6, 6, 6)`

Observed bank layering over shared backbones:

- the same non-`1` backbone can recur under different bank choices, so bank selection is not just a disguised block-kind choice
- sample-backed examples include:
  - backbone `(6, 5)` appearing with bank `0x200` in `4` checked files and with bank `0x400` in `3` checked files
  - backbone `(4,)` appearing in checked files with no non-zero bank and also with each of `0x100`, `0x200`, `0x300`, and `0x400`
  - backbone `(3,)` appearing both without a non-zero bank and with each of `0x100`, `0x200`, `0x300`, and `0x400`
- this supports treating the bank as a second axis layered on top of the block/backbone grammar rather than merged into it

Observed bank placement inside the clean repeated motifs:

- in the clean `(6,5)` family represented by
  - `think/battlethink115.dat`
  - `think/battlethink196.dat`
  - `think/battlethink200.dat`
  every banked operand/reference row uses bank `0x200`, while the linked control/operator rows in the same files keep `u16[5] = 0`
- in the sibling `(6,5)` family represented by
  - `think/battlethink116.dat`
  - `think/battlethink197.dat`
  - `think/battlethink201.dat`
  every banked operand/reference row uses bank `0x400`, while the linked control/operator rows again keep `u16[5] = 0`
- in the repeated `(6,6,5)` family represented by
  - `think/battlethink117.dat`
  - `think/battlethink198.dat`
  - `think/battlethink202.dat`
  every banked operand/reference row uses bank `0x300`, while the non-banked control rows keep `u16[5] = 0`
- in the repeated `(7,4,5)` family represented by
  - `think/battlethink118.dat`
  - `think/battlethink199.dat`
  - `think/battlethink203.dat`
  every banked operand/reference row uses bank `0x200`, while the structural/control rows keep `u16[5] = 0`
- across those clean motifs, bank selection is therefore stable at the whole-file family level rather than varying from one banked row to the next

Observed `u16[4]` slot placement inside the clean repeated motifs:

- in the clean bank-`0x200` `(6,5)` family represented by
  - `think/battlethink115.dat`
  - `think/battlethink196.dat`
  - `think/battlethink200.dat`
  the banked rows use all four slots in a fixed per-row layout:
  - kind `6` selector `1 -> slot 2`
  - kind `6` selector `2 -> slot 0`
  - kind `6` selector `4 -> slot 3`
  - kind `6` selector `5 -> slot 1`
  - kind `5` selector `0 -> slot 1`
  - kind `5` selector `1 -> slot 0`
  - kind `5` selector `3 -> slot 2`
  - kind `5` selector `4 -> slot 1`
- in the sibling bank-`0x400` `(6,5)` family represented by
  - `think/battlethink116.dat`
  - `think/battlethink197.dat`
  - `think/battlethink201.dat`
  the banked rows again use a fixed slot layout, but with a different arrangement:
  - kind `6` selector `0 -> slot 0`
  - kind `6` selector `1 -> slot 1`
  - kind `6` selector `3 -> slot 3`
  - kind `6` selector `4 -> slot 0`
  - kind `6` selector `5 -> slot 2`
  - kind `5` selector `0 -> slot 1`
  - kind `5` selector `2 -> slot 2`
  - kind `5` selector `3 -> slot 0`
  - kind `5` selector `4 -> slot 1`
- in the bank-`0x300` `(6,6,5)` family represented by
  - `think/battlethink117.dat`
  - `think/battlethink198.dat`
  - `think/battlethink202.dat`
  the banked rows collapse mostly to slots `0` and `1`, with a single stable slot-`2` row:
  - the `u16[1] = 0x100`, `u16[2] = 0x0700` banked rows use slot `0`
  - the aligned `u16[1] = 0x100`, `u16[2] = 0x0600` middle rows use slot `1`
  - only the first kind-`6` block's terminal banked row uses slot `2`
- in the bank-`0x200` `(7,4,5)` family represented by
  - `think/battlethink118.dat`
  - `think/battlethink199.dat`
  - `think/battlethink203.dat`
  most banked rows keep stable slot identities, but two leading rows admit a one-step sibling swap:
  - kind `7` selector `1` uses slot `0` or `1`
  - kind `7` selector `2` uses slot `3`
  - kind `7` selector `5` uses slot `0`
  - kind `4` selector `0` uses slot `1`
  - kind `5` selector `0` uses slot `1` or `2`
  - kind `5` selector `2` uses slot `0`
  - kind `5` selector `4` uses slot `2`
- across those clean motifs, `u16[4]` behaves like a row-local slot assignment inside the file-scoped bank, with only small sibling-family renumbering in the `(7,4,5)` case

Observed bankless `0x2xx` operator-family usage:

- the bankless paired families
  - `0x21E`
  - `0x228`
  - `0x232`
  - `0x23C`
  - `0x246`
  are sparse rather than universal:
  - `135/208` checked `BTTK` files use none of them
  - `62/208` use exactly one such family
  - only `11/208` mix multiple `0x2xx` families
- all checked `0x2xx` rows keep `u16[5] = 0`
- this supports the earlier interpretation that these rows are bankless operator/control-side insertions rather than more banked operand rows

Observed family-level `0x2xx` profiles:

- `0x21E` appears `13` times:
  - mostly in kinds `4` and `6`
  - always bracketed by banked rows in the same block (`13/13` have a banked predecessor and `13/13` have a banked successor)
  - the predecessor is usually `0x146` or `0x100`, and the successor is usually `0x100` or `0x146`
- `0x228` appears `15` times:
  - mostly in kind `4`
  - `13/15` have a banked predecessor and `13/15` have a banked successor
  - the predecessor is usually `0x13C`, and the successor is usually `0x100`
  - all `15/15` occur on a selector that also has a banked row in the same block
- `0x232` appears `30` times and is the largest `0x2xx` family:
  - it is heavily concentrated in band `0x600` (`21/30`)
  - it appears mainly in kinds `4`, `5`, and `6`
  - `22/30` have a banked predecessor and `24/30` have a banked successor
  - it often appears as a consecutive mini-run of `0x232` rows inside one block rather than as a lone insertion
- `0x23C` appears `27` times:
  - mainly in kinds `4` and `5`
  - it often occurs at the start of a block (`12/27`)
  - when it is not block-leading, the predecessor is usually `0x100`
  - the successor is usually `0x128` (`21/27`)
- `0x246` appears `21` times:
  - mainly in kinds `4` and `5`
  - it often occurs at the start of a block (`8/21`)
  - the successor is usually `0x11E` (`14/21`)

Observed file-level `0x2xx` family sets:

- when `0x2xx` rows appear at all, the file usually stays inside one such family:
  - `0x23C` only: `17` files
  - `0x232` only: `14` files
  - `0x228` only: `13` files
  - `0x246` only: `9` files
  - `0x21E` only: `9` files
- the most important mixed-family case in the checked sample is `0x21E + 0x232`, which appears exactly in:
  - `think/battlethink116.dat`
  - `think/battlethink197.dat`
  - `think/battlethink201.dat`

Observed `0x2xx` placement inside the clean repeated motifs:

- the clean bank-`0x200` `(6,5)` family represented by
  - `think/battlethink115.dat`
  - `think/battlethink196.dat`
  - `think/battlethink200.dat`
  uses no `0x2xx` rows
- the sibling bank-`0x400` `(6,5)` family represented by
  - `think/battlethink116.dat`
  - `think/battlethink197.dat`
  - `think/battlethink201.dat`
  injects one fixed `0x2xx` cluster into the first kind-`6` block:
  - selector `2`: `0x232`, `0x232`
  - selector `3`: `0x21E`
  - this cluster sits between the banked selector-`1` row and the later banked selector-`3` / selector-`4` rows
- the bank-`0x300` `(6,6,5)` family represented by
  - `think/battlethink117.dat`
  - `think/battlethink198.dat`
  - `think/battlethink202.dat`
  uses no `0x2xx` rows
- the bank-`0x200` `(7,4,5)` family represented by
  - `think/battlethink118.dat`
  - `think/battlethink199.dat`
  - `think/battlethink203.dat`
  injects one fixed `0x23C` row in the kind-`4` block at selector `1`, immediately after the banked selector-`0` row and before the structural `0x528` row
- across those clean motifs, the `0x2xx` families behave like optional bankless operator-side inserts layered on top of the same underlying banked slot grammar

Observed band templates inside the clean repeated motifs:

- in the clean `(6,5)` family represented by
  - `think/battlethink115.dat`
  - `think/battlethink196.dat`
  - `think/battlethink200.dat`
  the band layout is almost entirely `0x600`:
  - first kind `6`: `0x000, 0x600, 0x600, 0x600, 0x600, 0x600`
  - final kind `5`: `0x600, 0x600, 0x600, 0x600, 0x000, 0x600`
- in the clean `(6,5)` family represented by
  - `think/battlethink116.dat`
  - `think/battlethink197.dat`
  - `think/battlethink201.dat`
  the band layout becomes layered rather than uniform:
  - first kind `6`: `0x400, 0x400, 0x600, 0x600, 0x600, 0x600, 0x700, 0x700`
  - final kind `5`: `0x500, 0x500, 0x400, 0x400, 0x400`
- in the repeated `(6,6,5)` triplet
  - `think/battlethink117.dat`
  - `think/battlethink198.dat`
  - `think/battlethink202.dat`
  the band layout stabilizes into an alternating `0x600/0x700` scheme:
  - first kind `6`: `0x600, 0x700, 0x600, 0x700, 0x600, 0x600`
  - second kind `6`: `0x700, 0x700, 0x600, 0x700, 0x600, 0x600`
  - final kind `5`: `0x700, 0x700, 0x600, 0x700, 0x600`
- in the repeated `(7,4,5)` triplet
  - `think/battlethink118.dat`
  - `think/battlethink199.dat`
  - `think/battlethink203.dat`
  the three blocks use three different band layers:
  - kind `7`: `0x000, 0x400, 0x400, 0x000, 0x000, 0x400, 0x000`
  - kind `4`: `0x500, 0x600, 0x000, 0x000, 0x000`
  - final kind `5`: `0x100, 0x500, 0x400, 0x100, 0x100`
- these stable motif templates support the interpretation that the major `u16[2]` bands behave like row-role namespaces or stages inside a fixed block grammar, rather than like one flat global ID space with random values

Observed motion-side correlation limits:

- the most likely nearby external targets were checked directly:
  - `motion/battlecharamotionsequence.dat`
  - all `19` `motion/exmotset/battlecharaexmotset_*.dat` files
- those structured motion-side tables do not show a convincing reuse of the main `BTTK` `u16[2]` operand bands
- all `19` checked `exmotset` files repeatedly use `0x0100` and `0x0200` halfwords, but they do not show dense `0x0400`/`0x0500`/`0x0600`/`0x0700`-band reuse
- `motion/battlecharamotionsequence.dat` contains only isolated band-like halfwords:
  - one `0x0100`
  - one `0x0302`
  - one `0x0504`
  - one `0x0706`
- this means the strongest motion-side overlap is currently with the `BTTK` `u16[1] = 0x100/0x200` row families, not with the `u16[2]` operand namespaces
- so there is not yet sample-backed evidence that `BTTK` `u16[2]` directly indexes `battlecharamotionsequence` or `exmotset` entries

Observed kind-`6` to kind-`5` reduction in the `(6,6,5)` triplet:

- in all three of
  - `think/battlethink117.dat`
  - `think/battlethink198.dat`
  - `think/battlethink202.dat`
  the final kind-`5` block closely matches the preceding kind-`6` block
- the common reduction rule is:
  - remove the selector-`4` row `(4, 0x0300, 0x0600, 0xFFFF, 33, 0, 0, 0)`
  - then collapse the trailing selector `5` to `4`
- this rule reproduces the final kind-`5` block exactly in `think/battlethink117.dat` and `think/battlethink202.dat`
- in `think/battlethink198.dat`, the same reduction still holds except that the first row's `u16[2]` changes from `0x702` in the kind-`6` block to `0x703` in the final kind-`5` block

Observed version-to-version extension pattern:

- the kind-sequence templates suggest that later versions usually extend earlier families by prepending one new setup block while keeping the later tail shape
- sample-backed examples:
  - version `1` `(4)` -> version `2` `(1,4)` -> version `3` `(1,1,4)` -> version `4` `(1,1,1,4)`
  - version `1` `(3)` -> version `2` `(1,3)` -> version `3` `(1,1,3)` -> version `4` `(1,1,1,3)`
  - version `1` `(5)` -> version `2` `(6,5)` -> version `3` `(6,6,5)`
  - version `1` `(5)` -> version `2` `(4,5)` -> version `3` `(7,4,5)`

This makes the sample-backed `BTTK` model look more like a small versioned block language than a single flat record table.

Observed non-zero final-record-word exceptions:

- `think/battlethink001.dat`
- `think/battlethink023.dat`
- `think/battlethink074.dat`
- `think/battlethink106.dat`
- `think/battlethink192.dat`
- `think/battlethink193.dat`

So the current best structural model is:

- top-level `BTTK` container with version-controlled block count
- each block = local header + array of packed `16`-byte records
- local-header byte `1` redundantly stores the record count in normal blocks
- block kind is a real subtype marker, not just padding
- later versions add more blocks rather than replacing the earlier layout

Remaining `BTTK` questions:

- what the major `u16[2]` bands mean semantically, beyond acting like row-role namespaces or operand classes
- what the bank values `0x100/0x200/0x300/0x400` correspond to in gameplay terms
- what the bankless structural/control rows
  - `0x300`
  - `0x500`
  - `0x51E`
  - `0x528`
  - `0x532`
  - `0x53C`
  actually do inside the block language
- whether the `0x2xx` operator-side rows can be mapped to specific actions such as tests, redirects, or slot/bank transitions
- whether any `BTTK` fields can be tied convincingly to external game systems rather than only to internal block grammar

### `motion/exmotset`

`19/228` `.dat` files live under `motion/exmotset/`.

Observed common facts across all `19`:

- the first `u32` is always `0x24` (`36`)
- file sizes are `0x3F8`, `0x3FC`, or `0x400`
- the next `36` `u32` values form a monotonic offset table
- the offset table occupies `0x94` bytes total (`4 + 36 * 4`)
- all checked offsets are relative to the payload start at `0x94`

Observed offset-table behavior:

- the first offsets are `0x0, 0x6, 0xC, 0x12, ...`
- step sizes are mostly `6`, with some `7`
- packed data begins immediately after the offset table at `0x94`

These files appear to be small indexed tables with `36` payload-relative records.

### `motion/battlecharamotionsequence.dat`

This is the only sample `.dat` in its family.

Observed structure:

- first `u32` is `0x14` (`20`)
- file size is `0x54`
- `0x54 = 4 + 20 * 4`

That fits a simple layout of one count followed by `20` four-byte records.

## LUC Format Observations

The only observed `.luc` file is `script/im.luc`.

Observed facts:

- it is plain text, not opaque binary
- it begins with an ASCII comment banner
- the content decodes cleanly as UTF-8
- it contains script-style comments, tags, and Japanese text annotations

In this sample, `.luc` looks like source text rather than a compiled resource.

## PBD Format Observations

Observed `.pbd` files:

- `se/dance.pbd`
- `btlfix.pbd`
- `common.pbd`
- `map_menu.pbd`

Shared observed facts across all four:

- no magic at offset `0x00`
- first `16` bytes are all zero
- the first non-zero byte appears at `0x10`
- file sizes are `0x10` aligned in all four checked samples
- `file_size = 0x10 + record_count * 0x10` exactly in all four checked samples

Observed fixed-record layout:

- after the `0x10`-byte zero preamble, the remaining body is a flat stream of `0x10`-byte records
- observed record counts are:
  - `se/dance.pbd`: `35434`
  - `btlfix.pbd`: `57912`
  - `common.pbd`: `11504`
  - `map_menu.pbd`: `5343`

Observed record-class behavior:

- record byte `1` only takes values `0`, `1`, or `7` across all `110193` checked records
- `110017` records use byte `1 = 0` and appear to be the normal payload rows
- `60` records use byte `1 = 1` and behave like marker records
- `60` records use byte `1 = 7` and are all the exact sentinel value `00 07 77 77 77 77 77 77 77 77 77 77 77 77 77 77`
- all `56` all-zero records in the sample appear only as post-sentinel padding rows

Observed delimiter pattern:

- every checked `byte1 = 1` marker record is immediately followed by the all-`0x77` sentinel record
- `56/60` such marker+sentinel pairs are then followed by exactly one all-zero record
- the remaining `4/60` pairs occur at end-of-file and have no trailing zero record
- no checked sentinel record appears without a preceding `byte1 = 1` marker

Observed normal-record facts:

- in all non-zero, non-sentinel payload rows, record byte `1` is always `0`
- in those normal rows, record byte `0` ranges from `0` to `76`
- the remaining bytes are dense packed binary with no stable ASCII or UTF text structure visible in these samples

Current interpretation:

- `.pbd` is a real separate format family
- the format does not expose a simple four-byte magic in these samples
- the sample-backed structure is now strong enough to describe `.pbd` as a fixed-record stream with explicit delimiter records rather than an opaque blob
- semantic field labeling for the normal records still needs more samples or game-side usage context

## COL Format Observations

`.col` files were observed inside extracted nested KPDs from the same sample archive.

Checked samples:

- `st09_h002_00.col`
- `st09_h003_00.col`
- `st09_h005_00.col`

Observed common facts:

- they begin with `COLS`
- the first `12` bytes are `43 4F 4C 53 01 00 01 00 01 00 01 00`
- `u32` at `0x0C` is `0xCDCDCDCD` in all three checked samples
- the checked samples all have size `0x5C0`
- dword `0xF0F00026` appears at `0x10` in all three checked samples
- the body contains many little-endian float values, consistent with geometry-like data

Observed main-body split:

- bytes `0x14-0x56B` occupy `0x558` bytes total
- `0x558 = 38 * 0x24`
- the low byte of the control word at `0x10` is also `0x26` (`38`)
- this strongly suggests `38` fixed-size main records of `0x24` bytes each after the `0x10` control word
- each such record is `9` dwords wide and is mostly float-like data

Verified `0x24` record model:

Each main record is `9` little-endian floats:

| Float Index | Offset | Meaning |
| --- | --- | --- |
| `0` | `+0x00` | `x1` |
| `1` | `+0x04` | `y1` |
| `2` | `+0x08` | `x2` |
| `3` | `+0x0C` | `y2` |
| `4` | `+0x10` | `dx = x2 - x1` |
| `5` | `+0x14` | `dy = y2 - y1` |
| `6` | `+0x18` | `nx` |
| `7` | `+0x1C` | `ny` |
| `8` | `+0x20` | `length = hypot(dx, dy)` |

This model was checked against all `38` records in all `3` samples:

- `dx` and `dy` match `x2 - x1` and `y2 - y1` for `38/38` records in each sample
- `length` matches `sqrt(dx^2 + dy^2)` for `38/38` records in each sample
- `(nx, ny)` is a unit perpendicular to the segment direction for `38/38` records in each sample

This strongly indicates that the main body stores ordered 2D collision edges or boundary segments.

Observed segment-list behavior:

- each checked file contains `33` axis-aligned records and `5` sloped records
- the list order preserves the same chain breaks in all three samples
- connected runs by endpoint equality are:
  - `0`
  - `1`
  - `2`
  - `3`
  - `4-11`
  - `12`
  - `13`
  - `14`
  - `15`
  - `16`
  - `17`
  - `18-21`
  - `22-25`
  - `26`
  - `27`
  - `28-32`
  - `33-37`

So the file stores more than just an unordered segment soup; it preserves a stable chain layout across the checked maps.

Observed cross-sample transform behavior:

- `st09_h003_00.col` matches the `st09_h002_00.col` segment data under an approximate `180` degree rotation: `(x, y) -> (-x, -y)`
- `st09_h005_00.col` matches the `st09_h002_00.col` segment data under an approximate `90` degree rotation: `(x, y) -> (-y, x)`
- the same transform applies to segment endpoints, deltas, normals, and lengths, with only small float-rounding differences

This means the three checked `COLS` files share one collision template topology expressed in different orientations.

Observed shared footer:

- bytes `0x56C-0x5BF` form a `0x54`-byte footer
- this footer is byte-identical across all three checked samples
- the footer begins with:
  - `0x56C: 0x00010002`
  - `0x570: 0xF0F00004`
  - `0x574: 0x00010000`
  - `0x578: 0x00000003`
  - `0x57C: 0x00020003`
- the footer splits cleanly as:
  - `0x14` bytes of header/control words
  - `4` records of `0x10` bytes each
- those `4` records are best viewed as `vec4`-like float tuples
- the first tuple is approximately `(0, 0, 1, 0)`
- the remaining three tuples are constant `20`-scale values shared across all three checked samples

The exact semantic meaning of these four footer vectors is still unresolved, but the footer is clearly a second structured chunk rather than trailing garbage.

This is consistent with the community interpretation that `COLS` is a collision-related format.

## GMO Format Observations

All `710` sample `.gmo` files begin with `OMG.00.1PSP`.

Observed common header pattern:

| Offset | Type | Observed value |
| --- | --- | --- |
| `0x00` | `char[12]` | `OMG.00.1PSP\\0` |
| `0x0C` | `u32` | `0x00000000` in `710/710` |
| `0x10` | `u32` | `0x00100002` in `710/710` |
| `0x14` | `u32` | `file_size - 0x10` in `710/710` |
| `0x18` | `u32` | `0x10` in `710/710` |
| `0x1C` | `u32` | `0x10` in `710/710` |
| `0x20` | `u32` | `0x00180003` in `710/710` |
| `0x24` | `u32` | equals `file_size - 0x20` in `573/710`, so not universal |
| `0x28` | `u32` | `0x18` in `710/710` |
| `0x2C` | `u32` | `0x18` in `710/710` |
| `0x30` | `char[8]` | `model-0\\0` in `710/710` |

Small GMO files are normal in this sample. For example:

- `cam.gmo`: `0xD4`
- `w0000.gmo`: `0xE0`
- `op_body_mot.gmo`: `0x6D8`
- `op_face_mot.gmo`: `0x1B14`

These small files are internally consistent:

- the field at `0x14` still matches `file_size - 0x10`
- archive data after EOF is padding, not the start of another file

## ANA Format Observations

All `30` sample `.ana` files:

- begin with `@ANA `
- contain at least one embedded `@ANT` block

An embedded `@ANT` marker near the end of an `.ana` file is therefore not, by itself, evidence of truncation.

## Parser Rules That Fit This Sample

A parser or extractor for this archive family should:

1. parse all valid `0x50` entries, including singleton runs
2. treat the root table as storage-pool metadata rather than a direct file table
3. resolve file locations with `physical_offset = pool_base + offset_stored`
4. trust stored file size first
5. support split pools such as `staffroll`
6. allow for nodes that may contain both child pools and direct files
7. for hierarchical KPDs, choose child-pool spacing from the archive's own `data_size` fit rather than assuming `0x800`
8. support at least two checked child-pool alignments: `0x800` and `0x10`
9. expect many nested archives to resolve correctly at raw file offset `0` once the correct child-pool alignment is used

## Remaining Open Items

- the exact role of the structured block at `0x0800-0x0FFF`
- the exact role of the metadata between `0x1AF0` and `0x2800`
- the exact meaning of header field `0x20`
- the owner of the reserved gap before the `voice` pool
- full routing rules for `staffroll` sub-pools
- detailed field semantics for `STFR`, `MOTC`, `BTTK`, `.pbd`, and `COLS`
