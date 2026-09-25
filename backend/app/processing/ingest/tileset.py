"""Read an uploaded 3D Tiles tileset archive without unpacking it.

A tileset upload never reaches GDAL. Its archive is read with ``zipfile``
alone, and every check here runs on the central directory and the
``tileset.json`` entry, so a refusal lands before any object is written.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import stat
import struct
import tempfile
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, NoReturn
from urllib.parse import unquote

import structlog
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.tiles3d import (
    TILESET_ARCHIVE_SUFFIX,
    TILESET_ENTRY_POINT,
    TILESET_FILE_TYPE,
    TILESET_UPLOAD_SUFFIXES,
)
from app.core.upload_errors import UnsafeUploadError
from app.platform.storage import StorageProvider
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.processing.ingest.schemas import TilesetPreviewResponse
from app.processing.ingest.validation import (
    _ZIP64_EOCD,
    _ZIP64_LOCATOR,
    _ZIP64_LOCATOR_SIGNATURE,
    MAX_CENTRAL_DIRECTORY_BYTES,
    MAX_COMPRESSION_RATIO,
    _end_record_index,
    _member_read_errors,
    _validate_zip_directory_cardinality,
    _zip_directory_metadata,
)

if TYPE_CHECKING:
    from app.platform.jobs.models import IngestJob

logger = structlog.get_logger(__name__)

# The job-row field holding the unpacked total the upload door measured, which
# the commit door checks against the quota again.
TILESET_UNPACKED_BYTES_FIELD = "tileset_unpacked_bytes"

# tileset.json is parsed whole, so it has its own bounds. A tile tree nests two
# JSON levels per tile level, so 128 still allows a tree 60 tiles deep.
MAX_TILESET_JSON_BYTES = 16 * 1024 * 1024
MAX_TILESET_JSON_DEPTH = 128

# Every name becomes a storage key under a tenant and attempt prefix, which S3
# caps at 1024 bytes, and the local adapter writes a temporary file named
# after each segment plus 37 bytes, which a filesystem caps at 255.
MAX_ENTRY_NAME_BYTES = 800
MAX_ENTRY_SEGMENT_BYTES = 200

TILESET_VERSIONS = frozenset({"1.0", "1.1"})

# The volumes the root may declare and how many numbers each takes. A region
# is read first because it is the only one that yields an extent.
_BOUNDING_VOLUMES = (("region", 6), ("box", 12), ("sphere", 4))

# How far a region may stray past a pole or the antimeridian and still be read
# as reaching it; writers round pi, sometimes upward.
_REGION_TOLERANCE_RADIANS = 1e-6

_READABLE_METHODS = frozenset(
    {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA}
)

# Control characters, and the separators and escapes that let a name mean a
# different path to storage, to a filesystem or to the tileset route.
_FORBIDDEN_NAME_CHARACTERS = re.compile(r"[\x00-\x1f\x7f\\:%]")

# zipfile trims a name at its first NUL and may take it from this extra field
# instead of the central directory, so both recorded forms are checked.
_UNICODE_PATH_EXTRA_FIELD = 0x7075

# The closing quote is optional: an unclosed string then runs to the end instead
# of failing and rescanning from every later quote. json.loads refuses it anyway.
_JSON_STRING = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"?')
_NOT_A_BRACKET = re.compile(r"[^\[\]{}]+")

# urijs, which CesiumJS resolves URIs with, and browsers drop these blanks from
# a URI's ends, and tabs and newlines from anywhere in it. Dropping more than
# they do only refuses more.
_URI_BLANKS = (
    "".join(map(chr, [*range(0x21), 0x85, 0xA0, 0x1680, *range(0x2000, 0x200B)]))
    + "\u2028\u2029\u202f\u205f\u3000\ufeff"
)
_URI_DROPPED = dict.fromkeys(map(ord, "\t\n\r"))

# glTF and tileset extensions whose schemaUri names a metadata schema.
_SCHEMA_EXTENSIONS = (
    "3DTILES_metadata",
    "EXT_structural_metadata",
    "EXT_feature_metadata",
)

# A .3tz archive's last entry, an index of its other entries by name hash.
_ARCHIVE_INDEX = "@3dtilesIndex1@"

# The end-of-central-directory record, its longest comment, and the ZIP64
# locator right before it.
_ARCHIVE_TAIL_BYTES = 22 + 0xFFFF + 20
_LOCAL_HEADER_BYTES = 30


@dataclass(frozen=True)
class TilesetFacts:
    """What the tileset's own ``tileset.json`` says about it."""

    version: str
    geometric_error: float | None
    bounding_volume: str
    # [west, south, east, north] in degrees; west > east when it crosses the
    # antimeridian, and None for a box or sphere.
    extent_bbox: tuple[float, float, float, float] | None


@dataclass(frozen=True)
class TilesetLayout:
    """The archive's files, keyed relative to the folder holding tileset.json."""

    files: tuple[tuple[zipfile.ZipInfo, str], ...]
    entry_point: zipfile.ZipInfo
    unpacked_bytes: int
    entry_count: int


@dataclass(frozen=True)
class Tileset:
    layout: TilesetLayout
    facts: TilesetFacts


def _refuse(message: str, *, reason: str) -> NoReturn:
    # Never the entry name: the refusal may be about the characters in it.
    logger.warning("Tileset archive refused", event_type="security", reason=reason)
    raise UnsafeUploadError(message)


def _recorded_names(info: zipfile.ZipInfo) -> list[str]:
    names = [info.orig_filename]
    extra = info.extra
    while len(extra) >= 4:
        kind, size = struct.unpack("<HH", extra[:4])
        if kind == _UNICODE_PATH_EXTRA_FIELD:
            names.append(extra[9 : 4 + size].decode("utf-8", "replace"))
        extra = extra[4 + size :]
    return names


def _entry_path(info: zipfile.ZipInfo) -> str:
    """The entry's path without a directory's trailing slash, or a refusal."""
    if any(_FORBIDDEN_NAME_CHARACTERS.search(n) for n in _recorded_names(info)):
        _refuse(
            "An entry name in the archive contains a control character, a "
            "backslash, a colon or a percent sign. Rename it and zip the "
            "tileset again.",
            reason="tileset_entry_characters",
        )
    path = info.filename[:-1] if info.is_dir() else info.filename
    segments = path.split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        _refuse(
            "An entry in the archive has an absolute path, or an empty, '.' or "
            "'..' path segment. Every entry must sit below the archive root.",
            reason="tileset_entry_path",
        )
    if len(path.encode()) > MAX_ENTRY_NAME_BYTES or any(
        len(segment.encode()) > MAX_ENTRY_SEGMENT_BYTES for segment in segments
    ):
        _refuse(
            f"An entry name in the archive is longer than {MAX_ENTRY_NAME_BYTES} "
            f"bytes, or has a part longer than {MAX_ENTRY_SEGMENT_BYTES}.",
            reason="tileset_entry_length",
        )
    return path


def _check_entry_contents(info: zipfile.ZipInfo) -> None:
    kind = stat.S_IFMT(info.external_attr >> 16)
    if kind not in ((0, stat.S_IFDIR) if info.is_dir() else (0, stat.S_IFREG)):
        _refuse(
            "The archive contains a symbolic link or a special file. A tileset "
            "archive may hold only folders and regular files.",
            reason="tileset_special_entry",
        )
    if info.flag_bits & 0x1 or info.compress_type not in _READABLE_METHODS:
        _refuse(
            "The archive contains an encrypted entry or one compressed with a "
            "method this server cannot read.",
            reason="tileset_unreadable_entry",
        )
    if info.file_size and (
        info.compress_size == 0
        or info.file_size > MAX_COMPRESSION_RATIO * info.compress_size
    ):
        _refuse(
            "An entry in the archive expands to more than "
            f"{MAX_COMPRESSION_RATIO} times its compressed size.",
            reason="zip_bomb_indicator",
        )


def _fold(path: str) -> str:
    """The one spelling a case-insensitive disk gives every form of ``path``."""
    return unicodedata.normalize("NFC", path).casefold()


def _refuse_collisions(paths: list[tuple[str, bool]]) -> None:
    """Refuse two entries that would land on one path of a case-insensitive disk."""
    # "/" becomes NUL, which no name holds, so each path sorts right before the
    # paths inside it and only neighbours need comparing.
    keyed = sorted(
        (_fold(path).replace("/", "\0"), is_dir, path) for path, is_dir in paths
    )
    for (key, is_dir, path), (next_key, next_is_dir, _) in pairwise(keyed):
        if key == next_key and not (is_dir or next_is_dir):
            _refuse(
                "Two entries in the archive differ only by letter case or "
                f"Unicode form ({path!r}), so one would overwrite the other.",
                reason="tileset_entry_collision",
            )
        if not is_dir and (key == next_key or next_key.startswith(f"{key}\0")):
            _refuse(
                f"The archive has both a file and a folder at {path!r}.",
                reason="tileset_entry_collision",
            )


def _tileset_root(paths: list[tuple[str, bool]]) -> str:
    """The folder prefix holding tileset.json: none, or the one top-level folder."""
    files = {path for path, is_dir in paths if not is_dir}
    if TILESET_ENTRY_POINT in files:
        return ""
    tops = {path.split("/", 1)[0] for path, _ in paths}
    if len(tops) == 1 and f"{next(iter(tops))}/{TILESET_ENTRY_POINT}" in files:
        return f"{next(iter(tops))}/"
    if len(tops) > 1:
        _refuse(
            f"The archive has no {TILESET_ENTRY_POINT} at its root and holds "
            f"{len(tops)} top-level entries. Put {TILESET_ENTRY_POINT} at the "
            "root, or everything inside one folder.",
            reason="tileset_layout",
        )
    _refuse(
        f"The archive has no {TILESET_ENTRY_POINT} at its root or inside a "
        "single top-level folder.",
        reason="tileset_layout",
    )


def _is_packaging(path: str) -> bool:
    """Whether Finder or a .3tz writer added the entry: never tileset content."""
    name = path.rpartition("/")[2]
    return (
        path == _ARCHIVE_INDEX
        or path.partition("/")[0] == "__MACOSX"
        or name.startswith("._")
        or name == ".DS_Store"
    )


def read_layout(archive: zipfile.ZipFile) -> TilesetLayout:
    """Check every entry the central directory lists and locate tileset.json."""
    entries = archive.infolist()
    kept: list[tuple[zipfile.ZipInfo, str]] = []
    for info in entries:
        path = _entry_path(info)
        _check_entry_contents(info)
        if not _is_packaging(path):
            kept.append((info, path))
    paths = [(path, info.is_dir()) for info, path in kept]
    _refuse_collisions(paths)
    root = _tileset_root(paths)

    files = tuple((info, path[len(root) :]) for info, path in kept if not info.is_dir())
    unpacked_bytes = sum(info.file_size for info, _ in files)
    cap = settings.max_tileset_unpacked_mb * 1024 * 1024
    if unpacked_bytes > cap:
        _refuse(
            f"The tileset unpacks to {unpacked_bytes / 1024**2:.1f} MB, more "
            f"than the {settings.max_tileset_unpacked_mb} MB this server accepts.",
            reason="zip_bomb_indicator",
        )
    # Overlapping entries share compressed bytes, so only this sum keeps the
    # per-entry ratio a bound on the whole archive's expansion.
    if sum(info.compress_size for info in entries) > os.path.getsize(archive.filename):
        _refuse(
            "The archive's entries claim more compressed data than the archive "
            "holds, so some of them overlap.",
            reason="zip_bomb_indicator",
        )
    entry_point = archive.getinfo(root + TILESET_ENTRY_POINT)
    if max(entry_point.file_size, entry_point.compress_size) > MAX_TILESET_JSON_BYTES:
        _refuse(
            f"{TILESET_ENTRY_POINT} is larger than the "
            f"{MAX_TILESET_JSON_BYTES // 1024**2} MB this server reads.",
            reason="tileset_json_size",
        )
    return TilesetLayout(
        files=files,
        entry_point=entry_point,
        unpacked_bytes=unpacked_bytes,
        entry_count=len(entries),
    )


def _nesting_depth(text: str) -> int:
    depth = deepest = 0
    for bracket in _NOT_A_BRACKET.sub("", _JSON_STRING.sub("", text)):
        depth += 1 if bracket in "[{" else -1
        deepest = max(deepest, depth)
    return deepest


def _reject_constant(name: str) -> NoReturn:
    raise ValueError(f"{name} is not a JSON number")


def _is_finite_number(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _region_extent(region: list[float]) -> tuple[float, float, float, float]:
    west, south, east, north = region[:4]
    reach = math.pi + _REGION_TOLERANCE_RADIANS
    if not (
        abs(west) <= reach
        and abs(east) <= reach
        and -reach / 2 <= south <= north <= reach / 2
    ):
        _refuse(
            "The root region must hold longitudes within ±π and latitudes "
            "within ±π/2 radians, with south no greater than north.",
            reason="tileset_region",
        )
    return (
        max(-180.0, min(180.0, math.degrees(west))),
        max(-90.0, min(90.0, math.degrees(south))),
        max(-180.0, min(180.0, math.degrees(east))),
        max(-90.0, min(90.0, math.degrees(north))),
    )


def _read_tileset_json(
    archive: zipfile.ZipFile, info: zipfile.ZipInfo, name: str
) -> dict:
    """Parse one tileset JSON member of the archive, within the size and depth bounds."""
    if max(info.file_size, info.compress_size) > MAX_TILESET_JSON_BYTES:
        _refuse(
            f"{name} is larger than the {MAX_TILESET_JSON_BYTES // 1024**2} MB "
            "this server reads.",
            reason="tileset_json_size",
        )
    with _member_read_errors(name):
        with archive.open(info) as handle:
            raw = handle.read(MAX_TILESET_JSON_BYTES + 1)
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        _refuse(f"{name} is not UTF-8.", reason="tileset_json")
    if _nesting_depth(text) > MAX_TILESET_JSON_DEPTH:
        _refuse(
            f"{name} nests deeper than {MAX_TILESET_JSON_DEPTH} levels.",
            reason="tileset_json_depth",
        )
    try:
        document = json.loads(text, parse_constant=_reject_constant)
    except ValueError:
        _refuse(f"{name} is not valid JSON.", reason="tileset_json")
    if not isinstance(document, dict):
        _refuse(f"{name} is not a JSON object.", reason="tileset_json")
    return document


def _object(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _members(value: object) -> list:
    """A JSON array's entries, or an object's values: a client indexes both alike."""
    if isinstance(value, dict):
        return list(value.values())
    return value if isinstance(value, list) else []


def _tile_uris(root: object) -> Iterator[object]:
    """Every content and subtree URI the tile tree under ``root`` names."""
    tiles: list[object] = [root]
    while tiles:
        tile = tiles.pop()
        if not isinstance(tile, dict):
            continue
        extensions = _object(tile.get("extensions"))
        multiple = _object(extensions.get("3DTILES_multiple_contents"))
        for content in (
            tile.get("content"),
            *_members(tile.get("contents")),
            *_members(multiple.get("contents")),
            *_members(multiple.get("content")),
        ):
            # "url" is the pre-1.0 spelling some exporters still write.
            yield from (_object(content).get(k) for k in ("uri", "url"))
        for implicit in (
            tile.get("implicitTiling"),
            extensions.get("3DTILES_implicit_tiling"),
        ):
            yield _object(_object(implicit).get("subtrees")).get("uri")
        tiles.extend(_members(tile.get("children")))


def _document_uris(document: dict) -> Iterator[tuple[object, bool]]:
    """Each URI a client resolves from a tileset, glTF or subtree JSON document.

    Paired with whether a data: URI is safe there: a schema, buffer, image or
    shader names nothing further, but inline content could name anything.
    """
    for uri in _tile_uris(document.get("root")):
        yield uri, False
    extensions = _object(document.get("extensions"))
    yield document.get("schemaUri"), True
    for name in _SCHEMA_EXTENSIONS:
        yield _object(extensions.get(name)).get("schemaUri"), True
    for entries in (
        document.get("buffers"),
        document.get("images"),
        document.get("shaders"),
        _object(extensions.get("KHR_techniques_webgl")).get("shaders"),
    ):
        for entry in _members(entries):
            yield _object(entry).get("uri"), True


def _leaves_tileset(folder: str, uri: str, *, inline_ok: bool) -> bool:
    """Whether ``uri``, read in ``folder``, names anything outside the tileset."""
    uri = uri.translate(_URI_DROPPED).strip(_URI_BLANKS)
    if inline_ok and uri[:5].lower() == "data:":
        return False
    path = uri.split("#", 1)[0].split("?", 1)[0]
    # The server decodes an encoded slash into a separator the client never saw,
    # so the file it serves would resolve its own URIs from a shallower folder.
    if "%2f" in path.lower():
        return True
    path = unquote(path)
    if ":" in path or "\\" in path or path.startswith("/"):
        return True
    depth = len(folder.split("/")) if folder else 0
    for segment in path.split("/"):
        if segment == "..":
            depth -= 1
            if depth < 0:
                return True
        elif segment not in ("", "."):
            depth += 1
    return False


def check_uri(key: str, uri: object, *, inline_ok: bool) -> None:
    """Refuse a URI in the file at ``key`` that names something outside the tileset."""
    folder = key.rpartition("/")[0]
    # urijs builds a URI from an object's hostname and path fields, so only a
    # string can be checked.
    if uri is not None and (
        not isinstance(uri, str) or _leaves_tileset(folder, uri, inline_ok=inline_ok)
    ):
        _refuse(
            f"{key} names content outside the tileset: an absolute URI, "
            "or a path that climbs out of it with '..'. Content must be "
            "a relative path to a file in the archive.",
            reason="tileset_content_uri",
        )


def check_uris(document: dict, key: str) -> None:
    """Refuse any URI in ``document``, the file at ``key``, that leaves the tileset."""
    for uri, inline_ok in _document_uris(document):
        check_uri(key, uri, inline_ok=inline_ok)


def read_facts(document: dict) -> TilesetFacts:
    """Read the version, root geometric error and bounding volume from tileset.json."""
    asset = document.get("asset")
    version = asset.get("version") if isinstance(asset, dict) else None
    if not isinstance(version, str) or version not in TILESET_VERSIONS:
        _refuse(
            f"{TILESET_ENTRY_POINT} must declare asset.version "
            f"{' or '.join(repr(v) for v in sorted(TILESET_VERSIONS))}.",
            reason="tileset_version",
        )

    root = document.get("root")
    volume = root.get("boundingVolume") if isinstance(root, dict) else None
    if not isinstance(root, dict) or not isinstance(volume, dict):
        _refuse(
            f"{TILESET_ENTRY_POINT} has no root tile with a boundingVolume.",
            reason="tileset_bounding_volume",
        )
    for kind, size in _BOUNDING_VOLUMES:
        values = volume.get(kind)
        if values is None:
            continue
        if not (
            isinstance(values, list)
            and len(values) == size
            and all(_is_finite_number(value) for value in values)
        ):
            _refuse(
                f"The root boundingVolume's {kind} must be {size} finite numbers.",
                reason="tileset_bounding_volume",
            )
        break
    else:
        _refuse(
            "The root boundingVolume has no region, box or sphere.",
            reason="tileset_bounding_volume",
        )

    geometric_error = root.get("geometricError")
    if geometric_error is not None and not (
        _is_finite_number(geometric_error) and geometric_error >= 0
    ):
        _refuse(
            "The root tile's geometricError must be a non-negative number.",
            reason="tileset_geometric_error",
        )
    return TilesetFacts(
        version=version,
        geometric_error=None if geometric_error is None else float(geometric_error),
        bounding_volume=kind,
        extent_bbox=_region_extent(values) if kind == "region" else None,
    )


def _open_checked(path: str) -> zipfile.ZipFile:
    """Open the archive once its entry count and directory size are bounded."""
    try:
        _validate_zip_directory_cardinality(path, settings.max_tileset_entries)
        return zipfile.ZipFile(path)
    except UnsafeUploadError:
        raise
    except zipfile.BadZipFile as exc:
        raise UnsafeUploadError("The upload is not a valid ZIP archive.") from exc
    except ValueError as exc:
        raise UnsafeUploadError(str(exc)) from exc


def inspect_tileset(path: str) -> Tileset:
    """Check a local tileset archive from its directory and tileset.json."""
    with _open_checked(path) as archive:
        layout = read_layout(archive)
        document = _read_tileset_json(archive, layout.entry_point, TILESET_ENTRY_POINT)
        facts = read_facts(document)
        check_uris(document, TILESET_ENTRY_POINT)
        return Tileset(layout=layout, facts=facts)


def _write_at(path: str, offset: int, data: bytes) -> None:
    with open(path, "r+b") as probe:
        probe.seek(offset)
        probe.write(data)


async def _copy_range(
    storage: StorageProvider, key: str, probe: str, offset: int, length: int
) -> bytes:
    if length <= 0:
        return b""
    data = await storage.get_range(key, offset, length)
    await asyncio.to_thread(_write_at, probe, offset, data)
    return data


def _zip64_record_offset(tail: bytes) -> int | None:
    """The offset of the ZIP64 end record that the locator in ``tail`` names."""
    end = _end_record_index(tail)
    locator = end - _ZIP64_LOCATOR.size
    if end < 0 or locator < 0 or not tail.startswith(_ZIP64_LOCATOR_SIGNATURE, locator):
        return None
    return _ZIP64_LOCATOR.unpack_from(tail, locator)[2]


async def inspect_stored_tileset(storage: StorageProvider, key: str) -> Tileset:
    """``inspect_tileset`` for an object in storage, without downloading it.

    A sparse local file of the object's size gets only the ranges the checks
    read: the archive's tail, a ZIP64 end record, the central directory, and
    the tileset.json entry. ``key`` is the physical key.
    """
    size = await storage.size(key)
    handle, probe = tempfile.mkstemp(
        prefix="tileset-probe-", suffix=".zip", dir=settings.upload_staging_dir
    )
    try:
        os.ftruncate(handle, size)
        os.close(handle)
        handle = -1
        tail = min(size, _ARCHIVE_TAIL_BYTES)
        tail_bytes = await _copy_range(storage, key, probe, size - tail, tail)
        # Extensible data can put a ZIP64 end record any distance before its
        # locator, so it is read from wherever the locator says.
        record = _zip64_record_offset(tail_bytes)
        if record is not None and record + _ZIP64_EOCD.size <= size:
            await _copy_range(storage, key, probe, record, _ZIP64_EOCD.size)
        try:
            _, offset, length = await asyncio.to_thread(_zip_directory_metadata, probe)
        except zipfile.BadZipFile as exc:
            raise UnsafeUploadError("The upload is not a valid ZIP archive.") from exc
        if length > MAX_CENTRAL_DIRECTORY_BYTES:
            _refuse(
                "The archive's central directory exceeds the "
                f"{MAX_CENTRAL_DIRECTORY_BYTES // 1024**2} MB metadata limit.",
                reason="zip_bomb_indicator",
            )
        await _copy_range(storage, key, probe, offset, length)

        def _layout() -> TilesetLayout:
            with _open_checked(probe) as archive:
                return read_layout(archive)

        layout = await asyncio.to_thread(_layout)
        entry_point = layout.entry_point
        header = await storage.get_range(
            key, entry_point.header_offset, _LOCAL_HEADER_BYTES
        )
        if len(header) < _LOCAL_HEADER_BYTES:
            raise UnsafeUploadError("The upload is not a valid ZIP archive.")
        name_length, extra_length = struct.unpack("<HH", header[26:30])
        await _copy_range(
            storage,
            key,
            probe,
            entry_point.header_offset,
            _LOCAL_HEADER_BYTES
            + name_length
            + extra_length
            + entry_point.compress_size,
        )

        def _facts() -> TilesetFacts:
            with _open_checked(probe) as archive:
                info = archive.getinfo(entry_point.filename)
                document = _read_tileset_json(archive, info, TILESET_ENTRY_POINT)
                facts = read_facts(document)
                # The probe holds no other member's bytes; the worker, which has
                # the whole archive, checks every file before its first put.
                check_uris(document, TILESET_ENTRY_POINT)
                return facts

        return Tileset(layout=layout, facts=await asyncio.to_thread(_facts))
    finally:
        if handle >= 0:
            os.close(handle)
        Path(probe).unlink(missing_ok=True)


async def inspect_staged_tileset(file_path: str) -> Tileset:
    """Check a staged upload wherever it sits: a local path or a storage key."""
    from app.core.tenancy import is_multi_tenant
    from app.platform.storage import get_storage

    local = Path(file_path)
    if local.exists() and (local.is_absolute() or not is_multi_tenant()):
        return await asyncio.to_thread(inspect_tileset, file_path)
    key = (
        resolve_current_storage_key(file_path)
        if file_path.startswith("staging/")
        else file_path
    )
    return await inspect_stored_tileset(get_storage(), key)


def require_tileset_archive(kind: str | None, filename: str | None) -> None:
    """Refuse a tileset upload that is not a .zip or .3tz, before any job exists.

    A .3tz holds only a tileset, so one sent without the tileset kind is refused.
    """
    suffix = Path(filename or "").suffix.lower()
    if kind == TILESET_FILE_TYPE and suffix not in TILESET_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A 3D Tiles tileset is uploaded as a .zip or .3tz archive.",
        )
    if kind != TILESET_FILE_TYPE and suffix == TILESET_ARCHIVE_SUFFIX:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "A .3tz archive holds a 3D Tiles tileset. Upload it with "
                f"kind={TILESET_FILE_TYPE}."
            ),
        )


def tileset_job_metadata(kind: str | None) -> dict[str, str]:
    """The job-row stamp that sends an upload down the tileset path, or nothing."""
    return {"file_type": TILESET_FILE_TYPE} if kind == TILESET_FILE_TYPE else {}


async def staged_tileset_metadata(path: str, kind: str | None) -> dict:
    """What a tileset upload's job row binds, once its archive passes every check."""
    if kind != TILESET_FILE_TYPE:
        return {}
    tileset = await asyncio.to_thread(inspect_tileset, path)
    return {
        **tileset_job_metadata(kind),
        TILESET_UNPACKED_BYTES_FIELD: tileset.layout.unpacked_bytes,
    }


def staged_unpacked_bytes(job: "IngestJob") -> int:
    """The unpacked total the upload door recorded on a tileset job."""
    return int((job.user_metadata or {}).get(TILESET_UNPACKED_BYTES_FIELD) or 0)


async def preview_staged_tileset(
    job_id: uuid.UUID, source_filename: str | None, file_path: str
) -> TilesetPreviewResponse:
    """The preview of a staged tileset; an archive that fails a check is a 422."""
    try:
        tileset = await inspect_staged_tileset(file_path)
    except UnsafeUploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    facts = tileset.facts
    return TilesetPreviewResponse(
        job_id=job_id,
        source_filename=source_filename,
        version=facts.version,
        geometric_error=facts.geometric_error,
        bounding_volume=facts.bounding_volume,
        extent_bbox=list(facts.extent_bbox) if facts.extent_bbox else None,
        unpacked_bytes=tileset.layout.unpacked_bytes,
        entry_count=tileset.layout.entry_count,
    )
