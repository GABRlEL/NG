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

EMBEDDED_SIGNATURES = {
    ".gmo": KNOWN_SIGNATURES[".gmo"],
    ".mwm": KNOWN_SIGNATURES[".mwm"],
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
    if ext == ".bin":
        if len(blob) < 0x0C:
            return False
        magic = blob[:4]
        if not all((0x30 <= byte <= 0x39) or (0x41 <= byte <= 0x5A) or byte == 0x5F for byte in magic):
            return False
        return read_u32(blob, 4) == 0x00010000 and read_u32(blob, 8) == 0x14
    sig = KNOWN_SIGNATURES.get(ext)
    if sig is None:
        return None
    return blob.startswith(sig)


def parse_embedded_gmo_size(buf: bytes, offset: int) -> int | None:
    sig = EMBEDDED_SIGNATURES[".gmo"]
    if offset < 0 or offset + len(sig) > len(buf) or not buf.startswith(sig, offset):
        return None
    if offset + 0x18 > len(buf):
        return None
    body_len = read_u32(buf, offset + 0x14)
    total_size = body_len + 0x10
    return total_size if total_size > 0 else None


def parse_embedded_mwm_size(buf: bytes, offset: int) -> int | None:
    sig = EMBEDDED_SIGNATURES[".mwm"]
    if offset < 0 or offset + len(sig) > len(buf) or not buf.startswith(sig, offset):
        return None
    if offset + 0x14 > len(buf):
        return None

    header_size = read_u32(buf, offset + 0x08)
    count = read_u32(buf, offset + 0x0C)
    if header_size < 0x14 or header_size > 0x1000 or count > 0x10000:
        return None

    table_start = offset + header_size
    table_end = table_start + count * 0x10
    if table_end > len(buf):
        return None

    max_payload_end = 0
    for index in range(count):
        record_pos = table_start + index * 0x10
        byte_length = read_u32(buf, record_pos + 8)
        rel_offset = read_u32(buf, record_pos + 12)
        payload_end = rel_offset + byte_length
        if payload_end < rel_offset:
            return None
        max_payload_end = max(max_payload_end, payload_end)

    total_size = header_size + count * 0x10 + max_payload_end
    return total_size if total_size > 0 else None


EMBEDDED_SIZE_PARSERS = {
    ".gmo": parse_embedded_gmo_size,
    ".mwm": parse_embedded_mwm_size,
}


def output_path_for_name(out_dir: str, name: str) -> str:
    return os.path.join(out_dir, name.replace("/", os.sep))


def entry_output_name(entry: dict[str, Any]) -> str:
    name = entry["name"]
    node_id = entry.get("node_id")
    if not node_id or node_id == "root":
        return name
    prefix = node_id.split("/", 1)[1] if "/" in node_id else ""
    return f"{prefix}/{name}" if prefix else name


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
    signature_offset: int | None = None
    normalized_physical_offset: int | None = None
    normalized_size: int | None = None
    normalization_note: str | None = None
    carried_by_entry_id: str | None = None

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
            "signature_offset": self.signature_offset,
            "normalized_physical_offset": self.normalized_physical_offset,
            "normalized_size": self.normalized_size,
            "normalization_note": self.normalization_note,
            "carried_by_entry_id": self.carried_by_entry_id,
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
        entry_type = read_u32(self.buf, offset)
        if entry_type not in (0, 1):
            return False
        if read_u32(self.buf, offset + 4) != 0:
            return False
        offset_stored = read_u64(self.buf, offset + 8)
        size = read_u64(self.buf, offset + 16)
        if size == 0 or size > 0x7FFFFFFF:
            return False
        if entry_type == 1 and offset_stored + size > self.header.data_size_u64:
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

    def validate_signature(self, entry: Entry, normalized: bool = False) -> bool | None:
        physical_offset = entry.physical_offset
        if normalized and entry.normalized_physical_offset is not None:
            physical_offset = entry.normalized_physical_offset
        if physical_offset is None:
            return None
        end = min(physical_offset + 0x20, self.file_size)
        return signature_matches(ext_of(entry.name), self.buf[physical_offset:end])


class LayoutBuilder:
    def __init__(self, archive: KPDArchive):
        self.archive = archive
        self.nodes: dict[str, Node] = {}
        self.warnings: list[str] = []
        self.child_pool_alignment = archive.alignment

    def _has_span_mismatch_warning(self) -> bool:
        return any(warning.startswith("Hierarchical span mismatch:") for warning in self.warnings)

    def build(self, layout: str) -> tuple[str, str, dict[str, Node], list[str]]:
        if layout == "flat":
            root_id = self._build_flat()
            self._annotate_normalization_candidates()
            return layout, root_id, self.nodes, self.warnings
        if layout == "ng-datapack":
            root_id = self._build_ng_datapack(strict=True)
            self._annotate_normalization_candidates()
            return layout, root_id, self.nodes, self.warnings
        if layout != "auto":
            raise ValueError(f"Unsupported layout: {layout}")

        try:
            root_id = self._build_ng_datapack(strict=False)
        except ValueError:
            self.nodes.clear()
            self.warnings.clear()
            root_id = self._build_flat()
            self._annotate_normalization_candidates()
            return "flat", root_id, self.nodes, self.warnings

        if self._has_span_mismatch_warning():
            self.nodes.clear()
            self.warnings.clear()
            root_id = self._build_flat()
            self._annotate_normalization_candidates()
            return "flat", root_id, self.nodes, self.warnings

        root = self.nodes[root_id]
        nonempty_children = sum(1 for child_id in root.child_ids if self.nodes[child_id].span_aligned > 0)
        if nonempty_children >= 2:
            self._annotate_normalization_candidates()
            return "ng-datapack", root_id, self.nodes, self.warnings

        self.nodes.clear()
        self.warnings.clear()
        root_id = self._build_flat()
        self._annotate_normalization_candidates()
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

        self.child_pool_alignment = self._resolve_child_pool_alignment(root_id)
        self._compute_span(self.nodes[root_id], self.child_pool_alignment)
        self._assign_bases(self.nodes[root_id], self.archive.header.data_start_u64, self.child_pool_alignment)

        expected_span = self.archive.header.data_size_u64
        actual_span = self.nodes[root_id].span_aligned
        if actual_span != expected_span:
            message = f"Hierarchical span mismatch: computed {actual_span:#x}, expected {expected_span:#x}"
            if strict:
                raise ValueError(message)
            self.warnings.append(message)

        return root_id

    def _resolve_child_pool_alignment(self, root_id: str) -> int:
        expected_span = self.archive.header.data_size_u64
        candidates: list[int] = []
        for candidate in (self.archive.alignment, 0x10):
            if candidate not in candidates:
                candidates.append(candidate)

        best_alignment = candidates[0]
        best_delta: int | None = None
        for candidate in candidates:
            actual_span = self._compute_span(self.nodes[root_id], candidate)
            delta = abs(actual_span - expected_span)
            if actual_span == expected_span:
                return candidate
            if best_delta is None or delta < best_delta:
                best_alignment = candidate
                best_delta = delta
        return best_alignment

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

    def _compute_span(self, node: Node, child_alignment: int) -> int:
        child_span = sum(align_up(self._compute_span(self.nodes[child_id], child_alignment), child_alignment) for child_id in node.child_ids)

        raw_file_end = 0
        for entry_id in node.file_entry_ids:
            entry = self.archive.entries[entry_id]
            raw_file_end = max(raw_file_end, entry.offset_stored + entry.size)

        raw_end = max(child_span, raw_file_end)
        node.span_aligned = align_up(raw_end, child_alignment) if raw_end else 0
        return node.span_aligned

    def _assign_bases(self, node: Node, base: int, child_alignment: int) -> None:
        node.data_base = base
        child_prefix_span = 0
        if node.child_ids:
            cur = base
            for child_id in node.child_ids:
                child = self.nodes[child_id]
                self._assign_bases(child, cur, child_alignment)
                cur += align_up(child.span_aligned, child_alignment)
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

    def _matching_embedded_offsets(self, host_entry: Entry, ext: str, expected_size: int) -> list[tuple[int, int]]:
        parser = EMBEDDED_SIZE_PARSERS.get(ext)
        sig = EMBEDDED_SIGNATURES.get(ext)
        if parser is None or sig is None or host_entry.physical_offset is None:
            return []

        start = host_entry.physical_offset
        end = min(start + host_entry.size, self.archive.file_size)
        if end <= start + 1:
            return []

        matches: list[tuple[int, int]] = []
        cursor = start + 1
        while cursor < end:
            match_pos = self.archive.buf.find(sig, cursor, end)
            if match_pos == -1:
                break
            parsed_size = parser(self.archive.buf, match_pos)
            if parsed_size == expected_size and match_pos + parsed_size <= self.archive.file_size:
                matches.append((match_pos - start, match_pos))
            cursor = match_pos + 1
        return matches

    def _set_normalization(
        self,
        entry: Entry,
        signature_offset: int,
        normalized_physical_offset: int,
        normalized_size: int,
        note: str,
        carried_by_entry_id: str | None = None,
    ) -> None:
        entry.signature_offset = signature_offset
        entry.normalized_physical_offset = normalized_physical_offset
        entry.normalized_size = normalized_size
        entry.normalization_note = note
        entry.carried_by_entry_id = carried_by_entry_id

    def _annotate_normalization_candidates(self) -> None:
        for node in self.nodes.values():
            file_entries = [
                self.archive.entries[entry_id]
                for entry_id in node.file_entry_ids
                if self.archive.entries[entry_id].physical_offset is not None
                and ext_of(self.archive.entries[entry_id].name) in EMBEDDED_SIZE_PARSERS
            ]
            if not file_entries:
                continue

            file_entries.sort(key=lambda entry: (entry.physical_offset or 0, entry.entry_pos))
            size_counter = Counter((ext_of(entry.name), entry.size) for entry in file_entries)
            claimed_offsets: set[int] = set()

            for entry in file_entries:
                ext = ext_of(entry.name)
                if size_counter[(ext, entry.size)] != 1:
                    continue
                matches = self._matching_embedded_offsets(entry, ext, entry.size)
                if len(matches) == 1 and matches[0][1] not in claimed_offsets:
                    self._set_normalization(
                        entry=entry,
                        signature_offset=matches[0][0],
                        normalized_physical_offset=matches[0][1],
                        normalized_size=entry.size,
                        note="embedded-self",
                    )
                    claimed_offsets.add(matches[0][1])

            for index in range(1, len(file_entries)):
                entry = file_entries[index]
                if entry.normalized_physical_offset is not None:
                    continue
                ext = ext_of(entry.name)
                if size_counter[(ext, entry.size)] != 1:
                    continue

                prev_entry = file_entries[index - 1]
                matches = [
                    match
                    for match in self._matching_embedded_offsets(prev_entry, ext, entry.size)
                    if match[1] not in claimed_offsets
                ]
                if len(matches) == 1:
                    self._set_normalization(
                        entry=entry,
                        signature_offset=matches[0][0],
                        normalized_physical_offset=matches[0][1],
                        normalized_size=entry.size,
                        note="carried-by-previous-sibling",
                        carried_by_entry_id=prev_entry.entry_id,
                    )
                    claimed_offsets.add(matches[0][1])


def serialize_manifest(
    archive: KPDArchive,
    layout_name: str,
    root_id: str,
    nodes: dict[str, Node],
    warnings: list[str],
    child_pool_alignment: int,
) -> dict[str, Any]:
    signature_counter = Counter()
    verified_counter = Counter()
    normalized_signature_counter = Counter()
    normalized_verified_counter = Counter()
    normalization_counter = Counter()
    file_entries = [entry for entry in archive.entries.values() if entry.type == 1]
    for entry in file_entries:
        ext = ext_of(entry.name)
        ok = archive.validate_signature(entry)
        if ok is not None:
            signature_counter[ext] += 1
            if ok:
                verified_counter[ext] += 1
        normalized_ok = archive.validate_signature(entry, normalized=True) if entry.normalized_physical_offset is not None else None
        if normalized_ok is not None:
            normalized_signature_counter[ext] += 1
            if normalized_ok:
                normalized_verified_counter[ext] += 1
        if entry.normalization_note is not None:
            normalization_counter[entry.normalization_note] += 1

    return {
        "tool": "pyKPDTool_rebuilt_v3",
        "format_version": 3,
        "source_path": archive.path,
        "entry_size": archive.entry_size,
        "alignment": archive.alignment,
        "child_pool_alignment": child_pool_alignment,
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
        "normalized_signature_verification": {
            ext: {
                "verified": normalized_verified_counter.get(ext, 0),
                "checked": normalized_signature_counter.get(ext, 0),
            }
            for ext in sorted(normalized_signature_counter)
        },
        "normalization": {
            "annotated": sum(normalization_counter.values()),
            "by_note": {note: normalization_counter[note] for note in sorted(normalization_counter)},
        },
        "runs": [run.to_dict() for run in archive.runs],
        "nodes": [nodes[node_id].to_dict() for node_id in sorted(nodes)],
        "entries": [archive.entries[entry_id].to_dict() for entry_id in sorted(archive.entries)],
    }


def build_manifest(path: str, layout: str, entry_size: int) -> dict[str, Any]:
    archive = KPDArchive(path=path, entry_size=entry_size)
    builder = LayoutBuilder(archive)
    layout_name, root_id, nodes, warnings = builder.build(layout)
    return serialize_manifest(archive, layout_name, root_id, nodes, warnings, builder.child_pool_alignment)


def compact_bases_from_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    nodes = manifest.get("nodes", [])
    entries = manifest.get("entries", [])
    return {
        "tool": manifest.get("tool"),
        "format_version": manifest.get("format_version"),
        "layout": manifest.get("layout"),
        "child_pool_alignment": manifest.get("child_pool_alignment"),
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
                "output_name": entry_output_name(entry),
                "node_id": entry["node_id"],
                "physical_offset": entry["physical_offset"],
                "size": entry["size"],
                "signature_offset": entry.get("signature_offset"),
                "normalized_physical_offset": entry.get("normalized_physical_offset"),
                "normalized_size": entry.get("normalized_size"),
                "normalization_note": entry.get("normalization_note"),
                "carried_by_entry_id": entry.get("carried_by_entry_id"),
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
    base_map = {item["entry_id"]: item for item in bases["files"]}

    buf = Path(args.kpd).read_bytes()
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    extracted = 0
    skipped = 0
    collisions = 0
    normalized_hits = 0
    written_paths: set[str] = set()

    for entry in manifest_file_entries(manifest):
        name = entry["name"]
        output_name = entry_output_name(entry)
        if not (should_extract(name, args.match) or should_extract(output_name, args.match)):
            continue
        base_info = base_map.get(entry["entry_id"], {})
        size = int(entry["size"])
        physical_offset = base_info.get("physical_offset", entry.get("physical_offset"))
        if args.normalized:
            normalized_offset = base_info.get("normalized_physical_offset", entry.get("normalized_physical_offset"))
            normalized_size = base_info.get("normalized_size", entry.get("normalized_size"))
            if normalized_offset is not None:
                physical_offset = normalized_offset
                size = int(normalized_size or size)
                normalized_hits += 1
        if physical_offset is None:
            skipped += 1
            continue
        if physical_offset < 0 or physical_offset + size > len(buf):
            skipped += 1
            continue
        out_path = output_path_for_name(out_dir, output_name)
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
    if args.normalized:
        print(f"Normalized hits: {normalized_hits}")


def positive_int(value: str) -> int:
    return int(value, 0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rebuilt KPD tool v2: includes singleton runs, hierarchical pool resolution, flat fallback, and optional embedded-header normalization."
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
    extract_parser.add_argument(
        "--normalized",
        action="store_true",
        help="Use annotated normalized offsets for embedded GMO/MWM cases when available.",
    )
    extract_parser.set_defaults(fn=cmd_extract)

    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
