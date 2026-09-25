"""Build 3D Tiles tileset archives for the upload tests."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path

REGION = [-1.3197, 0.6988, -1.3196, 0.6989, 0.0, 88.0]

GLB_JSON = 0x4E4F534A
GLB_BIN = 0x004E4942


def tileset_json(
    *,
    version: object = "1.1",
    volume: dict | None = None,
    geometric_error: object = 70.0,
    extra: dict | None = None,
) -> bytes:
    root: dict = {"boundingVolume": volume or {"region": REGION}, "refine": "ADD"}
    if geometric_error is not None:
        root["geometricError"] = geometric_error
    return json.dumps(
        {
            "asset": {"version": version},
            "geometricError": 500.0,
            "root": root,
            **(extra or {}),
        }
    ).encode()


def zip_bytes(
    entries: list[tuple[str | zipfile.ZipInfo, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buffer.getvalue()


def build_zip(
    path: Path,
    entries: list[tuple[str | zipfile.ZipInfo, bytes]],
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> str:
    path.write_bytes(zip_bytes(entries, compression=compression))
    return str(path)


def tileset_zip(path: Path, *more: tuple[str | zipfile.ZipInfo, bytes], **json_kw):
    return build_zip(
        path,
        [("tileset.json", tileset_json(**json_kw)), ("0/0.glb", b"glb"), *more],
    )


def gltf_json(**fields: object) -> bytes:
    return json.dumps({"asset": {"version": "2.0"}, **fields}).encode()


def _padded(data: bytes, width: int = 8) -> bytes:
    return data + b" " * (-len(data) % width)


def glb(
    document: bytes,
    *,
    version: int = 2,
    chunks: list[tuple[int, bytes]] | None = None,
) -> bytes:
    """A binary glTF with ``document`` as its JSON chunk and a small BIN chunk."""
    if version == 1:
        header = struct.pack("<4s4I", b"glTF", 1, 20 + len(document), len(document), 0)
        return header + document
    if chunks is None:
        chunks = [(GLB_JSON, _padded(document, 4)), (GLB_BIN, bytes(4))]
    body = b"".join(struct.pack("<2I", len(data), kind) + data for kind, data in chunks)
    return struct.pack("<4s2I", b"glTF", 2, 12 + len(body)) + body


def b3dm(gltf: bytes, *, legacy: int = 0) -> bytes:
    """A Batched 3D Model around ``gltf``, in the current or a legacy header."""
    if legacy == 1:
        # [batchLength] [batchTableByteLength]
        return struct.pack("<4s4I", b"b3dm", 1, 20 + len(gltf), 0, 0) + gltf
    if legacy == 2:
        # [batchTableJsonByteLength] [batchTableBinaryByteLength] [batchLength]
        return struct.pack("<4s5I", b"b3dm", 1, 24 + len(gltf), 0, 0, 0) + gltf
    table = _padded(b'{"BATCH_LENGTH":0}')
    length = 28 + len(table) + len(gltf)
    return struct.pack("<4s6I", b"b3dm", 1, length, len(table), 0, 0, 0) + table + gltf


def i3dm(gltf: bytes, *, gltf_format: int = 1) -> bytes:
    """An Instanced 3D Model embedding ``gltf``, or naming it by URI with format 0."""
    table = _padded(b'{"INSTANCES_LENGTH":0}')
    length = 32 + len(table) + len(gltf)
    header = struct.pack("<4s7I", b"i3dm", 1, length, len(table), 0, 0, 0, gltf_format)
    return header + table + gltf


def cmpt(*tiles: bytes) -> bytes:
    body = b"".join(tiles)
    return struct.pack("<4s3I", b"cmpt", 1, 16 + len(body), len(tiles)) + body


def subtree(document: bytes) -> bytes:
    """A binary implicit-tiling subtree with ``document`` as its JSON chunk."""
    data = _padded(document)
    return struct.pack("<4sIQQ", b"subt", 1, len(data), 0) + data


def pnts() -> bytes:
    """A Point Cloud tile of one point at the origin."""
    table = _padded(b'{"POINTS_LENGTH":1,"POSITION":{"byteOffset":0}}')
    positions = bytes(12)
    length = 28 + len(table) + len(positions)
    header = struct.pack("<4s6I", b"pnts", 1, length, len(table), len(positions), 0, 0)
    return header + table + positions


def three_tz(entries: list[tuple[str, bytes]]) -> bytes:
    """A .3tz archive: ``entries``, then the stored ``@3dtilesIndex1@`` index of them.

    Each index record is an entry name's MD5 and its local header offset, sorted
    by the MD5 read as two little-endian 64-bit integers.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)
        records = sorted(
            (
                (hashlib.md5(info.filename.encode()).digest(), info.header_offset)
                for info in archive.infolist()
            ),
            key=lambda record: struct.unpack("<2Q", record[0]),
        )
        index = b"".join(
            digest + struct.pack("<Q", offset) for digest, offset in records
        )
        archive.writestr(
            zipfile.ZipInfo("@3dtilesIndex1@"), index, compress_type=zipfile.ZIP_STORED
        )
    return buffer.getvalue()
