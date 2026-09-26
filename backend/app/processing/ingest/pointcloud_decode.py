"""Decode a COPC file's points with lazrs, in the child process the parent kills at a deadline.

``python -m app.processing.ingest.pointcloud_decode top|every <path>``
decodes the top node, or every node holding points, after checking the file
again as the parent did. It prints one JSON object: the decoded points' low
and high corners, the name of the check the file failed, or an internal
failure. ``pointcloud.py`` runs it and turns the reply into its own refusals.
"""

from __future__ import annotations

import io
import json
import os
import sys

import lazrs
import numpy as np
import structlog

from app.processing.ingest.pointcloud import (
    Read,
    _check_node,
    _chunk_table_frame,
    _Layout,
    _Node,
    _read_layout,
    _reader,
)


class _Refused(Exception):
    """A check only the decoder can make, which the file failed; ``args[0]`` names it."""


def _lazrs_failed(exc: BaseException) -> bool:
    """Whether lazrs raised ``exc`` as an error or a Rust panic, not an interrupt."""
    return isinstance(exc, Exception) or type(exc).__name__ == "PanicException"


def _check_chunk_table(read: Read, layout: _Layout, size: int) -> None:
    """Refuse a file a LAZ reader would read differently from its octree.

    A LAZ reader takes each chunk's point count and byte size from the chunk
    table, and finds the chunks one after another from the start of the point
    data, past the table's 8-byte offset. The table must list every node's
    chunk that way, in file order.
    """
    span = _chunk_table_frame(read, layout, size)
    try:
        table = lazrs.read_chunk_table_only(
            io.BytesIO(read(*span)), lazrs.LazVlr(layout.laszip)
        )
    except BaseException as exc:  # broad: a Rust panic reaches Python as pyo3's PanicException, which is no Exception
        if not _lazrs_failed(exc):
            raise
        raise _Refused("chunk_table") from exc
    start = layout.header.point_offset + 8
    for node, entry in zip(sorted(layout.nodes, key=lambda node: node.offset), table):
        if (node.offset, (node.count, node.size)) != (start, entry):
            raise _Refused("chunk_table")
        start += node.size


def _decode(read: Read, layout: _Layout, node: _Node) -> tuple[np.ndarray, np.ndarray]:
    """Decode one node with lazrs, check where its points sit, and return their low and high corners.

    Each corner also carries X wrapped into [-180, 180) and into [0, 360).
    """
    header = layout.header
    _check_node(read, layout, node)
    offset, size, count = node.offset, node.size, node.count
    chunk = read(offset, size)
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
        if not _lazrs_failed(exc):
            raise
        raise _Refused("decode") from exc
    xyz = np.ndarray(
        (count, 3), dtype="<i4", buffer=points, strides=(header.record_length, 4)
    )
    scales, offsets = np.array(header.scales), np.array(header.offsets)
    edge = 2 * layout.halfsize / 2**node.depth
    key = np.array((node.x, node.y, node.z))
    with np.errstate(over="ignore", invalid="ignore"):
        # A negative scale maps the largest raw value to the lowest coordinate.
        ends = np.stack((xyz.min(axis=0), xyz.max(axis=0))) * scales + offsets
        cell = np.array(layout.center) - layout.halfsize + edge * key
        cell_end = cell + edge
    # Finite header values can still overflow to inf or NaN, which slip past
    # the comparisons below.
    if not np.isfinite(ends).all():
        raise _Refused("decode_overflow")
    if not np.isfinite((cell, cell_end)).all():
        raise _Refused("cell_overflow")
    low, high, slack = ends.min(axis=0), ends.max(axis=0), np.abs(scales)
    if (low < np.array(header.mins) - slack).any() or (
        high > np.array(header.maxs) + slack
    ).any():
        raise _Refused("decode_bounds")
    # Each level halves the octree's cube, and a COPC reader reads a node only
    # for a query that meets its cell, so a point outside the cell is hidden.
    if (low < cell - slack).any() or (high > cell_end + slack).any():
        raise _Refused("decode_voxel")
    # A cloud each side of one encoding's seam is narrow in the other, so a
    # geographic CRS's extent reads longitudes both ways, in place.
    x = xyz[:, 0] * scales[0]
    x += offsets[0] + 180
    np.remainder(x, 360, out=x)
    x -= 180
    west, east = x.min(), x.max()
    np.remainder(x, 360, out=x)
    return np.append(low, (west, x.min())), np.append(high, (east, x.max()))


def decode_file(path: str, *, every: bool) -> tuple[list[float], list[float]]:
    """The low and high corners of the top node's points, or of every node's."""
    size = os.path.getsize(path)
    with open(path, "rb") as source:
        read = _reader(source)
        layout = _read_layout(read, size)
        _check_chunk_table(read, layout, size)
        nodes = layout.nodes if every else layout.nodes[:1]
        low, high = _decode(read, layout, nodes[0])
        for node in nodes[1:]:
            node_low, node_high = _decode(read, layout, node)
            low, high = np.minimum(low, node_low), np.maximum(high, node_high)
    return low.tolist(), high.tolist()


def main(argv: list[str]) -> int:
    try:
        nodes, path = argv
        if nodes not in ("top", "every"):
            raise ValueError(nodes)
        low, high = decode_file(path, every=nodes == "every")
        result: dict = {"low": low, "high": high}
    except _Refused as refused:
        result = {"refused": refused.args[0]}
    except Exception as exc:  # broad: any other failure goes back as its class name
        print(json.dumps({"error": "internal", "exception": type(exc).__name__}))
        return 1
    print(json.dumps({"result": result}))
    return 0


if __name__ == "__main__":
    # The reply is the only thing on stdout.
    structlog.configure(logger_factory=structlog.PrintLoggerFactory(sys.stderr))
    sys.exit(main(sys.argv[1:]))
