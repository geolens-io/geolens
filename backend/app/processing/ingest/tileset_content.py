"""Refuse a URI that leaves the tileset from any file in its archive.

CesiumJS resolves every URI a tileset's files name from the resource that
loaded the tileset, credentials included, so a URI naming another origin
would send them there. Each file is typed as CesiumJS types it, by its magic
or else as JSON, and only the parts a client parses as JSON are parsed here.
"""

from __future__ import annotations

import json
import re
import struct
import zipfile
from dataclasses import dataclass
from typing import IO, NoReturn

from app.processing.ingest import tileset
from app.processing.ingest.tileset import TilesetLayout, _refuse, check_uri, check_uris
from app.processing.ingest.validation import _member_read_errors

# What the scan reads in all, across every file: the JSON it parses, and the
# tile and GLB chunk headers it walks to find that JSON.
MAX_SCANNED_JSON_BYTES = 1024**3
MAX_CONTENT_HEADERS = 10_000_000
MAX_COMPOSITE_DEPTH = 16

# b3dm's two legacy headers put a JSON quote or the "glTF" magic where a
# length would be, which reads as at least this.
_B3DM_LEGACY_LENGTH = 0x22000000
_GLB_JSON_CHUNK = 0x4E4F534A
_TILES = frozenset({b"b3dm", b"i3dm", b"cmpt", b"subt"})
_TILES_WITHOUT_URIS = frozenset({b"pnts", b"vctr", b"geom", b"voxl"})
# CesiumJS hands a composite's gltf-typed tile the whole composite, which its
# glTF loader can't read, and then goes on to the tiles after it.
_GLTF_TILE = b"gltf"

_UTF8_BOM = b"\xef\xbb\xbf"
_JSON_BLANKS = b" \t\n\r"
_JSON_HEAD_BYTES = 4096
# JSON admits no other control character, inside a string or out of one.
_CONTROL_BYTE = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _refuse_overlap(key: str) -> NoReturn:
    _refuse(
        f"The tile headers in {key} overlap or point backwards.",
        reason="tileset_content_bounds",
    )


@dataclass
class _Budget:
    json_bytes: int
    headers: int


class _Member:
    """One file of the archive, read forward only; the last read can be reread."""

    def __init__(self, handle: IO[bytes], key: str, size: int, budget: _Budget):
        self.key = key
        self.size = size
        self.budget = budget
        self._handle = handle
        self._start = 0
        self._last = b""

    def read(self, offset: int, length: int) -> bytes:
        end = min(offset + length, self.size)
        if offset >= end:
            return b""
        if offset < self._start:
            _refuse_overlap(self.key)
        last_end = self._start + len(self._last)
        if end <= last_end:
            return self._last[offset - self._start : end - self._start]
        if offset < last_end:
            data = self._last[offset - self._start :] + self._handle.read(
                end - last_end
            )
        else:
            self._handle.seek(offset)
            data = self._handle.read(end - offset)
        self._start, self._last = offset, data
        return data

    def count_header(self) -> None:
        self.budget.headers -= 1
        if self.budget.headers < 0:
            _refuse(
                "The tileset's files hold more than "
                f"{MAX_CONTENT_HEADERS:,} tile and chunk headers, more than this "
                "server reads.",
                reason="tileset_content_bounds",
            )

    def read_part(self, start: int, end: int) -> bytes:
        """A JSON or URI part of this file, within the per-part and total bounds."""
        if end - start > tileset.MAX_TILESET_JSON_BYTES:
            _refuse(
                f"{self.key} holds a JSON or URI part larger than the "
                f"{tileset.MAX_TILESET_JSON_BYTES // 1024**2} MB this server reads.",
                reason="tileset_json_size",
            )
        self.budget.json_bytes -= end - start
        if self.budget.json_bytes < 0:
            _refuse(
                "The tileset's files hold more JSON than the "
                f"{MAX_SCANNED_JSON_BYTES // 1024**2} MB this server reads in all.",
                reason="tileset_json_size",
            )
        return self.read(start, end - start)


def _may_be_json_object(head: bytes) -> bool:
    """Whether JSON.parse could make an object of bytes that start with ``head``."""
    if _CONTROL_BYTE.search(head):
        return False
    text = head.removeprefix(_UTF8_BOM).lstrip(_JSON_BLANKS)
    if text[:1] != b"{":
        return not text
    return text[1:].lstrip(_JSON_BLANKS)[:1] in (b"", b'"', b"}")


def _check_json(member: _Member, start: int, end: int) -> None:
    if start >= end or not _may_be_json_object(
        member.read(start, min(end - start, _JSON_HEAD_BYTES))
    ):
        return
    raw = member.read_part(start, end)
    if _CONTROL_BYTE.search(raw):
        return
    try:
        # Numbers as floats, as JSON.parse reads them: Python refuses an
        # integer past 4300 digits, which would skip a document CesiumJS reads.
        document = json.loads(
            raw.decode("utf-8-sig", "replace"), strict=False, parse_int=float
        )
    except RecursionError:
        _refuse(
            f"{member.key} holds JSON nested too deeply to read.",
            reason="tileset_json_depth",
        )
    except ValueError:
        return
    if isinstance(document, dict):
        check_uris(document, member.key)


def _check_glb(member: _Member, start: int, end: int) -> None:
    header = member.read(start, 20)
    if len(header) < 12:
        return
    version, length = struct.unpack_from("<2I", header, 4)
    if version == 1 and len(header) == 20:
        content_length, content_format = struct.unpack_from("<2I", header, 12)
        if content_format == 0:
            _check_json(member, start + 20, min(start + 20 + content_length, end))
    elif version == 2:
        # Every chunk is walked: CesiumJS keeps the last JSON chunk, and a
        # chunk starting past the end holds nothing.
        offset = start + 12
        while offset < start + length and offset + 8 < end:
            member.count_header()
            chunk_length, chunk_type = struct.unpack("<2I", member.read(offset, 8))
            offset += 8
            if chunk_type == _GLB_JSON_CHUNK:
                _check_json(member, offset, min(offset + chunk_length, end))
            offset += chunk_length


def _check_gltf(member: _Member, start: int, end: int) -> None:
    """The glTF a b3dm or i3dm embeds: a GLB, or else JSON."""
    if start >= end:
        return
    if member.read(start, 4) == b"glTF":
        _check_glb(member, start, end)
    else:
        _check_json(member, start, end)


def _table_end(
    offset: int, ft_json: int, ft_bin: int, bt_json: int, bt_bin: int
) -> int:
    # The batch table's binary is skipped only when it has JSON.
    return offset + ft_json + ft_bin + (bt_json + bt_bin if bt_json else 0)


def _check_b3dm(member: _Member, start: int) -> None:
    header = member.read(start, 28)
    if len(header) < 28:
        return
    version, length, ft_json, ft_bin, bt_json, bt_bin = struct.unpack_from(
        "<6I", header, 4
    )
    if version != 1:
        return
    offset = start + 28
    if bt_json >= _B3DM_LEGACY_LENGTH:
        offset, ft_json, ft_bin, bt_json, bt_bin = start + 20, 0, 0, ft_bin, 0
    elif bt_bin >= _B3DM_LEGACY_LENGTH:
        offset, ft_json, ft_bin, bt_json, bt_bin = start + 24, 0, 0, ft_json, ft_bin
    offset = _table_end(offset, ft_json, ft_bin, bt_json, bt_bin)
    _check_gltf(member, offset, min(start + length, member.size))


def _check_i3dm(member: _Member, start: int) -> None:
    header = member.read(start, 32)
    if len(header) < 32:
        return
    version, length, ft_json, ft_bin, bt_json, bt_bin, gltf_format = struct.unpack_from(
        "<7I", header, 4
    )
    if version != 1 or ft_json == 0:
        return
    offset = _table_end(start + 32, ft_json, ft_bin, bt_json, bt_bin)
    end = min(start + length, member.size)
    if gltf_format == 1:
        _check_gltf(member, offset, end)
    elif gltf_format == 0 and offset < end:
        # The model is a URI, resolved from the i3dm's folder.
        url = member.read_part(offset, end).decode("utf-8", "replace")
        check_uri(member.key, url, inline_ok=False)


def _check_subtree(member: _Member, start: int) -> None:
    header = member.read(start, 24)
    if len(header) < 24:
        return
    # CesiumJS reads only the low half of the 64-bit JSON length.
    (json_length,) = struct.unpack_from("<I", header, 8)
    _check_json(member, start + 24, min(start + 24 + json_length, member.size))


def _check_composite(member: _Member, start: int, depth: int) -> None:
    if depth > MAX_COMPOSITE_DEPTH:
        _refuse(
            f"{member.key} nests composite tiles deeper than "
            f"{MAX_COMPOSITE_DEPTH} levels.",
            reason="tileset_content_bounds",
        )
    header = member.read(start, 16)
    if len(header) < 16:
        return
    version, _, tiles = struct.unpack_from("<3I", header, 4)
    if version != 1:
        return
    inner = start + 16
    for _ in range(tiles):
        head = member.read(inner, 12)
        if len(head) < 12:
            return
        member.count_header()
        magic, (length,) = head[:4], struct.unpack_from("<I", head, 8)
        if length < 12:
            # The next tile would start inside this one's header.
            _refuse_overlap(member.key)
        if magic in _TILES:
            _check_tile(member, inner, magic, depth + 1)
        elif magic == _GLTF_TILE:
            _refuse(
                f"{member.key} holds a composite tile typed gltf, which no "
                "writer produces and a client reads past without loading.",
                reason="tileset_composite_gltf",
            )
        elif magic not in _TILES_WITHOUT_URIS:
            # CesiumJS throws at a tile type it has no factory for.
            return
        inner += length


def _check_tile(member: _Member, start: int, magic: bytes, depth: int) -> None:
    if magic == b"b3dm":
        _check_b3dm(member, start)
    elif magic == b"i3dm":
        _check_i3dm(member, start)
    elif magic == b"cmpt":
        _check_composite(member, start, depth)
    else:
        _check_subtree(member, start)


def _check_file(member: _Member) -> None:
    magic = member.read(0, 4)
    if magic == b"glTF":
        _check_glb(member, 0, member.size)
    elif magic in _TILES:
        _check_tile(member, 0, magic, 1)
    elif magic not in _TILES_WITHOUT_URIS:
        _check_json(member, 0, member.size)


def check_archive_uris(path: str, layout: TilesetLayout) -> None:
    """Refuse a file in the checked archive that names a URI outside the tileset."""
    budget = _Budget(json_bytes=MAX_SCANNED_JSON_BYTES, headers=MAX_CONTENT_HEADERS)
    with zipfile.ZipFile(path) as archive:
        for info, key in layout.files:
            with _member_read_errors(key), archive.open(info) as handle:
                _check_file(_Member(handle, key, info.file_size, budget))
