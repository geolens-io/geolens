"""Refuse a URI that leaves the tileset from any file in its archive.

CesiumJS resolves every URI a tileset's files name from the resource that
loaded the tileset, credentials included, so a URI naming another origin
would send them there. Each file is typed as CesiumJS types it, by its magic
or else as JSON, and only the parts a client parses as JSON are parsed here.
The same read records the tileset's content types and required extensions.
"""

from __future__ import annotations

import json
import re
import struct
import zipfile
from dataclasses import dataclass, field
from typing import IO, NoReturn

from app.processing.ingest import tileset
from app.processing.ingest.tileset import (
    TilesetContents,
    TilesetLayout,
    _object,
    _refuse,
    check_uri,
    check_uris,
)
from app.processing.ingest.validation import _member_read_errors

# What the scan reads in all, across every file: the JSON it parses, and the
# tile and GLB chunk headers it walks to find that JSON.
MAX_SCANNED_JSON_BYTES = 1024**3
MAX_CONTENT_HEADERS = 10_000_000
MAX_COMPOSITE_DEPTH = 16
# Far more than any tileset lists; the names are stored on the dataset row.
MAX_REQUIRED_EXTENSIONS = 256

# b3dm's two legacy headers put a JSON quote or the "glTF" magic where a
# length would be, which reads as at least this.
_B3DM_LEGACY_LENGTH = 0x22000000
_GLB_JSON_CHUNK = 0x4E4F534A
_TILES = frozenset({b"b3dm", b"i3dm", b"cmpt", b"subt"})
_TILES_WITHOUT_URIS = frozenset({b"pnts", b"vctr", b"geom", b"voxl"})
# CesiumJS hands a composite's gltf-typed tile the whole composite, which its
# glTF loader can't read, and then goes on to the tiles after it.
_GLTF_TILE = b"gltf"
_CONTENT_TYPES = {
    b"b3dm": "b3dm",
    b"i3dm": "i3dm",
    b"cmpt": "cmpt",
    b"subt": "subtree",
    b"pnts": "pnts",
    b"vctr": "vctr",
    b"geom": "geom",
    b"glTF": "glb",
}
# How extensions are named; anything else is no extension a client knows.
_EXTENSION_NAME = re.compile(r"[A-Za-z0-9_]{1,64}")

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
class _Scan:
    """The budgets every file shares, and what the files hold."""

    json_bytes: int
    headers: int
    content_types: set[str] = field(default_factory=set)
    extensions_required: set[str] = field(default_factory=set)

    def require(self, names: object) -> None:
        """Keep the extensions an extensionsRequired array names."""
        for name in names if isinstance(names, list) else []:
            if isinstance(name, str) and _EXTENSION_NAME.fullmatch(name):
                self.extensions_required.add(name)
        if len(self.extensions_required) > MAX_REQUIRED_EXTENSIONS:
            _refuse(
                "The tileset's files require more than "
                f"{MAX_REQUIRED_EXTENSIONS} extensions, more than this server reads.",
                reason="tileset_content_bounds",
            )


class _Member:
    """One file of the archive, read forward only; the last read can be reread."""

    def __init__(self, handle: IO[bytes], key: str, size: int, scan: _Scan):
        self.key = key
        self.size = size
        self.scan = scan
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
        self.scan.headers -= 1
        if self.scan.headers < 0:
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
        self.scan.json_bytes -= end - start
        if self.scan.json_bytes < 0:
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


def _check_json(member: _Member, start: int, end: int) -> dict | None:
    """The JSON object a client would parse from [start, end), once its URIs pass."""
    if start >= end or not _may_be_json_object(
        member.read(start, min(end - start, _JSON_HEAD_BYTES))
    ):
        return None
    raw = member.read_part(start, end)
    if _CONTROL_BYTE.search(raw):
        return None
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
        return None
    if not isinstance(document, dict):
        return None
    check_uris(document, member.key)
    return document


def _check_gltf_json(member: _Member, start: int, end: int) -> None:
    document = _check_json(member, start, end)
    if document is not None:
        member.scan.require(document.get("extensionsRequired"))


def _check_glb(member: _Member, start: int, end: int) -> None:
    header = member.read(start, 20)
    if len(header) < 12:
        return
    version, length = struct.unpack_from("<2I", header, 4)
    if version == 1 and len(header) == 20:
        content_length, content_format = struct.unpack_from("<2I", header, 12)
        if content_format == 0:
            _check_gltf_json(member, start + 20, min(start + 20 + content_length, end))
    elif version == 2:
        # Every chunk is walked: CesiumJS keeps the last JSON chunk, and a
        # chunk starting past the end holds nothing.
        offset = start + 12
        while offset < start + length and offset + 8 < end:
            member.count_header()
            chunk_length, chunk_type = struct.unpack("<2I", member.read(offset, 8))
            offset += 8
            if chunk_type == _GLB_JSON_CHUNK:
                _check_gltf_json(member, offset, min(offset + chunk_length, end))
            offset += chunk_length


def _check_gltf(member: _Member, start: int, end: int) -> None:
    """The glTF a b3dm or i3dm embeds: a GLB, or else JSON."""
    if start >= end:
        return
    if member.read(start, 4) == b"glTF":
        _check_glb(member, start, end)
    else:
        _check_gltf_json(member, start, end)


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
        _record_type(member.scan, magic)
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


def _record_type(scan: _Scan, magic: bytes) -> None:
    content_type = _CONTENT_TYPES.get(magic)
    if content_type is not None:
        scan.content_types.add(content_type)


def _record_json_file(scan: _Scan, document: dict) -> None:
    """Type a JSON file the way CesiumJS does, and keep what it requires."""
    if document.get("root") is not None:
        scan.require(document.get("extensionsRequired"))
        # 1.0 tilesets list the glTF extensions their content requires here.
        content_gltf = _object(document.get("extensions")).get("3DTILES_content_gltf")
        scan.require(_object(content_gltf).get("extensionsRequired"))
    elif document.get("asset") is not None:
        scan.content_types.add("gltf")
        scan.require(document.get("extensionsRequired"))
    elif document.get("tileAvailability") is not None:
        scan.content_types.add("subtree")


def _check_file(member: _Member) -> None:
    magic = member.read(0, 4)
    _record_type(member.scan, magic)
    if magic == b"glTF":
        _check_glb(member, 0, member.size)
    elif magic in _TILES:
        _check_tile(member, 0, magic, 1)
    elif magic not in _TILES_WITHOUT_URIS:
        document = _check_json(member, 0, member.size)
        if document is not None:
            _record_json_file(member.scan, document)


def scan_tileset_archive(path: str, layout: TilesetLayout) -> TilesetContents:
    """Refuse a file that names a URI outside the tileset; report what the files hold."""
    scan = _Scan(json_bytes=MAX_SCANNED_JSON_BYTES, headers=MAX_CONTENT_HEADERS)
    with zipfile.ZipFile(path) as archive:
        for info, key in layout.files:
            with _member_read_errors(key), archive.open(info) as handle:
                _check_file(_Member(handle, key, info.file_size, scan))
    return TilesetContents(
        content_types=tuple(sorted(scan.content_types)),
        extensions_required=tuple(sorted(scan.extensions_required)),
    )
