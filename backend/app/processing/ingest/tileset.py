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
from itertools import pairwise, product
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, NoReturn
from urllib.parse import unquote

import structlog

from app.core.config import settings
from app.core.tiles3d import (
    TILESET_ARCHIVE_SUFFIX,
    TILESET_ENTRY_POINT,
    TILESET_FILE_TYPE,
    TILESET_UPLOAD_SUFFIXES,
)
from app.core.upload_errors import UnsafeUploadError
from app.platform.jobs.models import TILESET_UNPACKED_BYTES_FIELD
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
    compression_refusal,
)

if TYPE_CHECKING:
    from app.platform.jobs.models import IngestJob

logger = structlog.get_logger(__name__)

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
# is read first because it is already in degrees and ignores the transform.
_BOUNDING_VOLUMES = (("region", 6), ("box", 12), ("sphere", 4))

# How far a region may stray past a pole or the antimeridian and still be read
# as reaching it; writers round pi, sometimes upward.
_REGION_TOLERANCE_RADIANS = 1e-6

# A box or sphere is georeferenced when its centre lies this far from the
# Earth's centre, about 120 km either side of the WGS 84 ellipsoid, or when the
# volume meets the ellipsoid; a local frame sits near the origin, well inside it.
_GEOCENTRIC_RANGE_METRES = (6.25e6, 6.5e6)
_WGS84_A = 6378137.0
_WGS84_B = _WGS84_A * (1 - 1 / 298.257223563)
# Every meridian's centre of curvature lies within a*e^2 (42.7 km) of the
# Earth's centre across the axis and a^2*e^2/b (42.8 km) along it.
_EVOLUTE_REACH_METRES = 43_000.0
# Samples along each edge of a box face, or along a sphere's meridians and
# parallels; 32 keeps the padding for the gaps between them near 3% of the size.
_SURFACE_SAMPLES = 32

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
    # antimeridian, and None for a box or sphere that is not in EPSG:4978.
    extent_bbox: tuple[float, float, float, float] | None


@dataclass(frozen=True)
class TilesetContents:
    """What reading every file of the tileset finds, sorted."""

    # b3dm, i3dm, pnts, cmpt, glb, gltf, subtree, and the vctr and geom formats
    # CesiumJS still reads, inner composite tiles included.
    content_types: tuple[str, ...]
    # extensionsRequired of every tileset JSON and glTF in the archive.
    extensions_required: tuple[str, ...]


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
    # Only the worker reads every file, so the doors leave this unset.
    contents: TilesetContents | None = None


def _refuse(
    message: str,
    *,
    reason: str,
    code: str | None = None,
    values: dict[str, str | int] | None = None,
) -> NoReturn:
    # Never the entry name: the refusal may be about the characters in it.
    logger.warning("Tileset archive refused", event_type="security", reason=reason)
    # `reason` is the internal log tag; `code` is the public one on the
    # wire, defaulting to it except where the zip-bomb checks below split
    # one `reason` into several codes with different values.
    raise UnsafeUploadError(message, code=code or reason, values=values)


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
    if info.flag_bits & 0x1:
        _refuse(
            "The archive contains an encrypted entry.",
            reason="tileset_unreadable_entry",
        )
    if refusal := compression_refusal(info):
        method = zipfile.compressor_names.get(
            info.compress_type, f"method {info.compress_type}"
        )
        _refuse(
            refusal,
            reason="tileset_unreadable_entry",
            code="unsupported_zip_compression",
            values={"method": method},
        )
    if info.file_size and (
        info.compress_size == 0
        or info.file_size > MAX_COMPRESSION_RATIO * info.compress_size
    ):
        _refuse(
            "An entry in the archive expands to more than "
            f"{MAX_COMPRESSION_RATIO} times its compressed size.",
            reason="zip_bomb_indicator",
            code="zip_bomb_ratio",
            values={"max_ratio": MAX_COMPRESSION_RATIO},
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
                values={"path": path},
            )
        if not is_dir and (key == next_key or next_key.startswith(f"{key}\0")):
            _refuse(
                f"The archive has both a file and a folder at {path!r}.",
                reason="tileset_entry_collision",
                values={"path": path},
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
            code="tileset_unpacked_too_large",
            values={"limit_mb": settings.max_tileset_unpacked_mb},
        )
    # Overlapping entries share compressed bytes, so only this sum keeps the
    # per-entry ratio a bound on the whole archive's expansion.
    if sum(info.compress_size for info in entries) > os.path.getsize(archive.filename):
        _refuse(
            "The archive's entries claim more compressed data than the archive "
            "holds, so some of them overlap.",
            reason="zip_bomb_indicator",
            code="zip_entries_overlap",
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
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


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


def _geodetic(x: float, y: float, z: float) -> tuple[float, float]:
    """Longitude and latitude in degrees of an EPSG:4978 point, by Bowring's formula."""
    e2 = 1 - (_WGS84_B / _WGS84_A) ** 2
    ep2 = (_WGS84_A / _WGS84_B) ** 2 - 1
    p = math.hypot(x, y)
    theta = math.atan2(z * _WGS84_A, p * _WGS84_B)
    latitude = math.atan2(
        z + ep2 * _WGS84_B * math.sin(theta) ** 3,
        p - e2 * _WGS84_A * math.cos(theta) ** 3,
    )
    return math.degrees(math.atan2(y, x)), math.degrees(latitude)


def _cross(u: list[float], v: list[float]) -> list[float]:
    return [
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    ]


def _dot(u: list[float], v: list[float]) -> float:
    return sum(a * b for a, b in zip(u, v))


def _axis_span(
    center: list[float], axes: list[list[float]]
) -> tuple[float, float] | None:
    """Where the volume meets the Earth's axis, as a range of z, or None if it misses.

    The axis line is (0, 0, t); in the volume's own coordinates it is
    ``origin + t * step``, and each coordinate must stay within ±1.
    """
    det = _dot(axes[0], _cross(axes[1], axes[2]))
    if det == 0 or not math.isfinite(det):
        return None

    def local(point: list[float]) -> list[float]:
        # Cramer's rule for the point's coordinates along the three half-axes.
        return [
            _dot(point, _cross(axes[1], axes[2])) / det,
            _dot(axes[0], _cross(point, axes[2])) / det,
            _dot(axes[0], _cross(axes[1], point)) / det,
        ]

    origin = local([-value for value in center])
    step = local([0.0, 0.0, 1.0])
    if not all(math.isfinite(value) for value in origin + step):
        return None
    low, high = -math.inf, math.inf
    for start, rate in zip(origin, step):
        if rate == 0:
            if not abs(start) <= 1:
                return None
            continue
        ends = sorted(((-1 - start) / rate, (1 - start) / rate))
        low, high = max(low, ends[0]), min(high, ends[1])
    return (low, high) if low <= high else None


def _surface(
    center: list[float], axes: list[list[float]], radius: float
) -> tuple[list[list[float]], float]:
    """Sample the faces of a box (``axes``) or a sphere (``radius``).

    Returns the points and a distance every surface point lies within of one.
    """
    n = _SURFACE_SAMPLES
    steps = [2 * i / (n - 1) - 1 for i in range(n)]
    if axes:
        points = [
            [
                c + side * axes[k][x] + u * axes[i][x] + v * axes[j][x]
                for x, c in enumerate(center)
            ]
            for k, i, j in ((0, 1, 2), (1, 0, 2), (2, 0, 1))
            for side, u, v in product((-1, 1), steps, steps)
        ]
        norms = [math.hypot(*axis) for axis in axes]
        # A point of a grid cell is within half the sum of its sides of a corner.
        return points, max(
            norms[1] + norms[2], norms[0] + norms[2], norms[0] + norms[1]
        ) / (n - 1)
    points = [
        [
            center[0] + radius * math.cos(lat) * math.cos(lon),
            center[1] + radius * math.cos(lat) * math.sin(lon),
            center[2] + radius * math.sin(lat),
        ]
        for lat, lon in product(
            [s * math.pi / 2 for s in steps], [s * math.pi for s in steps]
        )
    ]
    # A point is within half a cell's meridian and widest parallel arcs of a sample.
    return points, radius * 1.5 * math.pi / (n - 1)


def _cartesian_extent(
    kind: str, values: list[float], transform: object
) -> tuple[float, float, float, float] | None:
    """The WGS 84 extent of a root box or sphere placed in EPSG:4978, else None.

    The extent may be wider than the volume, never narrower.
    """
    if transform is None:
        transform = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    if not (
        isinstance(transform, list)
        and len(transform) == 16
        and all(_is_finite_number(value) for value in transform)
    ):
        return None
    m = [float(value) for value in transform]

    # Column-major, and like CesiumJS the bottom row is not applied.
    def linear(v: list[float]) -> list[float]:
        return [m[i] * v[0] + m[4 + i] * v[1] + m[8 + i] * v[2] for i in range(3)]

    center = [a + b for a, b in zip(linear([float(v) for v in values[:3]]), m[12:15])]
    rest = [float(value) for value in values[3:]]
    if kind == "box":
        axes, radius = [linear(rest[i : i + 3]) for i in (0, 3, 6)], 0.0
        crossing = _axis_span(center, axes)
    else:
        columns = [linear([float(i == j) for j in range(3)]) for i in range(3)]
        # Gershgorin's bound on the largest eigenvalue of the transform's Gram
        # matrix: the sphere stretches by at most its square root.
        stretch = max(sum(abs(_dot(a, b)) for b in columns) for a in columns)
        axes, radius = [], abs(rest[0]) * math.sqrt(stretch)
        reach = radius * radius - center[0] * center[0] - center[1] * center[1]
        crossing = None
        if reach >= 0:
            half = math.sqrt(reach)
            crossing = (center[2] - half, center[2] + half)

    points, gap = _surface(center, axes, radius)
    if not all(math.isfinite(value) for point in points for value in point):
        return None
    nearest = min(math.hypot(*point) for point in points) - gap
    holds_origin = crossing is not None and crossing[0] <= 0 <= crossing[1]
    # Stretching z by a/b turns the ellipsoid into a sphere; a box peaks at a corner.
    outer = [math.hypot(x, y, z * _WGS84_A / _WGS84_B) for x, y, z in [center, *points]]
    outermost = max(outer) if axes else outer[0] + radius * _WGS84_A / _WGS84_B
    low, high = _GEOCENTRIC_RANGE_METRES
    meets_ellipsoid = outermost >= _WGS84_A and (holds_origin or nearest <= _WGS84_A)
    if not (low <= math.hypot(*center) <= high or meets_ellipsoid):
        return None
    # Latitude and longitude lose their meaning near the Earth's centre, so a
    # volume reaching in that far may hold content anywhere.
    if holds_origin or not nearest > _EVOLUTE_REACH_METRES:
        return -180.0, -90.0, 180.0, 90.0
    # An interior point shares its latitude and longitude with the surface
    # point where its outward ellipsoid normal leaves the volume.
    lons, lats = zip(*(_geodetic(*point) for point in points))
    # A step of `gap` metres turns latitude by at most `gap` over the distance
    # to the meridian's centre of curvature, and longitude by at most `gap`
    # over the distance from the axis.
    lat_pad = math.degrees(gap / (nearest - _EVOLUTE_REACH_METRES))
    south, north = max(-90.0, min(lats) - lat_pad), min(90.0, max(lats) + lat_pad)
    from_axis = min(math.hypot(point[0], point[1]) for point in points) - gap
    lon_pad = math.degrees(gap / from_axis) if from_axis > 0 else math.inf

    west, east = min(lons), max(lons)
    # A convex volume clear of the Earth's axis spans under 180 degrees of
    # longitude, so a wider span crosses the antimeridian.
    if east - west > 180:
        west = min(lon for lon in lons if lon >= 0)
        east = max(lon for lon in lons if lon < 0)
    if crossing is None and (east - west) % 360 + 2 * lon_pad < 360:
        west, east = west - lon_pad, east + lon_pad
        return west + 360 * (west < -180), south, east - 360 * (east > 180), north
    if crossing is not None:
        north = 90.0 if crossing[1] > 0 else north
        south = -90.0 if crossing[0] < 0 else south
    return -180.0, south, 180.0, north


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
            return parse_tileset_json(handle.read(MAX_TILESET_JSON_BYTES + 1), name)


def parse_tileset_json(raw: bytes, name: str) -> dict:
    """Parse a tileset JSON document within the depth bound; refuse anything else."""
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
        extent_bbox=(
            _region_extent(values)
            if kind == "region"
            else _cartesian_extent(kind, values, root.get("transform"))
        ),
    )


def _open_checked(path: str) -> zipfile.ZipFile:
    """Open the archive once its entry count and directory size are bounded."""
    try:
        _validate_zip_directory_cardinality(path, settings.max_tileset_entries)
        return zipfile.ZipFile(path)
    except UnsafeUploadError:
        raise
    except zipfile.BadZipFile as exc:
        raise UnsafeUploadError(
            "The upload is not a valid ZIP archive.", code="invalid_zip_container"
        ) from exc
    except ValueError as exc:
        # `_validate_zip_directory_cardinality`'s own refusals are already
        # UnsafeUploadError and caught above; this is a defensive net.
        raise UnsafeUploadError(str(exc), code="unsafe_upload_content") from exc


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
            raise UnsafeUploadError(
                "The upload is not a valid ZIP archive.", code="invalid_zip_container"
            ) from exc
        if length > MAX_CENTRAL_DIRECTORY_BYTES:
            limit_mb = MAX_CENTRAL_DIRECTORY_BYTES // 1024**2
            _refuse(
                f"The archive's central directory exceeds the {limit_mb} MB "
                "metadata limit.",
                reason="zip_bomb_indicator",
                code="zip_directory_too_large",
                values={"limit_mb": limit_mb},
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
            raise UnsafeUploadError(
                "The upload is not a valid ZIP archive.", code="invalid_zip_container"
            )
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

    Raises the module's own coded exception, like every other check here,
    since every caller is a door that converts it.
    """
    suffix = Path(filename or "").suffix.lower()
    if kind == TILESET_FILE_TYPE and suffix not in TILESET_UPLOAD_SUFFIXES:
        raise UnsafeUploadError(
            "A 3D Tiles tileset is uploaded as a .zip or .3tz archive.",
            code="tileset_extension_mismatch",
        )
    if kind != TILESET_FILE_TYPE and suffix == TILESET_ARCHIVE_SUFFIX:
        raise UnsafeUploadError(
            "A .3tz archive holds a 3D Tiles tileset. Upload it with "
            f"kind={TILESET_FILE_TYPE}.",
            code="tileset_kind_required",
            values={"file_type": TILESET_FILE_TYPE},
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
    """The preview of a staged tileset; an archive that fails a check is a 422.

    Lets ``UnsafeUploadError`` propagate: the caller (``preview_file``) is
    the door that converts it.
    """
    tileset = await inspect_staged_tileset(file_path)
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
