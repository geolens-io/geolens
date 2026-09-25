"""Check an uploaded COPC point cloud before anything stores or serves it.

A point cloud never reaches GDAL. Its header, VLRs and octree hierarchy are
parsed here with ``struct`` under fixed bounds, and lazrs decodes one node to
show the chunks decode as declared. Every check reads a local file: the staged
upload, or a sparse probe holding only the ranges the checks read from an
object in storage.
"""

from __future__ import annotations

import asyncio
import math
import os
import struct
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import lazrs
import numpy as np
import structlog
from fastapi import HTTPException, status

from app.core.config import settings
from app.core.pointcloud import LAZ_WITHOUT_KIND, POINTCLOUD_FILE_TYPE, is_laz
from app.core.upload_errors import CodedUploadError, refusal_detail
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
# Both the compressed and the decoded size of the one node decoded.
MAX_DECODE_BYTES = 64 * 1024 * 1024
MAX_WKT_BYTES = 64 * 1024

# LASzip item types each point format carries (POINT14, then RGB14 or
# RGBNIR14), with their sizes; BYTE14 items hold extra bytes of any size.
_ITEMS = {6: ((10, 30),), 7: ((10, 30), (11, 6)), 8: ((10, 30), (12, 8))}
_BYTE14 = 14
_LAYERED_CHUNKED = 3

_VLR = struct.Struct("<2x16sHH32x")
_EVLR = struct.Struct("<2x16sHQ32x")
_ENTRY = struct.Struct("<iiiiqii")
_COPC_INFO = (b"copc", 1)
_COPC_HIERARCHY = (b"copc", 1000)
_LASZIP = (b"laszip encoded", 22204)
_WKT = (b"LASF_Projection", 2112)

_NOT_COPC = (
    "This point cloud is not a COPC file. Convert it with PDAL's writers.copc "
    "or untwine; GeoLens doesn't convert point clouds yet."
)
_TRUNCATED = "The point cloud file is truncated or its header is damaged."
_NO_CRS = "The point cloud has no coordinate reference system GeoLens can read."
_DECODE_FAILED = "The point cloud's points don't decode as its header describes."

Read = Callable[[int, int], bytes]


@dataclass(frozen=True)
class PointCloud:
    """What a checked COPC file holds, as the catalog records it."""

    point_count: int
    point_format: int
    srid: int | None
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
    # The shallowest node holding points, as (offset, byte size, point count).
    node: tuple[int, int, int]


def _refusal(
    code: str, message: str, *, reason: str, **values: object
) -> CodedUploadError:
    logger.warning("Point cloud refused", event_type="security", reason=reason)
    return CodedUploadError(code, message, **values)


def _invalid(message: str, *, reason: str, **values: object) -> CodedUploadError:
    return _refusal("pointcloud_invalid", message, reason=reason, **values)


def _read_header(data: bytes, size: int) -> _Header:
    """Parse the LAS header, refusing anything but LAS 1.4 LAZ in format 6 to 8."""
    if not data.startswith(b"LASF"):
        raise _invalid("The file is not a LAS or LAZ point cloud.", reason="not_las")
    if len(data) < HEADER_SIZE:
        raise _refusal("pointcloud_not_copc", _NOT_COPC, reason="short_header")
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
        raise _refusal("pointcloud_not_copc", _NOT_COPC, reason="not_copc")
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


def _check_laszip(data: bytes, header: _Header) -> None:
    """Refuse a LASzip record lazrs would misread for this point format."""
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


def _walk(
    read: Read, header: _Header, root: tuple[int, int], hierarchy: range
) -> tuple[int, int, int]:
    """Check every hierarchy page and return the shallowest node holding points.

    A page is read once at most, from inside the hierarchy record; a node's
    points lie inside the point data; and the nodes' counts sum to the header's.
    """
    pages = [root]
    seen_pages: set[tuple[int, int]] = set()
    seen_keys: set[tuple[int, int, int, int]] = set()
    entries = total = 0
    shallowest: tuple[int, int, int, int] | None = None
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
            total += count
            if shallowest is None or depth < shallowest[0]:
                shallowest = (depth, node_offset, node_size, count)
    if shallowest is None or total != header.point_count:
        raise _invalid(
            "The hierarchy's point counts don't add up to the header's.",
            reason="point_count",
        )
    return shallowest[1:]


def _read_layout(read: Read, size: int) -> _Layout:
    header = _read_header(read(0, min(size, HEADER_SIZE)), size)
    vlrs = _read_records(read, HEADER_SIZE, header.point_offset, header.vlr_count, _VLR)
    if not vlrs or vlrs[0][0] != _COPC_INFO or vlrs[0][2] != 160:
        raise _refusal("pointcloud_not_copc", _NOT_COPC, reason="no_copc_info")
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
        raise _refusal("pointcloud_no_crs", _NO_CRS, reason="no_wkt")
    laszip = read(*found[_LASZIP])
    _check_laszip(laszip, header)
    wkt_offset, wkt_length = found[_WKT]
    if wkt_length > MAX_WKT_BYTES:
        raise _refusal("pointcloud_no_crs", _NO_CRS, reason="wkt_limit")
    root = struct.unpack_from("<QQ", read(vlrs[0][1] + 40, 16))
    hierarchy_offset, hierarchy_length = found[_COPC_HIERARCHY]
    node = _walk(
        read,
        header,
        root,
        range(hierarchy_offset, hierarchy_offset + hierarchy_length),
    )
    return _Layout(header, laszip, read(wkt_offset, wkt_length), node)


def _decode(read: Read, layout: _Layout) -> None:
    """Decode one node with lazrs and check its points sit inside the header's bounds."""
    header = layout.header
    offset, size, count = layout.node
    if max(size, count * header.record_length) > MAX_DECODE_BYTES:
        raise _invalid(
            "The octree's top node exceeds the "
            f"{MAX_DECODE_BYTES // 1024**2} MB decode limit.",
            reason="decode_limit",
            limit_mb=MAX_DECODE_BYTES // 1024**2,
        )
    points = bytearray(count * header.record_length)
    try:
        lazrs.decompress_points_with_chunk_table(
            read(offset, size),
            layout.laszip,
            points,
            [(count, size)],
            lazrs.DecompressionSelection(lazrs.SELECTIVE_DECOMPRESS_ALL),
        )
    except BaseException as exc:  # broad: a Rust panic reaches Python as pyo3's PanicException, which is no Exception
        if not isinstance(exc, Exception) and type(exc).__name__ != "PanicException":
            raise
        raise _refusal(
            "pointcloud_decode_failed", _DECODE_FAILED, reason="decode"
        ) from exc
    xyz = np.ndarray(
        (count, 3), dtype="<i4", buffer=points, strides=(header.record_length, 4)
    )
    scales, offsets = np.array(header.scales), np.array(header.offsets)
    low = xyz.min(axis=0) * scales + offsets
    high = xyz.max(axis=0) * scales + offsets
    if (low < np.array(header.mins) - scales).any() or (
        high > np.array(header.maxs) + scales
    ).any():
        raise _refusal(
            "pointcloud_decode_failed", _DECODE_FAILED, reason="decode_bounds"
        )


def _crs_facts(
    wkt: bytes, header: _Header
) -> tuple[int | None, str | None, tuple[float, float, float, float]]:
    """The horizontal EPSG code, the vertical CRS name and the WGS84 extent."""
    from rasterio.coords import BoundingBox
    from rasterio.crs import CRS

    from app.processing.raster.cog import _wgs84_bbox

    try:
        crs = CRS.from_wkt(wkt.split(b"\0", 1)[0].decode())
        projjson = crs.to_dict(projjson=True)
        parts = projjson.get("components") or [projjson]
        horizontal = CRS.from_dict(parts[0]) if len(parts) > 1 else crs
        bounds = BoundingBox(*header.mins[:2], *header.maxs[:2])
        bbox = _wgs84_bbox(SimpleNamespace(crs=horizontal, bounds=bounds))
        srid = horizontal.to_epsg()
    except Exception as exc:  # broad: PROJ reports an unusable CRS through several rasterio error types
        raise _refusal("pointcloud_no_crs", _NO_CRS, reason="crs") from exc
    if not all(map(math.isfinite, bbox)):
        raise _refusal("pointcloud_no_crs", _NO_CRS, reason="extent")
    name = str(parts[1].get("name") or "") if len(parts) > 1 else ""
    vertical = "".join(c for c in name if c.isprintable())[:255] or None
    return srid, vertical, tuple(bbox)


def inspect_pointcloud(path: str) -> PointCloud:
    """Check a COPC file on local disk; a refusal is a ``CodedUploadError``."""
    size = os.path.getsize(path)
    with open(path, "rb") as source:

        def read(offset: int, length: int) -> bytes:
            source.seek(offset)
            data = source.read(length)
            if len(data) != length:
                raise _invalid(_TRUNCATED, reason="short_read")
            return data

        layout = _read_layout(read, size)
        _decode(read, layout)
    header = layout.header
    srid, vertical, bbox = _crs_facts(layout.wkt, header)
    return PointCloud(
        point_count=header.point_count,
        point_format=header.point_format,
        srid=srid,
        vertical_crs=vertical,
        extent_bbox=bbox,
        z_min=header.mins[2],
        z_max=header.maxs[2],
        size_bytes=size,
    )


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
        offset, length, _ = (await asyncio.to_thread(_layout_of, probe)).node
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


def require_pointcloud_file(kind: str | None, filename: str | None) -> None:
    """Refuse a point cloud that is not a .laz, or a .laz without the point cloud kind."""
    if kind == POINTCLOUD_FILE_TYPE and not is_laz(filename):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=refusal_detail(CodedUploadError("pointcloud_not_copc", _NOT_COPC)),
        )
    if kind != POINTCLOUD_FILE_TYPE and is_laz(filename):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=LAZ_WITHOUT_KIND
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
    """The preview of a staged point cloud; a file that fails a check is a 422."""
    try:
        cloud = await inspect_staged_pointcloud(file_path)
    except CodedUploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=refusal_detail(exc),
        ) from exc
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
