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

TEXTURE_FORMAT_LABELS = {
    0x0000: "NONE",
    0x0001: "UBYTE",
    0x0002: "USHORT",
    0x0003: "FLOAT",
}

COLOR_FORMAT_LABELS = {
    0x0000: "NONE",
    0x0010: "PF5650",
    0x0014: "PF5551",
    0x0018: "PF4444",
    0x001C: "PF8888",
}

NORMAL_FORMAT_LABELS = {
    0x0000: "NONE",
    0x0020: "BYTE",
    0x0040: "SHORT",
    0x0060: "FLOAT",
}

VERTEX_FORMAT_LABELS = {
    0x0000: "NONE",
    0x0080: "BYTE",
    0x0100: "SHORT",
    0x0180: "FLOAT",
}

WEIGHT_FORMAT_LABELS = {
    0x0000: "NONE",
    0x0200: "UBYTE",
    0x0400: "USHORT",
    0x0600: "FLOAT",
}

WEIGHT_COUNT_FLAGS = (
    (0x1C000, 8),
    (0x18000, 7),
    (0x14000, 6),
    (0x10000, 5),
    (0x0C000, 4),
    (0x08000, 3),
    (0x04000, 2),
)

PRIM_SEQUENTIAL_ID = 0x0100
FCURVE_FLOAT16 = 0x0080
UNKNOWN_ARRAY_FLAG = 0x02000000


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
    payload: dict | None = None
    children: list["Chunk"] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def base_id(self) -> int:
        return self.chunk_id & ~HALF_CHUNK_ID

    @property
    def half_chunk(self) -> bool:
        return (self.chunk_id & HALF_CHUNK_ID) != 0

    @property
    def size(self) -> int:
        return self.next_offs

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
            "payload": self.payload,
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


def safe_unpack(fmt: str, data: bytes, offset: int, end: int | None = None):
    size = struct.calcsize(fmt)
    limit = len(data) if end is None else min(len(data), end)
    if offset < 0 or offset + size > limit:
        return None
    return struct.unpack_from(fmt, data, offset)


def read_ascii_z(data: bytes) -> str:
    nul = data.find(b"\x00")
    raw = data[:nul] if nul >= 0 else data
    return raw.decode("ascii", "ignore")


def read_vec_f32(data: bytes, offset: int, count: int, end: int | None = None) -> list[float] | None:
    values = safe_unpack("<" + "f" * count, data, offset, end)
    return list(values) if values is not None else None


def read_mat4_f32(data: bytes, offset: int, end: int | None = None) -> list[list[float]] | None:
    values = read_vec_f32(data, offset, 16, end)
    if values is None:
        return None
    return [values[index : index + 4] for index in range(0, 16, 4)]


def read_f16(data: bytes, offset: int, end: int | None = None) -> float | None:
    value = safe_unpack("<e", data, offset, end)
    return float(value[0]) if value is not None else None


def decode_ref_triplet(payload: bytes) -> dict | None:
    fields = safe_unpack("<BBBB", payload, 0, len(payload))
    if fields is None:
        return None
    index, level, type_id, reserved = fields
    return {
        "index": index,
        "level": level,
        "type": type_id,
        "reserved": reserved,
    }


def decode_color_pf4444(raw: bytes) -> list[int]:
    if len(raw) < 2:
        return []
    word = int.from_bytes(raw[:2], "little", signed=False)
    return [((word >> shift) & 0xF) * 0x11 for shift in (0, 4, 8, 12)]


def decode_color_pf5551(raw: bytes) -> list[int]:
    if len(raw) < 2:
        return []
    word = int.from_bytes(raw[:2], "little", signed=False)
    r = ((word >> 0) & 0x1F) * 255 // 31
    g = ((word >> 5) & 0x1F) * 255 // 31
    b = ((word >> 10) & 0x1F) * 255 // 31
    a = 255 if (word & 0x8000) else 0
    return [r, g, b, a]


def decode_color_pf5650(raw: bytes) -> list[int]:
    if len(raw) < 2:
        return []
    word = int.from_bytes(raw[:2], "little", signed=False)
    r = ((word >> 0) & 0x1F) * 255 // 31
    g = ((word >> 5) & 0x3F) * 255 // 63
    b = ((word >> 11) & 0x1F) * 255 // 31
    return [r, g, b, 255]


def decode_color_chunk(payload: bytes) -> dict | None:
    values = read_vec_f32(payload, 0, 4, len(payload))
    if values is None:
        return None
    return {
        "rgba_unit": values,
        "rgba_scaled": [values[0] * 255.0, values[1] * 255.0, values[2] * 255.0, values[3] * 100.0],
    }


def decode_array_layout(vertex_type: int, format2: int) -> dict:
    texture_code = vertex_type & 0x0003
    color_code = vertex_type & 0x001C
    normal_code = vertex_type & 0x0060
    vertex_code = vertex_type & 0x0180
    weight_code = vertex_type & 0x0600
    weight_count = 0
    if weight_code != 0x0000:
        weight_count = 1
        for flag, count in WEIGHT_COUNT_FLAGS:
            if (vertex_type & flag) == flag:
                weight_count = count
                break

    texture_bytes = {0x0000: 0, 0x0001: 2, 0x0002: 4, 0x0003: 8}[texture_code]
    color_bytes = {0x0000: 0, 0x0010: 2, 0x0014: 2, 0x0018: 2, 0x001C: 4}[color_code]
    normal_bytes = {0x0000: 0, 0x0020: 3, 0x0040: 6, 0x0060: 12}[normal_code]
    vertex_bytes = {0x0000: 0, 0x0080: 3, 0x0100: 6, 0x0180: 12}[vertex_code]
    if weight_code == 0x0200:
        weight_bytes = weight_count + (weight_count % 2)
    elif weight_code == 0x0400:
        weight_bytes = weight_count * 2
    elif weight_code == 0x0600:
        weight_bytes = weight_count * 4
    else:
        weight_bytes = 0
    uv_offset_bytes = max(format2, 0) * 4

    return {
        "vertex_type": f"0x{vertex_type:08X}",
        "texture_format": TEXTURE_FORMAT_LABELS.get(texture_code, "UNKNOWN"),
        "color_format": COLOR_FORMAT_LABELS.get(color_code, "UNKNOWN"),
        "normal_format": NORMAL_FORMAT_LABELS.get(normal_code, "UNKNOWN"),
        "vertex_format": VERTEX_FORMAT_LABELS.get(vertex_code, "UNKNOWN"),
        "weight_format": WEIGHT_FORMAT_LABELS.get(weight_code, "UNKNOWN"),
        "weight_count": weight_count,
        "has_unknown_flag": (vertex_type & UNKNOWN_ARRAY_FLAG) == UNKNOWN_ARRAY_FLAG,
        "uv_offset_pairs": format2,
        "record_stride_estimate": uv_offset_bytes + weight_bytes + texture_bytes + color_bytes + normal_bytes + vertex_bytes,
    }


def read_component_floats(data: bytes, offset: int, fmt_name: str, count: int, signed: bool = True):
    if fmt_name == "FLOAT":
        values = safe_unpack("<" + "f" * count, data, offset)
        if values is None:
            return None, offset
        return [float(value) for value in values], offset + 4 * count
    if fmt_name == "SHORT":
        code = "h" if signed else "H"
        values = safe_unpack("<" + code * count, data, offset)
        if values is None:
            return None, offset
        scale = 32768.0
        return [value / scale for value in values], offset + 2 * count
    if fmt_name == "BYTE":
        code = "b" if signed else "B"
        values = safe_unpack("<" + code * count, data, offset)
        if values is None:
            return None, offset
        scale = 128.0
        return [value / scale for value in values], offset + count
    if fmt_name == "USHORT":
        values = safe_unpack("<" + "H" * count, data, offset)
        if values is None:
            return None, offset
        return [value / 32768.0 for value in values], offset + 2 * count
    if fmt_name == "UBYTE":
        values = safe_unpack("<" + "B" * count, data, offset)
        if values is None:
            return None, offset
        return [value / 128.0 for value in values], offset + count
    return None, offset


def decode_arrays_payload(payload: bytes, preview_limit: int) -> dict | None:
    header = safe_unpack("<IIII", payload, 0, len(payload))
    if header is None:
        return None
    vertex_type, verts_count, morphs_count, format2 = header
    layout = decode_array_layout(vertex_type, format2)
    cursor = 16
    preview_vertices = []
    truncated = False
    preview_count = min(verts_count, preview_limit)
    for _ in range(preview_count):
        item: dict = {}
        if format2 > 0:
            uv_pairs = []
            for _pair in range(format2):
                pair = safe_unpack("<HH", payload, cursor, len(payload))
                if pair is None:
                    truncated = True
                    break
                uv_pairs.append([pair[0] / 32768.0, pair[1] / 32768.0])
                cursor += 4
            item["uv_offsets"] = uv_pairs
            if truncated:
                break

        if layout["weight_format"] != "NONE":
            weights, cursor = read_component_floats(
                payload, cursor, layout["weight_format"], layout["weight_count"], signed=False
            )
            if weights is None:
                truncated = True
                break
            item["weights"] = weights
            if layout["weight_format"] == "UBYTE" and layout["weight_count"] % 2:
                cursor += 1

        if layout["texture_format"] != "NONE":
            texcoord, cursor = read_component_floats(payload, cursor, layout["texture_format"], 2, signed=False)
            if texcoord is None:
                truncated = True
                break
            item["texcoord"] = texcoord

        color_format = layout["color_format"]
        if color_format != "NONE":
            if color_format == "PF8888":
                if cursor + 4 > len(payload):
                    truncated = True
                    break
                raw = payload[cursor : cursor + 4]
                item["color_rgba8"] = list(raw)
                cursor += 4
            else:
                if cursor + 2 > len(payload):
                    truncated = True
                    break
                raw = payload[cursor : cursor + 2]
                if color_format == "PF4444":
                    item["color_rgba8"] = decode_color_pf4444(raw)
                elif color_format == "PF5551":
                    item["color_rgba8"] = decode_color_pf5551(raw)
                elif color_format == "PF5650":
                    item["color_rgba8"] = decode_color_pf5650(raw)
                cursor += 2

        if layout["normal_format"] != "NONE":
            normal, cursor = read_component_floats(payload, cursor, layout["normal_format"], 3, signed=True)
            if normal is None:
                truncated = True
                break
            item["normal"] = normal

        if layout["vertex_format"] != "NONE":
            vertex, cursor = read_component_floats(payload, cursor, layout["vertex_format"], 3, signed=True)
            if vertex is None:
                truncated = True
                break
            item["vertex"] = vertex

        preview_vertices.append(item)

    consumed_preview_bytes = cursor
    expected_min_payload_bytes = 16 + layout["record_stride_estimate"] * verts_count
    return {
        "vertex_type": layout["vertex_type"],
        "verts_count": verts_count,
        "morphs_count": morphs_count,
        "format2": format2,
        "layout": layout,
        "payload_bytes": len(payload),
        "expected_min_payload_bytes": expected_min_payload_bytes,
        "consumed_preview_bytes": consumed_preview_bytes,
        "preview_vertices": preview_vertices,
        "preview_truncated": truncated,
    }


def decode_draw_arrays_payload(payload: bytes, preview_limit: int) -> dict | None:
    if len(payload) < 16:
        return None
    arrays_ref = decode_ref_triplet(payload[:4])
    mode, vertex_count, primitive_count = struct.unpack_from("<III", payload, 4)
    cursor = 16
    sequential = (mode & PRIM_SEQUENTIAL_ID) == PRIM_SEQUENTIAL_ID
    result = {
        "arrays_ref": arrays_ref,
        "mode": f"0x{mode:08X}",
        "sequential": sequential,
        "vertex_count": vertex_count,
        "primitive_count": primitive_count,
    }
    if sequential:
        base_index = safe_unpack("<H", payload, cursor, len(payload))
        if base_index is not None:
            result["index_seed"] = base_index[0]
            cursor += 2
    else:
        preview = []
        for _ in range(min(primitive_count, preview_limit)):
            primitive = []
            for _vertex in range(vertex_count):
                value = safe_unpack("<H", payload, cursor, len(payload))
                if value is None:
                    result["preview_truncated"] = True
                    result["primitive_indices_preview"] = preview
                    result["consumed_preview_bytes"] = cursor
                    return result
                primitive.append(value[0])
                cursor += 2
            preview.append(primitive)
        result["primitive_indices_preview"] = preview
    result["consumed_preview_bytes"] = cursor
    return result


def decode_fcurve_payload(payload: bytes, preview_limit: int) -> dict | None:
    header = safe_unpack("<IIII", payload, 0, len(payload))
    if header is None:
        return None
    curve_type, value_count, frame_count, reserved = header
    float16 = (curve_type & FCURVE_FLOAT16) == FCURVE_FLOAT16
    cursor = 16
    preview = []
    for _ in range(min(frame_count, preview_limit)):
        if float16:
            time = read_f16(payload, cursor, len(payload))
            if time is None:
                break
            cursor += 2
            values = []
            for _value in range(value_count):
                item = read_f16(payload, cursor, len(payload))
                if item is None:
                    cursor = len(payload)
                    break
                values.append(item)
                cursor += 2
        else:
            time_tuple = safe_unpack("<f", payload, cursor, len(payload))
            if time_tuple is None:
                break
            time = float(time_tuple[0])
            cursor += 4
            value_tuple = safe_unpack("<" + "f" * value_count, payload, cursor, len(payload))
            if value_tuple is None:
                cursor = len(payload)
                break
            values = [float(item) for item in value_tuple]
            cursor += 4 * value_count
        preview.append({"time": time, "values": values})
    return {
        "type_raw": f"0x{curve_type:08X}",
        "uses_float16": float16,
        "value_count": value_count,
        "frame_count": frame_count,
        "reserved": reserved,
        "preview_frames": preview,
        "consumed_preview_bytes": cursor,
    }


def decode_file_image_payload(payload: bytes) -> dict | None:
    size_tuple = safe_unpack("<I", payload, 0, len(payload))
    if size_tuple is None:
        return None
    data_size = size_tuple[0]
    blob = payload[4 : 4 + min(data_size, max(0, len(payload) - 4))]
    signature = blob[:12]
    ascii_sig = signature.decode("ascii", "ignore").rstrip("\x00")
    return {
        "declared_size": data_size,
        "available_size": len(blob),
        "embedded_signature_ascii": ascii_sig,
        "embedded_signature_hex": signature.hex(),
    }


def decode_leaf_payload(chunk: Chunk, data: bytes, preview_limit: int) -> dict | None:
    payload_start = chunk.offset + (8 if chunk.half_chunk else chunk.args_offs)
    payload_end = chunk.offset + chunk.next_offs
    if payload_start > payload_end or payload_end > len(data):
        return {"error": "invalid payload bounds"}
    payload = data[payload_start:payload_end]
    base_id = chunk.base_id

    if base_id == 0x0007:
        return decode_arrays_payload(payload, preview_limit)
    if base_id == 0x000C:
        return decode_fcurve_payload(payload, preview_limit)
    if base_id == 0x0012:
        return {"file_name": read_ascii_z(payload)}
    if base_id == 0x0013:
        return decode_file_image_payload(payload)
    if base_id == 0x0014:
        values = read_vec_f32(payload, 0, 6, len(payload))
        if values is not None:
            return {"min": values[:3], "max": values[3:6]}
    if base_id == 0x0015:
        header = safe_unpack("<I", payload, 0, len(payload))
        if header is not None:
            values = []
            if header[0] == 0x00000180:
                values = read_vec_f32(payload, 4, 6, len(payload)) or []
            elif header[0] == 0x00000003:
                values = read_vec_f32(payload, 4, 4, len(payload)) or []
            return {
                "offset_format": f"0x{header[0]:08X}",
                "offset_format_name": {
                    0x00000180: "VERTEX_FLOAT",
                    0x00000003: "TEXTURE_FLOAT",
                }.get(header[0], "UNKNOWN"),
                "values": values,
            }
    if base_id in {0x0041, 0x0044, 0x004E, 0x0061, 0x0091}:
        ref = decode_ref_triplet(payload)
        if ref is not None:
            return ref
    if base_id == 0x0042:
        value = safe_unpack("<I", payload, 0, len(payload))
        if value is not None:
            return {"visibility": value[0]}
    if base_id == 0x0045:
        count = safe_unpack("<I", payload, 0, len(payload))
        if count is not None:
            result = {"count": count[0]}
            if count[0] > 0:
                matrix = read_mat4_f32(payload, 4, len(payload))
                if matrix is not None:
                    result["first_matrix"] = matrix
            return result
    if base_id in {0x0046, 0x0048, 0x0049, 0x004A, 0x004C}:
        values = read_vec_f32(payload, 0, 3, len(payload))
        if values is not None:
            return {"values": values}
    if base_id == 0x004B:
        values = read_vec_f32(payload, 0, 4, len(payload))
        if values is not None:
            return {"quat_xyzw": values}
    if base_id == 0x0062:
        count = safe_unpack("<I", payload, 0, len(payload))
        if count is not None:
            subsets = []
            cursor = 4
            for _ in range(count[0]):
                value = safe_unpack("<I", payload, cursor, len(payload))
                if value is None:
                    break
                subsets.append(value[0])
                cursor += 4
            return {"count": count[0], "subsets": subsets[:preview_limit]}
    if base_id == 0x0066:
        return decode_draw_arrays_payload(payload, preview_limit)
    if base_id in {0x0082, 0x0084, 0x0085}:
        return decode_color_chunk(payload)
    if base_id == 0x0083:
        color = decode_color_chunk(payload[:16])
        shine = safe_unpack("<f", payload, 16, len(payload))
        if color is not None:
            color["shininess"] = float(shine[0]) if shine is not None else None
            return color
    if base_id in {0x0086, 0x0087, 0x0088, 0x0093, 0x00B2}:
        value = safe_unpack("<f", payload, 0, len(payload))
        if value is not None:
            return {"value": float(value[0])}
    if base_id == 0x0092:
        value = safe_unpack("<I", payload, 0, len(payload))
        if value is not None:
            raw = value[0]
            return {
                "map_type_raw": f"0x{raw:08X}",
                "map_type_label": CHUNK_LABELS.get(raw & ~HALF_CHUNK_ID, "unknown"),
            }
    if base_id == 0x0094:
        values = safe_unpack("<III", payload, 0, len(payload))
        if values is not None:
            return {"mode": values[0], "src": values[1], "dst": values[2]}
    if base_id == 0x0095:
        values = safe_unpack("<II", payload, 0, len(payload))
        if values is not None:
            return {"func": values[0], "comp": values[1]}
    if base_id == 0x0096:
        values = safe_unpack("<II", payload, 0, len(payload))
        if values is not None:
            return {"mag": values[0], "min": values[1]}
    if base_id == 0x0097:
        values = safe_unpack("<II", payload, 0, len(payload))
        if values is not None:
            return {"u": values[0], "v": values[1]}
    if base_id == 0x0098:
        values = read_vec_f32(payload, 0, 4, len(payload))
        if values is not None:
            return {"u_offset": values[0], "v_offset": values[1], "u_tiling": values[2], "v_tiling": values[3]}
    if base_id == 0x0099:
        value = safe_unpack("<I", payload, 0, len(payload))
        if value is not None:
            return {"tex_gen": f"0x{value[0]:08X}"}
    if base_id == 0x009A:
        matrix = read_mat4_f32(payload, 0, len(payload))
        if matrix is not None:
            return {"matrix": matrix}
    if base_id == 0x00B1:
        values = read_vec_f32(payload, 0, 2, len(payload))
        if values is not None:
            return {"start": values[0], "end": values[1]}
    if base_id == 0x00B3:
        values = safe_unpack("<IIII", payload, 0, len(payload))
        if values is not None:
            return {
                "block": values[0],
                "type_raw": f"0x{values[1]:08X}",
                "type_label": CHUNK_LABELS.get(values[1] & ~HALF_CHUNK_ID, "unknown"),
                "index": values[2],
                "fcurve": values[3],
            }
    if base_id == 0x00F1:
        name = read_ascii_z(payload[:12])
        result = {"blind_data_name": name}
        value = safe_unpack("<I", payload, 12, len(payload))
        if name == "per3Helper" and value is not None:
            result["helper_id"] = value[0]
            vecs = []
            cursor = 16
            for _ in range(3):
                vec = read_vec_f32(payload, cursor, 3, len(payload))
                if vec is None:
                    break
                vecs.append(vec)
                cursor += 12
            result["vectors"] = vecs
        return result
    return None


def annotate_payloads(chunk: Chunk, data: bytes, preview_limit: int) -> None:
    if not chunk.children:
        chunk.payload = decode_leaf_payload(chunk, data, preview_limit)
    for child in chunk.children:
        annotate_payloads(child, data, preview_limit)


def payload_summary(chunk: Chunk) -> str | None:
    payload = chunk.payload
    if not payload:
        return None
    base_id = chunk.base_id
    if base_id == 0x0007:
        layout = payload.get("layout", {})
        weight_text = layout.get("weight_format")
        if weight_text == "NONE":
            weight_text = "NONE"
        else:
            weight_text = f"{weight_text}x{layout.get('weight_count')}"
        return (
            f"verts={payload.get('verts_count')} morphs={payload.get('morphs_count')} "
            f"tex={layout.get('texture_format')} color={layout.get('color_format')} "
            f"nrm={layout.get('normal_format')} pos={layout.get('vertex_format')} "
            f"w={weight_text} "
            f"stride~={layout.get('record_stride_estimate')}"
        )
    if base_id == 0x0066:
        ref = payload.get("arrays_ref") or {}
        return (
            f"arrays_ref=({ref.get('index')},{ref.get('level')},{ref.get('type')}) "
            f"mode={payload.get('mode')} verts={payload.get('vertex_count')} prims={payload.get('primitive_count')} "
            f"seq={payload.get('sequential')}"
        )
    if base_id == 0x0012:
        return f"file={payload.get('file_name')!r}"
    if base_id == 0x0013:
        return f"data={payload.get('declared_size')} sig={payload.get('embedded_signature_ascii')!r}"
    if base_id == 0x0014:
        return f"min={payload.get('min')} max={payload.get('max')}"
    if base_id == 0x0015:
        return f"format={payload.get('offset_format_name')} values={payload.get('values')}"
    if base_id in {0x0041, 0x0044, 0x004E, 0x0061, 0x0091}:
        return f"ref=({payload.get('index')},{payload.get('level')},{payload.get('type')})"
    if base_id in {0x0046, 0x0048, 0x0049, 0x004A, 0x004B, 0x004C}:
        return str(payload.get("values") or payload.get("quat_xyzw"))
    if base_id in {0x0082, 0x0083, 0x0084, 0x0085}:
        return f"rgba={payload.get('rgba_unit')}"
    if base_id == 0x00B1:
        return f"start={payload.get('start')} end={payload.get('end')}"
    if base_id == 0x00B2:
        return f"value={payload.get('value')}"
    if base_id == 0x00B3:
        return (
            f"block=0x{payload.get('block', 0):X} type={payload.get('type_label')} "
            f"index={payload.get('index')} fcurve={payload.get('fcurve')}"
        )
    if base_id == 0x000C:
        return (
            f"type={payload.get('type_raw')} values={payload.get('value_count')} "
            f"frames={payload.get('frame_count')} float16={payload.get('uses_float16')}"
        )
    return None


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


def inspect_gmo(path: Path, max_strings: int, decode_payloads: bool, preview_limit: int) -> GmoReport:
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
        if decode_payloads:
            annotate_payloads(root, data, preview_limit)
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


def format_chunk(chunk: Chunk, depth: int, max_depth: int, show_payloads: bool) -> list[str]:
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
    if show_payloads:
        summary = payload_summary(chunk)
        if summary:
            line += f" payload={summary}"
    lines = [line]
    if depth >= max_depth:
        return lines
    for child in chunk.children:
        lines.extend(format_chunk(child, depth + 1, max_depth, show_payloads))
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
        for line in format_chunk(report.root, 0, args.tree_depth, args.payloads):
            print(f"    {line}")
    if args.max_strings != 0 and report.strings:
        print("  strings:")
        values = report.strings if args.max_strings < 0 else report.strings[: args.max_strings]
        for value in values:
            print(f"    {value}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect GMO files and report chunk structure plus a coarse family classification."
    )
    parser.add_argument("paths", nargs="+", help="GMO files or directories to inspect")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    parser.add_argument("--tree", action="store_true", help="Print the parsed chunk tree in text mode")
    parser.add_argument(
        "--payloads",
        action="store_true",
        help="Decode selected leaf payloads and include summaries in the tree / structured payloads in JSON",
    )
    parser.add_argument(
        "--tree-depth",
        type=int,
        default=6,
        help="Maximum depth to print when --tree is enabled (default: 6)",
    )
    parser.add_argument(
        "--preview-limit",
        type=int,
        default=3,
        help="Maximum number of preview items to decode for variable-length payloads (default: 3)",
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

    reports = [
        inspect_gmo(
            path,
            args.max_strings if args.max_strings >= 0 else -1,
            args.payloads,
            args.preview_limit,
        )
        for path in paths
    ]
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
