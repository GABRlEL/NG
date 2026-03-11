# KPD Format Research Notes

This document was produced from:

- `kpd_documentation.txt`
- static analysis of `pyKPDTool.pysrc.txt`
- direct binary inspection of `psp_ng_DATAPACK.KPD`

The goal is to separate what is confirmed from what is still inferred.

## Scope

High-confidence results in this note are backed by the provided `psp_ng_DATAPACK.KPD` sample. Claims about other archives or variants should be treated as provisional unless they are rechecked against more files.

## Confirmed High-Level Layout

For `psp_ng_DATAPACK.KPD`:

- File magic: `DPLK`
- Version field: `0x00000100`
- File size: `0x11EE8000` (`300,843,008`)
- Main data area starts at `0x76800`
- Main data area size is `0x11E71800`, which equals `file_size - data_start`
- File-entry records are `0x50` bytes
- The archive is sector-aligned on `0x800` boundaries

Observed top-level layout:

| Range | Meaning | Confidence |
| --- | --- | --- |
| `0x0000-0x07FF` | Main header | Confirmed |
| `0x0800-0x0FFF` | Secondary structured block, not plain padding | Confirmed |
| `0x1000-0x1AEF` | Root entry table (`35` directory entries) | Confirmed |
| `0x1AF0-0x767FF` | Additional structured index data, entry runs, single-entry runs, and padding/descriptor blocks | Confirmed |
| `0x76800-EOF` | File data region | Confirmed |

## Main Header

The Python tool treats several header fields as `u32`, but the file uses `8-byte` spacing and the sample reads cleanly as `u64` fields with zero high dwords.

| Offset | Type | Value in sample | Notes |
| --- | --- | --- | --- |
| `0x00` | `char[4]` | `DPLK` | Archive magic |
| `0x04` | `u32` | `0x00000100` | Version |
| `0x08` | `u32` | `0x11EE8000` | File size low 32 bits |
| `0x10` | `u64` | `0x800` | Alignment-related |
| `0x18` | `u64` | `0x800` | Alignment-related |
| `0x20` | `u64` | `0x76000` | End of populated index area |
| `0x28` | `u64` | `0x76800` | Start of data area |
| `0x30` | `u64` | `0x11E71800` | Data area size; equals `file_size - data_start` |

The `0x30` field is not an unknown value in this sample. It is exactly the size of the data region.

## Entry Record (`0x50` bytes)

The community note about `0x50`-byte entries and a `0x36`-byte name field is correct.

| Offset | Type | Meaning | Confidence |
| --- | --- | --- | --- |
| `0x00` | `u32` | Entry type | Confirmed |
| `0x04` | `u32` | Always `0` in this sample | Confirmed |
| `0x08` | `u64` | Stored offset | Confirmed |
| `0x10` | `u64` | Stored size | Confirmed |
| `0x18` | `u16` | Always `0xFFFF` in this sample | Confirmed |
| `0x1A` | `char[0x36]` | ASCII name/path, NUL-padded | Confirmed |

Observed entry type values:

- `0`: directory/storage-pool entry
- `1`: file entry

Observed name behavior:

- Names are ASCII.
- Names may be plain basenames like `emotion.ana`.
- Names may also contain slashes like `battleevent/00_00_000_01_p00pack.kpd`.

Alignment facts:

- All observed `offset` values are `0x800` aligned.
- All observed directory `size` values are `0x800` aligned.
- File sizes are not generally `0x800` aligned.

## Index Runs

The supplied tool is directionally correct that the index is split into many short runs separated by gaps, but it is incomplete.

### What is confirmed

- Every entry starts on a `0x10` boundary.
- Contiguous entries form runs of `0x50`-byte records.
- The root table starts at `0x1000`.
- The sample contains `439` runs total before the data area if singleton runs are included.
- Run-length distribution is heavily skewed toward singletons.

Observed counts in this sample:

- Total directory entries: `39`
- Total file entries: `2369`
- Total entries: `2408`
- Runs of length `1`: `189`

### Why this matters

`pyKPDTool.pysrc.txt` only records runs where `n >= 2`. That drops:

- `188` file entries
- `1` directory entry
- `189` runs total

That is the single biggest bug in the current tooling.

Examples of valid singleton runs the current tool misses:

- `ana/bt_st_text.ana`
- `efa/healing.efa`
- `motion/battle_mot_00_04.gmo`
- `script/battle0000.lbn`
- `cam.gmo`
- `dlc.ana`
- `mis.ana`
- `motion/menu_motion.gmo`
- `en_logo.ana`
- `staffroll_00.bin`
- many voice files such as `000/000_009.at3`

## Root Table and Metadata Ranges

The first run at `0x1000` is a root directory/storage-pool table with `35` entries. Its `offset/size` pairs map cleanly onto later metadata ranges starting at `0x2800`.

Examples:

- Root entry `ana`: `offset=0x0`, `size=0x1000` maps to metadata range `0x2800-0x37FF`
- Root entry `battle`: `offset=0x1000`, `size=0x8000` maps to metadata range `0x3800-0xB7FF`
- Root entry `bgm`: `offset=0x9800`, `size=0x1800` maps to metadata range `0xC000-0xD7FF`

This is strong evidence that the first table indexes metadata pools, not direct file-data offsets.

Important consequence:

- The root entry names are storage buckets, not a reliable reconstruction of the visible path tree.

Examples:

- `pkdata` contains many `battleevent/*.kpd` and `script/*.kpd` files
- `battleevent` as a root entry does not directly contain those `battleevent/*.kpd` file records

## Inferred Data-Pool Model

This is the model that best fits the sample and validates against actual file headers.

### Confirmed behavior

- File `offset` values are relative, not absolute file positions.
- A large part of the archive can be explained by top-level storage pools laid out sequentially from `0x76800`.
- When the correct pool base is used, the stored offsets land directly on valid file headers. No sliding or magic hunting is needed.

### Verified pool bases

These bases were confirmed against real file headers in the sample:

| Pool | Metadata Range | Inferred/Verified Data Base | Files |
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

### Special case: `voice`

`voice` does not line up with the naive top-level accumulation unless its base is shifted to `0xFDB5000`.

That base is strongly supported because:

- it makes all `774` voice `.at3` files start with `RIFF....WAVEfmt `
- it closes the archive layout cleanly near the end of the file

This suggests an extra reserved gap before `voice`. The exact owner of that gap is still unresolved.

### Special case: `staffroll`

`staffroll` is not a single flat pool. It contains duplicate stored offset `0x0` across different file types, so it must be split internally.

Observed working sub-bases:

- `2d` / `en_logo.ana`: `0xFDA2800`
- `bin` / `staffroll_00.bin`: `0xFDAB000`
- `msg` / `msg_staffroll*.mwm`: `0xFDAF000`

This is also the clearest proof that some apparent padding blocks are really structural separators between sub-pools.

### Edge case: mixed child/data nodes

This edge case was not observed in `psp_ng_DATAPACK.KPD`, but it matters for extractor design.

A valid node of the same archive family may contain both:

- direct file entries with stored offsets relative to that node's data base
- nested child directories/sub-pools whose data spans also live inside that same node

An extractor cannot safely treat such a node as "children only" or "files only". It needs to:

- include both the summed child span and the direct-file end when computing the node span
- still assign `physical = node_base + stored_offset` for the direct files
- warn if a direct file starts inside the implied child-data prefix, because that layout is structurally ambiguous without more evidence

This is not a confirmed feature of the provided sample, but it is a real modeling edge case for future archives of the same family.

## Verified File Signatures

Using the base model above, these signatures were verified exhaustively in the sample:

| Extension | Verified Count | Header |
| --- | --- | --- |
| `.ana` | `30/30` | `@ANA 00 00 00` |
| `.gmo` | `710/710` | `OMG.00.1PSP` |
| `.gim` | `68/68` | `MIG.00.1PSP` |
| `.at3` | `801/801` | `RIFF .... WAVEfmt ` |
| `.lbn` | `69/69` | Lua bytecode: `1B 4C 75 61 51 00 01 04 04 04 08 00 00 00 00 00` |
| `.mwm` | `65/65` | `MWMS 00 00 01 00 14 00 00 00` |
| `.png` | `8/8` | Standard PNG header |
| `.phd` | `4/4` | `PPHD8 00 00 00 00 00 01 00` |
| `.kpd` | `349/349` | `DPLK 00 01 00 00` |
| `.efa` | `31/31` | `45 46 41 00` (`EFA\\0`) |
| `.bin` | `1/1` | `53 54 46 52 00 00 01 00 14 00 00 00` (`STFR...`) |

New findings not present in the supplied Python tool:

- `.efa` is a real, consistent magic-bearing format: `EFA\\0`
- `staffroll_00.bin` is not generic binary garbage; it has an `STFR` header
- nested `.kpd` files are confirmed and abundant (`349` entries)

Formats still unclear from this sample:

- `.pbd`: all four observed files begin with zero bytes
- `.luc`: only one sample; begins with ASCII `--==============`
- most `.dat` files are not a single format

Observed `.dat` subtypes:

- `think/battlethink*.dat`: `BTTK`
- `motion/exmotset/*.dat`: begins with `24 00 00 00`
- `motion/battlecharamotionsequence.dat`: begins with `14 00 00 00`

## What the Community Notes Got Right

- The archive does store many game files inside a single container.
- Entry size for this sample is `0x50`.
- The filename field is `0x36` bytes and NUL-padded.
- The index is split into many short runs rather than one continuous table.
- The current extraction problem is tied to relative offsets, not just to filename parsing.

## What the Community Notes Need Correction

### 1. The gaps are not just padding

The gaps between runs are not merely random `00`/`FF` padding with mysterious noise inside them.

In this sample, those gaps contain:

- valid single-entry tables
- nested directory entries
- secondary structured metadata blocks

So the “random gaps” are not the key to offset correction by themselves. A large part of the problem is that the archive structure is richer than the current parser assumes.

### 2. “Offsets do not account for padding” is incomplete

The current data suggests a more precise statement:

- offsets are relative to pool bases
- the archive contains multiple pools/sub-pools
- stored offsets already include the holes inside those pools

In other words, the core problem is not “global padding must be added to every offset.” The core problem is “the correct base changes by pool, and the current tool fails to model that.”

### 3. Not every visible path prefix has a matching root bucket

The first table is not a direct path tree. For example:

- `battleevent/*.kpd` files live under the `pkdata` storage pool
- `staffroll` is internally split into sub-pools

## Fact-Check of `pyKPDTool.pysrc.txt`

### Correct or mostly correct

- `ENTRY_SIZE = 0x50` is correct for this sample.
- The `name` field starts at `0x1A`.
- `type 0` vs `type 1` is a useful distinction.
- The known magic values for `.ana`, `.gmo`, `.gim`, `.at3`, `.lbn`, `.mwm`, `.png`, `.phd`, and `.kpd` are correct when the right pool base is used.

### Incorrect or misleading

#### `find_table_runs()` drops valid entries

This is the largest issue.

- The function only accepts runs where `n >= 2`.
- The sample contains `189` valid singleton runs.
- That means the dump phase misses `189` entries immediately.

#### Per-run base solving is too granular

Many runs belong to a larger shared pool.

Example:

- the `battle` pool uses one verified base `0x110800` for hundreds of files
- the current resolver instead invents multiple unrelated bases across its sub-runs

That behavior is a symptom of matching on magic hits inside the wrong structural model.

#### The resolver is vulnerable to false anchors

Because it scans the whole file for known magics and scores runs independently:

- common formats like `.kpd`, `.at3`, `.gmo`, `.lbn`, and `.mwm` can produce plausible but wrong anchors
- the chosen base can be structurally wrong even if a few headers happen to line up

#### Header field naming is too weak

The fields at `0x20`, `0x28`, and `0x30` should not be left as vague `ptr/unk` values for this sample:

- `0x28` is the data start
- `0x30` is the data size

Also, these fields are better treated as `u64`-spaced header fields, even if the sample keeps them below `2^32`.

### Practical consequence

The tool’s current failures are not mainly caused by unknown magics. They begin earlier:

1. it misses singleton tables
2. it models many real pools as unrelated per-run bases
3. it relies on global magic searches instead of archive structure

## Open Questions

- The exact role of the structured block at `0x800-0x0FFF` is still unresolved.
- The exact role of the structured data between `0x1AF0` and `0x2800` is still unresolved.
- The remaining empty top-level buckets likely explain the extra reserved gap before `voice`, but that is still an inference.
- `staffroll` clearly uses sub-pools, but the rule that maps its nested directory entries to those sub-bases is still incomplete.
- `.pbd`, `.luc`, and several `.dat` subtypes still need dedicated format work.

## Recommended Extraction Strategy

Based on this sample, a better extractor should:

1. parse every valid `0x50`-byte entry, including singleton runs
2. keep root/storage-pool structure instead of treating each short run as an independent data base
3. assign pool bases structurally, then use `physical = pool_base + stored_offset`
4. trust stored size first; use next-offset only as a sanity check
5. handle special split pools like `staffroll`
6. support nodes that contain both child pools and direct files instead of treating those cases as leaves or parents only

That should remove most of the current need for sliding bytes until a magic happens to match.
