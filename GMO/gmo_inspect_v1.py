#!/usr/bin/env python3
"""Inspect GMO files and report chunk structure.

This script is intentionally separate from the KPD tooling. It works on loose
`.gmo` files and focuses on the embedded GMO container itself.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


PRINTABLE_RE = re.compile(rb"[ -~]{4,}")

HALF_CHUNK_ID = 0x8000

CHUNK_LABELS = {
    0x0002: "FILE",
    0x0003: "MODEL",
    0x0004: "BONE",
    0x0005: "PART",
    0x0006: "MESH",
    0x0007: "ARRAYS",
    0x0008: "MATERIAL",
    0x0009: "LAYER",
    0x000A: "TEXTURE",
    0x000B: "MOTION",
    0x000C: "FCURVE",
    0x0012: "FILE_NAME",
    0x0013: "FILE_IMAGE",
    0x0014: "BOUNDING_BOX",
    0x0015: "ARRAY_OFFSET",
    0x0041: "PARENT_BONE",
    0x0042: "VISIBILITY",
    0x0044: "BLEND_BONES",
    0x0045: "BLEND_OFFSETS",
    0x0046: "PIVOT",
    0x0048: "TRANSLATE",
    0x0049: "ROTATE_ZYX",
    0x004A: "ROTATE_YXZ",
    0x004B: "ROTATE_Q",
    0x004C: "SCALE",
    0x004E: "DRAW_PART",
    0x0061: "SET_MATERIAL",
    0x0062: "BLEND_SUBSET",
    0x0066: "DRAW_ARRAYS",
    0x0082: "DIFFUSE",
    0x0083: "SPECULAR",
    0x0084: "EMISSION",
    0x0085: "AMBIENT",
    0x0086: "REFLECTION",
    0x0087: "REFRACTION",
    0x0088: "BUMP",
    0x0091: "SET_TEXTURE",
    0x0092: "MAP_TYPE",
    0x0093: "MAP_FACTOR",
    0x0094: "BLEND_FUNC",
    0x0095: "TEX_FUNC",
    0x0096: "TEX_FILTER",
    0x0097: "TEX_WRAP",
    0x0098: "TEX_CROP",
    0x0099: "TEX_GEN",
    0x009A: "TEX_MATRIX",
    0x00B1: "FRAME_LOOP",
    0x00B2: "FRAME_RATE",
    0x00B3: "ANIMATE",
    0x00F1: "BLIND_DATA",
}

CONTAINER_TYPES = {
    0x0002,
    0x0003,
    0x0004,
    0x0005,
    0x0006,
    0x0008,
    0x0009,
    0x000A,
    0x000B,
}

MESH_TYPES = {
    0x0006,
    0x0007,
    0x0008,
    0x0009,
    0x000A,
    0x0012,
    0x0013,
    0x0061,
    0x0062,
    0x0066,
    0x0091,
    0x0092,
    0x0093,
    0x0094,
    0x0095,
    0x0096,
    0x0097,
    0x0098,
    0x0099,
    0x009A,
}

MOTION_TYPES = {
    0x000B,
    0x000C,
    0x00B1,
    0x00B2,
    0x00B3,
}


@dataclass
class Chunk:
    offset: int
    chunk_id: int
    args_offs: int
    next_offs: int
    kind: str
    name: str = ""
    child_offs: int | None = None
    data_offs: int | None = None
    children: list["Chunk"] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def base_id(self) -> int:
        return self.chunk_id & ~HALF_CHUNK_ID

    @property
    def half_chunk(self) -> bool:
        return (self.chunk_id & HALF_CHUNK_ID) != 0

    def to_dict(self) -> dict:
        return {
            "offset": self.offset,
            "chunk_id": f"0x{self.chunk_id:04X}",
            "base_id": f"0x{self.base_id:04X}",
            "type_label": CHUNK_LABELS.get(self.base_id, "unknown"),
            "half_chunk": self.half_chunk,
            "args_offs": self.args_offs,
            "next_offs": self.next_offs,
            "kind": self.kind,
            "name": self.name,
            "child_offs": self.child_offs,
            "data_offs": self.data_offs,
            "errors": self.errors,
            "children": [child.to_dict() for child in self.children],
        }


@dataclass
class GmoReport:
    path: str
    size: int
    magic: str
    header_ok: bool
    body_length: int | None
    root: Chunk | None
    strings: list[str]
    marker_flags: dict[str, bool]
    chunk_counts: Counter
    family: str
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "size": self.size,
            "magic": self.magic,
            "header_ok": self.header_ok,
            "body_length": self.body_length,
            "family": self.family,
            "notes": self.notes,
            "marker_flags": self.marker_flags,
            "strings": self.strings,
            "chunk_counts": {
                f"0x{type_id:04X}": count
                for type_id, count in sorted(self.chunk_counts.items())
            },
            "root": self.root.to_dict() if self.root else None,
        }


def iter_gmo_paths(paths: Iterable[str]) -> Iterable[Path]:
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            if path.suffix.lower() == ".gmo":
                yield path
            continue
        if path.is_dir():
            for child in sorted(path.rglob("*.gmo")):
                if child.is_file():
                    yield child


def extract_strings(data: bytes, limit: int) -> list[str]:
    strings = [match.group().decode("ascii", "ignore") for match in PRINTABLE_RE.finditer(data)]
    if limit >= 0:
        return strings[:limit]
    return strings


def parse_chunk(data: bytes, pos: int) -> Chunk:
    chunk_id, args_offs, next_offs = struct.unpack_from("<HHI", data, pos)
    chunk = Chunk(
        offset=pos,
        chunk_id=chunk_id,
        args_offs=args_offs,
        next_offs=next_offs,
        kind="leaf",
    )
    if next_offs < 8:
        chunk.errors.append(f"invalid next_offs {next_offs}")
        return chunk
    if pos + next_offs > len(data):
        chunk.errors.append(f"chunk overruns file end ({pos + next_offs:#x} > {len(data):#x})")
        return chunk
    if chunk.half_chunk:
        chunk.kind = "half-leaf"
        return chunk
    if next_offs < 0x10 or pos + 0x10 > len(data):
        chunk.kind = "full-leaf"
        return chunk

    chunk.child_offs, chunk.data_offs = struct.unpack_from("<II", data, pos + 8)
    chunk.kind = "full-leaf"
    if chunk.args_offs > 0x10:
        name_bytes = data[pos + 0x10 : pos + chunk.args_offs]
        nul = name_bytes.find(b"\x00")
        if nul >= 0:
            raw_name = name_bytes[:nul]
            if raw_name and all(32 <= byte < 127 for byte in raw_name):
                chunk.name = raw_name.decode("ascii", "ignore")
                chunk.kind = "named-leaf"
    if chunk.base_id not in CONTAINER_TYPES:
        return chunk

    chunk.kind = "container" if not chunk.name else "named-container"
    cur = pos + chunk.args_offs
    while cur < pos + next_offs:
        child = parse_chunk(data, cur)
        chunk.children.append(child)
        if child.next_offs <= 0:
            chunk.errors.append(f"child at {cur:#x} has invalid next_offs {child.next_offs}")
            break
        cur += child.next_offs
    if cur != pos + next_offs:
        chunk.errors.append(f"child walk ended at {cur:#x}, expected {pos + next_offs:#x}")
    return chunk


def collect_chunk_counts(chunk: Chunk, counts: Counter | None = None) -> Counter:
    if counts is None:
        counts = Counter()
    counts[chunk.base_id] += 1
    for child in chunk.children:
        collect_chunk_counts(child, counts)
    return counts


def walk_chunks(chunk: Chunk) -> Iterable[Chunk]:
    yield chunk
    for child in chunk.children:
        yield from walk_chunks(child)


def classify_family(strings: list[str], counts: Counter) -> tuple[str, list[str]]:
    strings_lower = [value.lower() for value in strings]
    marker_flags = {
        "mesh_name": any("mesh-" in value for value in strings_lower),
        "arrays_name": any("arrays-" in value for value in strings_lower),
        "layer_name": any("layer-" in value for value in strings_lower),
        "gim_marker": any("mig.00.1psp" in value for value in strings_lower),
        "motion_name": any("motion-0" in value for value in strings_lower),
        "fcurve_name": any("fcurve-" in value for value in strings_lower),
        "camera_name": any("camera" in value for value in strings_lower),
        "point_name": any("point" in value for value in strings_lower),
        "effect_name": any("effect" in value for value in strings_lower),
        "root_name": any("root" in value for value in strings_lower),
    }
    notes: list[str] = []
    has_mesh_payload = any(type_id in MESH_TYPES for type_id in counts)
    has_motion_payload = any(type_id in MOTION_TYPES for type_id in counts)
    has_mesh_markers = any(
        marker_flags[key] for key in ("mesh_name", "arrays_name", "layer_name", "gim_marker")
    )

    if has_mesh_payload or has_mesh_markers:
        notes.append("contains mesh/material/image chunk families")
        return "mesh-bearing", notes
    if has_motion_payload or marker_flags["motion_name"] or marker_flags["fcurve_name"]:
        notes.append("contains motion/fcurve chunk families")
        return "motion-only", notes
    if marker_flags["camera_name"]:
        notes.append("camera-named helper with no mesh chunk families")
        return "camera-helper", notes
    if marker_flags["effect_name"]:
        notes.append("effect-named helper with no mesh chunk families")
        return "effect-helper", notes
    if marker_flags["point_name"]:
        notes.append("point/locator helper with no mesh chunk families")
        return "locator-helper", notes
    if len(counts) <= 3:
        notes.append("very shallow GMO tree with no mesh/material/motion payload chunks")
        return "bare-shell", notes
    notes.append("valid GMO tree, but no mesh/material payload markers were found")
    return "helper-or-unknown", notes


def inspect_gmo(path: Path, max_strings: int) -> GmoReport:
    data = path.read_bytes()
    magic = data[:12].decode("ascii", "ignore")
    body_length = struct.unpack_from("<I", data, 0x14)[0] if len(data) >= 0x18 else None
    header_ok = magic == "OMG.00.1PSP\x00" and body_length == len(data) - 0x10

    root = None
    chunk_counts: Counter = Counter()
    notes: list[str] = []
    if len(data) >= 0x18 and header_ok:
        root = parse_chunk(data, 0x10)
        chunk_counts = collect_chunk_counts(root)
        if root.errors:
            notes.extend(root.errors)
        for chunk in walk_chunks(root):
            if chunk.errors:
                notes.extend(f"{chunk.offset:#x}: {err}" for err in chunk.errors)

    all_strings = extract_strings(data, -1)
    family, family_notes = classify_family(all_strings, chunk_counts)
    notes = family_notes + notes

    marker_flags = {
        "mesh_name": any("mesh-" in value.lower() for value in all_strings),
        "arrays_name": any("arrays-" in value.lower() for value in all_strings),
        "layer_name": any("layer-" in value.lower() for value in all_strings),
        "gim_marker": any("mig.00.1psp" in value.lower() for value in all_strings),
        "motion_name": any("motion-0" in value.lower() for value in all_strings),
        "fcurve_name": any("fcurve-" in value.lower() for value in all_strings),
        "camera_name": any("camera" in value.lower() for value in all_strings),
        "point_name": any("point" in value.lower() for value in all_strings),
        "effect_name": any("effect" in value.lower() for value in all_strings),
    }
    strings = all_strings[:max_strings] if max_strings >= 0 else all_strings

    return GmoReport(
        path=str(path),
        size=len(data),
        magic=magic,
        header_ok=header_ok,
        body_length=body_length,
        root=root,
        strings=strings,
        marker_flags=marker_flags,
        chunk_counts=chunk_counts,
        family=family,
        notes=notes,
    )


def format_chunk(chunk: Chunk, depth: int, max_depth: int) -> list[str]:
    label = CHUNK_LABELS.get(chunk.base_id, "unknown")
    name_suffix = f" name={chunk.name!r}" if chunk.name else ""
    flags = " half" if chunk.half_chunk else ""
    child_suffix = (
        f" child=0x{chunk.child_offs:X} data=0x{chunk.data_offs:X}"
        if chunk.child_offs is not None and chunk.data_offs is not None
        else ""
    )
    line = (
        f"{'  ' * depth}0x{chunk.offset:06X} "
        f"chunk_id=0x{chunk.chunk_id:04X} base=0x{chunk.base_id:04X} ({label}) "
        f"args=0x{chunk.args_offs:X} next=0x{chunk.next_offs:X}{flags} "
        f"kind={chunk.kind}{name_suffix}{child_suffix}"
    )
    lines = [line]
    if depth >= max_depth:
        return lines
    for child in chunk.children:
        lines.extend(format_chunk(child, depth + 1, max_depth))
    return lines


def print_text_report(report: GmoReport, args: argparse.Namespace) -> None:
    print(report.path)
    print(f"  family: {report.family}")
    print(f"  size: 0x{report.size:X} ({report.size})")
    print(f"  magic: {report.magic!r}")
    body_text = f"0x{report.body_length:X}" if report.body_length is not None else "n/a"
    print(f"  body_length: {body_text}")
    print(f"  header_ok: {report.header_ok}")
    if report.notes:
        print(f"  notes: {'; '.join(dict.fromkeys(report.notes))}")
    if report.marker_flags:
        active_markers = [name for name, value in report.marker_flags.items() if value]
        if active_markers:
            print(f"  markers: {', '.join(active_markers)}")
    if report.chunk_counts:
        print("  chunk_counts:")
        for type_id, count in sorted(report.chunk_counts.items()):
            label = CHUNK_LABELS.get(type_id, "unknown")
            print(f"    0x{type_id:04X}: {count} ({label})")
    if args.tree and report.root:
        print("  chunk_tree:")
        for line in format_chunk(report.root, 0, args.tree_depth):
            print(f"    {line}")
    if args.max_strings != 0 and report.strings:
        print("  strings:")
        for value in report.strings[: args.max_strings]:
            print(f"    {value}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect GMO files and report chunk structure plus a coarse family classification."
    )
    parser.add_argument("paths", nargs="+", help="GMO files or directories to inspect")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument("--tree", action="store_true", help="Print the parsed chunk tree in text mode")
    parser.add_argument(
        "--tree-depth",
        type=int,
        default=6,
        help="Maximum depth to print when --tree is enabled (default: 6)",
    )
    parser.add_argument(
        "--max-strings",
        type=int,
        default=20,
        help="Maximum number of extracted printable strings to include (default: 20, 0 disables)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    paths = list(iter_gmo_paths(args.paths))
    if not paths:
        parser.error("no .gmo files were found in the provided paths")

    reports = [inspect_gmo(path, args.max_strings if args.max_strings >= 0 else -1) for path in paths]
    if args.json:
        json.dump([report.to_dict() for report in reports], sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    for index, report in enumerate(reports):
        if index:
            print()
        print_text_report(report, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
