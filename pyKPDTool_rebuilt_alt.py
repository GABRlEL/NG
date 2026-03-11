#!/usr/bin/env python3

import argparse
import fnmatch
import json
import os
import struct
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


ENTRY_SIZE_DEFAULT = 0x50
ALIGNMENT_DEFAULT = 0x800


KNOWN_SIGNATURES = {
    ".ana": b"@ANA \x00\x00\x00",
    ".gmo": b"OMG.00.1PSP",
    ".gim": b"MIG.00.1PSP",
    ".lbn": b"\x1bLuaQ\x00\x01\x04\x04\x04\x08\x00\x00\x00\x00\x00",
    ".mwm": b"MWMS\x00\x00\x01\x00\x14\x00\x00\x00",
    ".png": b"\x89PNG\x0D\x0A\x1A\x0A\x00\x00\x00\x0D\x49\x48\x44\x52",
    ".phd": b"PPHD8\x00\x00\x00\x00\x00\x01\x00",
    ".kpd": b"DPLK\x00\x01\x00\x00",
    ".efa": b"EFA\x00",
    ".bin": b"STFR\x00\x00\x01\x00\x14\x00\x00\x00",
}


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def ext_of(name: str) -> str:
    index = name.rfind(".")
    return name[index:].lower() if index != -1 else ""


def read_u32(buf: bytes, offset: int) -> int:
    return struct.unpack_from("<I", buf, offset)[0]


def read_u16(buf: bytes, offset: int) -> int:
    return struct.unpack_from("<H", buf, offset)[0]


def read_u64(buf: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", buf, offset)[0]


def signature_matches(ext: str, blob: bytes) -> bool | None:
    if ext == ".at3":
        return blob.startswith(b"RIFF") and blob[8:16] == b"WAVEfmt "
    sig = KNOWN_SIGNATURES.get(ext)
    if sig is None:
        return None
    return blob.startswith(sig)


def output_path_for_name(out_dir: str, name: str) -> str:
    return os.path.join(out_dir, name.replace("/", os.sep))


@dataclass
class Header:
    magic: str
    version_u32: int
    file_size_u32: int
    align0_u64: int
    align1_u64: int
    index_limit_u64: int
    data_start_u64: int
    data_size_u64: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "magic": self.magic,
            "version_u32": self.version_u32,
            "file_size_u32": self.file_size_u32,
            "align0_u64": self.align0_u64,
            "align1_u64": self.align1_u64,
            "index_limit_u64": self.index_limit_u64,
            "data_start_u64": self.data_start_u64,
            "data_size_u64": self.data_size_u64,
        }


@dataclass
class Entry:
    entry_id: str
    run_pos: int
    entry_pos: int
    index_in_run: int
    type: int
    zero_u32: int
    offset_stored: int
    size: int
    marker: int
    name: str
    node_id: str | None = None
    physical_offset: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "run_pos": self.run_pos,
            "entry_pos": self.entry_pos,
            "index_in_run": self.index_in_run,
            "type": self.type,
            "zero_u32": self.zero_u32,
            "offset_stored": self.offset_stored,
            "size": self.size,
            "marker": self.marker,
            "name": self.name,
            "node_id": self.node_id,
            "physical_offset": self.physical_offset,
        }


@dataclass
class Run:
    run_index: int
    run_pos: int
    end_pos: int
    entry_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_index": self.run_index,
            "run_pos": self.run_pos,
            "end_pos": self.end_pos,
            "count": len(self.entry_ids),
            "entry_ids": self.entry_ids,
        }


@dataclass
class Node:
    node_id: str
    name: str
    meta_start: int
    meta_end: int
    depth: int
    dir_entry_id: str | None = None
    child_table_run_positions: list[int] = field(default_factory=list)
    child_ids: list[str] = field(default_factory=list)
    file_entry_ids: list[str] = field(default_factory=list)
    data_base: int | None = None
    span_aligned: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "meta_start": self.meta_start,
            "meta_end": self.meta_end,
            "depth": self.depth,
            "dir_entry_id": self.dir_entry_id,
            "child_table_run_positions": self.child_table_run_positions,
            "child_ids": self.child_ids,
            "file_entry_ids": self.file_entry_ids,
            "data_base": self.data_base,
            "span_aligned": self.span_aligned,
        }


class KPDArchive:
    def __init__(self, path: str, entry_size: int = ENTRY_SIZE_DEFAULT, alignment: int = ALIGNMENT_DEFAULT):
        self.path = path
        self.entry_size = entry_size
        self.alignment = alignment
        self.buf = Path(path).read_bytes()
        self.file_size = len(self.buf)
        self.header = self._parse_header()
        self.index_scan_limit = min(self.header.data_start_u64, self.file_size)
        self.entries: dict[str, Entry] = {}
        self.runs: list[Run] = []
        self._runs_by_pos: dict[int, Run] = {}
        self._entries_by_pos: list[Entry] = []
        self._parse_runs()

    def _parse_header(self) -> Header:
        return Header(
            magic=self.buf[0:4].decode("ascii", "ignore"),
            version_u32=read_u32(self.buf, 4),
            file_size_u32=read_u32(self.buf, 8),
            align0_u64=read_u64(self.buf, 0x10),
            align1_u64=read_u64(self.buf, 0x18),
            index_limit_u64=read_u64(self.buf, 0x20),
            data_start_u64=read_u64(self.buf, 0x28),
            data_size_u64=read_u64(self.buf, 0x30),
        )

    def _looks_like_entry(self, offset: int) -> bool:
        if offset < 0 or offset + self.entry_size > self.index_scan_limit:
            return False
        if read_u32(self.buf, offset + 4) != 0:
            return False
        if read_u16(self.buf, offset + 24) != 0xFFFF:
            return False
        size = read_u64(self.buf, offset + 16)
        if size == 0 or size > 0x7FFFFFFF:
            return False
        name = self.buf[offset + 26:offset + self.entry_size].split(b"\x00", 1)[0]
        if not (1 <= len(name) <= 52):
            return False
        if any(c < 0x20 or c >= 0x7F for c in name):
            return False
        return True

    def _entry_from_offset(self, offset: int, run_pos: int, index_in_run: int) -> Entry:
        name = self.buf[offset + 26:offset + self.entry_size].split(b"\x00", 1)[0].decode("ascii", "ignore")
        entry_id = f"entry_{offset:08X}"
        return Entry(
            entry_id=entry_id,
            run_pos=run_pos,
            entry_pos=offset,
            index_in_run=index_in_run,
            type=read_u32(self.buf, offset),
            zero_u32=read_u32(self.buf, offset + 4),
            offset_stored=read_u64(self.buf, offset + 8),
            size=read_u64(self.buf, offset + 16),
            marker=read_u16(self.buf, offset + 24),
            name=name,
        )

    def _parse_runs(self) -> None:
        offset = 0
        run_index = 0
        while offset < self.index_scan_limit:
            if self._looks_like_entry(offset) and not self._looks_like_entry(offset - self.entry_size):
                run_pos = offset
                cur = offset
                entry_ids: list[str] = []
                index_in_run = 0
                while self._looks_like_entry(cur):
                    entry = self._entry_from_offset(cur, run_pos, index_in_run)
                    self.entries[entry.entry_id] = entry
                    self._entries_by_pos.append(entry)
                    entry_ids.append(entry.entry_id)
                    index_in_run += 1
                    cur += self.entry_size
                run = Run(run_index=run_index, run_pos=run_pos, end_pos=cur, entry_ids=entry_ids)
                self.runs.append(run)
                self._runs_by_pos[run_pos] = run
                run_index += 1
                offset = cur
                continue
            offset += 0x10
        self._entries_by_pos.sort(key=lambda entry: entry.entry_pos)

    def stats(self) -> dict[str, int]:
        type_counter = Counter(entry.type for entry in self.entries.values())
        return {
            "run_count": len(self.runs),
            "singleton_run_count": sum(1 for run in self.runs if len(run.entry_ids) == 1),
            "entry_count": len(self.entries),
            "directory_entry_count": type_counter.get(0, 0),
            "file_entry_count": type_counter.get(1, 0),
        }

    def validate_signature(self, entry: Entry) -> bool | None:
        if entry.physical_offset is None:
            return None
        end = min(entry.physical_offset + 0x20, self.file_size)
        return signature_matches(ext_of(entry.name), self.buf[entry.physical_offset:end])


class LayoutBuilder:
    def __init__(self, archive: KPDArchive):
        self.archive = archive
        self.nodes: dict[str, Node] = {}
        self.warnings: list[str] = []

    def build(self, layout: str) -> tuple[str, str, dict[str, Node], list[str]]:
        if layout == "flat":
            root_id = self._build_flat()
            return layout, root_id, self.nodes, self.warnings
        if layout == "ng-datapack":
            root_id = self._build_ng_datapack(strict=True)
            return layout, root_id, self.nodes, self.warnings
        if layout != "auto":
            raise ValueError(f"Unsupported layout: {layout}")

        try:
            root_id = self._build_ng_datapack(strict=False)
        except ValueError:
            self.nodes.clear()
            self.warnings.clear()
            root_id = self._build_flat()
            return "flat", root_id, self.nodes, self.warnings

        root = self.nodes[root_id]
        nonempty_children = sum(1 for child_id in root.child_ids if self.nodes[child_id].span_aligned > 0)
        if nonempty_children >= 2:
            return "ng-datapack", root_id, self.nodes, self.warnings

        self.nodes.clear()
        self.warnings.clear()
        root_id = self._build_flat()
        return "flat", root_id, self.nodes, self.warnings

    def _build_flat(self) -> str:
        root_id = "root"
        root = Node(
            node_id=root_id,
            name="root",
            meta_start=0,
            meta_end=self.archive.index_scan_limit,
            depth=0,
            data_base=self.archive.header.data_start_u64,
        )
        max_end = 0
        for entry in self.archive._entries_by_pos:
            if entry.type != 1:
                continue
            entry.node_id = root_id
            entry.physical_offset = root.data_base + entry.offset_stored
            root.file_entry_ids.append(entry.entry_id)
            max_end = max(max_end, entry.offset_stored + entry.size)
        root.span_aligned = align_up(max_end, self.archive.alignment) if max_end else 0
        self.nodes[root_id] = root
        return root_id

    def _build_ng_datapack(self, strict: bool) -> str:
        if not self.archive.runs:
            raise ValueError("No index runs found")
        root_run = self.archive.runs[0]
        root_entries = [self.archive.entries[entry_id] for entry_id in root_run.entry_ids]
        if not root_entries or any(entry.type != 0 for entry in root_entries):
            raise ValueError("First run is not a directory table")
        if len(self.archive.runs) < 2:
            raise ValueError("Not enough runs for hierarchical layout")

        child_meta_base = min(run.run_pos for run in self.archive.runs[1:])
        root_id = "root"
        root = Node(
            node_id=root_id,
            name="root",
            meta_start=root_run.run_pos,
            meta_end=self.archive.index_scan_limit,
            depth=0,
            child_table_run_positions=[root_run.run_pos],
        )
        self.nodes[root_id] = root

        for entry in root_entries:
            child_id = f"{root_id}/{entry.name}"
            child_start = child_meta_base + entry.offset_stored
            child_end = child_start + entry.size
            child = self._build_node(
                node_id=child_id,
                name=entry.name,
                meta_start=child_start,
                meta_end=child_end,
                depth=1,
                dir_entry=entry,
            )
            root.child_ids.append(child.node_id)

        self._compute_span(self.nodes[root_id])
        self._assign_bases(self.nodes[root_id], self.archive.header.data_start_u64)

        expected_span = self.archive.header.data_size_u64
        actual_span = self.nodes[root_id].span_aligned
        if actual_span != expected_span:
            message = f"Hierarchical span mismatch: computed {actual_span:#x}, expected {expected_span:#x}"
            if strict:
                raise ValueError(message)
            self.warnings.append(message)

        return root_id

    def _entries_in_range(self, start: int, end: int) -> list[Entry]:
        return [entry for entry in self.archive._entries_by_pos if start <= entry.entry_pos < end]

    def _build_node(self, node_id: str, name: str, meta_start: int, meta_end: int, depth: int, dir_entry: Entry) -> Node:
        entries = self._entries_in_range(meta_start, meta_end)
        node = Node(
            node_id=node_id,
            name=name,
            meta_start=meta_start,
            meta_end=meta_end,
            depth=depth,
            dir_entry_id=dir_entry.entry_id,
        )
        self.nodes[node_id] = node
        if not entries:
            return node

        first_run = self.archive._runs_by_pos[entries[0].run_pos]
        first_type1_pos = min((entry.entry_pos for entry in entries if entry.type == 1), default=None)
        child_table_runs: list[Run] = []
        if all(self.archive.entries[entry_id].type == 0 for entry_id in first_run.entry_ids):
            child_table_runs.append(first_run)
            next_run_pos = first_run.end_pos
            while next_run_pos in self.archive._runs_by_pos:
                run = self.archive._runs_by_pos[next_run_pos]
                if run.run_pos >= meta_end:
                    break
                if first_type1_pos is not None and run.run_pos >= first_type1_pos:
                    break
                if not all(self.archive.entries[entry_id].type == 0 for entry_id in run.entry_ids):
                    break
                child_table_runs.append(run)
                next_run_pos = run.end_pos
        node.child_table_run_positions = [run.run_pos for run in child_table_runs]

        dir_entries = [self.archive.entries[entry_id] for run in child_table_runs for entry_id in run.entry_ids]
        claimed_ranges: list[tuple[int, int]] = []
        if dir_entries:
            child_entries = [entry for entry in entries if entry.entry_id not in {dir_entry.entry_id for dir_entry in dir_entries}]
            if child_entries:
                child_meta_base = min(entry.entry_pos for entry in child_entries)
                for child_dir in dir_entries:
                    child_start = child_meta_base + child_dir.offset_stored
                    child_end = child_start + child_dir.size
                    child_id = f"{node_id}/{child_dir.name}"
                    child = self._build_node(
                        node_id=child_id,
                        name=child_dir.name,
                        meta_start=child_start,
                        meta_end=child_end,
                        depth=depth + 1,
                        dir_entry=child_dir,
                    )
                    node.child_ids.append(child.node_id)
                    claimed_ranges.append((child_start, child_end))

        def claimed(entry_pos: int) -> bool:
            return any(start <= entry_pos < end for start, end in claimed_ranges)

        for entry in entries:
            if entry.type != 1:
                continue
            if claimed(entry.entry_pos):
                continue
            entry.node_id = node.node_id
            node.file_entry_ids.append(entry.entry_id)

        if node.child_ids and node.file_entry_ids:
            self.warnings.append(f"Node {node.node_id} contains both child directories and direct files")

        return node

    def _compute_span(self, node: Node) -> int:
        child_span = sum(self._compute_span(self.nodes[child_id]) for child_id in node.child_ids)

        raw_file_end = 0
        for entry_id in node.file_entry_ids:
            entry = self.archive.entries[entry_id]
            raw_file_end = max(raw_file_end, entry.offset_stored + entry.size)

        raw_end = max(child_span, raw_file_end)
        node.span_aligned = align_up(raw_end, self.archive.alignment) if raw_end else 0
        return node.span_aligned

    def _assign_bases(self, node: Node, base: int) -> None:
        node.data_base = base
        child_prefix_span = 0
        if node.child_ids:
            cur = base
            for child_id in node.child_ids:
                child = self.nodes[child_id]
                self._assign_bases(child, cur)
                cur += child.span_aligned
            child_prefix_span = cur - base
        for entry_id in node.file_entry_ids:
            entry = self.archive.entries[entry_id]
            if child_prefix_span and entry.offset_stored < child_prefix_span:
                message = (
                    f"Node {node.node_id} direct file {entry.name} starts at {entry.offset_stored:#x} "
                    f"inside child data prefix {child_prefix_span:#x}"
                )
                if message not in self.warnings:
                    self.warnings.append(message)
            entry.physical_offset = base + entry.offset_stored


def serialize_manifest(
    archive: KPDArchive,
    layout_name: str,
    root_id: str,
    nodes: dict[str, Node],
    warnings: list[str],
) -> dict[str, Any]:
    signature_counter = Counter()
    verified_counter = Counter()
    file_entries = [entry for entry in archive.entries.values() if entry.type == 1]
    for entry in file_entries:
        ext = ext_of(entry.name)
        ok = archive.validate_signature(entry)
        if ok is not None:
            signature_counter[ext] += 1
            if ok:
                verified_counter[ext] += 1

    return {
        "tool": "pyKPDTool_rebuilt",
        "format_version": 1,
        "source_path": archive.path,
        "entry_size": archive.entry_size,
        "alignment": archive.alignment,
        "layout": layout_name,
        "root_node_id": root_id,
        "header": archive.header.to_dict(),
        "stats": archive.stats(),
        "warnings": warnings,
        "signature_verification": {
            ext: {
                "verified": verified_counter.get(ext, 0),
                "checked": signature_counter.get(ext, 0),
            }
            for ext in sorted(signature_counter)
        },
        "runs": [run.to_dict() for run in archive.runs],
        "nodes": [nodes[node_id].to_dict() for node_id in sorted(nodes)],
        "entries": [archive.entries[entry_id].to_dict() for entry_id in sorted(archive.entries)],
    }


def build_manifest(path: str, layout: str, entry_size: int) -> dict[str, Any]:
    archive = KPDArchive(path=path, entry_size=entry_size)
    builder = LayoutBuilder(archive)
    layout_name, root_id, nodes, warnings = builder.build(layout)
    return serialize_manifest(archive, layout_name, root_id, nodes, warnings)


def compact_bases_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    nodes = manifest.get("nodes", [])
    entries = manifest.get("entries", [])
    return {
        "tool": manifest.get("tool"),
        "format_version": manifest.get("format_version"),
        "layout": manifest.get("layout"),
        "root_node_id": manifest.get("root_node_id"),
        "header": manifest.get("header"),
        "nodes": [
            {
                "node_id": node["node_id"],
                "name": node["name"],
                "data_base": node["data_base"],
                "span_aligned": node["span_aligned"],
            }
            for node in nodes
        ],
        "files": [
            {
                "entry_id": entry["entry_id"],
                "name": entry["name"],
                "node_id": entry["node_id"],
                "physical_offset": entry["physical_offset"],
                "size": entry["size"],
            }
            for entry in entries
            if entry["type"] == 1
        ],
    }


def load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str, data: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=False)


def manifest_file_entries(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry for entry in manifest["entries"] if entry["type"] == 1]


def should_extract(name: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def cmd_dump(args: argparse.Namespace) -> None:
    manifest = build_manifest(args.kpd, args.layout, args.entry_size)
    write_json(args.out_json, manifest)
    print(f"Wrote manifest: {args.out_json}")
    print(f"Layout: {manifest['layout']}")
    print(f"Runs: {manifest['stats']['run_count']}")
    print(f"Entries: {manifest['stats']['entry_count']}")


def cmd_dump_bases(args: argparse.Namespace) -> None:
    manifest = load_json(args.manifest)
    bases = compact_bases_from_manifest(manifest)
    write_json(args.out_json, bases)
    print(f"Wrote bases: {args.out_json}")
    print(f"Nodes: {len(bases['nodes'])}")
    print(f"Files: {len(bases['files'])}")


def cmd_extract(args: argparse.Namespace) -> None:
    manifest = load_json(args.manifest)
    bases = load_json(args.bases)
    base_map = {item["entry_id"]: item["physical_offset"] for item in bases["files"]}

    buf = Path(args.kpd).read_bytes()
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    extracted = 0
    skipped = 0
    collisions = 0
    written_paths: set[str] = set()

    for entry in manifest_file_entries(manifest):
        name = entry["name"]
        if not should_extract(name, args.match):
            continue
        physical_offset = base_map.get(entry["entry_id"], entry.get("physical_offset"))
        size = int(entry["size"])
        if physical_offset is None:
            skipped += 1
            continue
        if physical_offset < 0 or physical_offset + size > len(buf):
            skipped += 1
            continue
        out_path = output_path_for_name(out_dir, name)
        if out_path in written_paths:
            collisions += 1
            if not args.overwrite:
                skipped += 1
                continue
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "wb") as handle:
            handle.write(buf[physical_offset:physical_offset + size])
        written_paths.add(out_path)
        extracted += 1

    print(f"Extracted: {extracted}")
    print(f"Skipped: {skipped}")
    print(f"Collisions: {collisions}")


def positive_int(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuilt KPD tool: includes singleton runs, hierarchical pool resolution, and flat fallback."
    )
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    dump_parser = subparsers.add_parser("dump")
    dump_parser.add_argument("kpd")
    dump_parser.add_argument("out_json")
    dump_parser.add_argument(
        "--layout",
        default="auto",
        choices=["auto", "flat", "ng-datapack"],
        help="Archive layout model. 'auto' prefers the hierarchical NG datapack layout and falls back to flat.",
    )
    dump_parser.add_argument("--entry-size", type=positive_int, default=ENTRY_SIZE_DEFAULT)
    dump_parser.set_defaults(fn=cmd_dump)

    bases_parser = subparsers.add_parser("dump_bases")
    bases_parser.add_argument("kpd")
    bases_parser.add_argument("manifest")
    bases_parser.add_argument("out_json")
    bases_parser.set_defaults(fn=cmd_dump_bases)

    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("kpd")
    extract_parser.add_argument("manifest")
    extract_parser.add_argument("bases")
    extract_parser.add_argument("out_dir")
    extract_parser.add_argument(
        "--match",
        action="append",
        default=[],
        help="Optional glob filter. Repeat to extract multiple name patterns.",
    )
    extract_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite colliding output paths instead of skipping them.",
    )
    extract_parser.set_defaults(fn=cmd_extract)

    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
