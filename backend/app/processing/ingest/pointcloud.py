"""Check an uploaded COPC point cloud before anything stores or serves it.

A point cloud never reaches GDAL. Its header, VLRs and octree hierarchy are
parsed here with ``struct`` under fixed bounds, and lazrs decodes nodes to
show the chunks decode as declared: the top node at the upload doors, every
node in the worker before the copy. Every check reads a local file: the staged
upload, a copy the worker downloads, or a sparse probe holding only the ranges
the doors' checks read from an object in storage.
"""

from __future__ import annotations

import asyncio
import math
import os
import re
import struct
import tempfile
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic
from types import SimpleNamespace
from typing import BinaryIO, Callable

import lazrs
import numpy as np
import structlog

from app.core.config import settings
from app.core.pointcloud import LAZ_WITHOUT_KIND, POINTCLOUD_FILE_TYPE, is_laz
from app.core.upload_errors import UnsafeUploadError
from app.platform.storage import StorageProvider
from app.platform.storage.titiler_url import resolve_current_storage_key
from app.processing.ingest.schemas import PointCloudPreviewResponse
from app.processing.ingest.tileset import _copy_range

logger = structlog.get_logger(__name__)

# COPC fixes the LAS 1.4 header at this size, so its info VLR starts here.
HEADER_SIZE = 375
# The header and VLRs before the point data, and the EVLRs after it.
MAX_VLR_BLOCK_BYTES = 1024 * 1024
MAX_EVLR_BLOCK_BYTES = 16 * 1024 * 1024
MAX_RECORDS = 1024
# Hierarchy entries read across every page, and the deepest octree level. A
# 1 km lidar tile of 39 million points has 1,680 nodes.
MAX_HIERARCHY_ENTRIES = 250_000
MAX_DEPTH = 24
# Both the compressed and the decoded size of each node decoded.
MAX_DECODE_BYTES = 64 * 1024 * 1024
# The most a node may decode to, as a multiple of its stored size. Real lidar
# tiles measure near ten, so a node far past it only multiplies decode work.
MAX_DECODE_RATIO = 64
# The worker's budget for decoding a whole file: a floor, or a second per MB
# of the file when that is longer, so no file holds the raster queue for long.
DECODE_FLOOR_SECONDS = 60
DECODE_SECONDS_PER_MB = 1
MAX_WKT_BYTES = 64 * 1024
# lazrs builds four 256-symbol models, about 9.6 KB, per extra byte before it
# reads a point, so the extra bytes a record may carry are bounded too.
MAX_EXTRA_BYTES = 1024

# LASzip item types each point format carries (POINT14, then RGB14 or
# RGBNIR14), with their sizes; BYTE14 items hold extra bytes of any size.
_ITEMS = {6: ((10, 30),), 7: ((10, 30), (11, 6)), 8: ((10, 30), (12, 8))}
_BYTE14 = 14
# The layers a chunk stores per item: POINT14 splits into nine, RGB14 is one,
# RGBNIR14 two, and each extra byte is a layer of its own.
_LAYERS = {10: 9, 11: 1, 12: 2}
_LAYERED_CHUNKED = 3

_VLR = struct.Struct("<2x16sHH32x")
_EVLR = struct.Struct("<2x16sHQ32x")
_ENTRY = struct.Struct("<iiiiqii")
# The COPC info record: the octree's center and half-size, the point spacing,
# the root hierarchy page's offset and size, and the GPS time range.
_INFO = struct.Struct("<5dQQ2d")
_COPC_INFO = (b"copc", 1)
_COPC_HIERARCHY = (b"copc", 1000)
_LASZIP = (b"laszip encoded", 22204)
_WKT = (b"LASF_Projection", 2112)

# The WKT nodes read for the CRS. PROJ never parses the uploaded WKT, since a
# WKT can name a grid file (PARAMETERFILE, a PROJ4 extension) PROJ would open.
_WKT_TOKEN = re.compile(r'\s*(?:("(?:[^"]|"")*")|([\[(])|([\])])|(,)|([^\s\[\](),"]+))')
_COMPOUND_CRS = frozenset({"COMPD_CS", "COMPOUNDCRS"})
_HORIZONTAL_CRS = frozenset(
    {
        "GEOGCS",
        "PROJCS",
        "GEODCRS",
        "GEODETICCRS",
        "GEOGCRS",
        "GEOGRAPHICCRS",
        "PROJCRS",
        "PROJECTEDCRS",
    }
)
_VERTICAL_CRS = frozenset({"VERT_CS", "VERTCRS", "VERTICALCRS"})

_NOT_COPC = (
    "This point cloud is not a COPC file. Convert it with PDAL's writers.copc "
    "or untwine; GeoLens doesn't convert point clouds yet."
)
_TRUNCATED = "The point cloud file is truncated or its header is damaged."
_NO_CRS = (
    "The point cloud has no coordinate reference system with an EPSG code "
    "GeoLens can read."
)
_DECODE_FAILED = "The point cloud's points don't decode as its header describes."

Read = Callable[[int, int], bytes]


@dataclass(frozen=True)
class PointCloud:
    """What a checked COPC file holds, as the catalog records it."""

    point_count: int
    point_format: int
    srid: int
    vertical_crs: str | None
    extent_bbox: tuple[float, float, float, float]
    z_min: float
    z_max: float
    size_bytes: int


@dataclass(frozen=True)
class _Header:
    point_offset: int
    vlr_count: int
    point_format: int
    record_length: int
    scales: tuple[float, float, float]
    offsets: tuple[float, float, float]
    mins: tuple[float, float, float]
    maxs: tuple[float, float, float]
    evlr_start: int
    evlr_count: int
    point_count: int


@dataclass(frozen=True)
class _Layout:
    header: _Header
    laszip: bytes
    wkt: bytes
    # Every node holding points, as (offset, byte size, point count), the
    # shallowest first.
    nodes: list[tuple[int, int, int]]
    # The per-layer sizes a chunk's header lists, one per LASzip layer.
    layers: int
    # The octree's cube, as its center and half the length of a side.
    center: tuple[float, float, float]
    halfsize: float


# Refusals of an ordinary file: plain LAS or LAZ, or one with no usable CRS.
_ORDINARY_REFUSALS = frozenset({"pointcloud_not_copc", "pointcloud_no_crs"})


def _logged(refusal: UnsafeUploadError, *, reason: str) -> UnsafeUploadError:
    if refusal.code in _ORDINARY_REFUSALS:
        logger.info("Point cloud refused", reason=reason)
    else:
        logger.warning("Point cloud refused", event_type="security", reason=reason)
    return refusal


def _invalid(message: str, *, reason: str, **values: str | int) -> UnsafeUploadError:
    return _logged(
        UnsafeUploadError(message, code="pointcloud_invalid", values=values),
        reason=reason,
    )


def _not_copc(*, reason: str) -> UnsafeUploadError:
    return _logged(
        UnsafeUploadError(_NOT_COPC, code="pointcloud_not_copc"), reason=reason
    )


def _no_crs(*, reason: str) -> UnsafeUploadError:
    return _logged(UnsafeUploadError(_NO_CRS, code="pointcloud_no_crs"), reason=reason)


def _decode_failed(*, reason: str) -> UnsafeUploadError:
    return _logged(
        UnsafeUploadError(_DECODE_FAILED, code="pointcloud_decode_failed"),
        reason=reason,
    )


def _read_header(data: bytes, size: int) -> _Header:
    """Parse the LAS header, refusing anything but LAS 1.4 LAZ in format 6 to 8."""
    if not data.startswith(b"LASF"):
        raise _invalid("The file is not a LAS or LAZ point cloud.", reason="not_las")
    if len(data) < HEADER_SIZE:
        raise _not_copc(reason="short_header")
    header_size, point_offset, vlr_count, format_byte, record_length = (
        struct.unpack_from("<HIIBH", data, 94)
    )
    point_format = format_byte & 0x3F
    if (
        (data[24], data[25]) != (1, 4)
        or header_size != HEADER_SIZE
        or not format_byte & 0x80
        or point_format not in _ITEMS
    ):
        raise _not_copc(reason="not_copc")
    scales = struct.unpack_from("<3d", data, 131)
    offsets = struct.unpack_from("<3d", data, 155)
    max_x, min_x, max_y, min_y, max_z, min_z = struct.unpack_from("<6d", data, 179)
    evlr_start, evlr_count, point_count = struct.unpack_from("<QIQ", data, 235)
    mins, maxs = (min_x, min_y, min_z), (max_x, max_y, max_z)
    if (
        not all(map(math.isfinite, (*scales, *offsets, *mins, *maxs)))
        or 0 in scales
        or any(low > high for low, high in zip(mins, maxs))
    ):
        raise _invalid("The file's header has no usable bounds.", reason="bounds")
    if not HEADER_SIZE <= point_offset <= size:
        raise _invalid(_TRUNCATED, reason="truncated")
    if point_offset > MAX_VLR_BLOCK_BYTES:
        raise _invalid(
            f"The file's VLRs exceed the {MAX_VLR_BLOCK_BYTES // 1024**2} MB limit.",
            reason="vlr_limit",
            limit_mb=MAX_VLR_BLOCK_BYTES // 1024**2,
        )
    return _Header(
        point_offset=point_offset,
        vlr_count=vlr_count,
        point_format=point_format,
        record_length=record_length,
        scales=scales,
        offsets=offsets,
        mins=mins,
        maxs=maxs,
        evlr_start=evlr_start,
        evlr_count=evlr_count,
        point_count=point_count,
    )


def _check_evlr_block(header: _Header, size: int) -> None:
    """Refuse a file whose EVLRs, which hold the hierarchy, are missing or oversized."""
    if header.evlr_count == 0:
        raise _invalid("The file has no COPC hierarchy.", reason="no_hierarchy")
    if not header.point_offset <= header.evlr_start <= size:
        raise _invalid(_TRUNCATED, reason="truncated")
    if size - header.evlr_start > MAX_EVLR_BLOCK_BYTES:
        raise _invalid(
            "The file's extended VLRs exceed the "
            f"{MAX_EVLR_BLOCK_BYTES // 1024**2} MB limit.",
            reason="evlr_limit",
            limit_mb=MAX_EVLR_BLOCK_BYTES // 1024**2,
        )
    if header.point_count == 0:
        raise _invalid("The point cloud holds no points.", reason="empty")


def _read_records(
    read: Read, start: int, end: int, count: int, layout: struct.Struct
) -> list[tuple[tuple[bytes, int], int, int]]:
    """``(user id, record id), data offset, data length`` of each packed record."""
    if count > MAX_RECORDS:
        raise _invalid(
            f"The file has more than {MAX_RECORDS} variable-length records.",
            reason="record_count",
            limit=MAX_RECORDS,
        )
    records = []
    offset = start
    for _ in range(count):
        data = offset + layout.size
        if data > end:
            raise _invalid(_TRUNCATED, reason="record_range")
        user_id, record_id, length = layout.unpack(read(offset, layout.size))
        if data + length > end:
            raise _invalid(_TRUNCATED, reason="record_range")
        records.append(((user_id.rstrip(b"\0"), record_id), data, length))
        offset = data + length
    return records


def _check_laszip(data: bytes, header: _Header) -> int:
    """Refuse a LASzip record lazrs would misread; return its chunks' layer count."""
    fields = struct.unpack_from("<HHBBHIIqqH", data) if len(data) >= 34 else None
    if (
        fields is None
        or fields[0] != _LAYERED_CHUNKED
        or len(data) != 34 + 6 * fields[9]
    ):
        raise _invalid("The file's LASzip record is damaged.", reason="laszip")
    items = [struct.unpack_from("<HH", data, 34 + 6 * i) for i in range(fields[9])]
    base = _ITEMS[header.point_format]
    extra = items[len(base) :]
    if (
        tuple(items[: len(base)]) != base
        or any(kind != _BYTE14 for kind, _ in extra)
        or sum(size for _, size in items) != header.record_length
    ):
        raise _invalid("The file's LASzip record is damaged.", reason="laszip")
    # Writers put every extra byte in one item; lazrs decodes each item per point.
    if len(extra) > 1 or any(size == 0 for _, size in extra):
        raise _invalid(
            "The file's LASzip record is damaged.", reason="laszip_extra_items"
        )
    extra_bytes = sum(size for _, size in extra)
    if extra_bytes > MAX_EXTRA_BYTES:
        raise _invalid(
            f"The file's points carry more than {MAX_EXTRA_BYTES} extra bytes.",
            reason="extra_bytes",
            limit=MAX_EXTRA_BYTES,
        )
    return sum(_LAYERS[kind] for kind, _ in base) + extra_bytes


def _walk(
    read: Read, header: _Header, root: tuple[int, int], hierarchy: range
) -> list[tuple[int, int, int]]:
    """Check every hierarchy page and return each node holding points, shallowest first.

    A page is read once at most, from inside the hierarchy record; each node's
    points lie inside the point data, overlap no other node's and decode to at
    most ``MAX_DECODE_RATIO`` times their stored size; and the nodes' counts sum
    to the header's.
    """
    pages = [root]
    seen_pages: set[tuple[int, int]] = set()
    seen_keys: set[tuple[int, int, int, int]] = set()
    entries = total = 0
    nodes: list[tuple[int, int, int, int]] = []
    while pages:
        page = pages.pop()
        offset, size = page
        if page in seen_pages:
            raise _invalid(
                "A hierarchy page is referenced more than once.", reason="page_cycle"
            )
        seen_pages.add(page)
        if (
            size <= 0
            or size % _ENTRY.size
            or offset < hierarchy.start
            or offset + size > hierarchy.stop
        ):
            raise _invalid(
                "A hierarchy page lies outside the hierarchy.", reason="page_range"
            )
        entries += size // _ENTRY.size
        if entries > MAX_HIERARCHY_ENTRIES:
            raise _invalid(
                f"The hierarchy has more than {MAX_HIERARCHY_ENTRIES:,} entries.",
                reason="hierarchy_limit",
                limit=MAX_HIERARCHY_ENTRIES,
            )
        for depth, x, y, z, node_offset, node_size, count in _ENTRY.iter_unpack(
            read(offset, size)
        ):
            if not 0 <= depth <= MAX_DEPTH or not all(
                0 <= c < 1 << depth for c in (x, y, z)
            ):
                raise _invalid(
                    "A hierarchy entry names a node outside the octree.",
                    reason="node_key",
                )
            if count == -1:
                pages.append((node_offset, node_size))
                continue
            key = (depth, x, y, z)
            if count < -1 or key in seen_keys:
                raise _invalid(
                    "A hierarchy entry is malformed or repeated.", reason="node_entry"
                )
            seen_keys.add(key)
            if count == 0:
                continue
            if (
                node_size <= 0
                or node_offset < header.point_offset
                or node_offset + node_size > header.evlr_start
            ):
                raise _invalid(
                    "A node's points lie outside the file's point data.",
                    reason="node_range",
                )
            if count * header.record_length > MAX_DECODE_RATIO * node_size:
                raise _invalid(
                    "A node of the octree decodes to more than "
                    f"{MAX_DECODE_RATIO} times its stored size.",
                    reason="decode_ratio",
                    limit=MAX_DECODE_RATIO,
                )
            total += count
            nodes.append((depth, node_offset, node_size, count))
    if not nodes or total != header.point_count:
        raise _invalid(
            "The hierarchy's point counts don't add up to the header's.",
            reason="point_count",
        )
    # A chunk two nodes share would be decoded once for each of them.
    by_offset = sorted(nodes, key=lambda node: node[1])
    for before, after in zip(by_offset, by_offset[1:]):
        if after[1] < before[1] + before[2]:
            raise _invalid(
                "Two nodes' points overlap in the file's point data.",
                reason="node_overlap",
            )
    # Stable, so the top node is the first one found at the least depth.
    nodes.sort(key=lambda node: node[0])
    return [node[1:] for node in nodes]


def _read_layout(read: Read, size: int) -> _Layout:
    header = _read_header(read(0, min(size, HEADER_SIZE)), size)
    vlrs = _read_records(read, HEADER_SIZE, header.point_offset, header.vlr_count, _VLR)
    if not vlrs or vlrs[0][0] != _COPC_INFO or vlrs[0][2] != 160:
        raise _not_copc(reason="no_copc_info")
    *center, halfsize, spacing, root_offset, root_size, gps_min, gps_max = _INFO.unpack(
        read(vlrs[0][1], _INFO.size)
    )
    if (
        not all(map(math.isfinite, (*center, halfsize, spacing, gps_min, gps_max)))
        or halfsize <= 0
        or spacing <= 0
        or gps_min > gps_max
    ):
        raise _invalid("The file's COPC info record is damaged.", reason="copc_info")
    _check_evlr_block(header, size)
    evlrs = _read_records(read, header.evlr_start, size, header.evlr_count, _EVLR)
    found = {}
    for key, offset, length in reversed(vlrs + evlrs):
        found[key] = (offset, length)
    if _LASZIP not in found:
        raise _invalid("The file has no LASzip record.", reason="no_laszip")
    if _COPC_HIERARCHY not in found:
        raise _invalid("The file has no COPC hierarchy.", reason="no_hierarchy")
    if _WKT not in found:
        raise _no_crs(reason="no_wkt")
    laszip = read(*found[_LASZIP])
    layers = _check_laszip(laszip, header)
    wkt_offset, wkt_length = found[_WKT]
    if wkt_length > MAX_WKT_BYTES:
        raise _no_crs(reason="wkt_limit")
    root = (root_offset, root_size)
    hierarchy_offset, hierarchy_length = found[_COPC_HIERARCHY]
    nodes = _walk(
        read,
        header,
        root,
        range(hierarchy_offset, hierarchy_offset + hierarchy_length),
    )
    wkt = read(wkt_offset, wkt_length)
    return _Layout(header, laszip, wkt, nodes, layers, tuple(center), halfsize)


def _check_chunk(chunk: bytes, layout: _Layout, count: int) -> None:
    """Refuse a chunk whose header would size lazrs's buffers past the chunk.

    A layered chunk opens with its first point stored raw, its point count and
    one byte size per layer, and lazrs allocates each layer from that size
    before reading it. The count must match the hierarchy's and the sizes must
    add up to the chunk.
    """
    record_length = layout.header.record_length
    fixed = record_length + 4 + 4 * layout.layers
    if len(chunk) < fixed:
        raise _decode_failed(reason="chunk_size")
    points = struct.unpack_from("<I", chunk, record_length)[0]
    sizes = struct.unpack_from(f"<{layout.layers}I", chunk, record_length + 4)
    if points != count or fixed + sum(sizes) != len(chunk):
        raise _decode_failed(reason="chunk_header")


def _decode(
    read: Read, layout: _Layout, node: tuple[int, int, int]
) -> tuple[np.ndarray, np.ndarray]:
    """Decode one node with lazrs, check where its points sit, and return their low and high corners."""
    header = layout.header
    offset, size, count = node
    if max(size, count * header.record_length) > MAX_DECODE_BYTES:
        raise _invalid(
            "A node of the octree exceeds the "
            f"{MAX_DECODE_BYTES // 1024**2} MB decode limit.",
            reason="decode_limit",
            limit_mb=MAX_DECODE_BYTES // 1024**2,
        )
    chunk = read(offset, size)
    _check_chunk(chunk, layout, count)
    points = bytearray(count * header.record_length)
    try:
        lazrs.decompress_points_with_chunk_table(
            chunk,
            layout.laszip,
            points,
            [(count, size)],
            lazrs.DecompressionSelection(lazrs.SELECTIVE_DECOMPRESS_ALL),
        )
    except BaseException as exc:  # broad: a Rust panic reaches Python as pyo3's PanicException, which is no Exception
        if not isinstance(exc, Exception) and type(exc).__name__ != "PanicException":
            raise
        raise _decode_failed(reason="decode") from exc
    xyz = np.ndarray(
        (count, 3), dtype="<i4", buffer=points, strides=(header.record_length, 4)
    )
    scales, offsets = np.array(header.scales), np.array(header.offsets)
    # A negative scale maps the largest raw value to the lowest coordinate.
    ends = np.stack((xyz.min(axis=0), xyz.max(axis=0))) * scales + offsets
    low, high, slack = ends.min(axis=0), ends.max(axis=0), np.abs(scales)
    if (low < np.array(header.mins) - slack).any() or (
        high > np.array(header.maxs) + slack
    ).any():
        raise _decode_failed(reason="decode_bounds")
    center = np.array(layout.center)
    if (low < center - layout.halfsize - slack).any() or (
        high > center + layout.halfsize + slack
    ).any():
        raise _invalid(
            "The point cloud's points lie outside its octree.", reason="decode_cube"
        )
    return low, high


def _parse_wkt(text: str) -> list:
    """WKT as nested ``[KEYWORD, *values]`` lists, read without interpreting it."""
    stack: list[list] = [[]]
    word: str | None = None
    text = text.strip()
    position = 0
    while position < len(text):
        match = _WKT_TOKEN.match(text, position)
        if match is None:
            raise ValueError("unreadable WKT")
        position = match.end()
        quoted, opening, closing, _, bare = match.groups()
        if bare is not None:
            word = bare
        elif opening is not None:
            if word is None:
                raise ValueError("unreadable WKT")
            stack.append([word.upper()])
            word = None
        elif quoted is not None:
            stack[-1].append(quoted[1:-1].replace('""', '"'))
        else:
            if word is not None:
                stack[-1].append(word)
                word = None
            if closing is not None:
                if len(stack) < 2:
                    raise ValueError("unreadable WKT")
                node = stack.pop()
                stack[-1].append(node)
    if word is not None or len(stack) != 1 or len(stack[0]) != 1:
        raise ValueError("unreadable WKT")
    return stack[0][0]


def _declared_crs(wkt: bytes) -> tuple[int, str]:
    """The horizontal CRS's EPSG code and the vertical CRS's name, as the WKT states them."""
    root = _parse_wkt(wkt.split(b"\0", 1)[0].decode())
    nodes = [item for item in root[1:] if isinstance(item, list)]
    horizontal = root if root[0] in _HORIZONTAL_CRS else None
    vertical = None
    if root[0] in _COMPOUND_CRS:
        horizontal = next((n for n in nodes if n[0] in _HORIZONTAL_CRS), None)
        vertical = next((n for n in nodes if n[0] in _VERTICAL_CRS), None)
    codes = [
        item[2]
        for item in (horizontal or [])[1:]
        if isinstance(item, list)
        and item[0] in {"AUTHORITY", "ID"}
        and len(item) > 2
        and str(item[1]).upper() == "EPSG"
    ]
    if not codes:
        raise ValueError("no EPSG code")
    srid = int(str(codes[-1]))
    # The catalog's srid column is a positive 32-bit integer.
    if not 0 < srid < 2**31:
        raise ValueError("EPSG code out of range")
    name = vertical[1] if vertical and len(vertical) > 1 else ""
    return srid, name if isinstance(name, str) else ""


def _crs_facts(
    wkt: bytes, mins: Sequence[float], maxs: Sequence[float]
) -> tuple[int, str | None, tuple[float, float, float, float]]:
    """The horizontal EPSG code, the vertical CRS name and the WGS84 extent of ``mins`` to ``maxs``."""
    from rasterio.coords import BoundingBox
    from rasterio.crs import CRS

    from app.processing.raster.cog import _wgs84_bbox

    try:
        srid, name = _declared_crs(wkt)
        bounds = BoundingBox(*mins[:2], *maxs[:2])
        bbox = _wgs84_bbox(SimpleNamespace(crs=CRS.from_epsg(srid), bounds=bounds))
    except (
        Exception
    ) as exc:  # broad: an unreadable WKT or an EPSG code PROJ can't use is one refusal
        raise _no_crs(reason="crs") from exc
    if not all(map(math.isfinite, bbox)):
        raise _no_crs(reason="extent")
    vertical = "".join(c for c in name if c.isprintable())[:255] or None
    return srid, vertical, tuple(bbox)


def _reader(source: BinaryIO) -> Read:
    """``Read`` over an open file, refusing a range that runs past its end."""

    def read(offset: int, length: int) -> bytes:
        source.seek(offset)
        data = source.read(length)
        if len(data) != length:
            raise _invalid(_TRUNCATED, reason="short_read")
        return data

    return read


def _inspect(path: str) -> tuple[PointCloud, _Layout, tuple[np.ndarray, np.ndarray]]:
    """``inspect_pointcloud``, with the layout it read and the top node's corners."""
    size = os.path.getsize(path)
    with open(path, "rb") as source:
        read = _reader(source)
        layout = _read_layout(read, size)
        corners = _decode(read, layout, layout.nodes[0])
    header = layout.header
    srid, vertical, bbox = _crs_facts(layout.wkt, header.mins, header.maxs)
    cloud = PointCloud(
        point_count=header.point_count,
        point_format=header.point_format,
        srid=srid,
        vertical_crs=vertical,
        extent_bbox=bbox,
        z_min=header.mins[2],
        z_max=header.maxs[2],
        size_bytes=size,
    )
    return cloud, layout, corners


def inspect_pointcloud(path: str) -> PointCloud:
    """Check a COPC file on local disk, decoding its top node; a refusal is an ``UnsafeUploadError``."""
    return _inspect(path)[0]


def _decode_node(
    path: str, layout: _Layout, node: tuple[int, int, int]
) -> tuple[np.ndarray, np.ndarray]:
    with open(path, "rb") as source:
        return _decode(_reader(source), layout, node)


async def inspect_every_node(path: str) -> PointCloud:
    """``inspect_pointcloud``, then every other node holding points decoded as the top one is.

    lazrs holds the GIL while it decodes, so each node gets a thread call of
    its own and the event loop runs between nodes. Between nodes the time
    spent is checked against the file's decode budget. The extent and the
    elevation range are the ones the decoded points cover, not the header's.
    """
    started = monotonic()
    cloud, layout, (low, high) = await asyncio.to_thread(_inspect, path)
    budget = max(
        DECODE_FLOOR_SECONDS, cloud.size_bytes * DECODE_SECONDS_PER_MB // 1024**2
    )
    for node in layout.nodes[1:]:
        if monotonic() - started > budget:
            raise _invalid(
                f"The point cloud takes more than {budget} seconds to decode.",
                reason="decode_time",
                limit=budget,
            )
        node_low, node_high = await asyncio.to_thread(_decode_node, path, layout, node)
        low, high = np.minimum(low, node_low), np.maximum(high, node_high)
    # Some writers round a header's bounds outward, so the points set the extent.
    low, high = low.tolist(), high.tolist()
    _, _, bbox = await asyncio.to_thread(_crs_facts, layout.wkt, low, high)
    return replace(cloud, extent_bbox=bbox, z_min=low[2], z_max=high[2])


def _layout_of(path: str) -> _Layout:
    with open(path, "rb") as source:

        def read(offset: int, length: int) -> bytes:
            source.seek(offset)
            return source.read(length)

        return _read_layout(read, os.path.getsize(path))


async def inspect_stored_pointcloud(storage: StorageProvider, key: str) -> PointCloud:
    """``inspect_pointcloud`` for an object in storage, without downloading it.

    A sparse local file of the object's size gets only the ranges the checks
    read: the header and VLRs, the EVLRs with the hierarchy, and the one node
    decoded. ``key`` is the physical key.
    """
    size = await storage.size(key)
    handle, probe = tempfile.mkstemp(
        prefix="pointcloud-probe-", suffix=".laz", dir=settings.upload_staging_dir
    )
    try:
        os.ftruncate(handle, size)
        os.close(handle)
        handle = -1
        head = await _copy_range(storage, key, probe, 0, min(size, HEADER_SIZE))
        header = _read_header(head, size)
        await _copy_range(
            storage, key, probe, HEADER_SIZE, header.point_offset - HEADER_SIZE
        )
        # Copied only when sane; otherwise the read below refuses it, in the
        # same order a local read does.
        evlr_bytes = size - header.evlr_start
        if (
            header.point_offset <= header.evlr_start
            and evlr_bytes <= MAX_EVLR_BLOCK_BYTES
        ):
            await _copy_range(storage, key, probe, header.evlr_start, evlr_bytes)
        offset, length, _ = (await asyncio.to_thread(_layout_of, probe)).nodes[0]
        if length <= MAX_DECODE_BYTES:
            await _copy_range(storage, key, probe, offset, length)
        return await asyncio.to_thread(inspect_pointcloud, probe)
    finally:
        if handle >= 0:
            os.close(handle)
        Path(probe).unlink(missing_ok=True)


def staged_source(file_path: str) -> tuple[bool, str]:
    """Whether a staged upload is a local file, and its path or physical key."""
    from app.core.tenancy import is_multi_tenant

    local = Path(file_path)
    if local.exists() and (local.is_absolute() or not is_multi_tenant()):
        return True, file_path
    if file_path.startswith("staging/"):
        return False, resolve_current_storage_key(file_path)
    return False, file_path


async def inspect_staged_pointcloud(file_path: str) -> PointCloud:
    """Check a staged upload wherever it sits: a local path or a storage key."""
    from app.platform.storage import get_storage

    is_local, source = staged_source(file_path)
    if is_local:
        return await asyncio.to_thread(inspect_pointcloud, source)
    return await inspect_stored_pointcloud(get_storage(), source)


async def staged_pointcloud_bytes(file_path: str) -> int:
    """The size of a staged point cloud, wherever it sits."""
    from app.platform.storage import get_storage

    is_local, source = staged_source(file_path)
    if is_local:
        return os.path.getsize(source)
    return await get_storage().size(source)


def require_pointcloud_file(kind: str | None, filename: str | None) -> None:
    """Refuse a point cloud that is not a .laz, or a .laz without the point cloud kind.

    Raises the module's coded exception, since every caller is a door that
    converts it.
    """
    if kind == POINTCLOUD_FILE_TYPE and not is_laz(filename):
        raise UnsafeUploadError(_NOT_COPC, code="pointcloud_not_copc")
    if kind != POINTCLOUD_FILE_TYPE and is_laz(filename):
        raise UnsafeUploadError(
            LAZ_WITHOUT_KIND,
            code="pointcloud_kind_required",
            values={"file_type": POINTCLOUD_FILE_TYPE},
        )


async def staged_pointcloud_metadata(path: str, kind: str | None) -> dict:
    """What a point cloud upload's job row binds, once its file passes every check."""
    if kind != POINTCLOUD_FILE_TYPE:
        return {}
    await asyncio.to_thread(inspect_pointcloud, path)
    return {"file_type": POINTCLOUD_FILE_TYPE}


async def preview_staged_pointcloud(
    job_id: uuid.UUID, source_filename: str | None, file_path: str
) -> PointCloudPreviewResponse:
    """The preview of a staged point cloud.

    Lets ``UnsafeUploadError`` propagate: the caller (``preview_file``) is
    the door that converts it.
    """
    cloud = await inspect_staged_pointcloud(file_path)
    return PointCloudPreviewResponse(
        job_id=job_id,
        source_filename=source_filename,
        point_count=cloud.point_count,
        point_format=cloud.point_format,
        srid=cloud.srid,
        vertical_crs=cloud.vertical_crs,
        extent_bbox=list(cloud.extent_bbox),
        z_min=cloud.z_min,
        z_max=cloud.z_max,
        size_bytes=cloud.size_bytes,
    )
