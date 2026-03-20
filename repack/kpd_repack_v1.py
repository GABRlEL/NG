#!/usr/bin/env python3

import argparse
import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyKPDTool_rebuilt_v4 import (
    ALIGNMENT_DEFAULT,
    ENTRY_SIZE_DEFAULT,
    KPDArchive,
    LayoutBuilder,
    Node,
    Entry,
    align_up,
    entry_output_name,
)


CANDIDATE_ALIGNMENTS = [0x800, 0x400, 0x200, 0x100, 0x80, 0x40, 0x20, 0x10, 1]


class RepackError(RuntimeError):
    pass


@dataclass
class ParsedArchive:
    path: str
    archive: KPDArchive
    builder: LayoutBuilder
    layout_name: str
    root_id: str
    nodes: dict[str, Node]
    warnings: list[str]
    flat_end_alignment: int
    file_entries: list[Entry]
    file_entries_by_id: dict[str, Entry]
    original_offset_by_id: dict[str, int]
    original_size_by_id: dict[str, int]
    original_physical_by_id: dict[str, int]


@dataclass
class Segment:
    kind: str
    ref_id: str
    original_offset: int
    original_size: int
    order_key: tuple[int, int]


@dataclass
class Replacement:
    entry_id: str
    target: str
    source_path: str
    blob: bytes


def positive_int(value: str) -> int:
    return int(value, 0)


def file_output_name(entry: Entry) -> str:
    return entry_output_name({"name": entry.name, "node_id": entry.node_id})


def infer_flat_end_alignment(archive: KPDArchive, root: Node) -> int:
    offsets = [archive.entries[entry_id].offset_stored for entry_id in root.file_entry_ids]
    data_size = archive.header.data_size_u64
    for candidate in CANDIDATE_ALIGNMENTS:
        if data_size % candidate != 0:
            continue
        if all(offset % candidate == 0 for offset in offsets):
            return candidate
    return 1


def parse_archive(path: str, layout: str, entry_size: int, allow_warnings: bool) -> ParsedArchive:
    archive = KPDArchive(path=path, entry_size=entry_size, alignment=ALIGNMENT_DEFAULT)
    builder = LayoutBuilder(archive)
    layout_name, root_id, nodes, warnings = builder.build(layout)
    if warnings and not allow_warnings:
        raise RepackError("Refusing to repack archive with layout warnings:\n" + "\n".join(warnings))

    root = nodes[root_id]
    flat_end_alignment = infer_flat_end_alignment(archive, root) if layout_name == "flat" else builder.child_pool_alignment
    file_entries = [entry for entry in archive.entries.values() if entry.type == 1]
    file_entries.sort(key=lambda entry: entry.entry_pos)
    original_offset_by_id = {entry.entry_id: entry.offset_stored for entry in file_entries}
    original_size_by_id = {entry.entry_id: entry.size for entry in file_entries}
    original_physical_by_id = {}
    for entry in file_entries:
        if entry.physical_offset is None:
            raise RepackError(f"Entry has no physical offset: {entry.name}")
        original_physical_by_id[entry.entry_id] = entry.physical_offset

    return ParsedArchive(
        path=path,
        archive=archive,
        builder=builder,
        layout_name=layout_name,
        root_id=root_id,
        nodes=nodes,
        warnings=warnings,
        flat_end_alignment=flat_end_alignment,
        file_entries=file_entries,
        file_entries_by_id={entry.entry_id: entry for entry in file_entries},
        original_offset_by_id=original_offset_by_id,
        original_size_by_id=original_size_by_id,
        original_physical_by_id=original_physical_by_id,
    )


def original_blob(parsed: ParsedArchive, entry_id: str) -> bytes:
    start = parsed.original_physical_by_id[entry_id]
    size = parsed.original_size_by_id[entry_id]
    return parsed.archive.buf[start:start + size]


def build_segments(parsed: ParsedArchive, node_id: str) -> list[Segment]:
    node = parsed.nodes[node_id]
    segments: list[Segment] = []

    for child_id in node.child_ids:
        child = parsed.nodes[child_id]
        if child.data_base is None or node.data_base is None:
            raise RepackError(f"Node lacks data base for child segment: {child_id}")
        dir_entry_pos = parsed.archive.entries[child.dir_entry_id].entry_pos if child.dir_entry_id else -1
        segments.append(
            Segment(
                kind="child",
                ref_id=child_id,
                original_offset=child.data_base - node.data_base,
                original_size=child.span_aligned,
                order_key=(child.data_base - node.data_base, dir_entry_pos),
            )
        )

    for entry_id in node.file_entry_ids:
        entry = parsed.archive.entries[entry_id]
        segments.append(
            Segment(
                kind="file",
                ref_id=entry_id,
                original_offset=parsed.original_offset_by_id[entry_id],
                original_size=parsed.original_size_by_id[entry_id],
                order_key=(parsed.original_offset_by_id[entry_id], entry.entry_pos),
            )
        )

    segments.sort(key=lambda segment: segment.order_key)
    return segments


def node_end_alignment(parsed: ParsedArchive) -> int:
    if parsed.layout_name == "ng-datapack":
        return parsed.builder.child_pool_alignment
    return parsed.flat_end_alignment


def rebuild_node(
    parsed: ParsedArchive,
    node_id: str,
    replacements: dict[str, Replacement],
    rebuilt_spans: dict[str, int],
) -> bytes:
    node = parsed.nodes[node_id]
    cursor = 0
    previous_original_end = 0
    pieces: list[tuple[int, bytes]] = []

    for segment in build_segments(parsed, node_id):
        gap = segment.original_offset - previous_original_end
        if gap < 0:
            raise RepackError(
                f"Original segment overlap in node {node_id}: {segment.ref_id} starts at "
                f"{segment.original_offset:#x} before previous end {previous_original_end:#x}"
            )
        cursor += gap
        if segment.kind == "child":
            child_blob = rebuild_node(parsed, segment.ref_id, replacements, rebuilt_spans)
            pieces.append((cursor, child_blob))
            rebuilt_spans[segment.ref_id] = len(child_blob)
            cursor += len(child_blob)
        else:
            replacement = replacements.get(segment.ref_id)
            blob = replacement.blob if replacement is not None else original_blob(parsed, segment.ref_id)
            entry = parsed.archive.entries[segment.ref_id]
            entry.offset_stored = cursor
            entry.size = len(blob)
            pieces.append((cursor, blob))
            cursor += len(blob)
        previous_original_end = segment.original_offset + segment.original_size

    total_size = align_up(cursor, node_end_alignment(parsed)) if cursor else 0
    out = bytearray(total_size)
    for offset, blob in pieces:
        out[offset:offset + len(blob)] = blob

    rebuilt_spans[node_id] = len(out)
    return bytes(out)


def patch_metadata(parsed: ParsedArchive, data_region: bytes) -> bytes:
    data_start = parsed.archive.header.data_start_u64
    out = bytearray(parsed.archive.buf[:data_start])

    for entry in parsed.file_entries:
        struct.pack_into("<Q", out, entry.entry_pos + 8, entry.offset_stored)
        struct.pack_into("<Q", out, entry.entry_pos + 16, entry.size)

    total_file_size = len(out) + len(data_region)
    if total_file_size > 0xFFFFFFFF:
        raise RepackError(f"Output file is too large for u32 header size field: {total_file_size:#x}")

    struct.pack_into("<I", out, 8, total_file_size)
    struct.pack_into("<Q", out, 0x30, len(data_region))
    return bytes(out) + data_region


def build_name_maps(parsed: ParsedArchive) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    exact: dict[str, list[str]] = {}
    basename: dict[str, list[str]] = {}
    for entry in parsed.file_entries:
        names = {entry.name, file_output_name(entry)}
        for name in names:
            exact.setdefault(name, []).append(entry.entry_id)
            base = Path(name).name
            basename.setdefault(base, []).append(entry.entry_id)
    return exact, basename


def resolve_entry_id(parsed: ParsedArchive, target: str, exact_map: dict[str, list[str]], basename_map: dict[str, list[str]]) -> str:
    candidates = exact_map.get(target, [])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise RepackError(f"Ambiguous replacement target '{target}' matches multiple exact entries")

    base_candidates = basename_map.get(Path(target).name, [])
    if len(base_candidates) == 1:
        return base_candidates[0]
    if len(base_candidates) > 1:
        raise RepackError(f"Ambiguous replacement target '{target}' matches multiple basenames")

    raise RepackError(f"Replacement target not found: {target}")


def parse_replacement_specs(parsed: ParsedArchive, specs: list[str]) -> dict[str, Replacement]:
    exact_map, basename_map = build_name_maps(parsed)
    replacements: dict[str, Replacement] = {}
    for spec in specs:
        if "=" not in spec:
            raise RepackError(f"Invalid --replace value '{spec}', expected ARCHIVE_NAME=LOCAL_PATH")
        target, source_path = spec.split("=", 1)
        entry_id = resolve_entry_id(parsed, target, exact_map, basename_map)
        entry = parsed.file_entries_by_id[entry_id]
        if entry.normalization_note is not None:
            raise RepackError(
                f"Refusing to repack normalized-only entry '{entry.name}' ({entry.normalization_note}). "
                "kpd_repack_v1 only supports raw standalone archive members."
            )
        blob = Path(source_path).read_bytes()
        replacements[entry_id] = Replacement(
            entry_id=entry_id,
            target=target,
            source_path=source_path,
            blob=blob,
        )
    return replacements


def verify_output(source: ParsedArchive, out_path: str, replacements: dict[str, Replacement]) -> list[str]:
    try:
        rebuilt = parse_archive(out_path, source.layout_name, source.archive.entry_size, allow_warnings=False)
    except Exception as exc:  # pragma: no cover - surfaced in CLI output
        return [f"Failed to re-parse rebuilt archive: {exc}"]

    errors: list[str] = []
    if rebuilt.layout_name != source.layout_name:
        errors.append(f"Layout changed from {source.layout_name} to {rebuilt.layout_name}")

    if source.archive.header.data_start_u64 != rebuilt.archive.header.data_start_u64:
        errors.append(
            f"data_start changed from {source.archive.header.data_start_u64:#x} "
            f"to {rebuilt.archive.header.data_start_u64:#x}"
        )

    if len(rebuilt.file_entries) != len(source.file_entries):
        errors.append(f"File count changed from {len(source.file_entries)} to {len(rebuilt.file_entries)}")
        return errors

    rebuilt_by_id = rebuilt.file_entries_by_id
    for entry in source.file_entries:
        other = rebuilt_by_id.get(entry.entry_id)
        if other is None:
            errors.append(f"Missing entry in rebuilt archive: {entry.entry_id} {entry.name}")
            if len(errors) >= 25:
                break
            continue
        if other.name != entry.name:
            errors.append(f"Entry name changed for {entry.entry_id}: {entry.name} -> {other.name}")
            if len(errors) >= 25:
                break
            continue
        expected = replacements.get(entry.entry_id).blob if entry.entry_id in replacements else original_blob(source, entry.entry_id)
        if other.size != len(expected):
            errors.append(f"Size mismatch for {entry.name}: expected {len(expected):#x}, got {other.size:#x}")
            if len(errors) >= 25:
                break
            continue
        if other.physical_offset is None:
            errors.append(f"Missing physical offset for rebuilt entry {entry.name}")
            if len(errors) >= 25:
                break
            continue
        actual = rebuilt.archive.buf[other.physical_offset:other.physical_offset + other.size]
        if actual != expected:
            errors.append(f"Payload mismatch for {entry.name}")
            if len(errors) >= 25:
                break

    if rebuilt.archive.header.file_size_u32 != rebuilt.archive.file_size:
        errors.append(
            f"Header file_size_u32 mismatch: {rebuilt.archive.header.file_size_u32:#x} vs actual {rebuilt.archive.file_size:#x}"
        )
    if rebuilt.archive.header.data_size_u64 != rebuilt.archive.file_size - rebuilt.archive.header.data_start_u64:
        errors.append(
            f"Header data_size_u64 mismatch: {rebuilt.archive.header.data_size_u64:#x} vs actual "
            f"{(rebuilt.archive.file_size - rebuilt.archive.header.data_start_u64):#x}"
        )

    return errors


def report_for_repack(parsed: ParsedArchive, out_path: str, replacements: dict[str, Replacement], verification_errors: list[str]) -> dict[str, Any]:
    return {
        "tool": "kpd_repack_v1",
        "source_path": parsed.path,
        "layout": parsed.layout_name,
        "entry_size": parsed.archive.entry_size,
        "child_pool_alignment": parsed.builder.child_pool_alignment,
        "flat_end_alignment": parsed.flat_end_alignment,
        "warnings": parsed.warnings,
        "output_path": out_path,
        "replacement_count": len(replacements),
        "replacements": [
            {
                "entry_id": replacement.entry_id,
                "name": parsed.file_entries_by_id[replacement.entry_id].name,
                "output_name": file_output_name(parsed.file_entries_by_id[replacement.entry_id]),
                "source_path": replacement.source_path,
                "new_size": len(replacement.blob),
            }
            for replacement in replacements.values()
        ],
        "verification": {
            "ok": not verification_errors,
            "error_count": len(verification_errors),
            "errors": verification_errors,
        },
    }


def cmd_list(args: argparse.Namespace) -> None:
    parsed = parse_archive(args.kpd, args.layout, args.entry_size, allow_warnings=args.allow_warnings)
    rows = []
    for entry in parsed.file_entries:
        rows.append(
            {
                "entry_id": entry.entry_id,
                "name": entry.name,
                "output_name": file_output_name(entry),
                "node_id": entry.node_id,
                "size": entry.size,
                "offset_stored": entry.offset_stored,
                "normalized": entry.normalization_note is not None,
                "normalization_note": entry.normalization_note,
            }
        )

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"Wrote list: {args.json_out}")
        print(f"Files: {len(rows)}")
        return

    print(f"Layout: {parsed.layout_name}")
    print(f"Files: {len(rows)}")
    if parsed.warnings:
        print("Warnings:")
        for warning in parsed.warnings:
            print(f"  {warning}")
    for row in rows:
        extra = f" normalized={row['normalization_note']}" if row["normalized"] else ""
        print(f"{row['output_name']} size={row['size']:#x} node={row['node_id']}{extra}")


def cmd_repack(args: argparse.Namespace) -> None:
    parsed = parse_archive(args.kpd, args.layout, args.entry_size, allow_warnings=args.allow_warnings)
    replacements = parse_replacement_specs(parsed, args.replace)

    if os.path.exists(args.out_kpd) and not args.overwrite:
        raise RepackError(f"Output already exists: {args.out_kpd}. Use --overwrite to replace it.")

    rebuilt_spans: dict[str, int] = {}
    data_region = rebuild_node(parsed, parsed.root_id, replacements, rebuilt_spans)
    out_buf = patch_metadata(parsed, data_region)
    Path(args.out_kpd).write_bytes(out_buf)

    verification_errors: list[str] = []
    if args.verify:
        verification_errors = verify_output(parsed, args.out_kpd, replacements)

    if args.report_json:
        report = report_for_repack(parsed, args.out_kpd, replacements, verification_errors)
        Path(args.report_json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote report: {args.report_json}")

    print(f"Wrote KPD: {args.out_kpd}")
    print(f"Layout: {parsed.layout_name}")
    print(f"Replacements: {len(replacements)}")
    print(f"Data size: {len(data_region):#x}")
    print(f"File size: {len(out_buf):#x}")
    if args.verify:
        print(f"Verify OK: {len(verification_errors) == 0}")
        if verification_errors:
            for error in verification_errors[:25]:
                print(f"  {error}")
            raise RepackError(f"Verification failed with {len(verification_errors)} error(s)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Conservative KPD repacker v1. Rebuilds the data region of supported 0x50-entry KPDs while preserving metadata bytes outside patched file offset/size fields."
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    list_parser = subparsers.add_parser("list", help="List repackable file entries in a KPD.")
    list_parser.add_argument("kpd")
    list_parser.add_argument("--layout", default="auto", choices=["auto", "flat", "ng-datapack"])
    list_parser.add_argument("--entry-size", type=positive_int, default=ENTRY_SIZE_DEFAULT)
    list_parser.add_argument("--json-out", help="Optional JSON output path for the file list.")
    list_parser.add_argument(
        "--allow-warnings",
        action="store_true",
        help="Allow archives that the parser marks with layout warnings.",
    )
    list_parser.set_defaults(fn=cmd_list)

    repack_parser = subparsers.add_parser("repack", help="Write a rebuilt KPD with one or more file replacements.")
    repack_parser.add_argument("kpd")
    repack_parser.add_argument("out_kpd")
    repack_parser.add_argument(
        "--replace",
        action="append",
        default=[],
        metavar="ARCHIVE_NAME=LOCAL_PATH",
        help="Replacement mapping. ARCHIVE_NAME can be the raw entry name, output name, or a unique basename. Repeat for multiple files.",
    )
    repack_parser.add_argument("--layout", default="auto", choices=["auto", "flat", "ng-datapack"])
    repack_parser.add_argument("--entry-size", type=positive_int, default=ENTRY_SIZE_DEFAULT)
    repack_parser.add_argument("--verify", action="store_true", help="Re-parse and compare the rebuilt archive after writing it.")
    repack_parser.add_argument("--report-json", help="Optional JSON report path.")
    repack_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite the output KPD if it already exists.",
    )
    repack_parser.add_argument(
        "--allow-warnings",
        action="store_true",
        help="Allow archives that the parser marks with layout warnings.",
    )
    repack_parser.set_defaults(fn=cmd_repack)

    args = parser.parse_args()
    try:
        args.fn(args)
    except RepackError as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
