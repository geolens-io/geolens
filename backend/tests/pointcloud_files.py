"""Build COPC point clouds in memory for the upload tests."""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass
from typing import Callable

import lazrs
from rasterio.crs import CRS

# NAD83 / UTM zone 12N + NAVD88 height, the compound CRS USGS 3DEP tiles carry.
WKT = CRS.from_user_input("EPSG:26912+5703").to_wkt().encode()
ORIGIN = (425_000.0, 4_513_000.0, 1_280.0)
SCALE = 0.01
# Where copc() writes the COPC info record's fields: after the 375-byte
# header and the first VLR's 54-byte header.
INFO_AT = 375 + 54

_RECORD_LENGTHS = {6: 30, 7: 36, 8: 38}
_VARIABLE_CHUNKS = 0xFFFFFFFF
# A format 6 chunk opens with its first point raw, its point count and nine
# layer sizes; the compressed layers follow.
_CHUNK_HEADER = 30 + 4 + 4 * 9


@dataclass(frozen=True)
class Layout:
    """Where the builder put the root node's chunk and the root hierarchy page."""

    chunk_offset: int
    chunk_size: int
    count: int
    page_offset: int


def root_entry(layout: Layout) -> tuple[int, ...]:
    return (0, 0, 0, 0, layout.chunk_offset, layout.chunk_size, layout.count)


def vlr(user_id: bytes, record_id: int, data: bytes) -> bytes:
    return struct.pack("<H16sHH32s", 0, user_id, record_id, len(data), b"") + data


def evlr(user_id: bytes, record_id: int, data: bytes) -> bytes:
    return struct.pack("<H16sHQ32s", 0, user_id, record_id, len(data), b"") + data


def records(
    count: int,
    point_format: int = 6,
    extra_bytes: int = 0,
    *,
    start: int = 0,
    span: int = 1000,
) -> bytes:
    """``count`` points on a diagonal from raw ``start``, ``span`` long, each with one return."""
    length = _RECORD_LENGTHS[point_format] + extra_bytes
    out = bytearray()
    for i in range(count):
        step = start + i * span // max(count - 1, 1)
        out += struct.pack(
            "<iiiHBBBBhHd", step, step, step // 10, 0, 0x11, 0, 2, 0, 0, 0, 0.0
        )
        out += bytes(length - 30)
    return bytes(out)


def compressed_chunk(
    points: bytes, point_format: int = 6, extra_bytes: int = 0
) -> bytes:
    """``points`` compressed as the one LAZ chunk a COPC node holds."""
    laz_vlr = lazrs.LazVlr.new_for_compression(point_format, extra_bytes)
    compressed = lazrs.compress_points(laz_vlr, points, False)
    return compressed[8 : struct.unpack_from("<q", compressed)[0]]


def laszip_record(point_format: int = 6, extra_bytes: int = 0) -> bytes:
    """The LASzip record of the builder's files, whose chunks vary in size."""
    laz_vlr = lazrs.LazVlr.new_for_compression(point_format, extra_bytes)
    record = bytearray(laz_vlr.record_data())
    struct.pack_into("<I", record, 12, _VARIABLE_CHUNKS)
    return bytes(record)


def chunk_table(entries: list[tuple[int, int]], record: bytes | None = None) -> bytes:
    """A LAZ chunk table listing each chunk's point count and byte size."""
    table = io.BytesIO()
    lazrs.write_chunk_table(table, entries, lazrs.LazVlr(record or laszip_record()))
    return table.getvalue()


def scrambled(chunk: bytes) -> bytes:
    """A format 6 chunk with its compressed layers inverted under an intact header."""
    return chunk[:_CHUNK_HEADER] + bytes(b ^ 0xFF for b in chunk[_CHUNK_HEADER:])


def copc(
    *,
    count: int = 100,
    point_format: int = 6,
    extra_bytes: int = 0,
    version: tuple[int, int] = (1, 4),
    compressed: bool = True,
    wkt: bytes | None = WKT,
    wkt_in_evlr: bool = False,
    info_first: bool = True,
    laszip: Callable[[bytes], bytes] | None = None,
    points: bytes | None = None,
    chunk: Callable[[bytes], bytes] | None = None,
    header_point_count: int | None = None,
    padding: bytes = b"",
    pages: Callable[[Layout], list[list[tuple[int, ...]]]] | None = None,
    pad: float = 0.0,
) -> bytes:
    """A one-node COPC, or one with a single fault named by a keyword.

    ``padding`` follows the root node's chunk inside the point data, where
    ``pages`` may name it as other nodes. The chunk table follows it, listing
    every entry holding points. ``pages`` returns the hierarchy pages, root
    page first, laid out one after another from ``Layout.page_offset``.
    ``pad`` widens the header's bounds and the octree's cube by that much on
    every side.
    """
    record = laszip_record(point_format, extra_bytes)
    laszip_data = laszip(record) if laszip else record
    chunk_bytes = compressed_chunk(
        points if points is not None else records(count, point_format, extra_bytes),
        point_format,
        extra_bytes,
    )
    if chunk:
        chunk_bytes = chunk(chunk_bytes)

    info = vlr(b"copc", 1, bytes(160))
    wkt_vlr = [] if wkt is None or wkt_in_evlr else [vlr(b"LASF_Projection", 2112, wkt)]
    others = [vlr(b"laszip encoded", 22204, laszip_data), *wkt_vlr]
    vlrs = [info, *others] if info_first else [*others, info]
    point_offset = 375 + sum(map(len, vlrs))
    chunk_offset = point_offset + 8
    table_offset = chunk_offset + len(chunk_bytes) + len(padding)

    def pages_at(page_offset: int) -> list[list[tuple[int, ...]]]:
        layout = Layout(chunk_offset, len(chunk_bytes), count, page_offset)
        return pages(layout) if pages else [[root_entry(layout)]]

    def table_of(page_list: list[list[tuple[int, ...]]]) -> bytes:
        chunks = sorted(e[4:] for page in page_list for e in page if e[6] > 0)
        return chunk_table([(count, size) for _, size, count in chunks], record)

    # Chunk entries don't move with the pages, so a first layout sizes the
    # table that the pages then follow.
    table = table_of(pages_at(0))
    evlr_start = table_offset + len(table)
    page_offset = evlr_start + 60
    page_list = pages_at(page_offset)
    assert table_of(page_list) == table
    hierarchy = b"".join(
        struct.pack("<iiiiqii", *entry) for page in page_list for entry in page
    )
    evlrs = [evlr(b"copc", 1000, hierarchy)]
    if wkt is not None and wkt_in_evlr:
        evlrs.append(evlr(b"LASF_Projection", 2112, wkt))

    body = bytearray(b"".join(vlrs))
    info_at = body.index(info) + 54
    top = 1000 * SCALE
    struct.pack_into(
        "<5dQQ",
        body,
        info_at,
        ORIGIN[0] + top / 2,
        ORIGIN[1] + top / 2,
        ORIGIN[2] + top / 2,
        top / 2 + pad,
        top / 10,
        page_offset,
        32 * len(page_list[0]),
    )

    header = bytearray(375)
    header[:4] = b"LASF"
    struct.pack_into("<H", header, 6, 0x10)
    header[24:26] = bytes(version)
    struct.pack_into(
        "<HIIBH",
        header,
        94,
        375,
        point_offset,
        len(vlrs),
        point_format | (0x80 if compressed else 0),
        _RECORD_LENGTHS[point_format] + extra_bytes,
    )
    struct.pack_into("<3d3d", header, 131, SCALE, SCALE, SCALE, *ORIGIN)
    struct.pack_into(
        "<6d",
        header,
        179,
        ORIGIN[0] + top + pad,
        ORIGIN[0] - pad,
        ORIGIN[1] + top + pad,
        ORIGIN[1] - pad,
        ORIGIN[2] + top / 10 + pad,
        ORIGIN[2] - pad,
    )
    struct.pack_into(
        "<QIQ",
        header,
        235,
        evlr_start,
        len(evlrs),
        count if header_point_count is None else header_point_count,
    )
    return (
        bytes(header)
        + bytes(body)
        + struct.pack("<q", table_offset)
        + chunk_bytes
        + padding
        + table
        + b"".join(evlrs)
    )


def two_ends(wkt: bytes = WKT) -> bytes:
    """An empty root over two 50-point nodes, one at each end of the points' diagonal.

    The nodes hold raw 0..10 and 990..1000 in cells (1,0,0,0) and (1,1,1,0),
    so no point lies between the two ends.
    """
    far = compressed_chunk(records(50, start=990, span=10))
    return copc(
        count=50,
        points=records(50, span=10),
        wkt=wkt,
        padding=far,
        pages=lambda at: [
            [
                (0, 0, 0, 0, 0, 0, 0),
                (1, 0, 0, 0, at.chunk_offset, at.chunk_size, 50),
                (1, 1, 1, 0, at.chunk_offset + at.chunk_size, len(far), 50),
            ]
        ],
        header_point_count=100,
    )


def reframed(
    data: bytes,
    scales: tuple[float, float, float],
    offsets: tuple[float, float, float],
    center: tuple[float, float, float],
    halfsize: float,
) -> bytes:
    """``data`` placed anew by ``scales`` and ``offsets``, in a cube at ``center``.

    ``data``'s raw points span 0..1000 in X and Y and 0..100 in Z, as copc()
    and two_ends() build them; the header's bounds follow.
    """
    bounds: list[float] = []
    for scale, offset, reach in zip(scales, offsets, (1000, 1000, 100)):
        ends = (offset, offset + scale * reach)
        bounds += [max(ends), min(ends)]
    out = bytearray(data)
    struct.pack_into("<3d3d", out, 131, *scales, *offsets)
    struct.pack_into("<6d", out, 179, *bounds)
    struct.pack_into("<4d", out, INFO_AT, *center, halfsize)
    return bytes(out)


def copc_nodes(
    counts: tuple[int, ...] = (120, 150),
    *,
    last_chunk: Callable[[bytes], bytes] | None = None,
    count_error: int = 0,
    size_error: int = 0,
    points: bytes | None = None,
    pad: float = 0.0,
) -> bytes:
    """A 100-point root node and up to two nodes below it, laid out after it.

    The nodes below the root hold the two halves of the points' diagonal, each
    in the cell of the octree's first level that its half crosses. The last
    may carry one fault: ``last_chunk`` rewrites its compressed bytes, and
    ``count_error`` and ``size_error`` shift the point count and byte size its
    hierarchy entry states. The header's point count is the entries' sum.
    ``points`` and ``pad`` are ``copc``'s.
    """
    chunks = [
        compressed_chunk(records(count, start=500 * i, span=500))
        for i, count in enumerate(counts)
    ]
    if last_chunk:
        chunks[-1] = last_chunk(chunks[-1])

    def pages(layout: Layout) -> list[list[tuple[int, ...]]]:
        entries = [root_entry(layout)]
        offset = layout.chunk_offset + layout.chunk_size
        for i, (count, data) in enumerate(zip(counts, chunks)):
            entries.append((1, i, i, 0, offset, len(data), count))
            offset += len(data)
        *key, offset, size, count = entries[-1]
        entries[-1] = (*key, offset, size + size_error, count + count_error)
        return [entries]

    return copc(
        points=points,
        padding=b"".join(chunks),
        pages=pages,
        header_point_count=100 + sum(counts) + count_error,
        pad=pad,
    )
