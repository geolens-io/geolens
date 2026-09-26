"""A COPC upload is checked from its header, VLRs, hierarchy and top node, and the worker decodes every node."""

from __future__ import annotations

import io
import os
import struct
import subprocess
import sys
import uuid
from fractions import Fraction
from pathlib import Path

import boto3
import lazrs
import pytest
from moto import mock_aws
from rasterio.crs import CRS
from structlog.testing import capture_logs

from app.core.config import settings
from app.core.upload_errors import UnsafeUploadError, refusal_detail
from app.platform.storage.local import LocalStorageProvider
from app.platform.storage.s3 import S3StorageProvider
from app.processing.ingest import pointcloud as pointcloud_module
from app.processing.ingest.pointcloud import (
    MAX_EXTRA_BYTES,
    inspect_every_node,
    inspect_pointcloud,
    inspect_stored_pointcloud,
)
from tests.pointcloud_files import (
    ORIGIN,
    SCALE,
    Layout,
    chunk_table,
    compressed_chunk,
    copc,
    copc_nodes,
    laszip_record,
    records,
    root_entry,
    scrambled,
)


def write(tmp_path: Path, data: bytes, name: str = "cloud.copc.laz") -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def refused(tmp_path: Path, data: bytes) -> UnsafeUploadError:
    with pytest.raises(UnsafeUploadError) as refusal:
        inspect_pointcloud(write(tmp_path, data))
    return refusal.value


def patched(data: bytes, offset: int, fmt: str, *values) -> bytes:
    out = bytearray(data)
    struct.pack_into(fmt, out, offset, *values)
    return bytes(out)


# Where copc() writes the COPC info record's fields: after the 375-byte
# header and the first VLR's 54-byte header.
_INFO_AT = 375 + 54


def child_page(layout: Layout, entries: list[tuple[int, ...]]):
    """A root page naming one child page, laid out right after it."""
    child = layout.page_offset + 64
    return [
        [root_entry(layout), (1, 0, 0, 0, child, 32 * len(entries), -1)],
        entries,
    ]


# --- What a COPC file yields ---------------------------------------------


@pytest.mark.parametrize("point_format", [6, 7, 8])
def test_a_copc_file_yields_its_facts(tmp_path, point_format) -> None:
    """Point count, format, CRS, extent and elevation come from the file itself."""
    data = copc(point_format=point_format)

    cloud = inspect_pointcloud(write(tmp_path, data))

    assert (cloud.point_count, cloud.point_format) == (100, point_format)
    assert (cloud.srid, cloud.vertical_crs) == (26912, "NAVD88 height")
    assert (cloud.z_min, cloud.z_max, cloud.size_bytes) == (1280.0, 1281.0, len(data))
    west, south, east, north = cloud.extent_bbox
    assert -111.89 < west < east < -111.88
    assert 40.76 < south < north < 40.77


def test_a_crs_in_an_extended_vlr_is_read(tmp_path) -> None:
    """LAS 1.4 lets the WKT record sit among the EVLRs."""
    cloud = inspect_pointcloud(write(tmp_path, copc(wkt_in_evlr=True)))

    assert cloud.srid == 26912


def test_a_horizontal_crs_alone_has_no_vertical_name(tmp_path) -> None:
    """A projected CRS with no vertical part records its EPSG code and no vertical CRS."""
    wkt = CRS.from_epsg(26912).to_wkt().encode()

    cloud = inspect_pointcloud(write(tmp_path, copc(wkt=wkt)))

    assert (cloud.srid, cloud.vertical_crs) == (26912, None)


def test_a_wkt2_compound_crs_is_read(tmp_path) -> None:
    """The EPSG code and vertical name come from WKT2 nodes as from WKT1 ones."""
    wkt = CRS.from_user_input("EPSG:26912+5703").to_wkt(version="WKT2_2019")

    cloud = inspect_pointcloud(write(tmp_path, copc(wkt=wkt.encode())))

    assert (cloud.srid, cloud.vertical_crs) == (26912, "NAVD88 height")


def test_a_node_with_no_points_is_skipped(tmp_path) -> None:
    """The spec allows an empty node; it holds no data range to check."""
    data = copc(pages=lambda layout: child_page(layout, [(1, 0, 0, 0, 0, 0, 0)]))

    assert inspect_pointcloud(write(tmp_path, data)).point_count == 100


# --- Refusals ------------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        copc(info_first=False),
        copc(compressed=False),
        copc(version=(1, 2)),
        patched(copc(), 104, "<B", 0x83),
    ],
    ids=["plain-laz", "uncompressed-las", "las-1.2", "point-format-3"],
)
def test_a_point_cloud_that_is_not_copc_is_refused_with_the_conversion_hint(
    tmp_path, data
) -> None:
    """Plain LAS and LAZ get pointcloud_not_copc, naming the tools that convert them."""
    refusal = refused(tmp_path, data)

    assert refusal.code == "pointcloud_not_copc"
    assert "writers.copc" in str(refusal) and "untwine" in str(refusal)
    assert refusal_detail(refusal) == {
        "code": "pointcloud_not_copc",
        "message": str(refusal),
    }


_CUSTOM = CRS.from_epsg(26912).to_wkt().rsplit(',AUTHORITY["EPSG","26912"]', 1)[0]


def _bound_crs(grid: str) -> bytes:
    """A WKT2 BOUNDCRS whose transformation names ``grid`` as its shift file."""
    return (
        f"BOUNDCRS[SOURCECRS[{CRS.from_epsg(26912).to_wkt(version='WKT2_2019')}],"
        f"TARGETCRS[{CRS.from_epsg(4326).to_wkt(version='WKT2_2019')}],"
        'ABRIDGEDTRANSFORMATION["shift",METHOD["NTv2",ID["EPSG",9615]],'
        f'PARAMETERFILE["Latitude and longitude difference file","{grid}"]]]'
    ).encode()


@pytest.mark.parametrize(
    "wkt",
    [
        None,
        b"not a coordinate system",
        b'LOCAL_CS["site grid",UNIT["metre",1]]',
        (_CUSTOM + "]").encode(),
        _bound_crs("/nonexistent/shift.gsb"),
        b'PROJCS["x",AUTHORITY["EPSG","26912"]',
        b'PROJCS["x",AUTHORITY["EPSG","999999999"]]',
    ],
    ids=[
        "none",
        "unparseable",
        "local",
        "no-epsg-code",
        "bound",
        "unbalanced",
        "unknown-code",
    ],
)
def test_a_point_cloud_without_a_usable_crs_is_refused(tmp_path, wkt) -> None:
    """A CRS with no EPSG code GeoLens can read is refused."""
    assert refused(tmp_path, copc(wkt=wkt)).code == "pointcloud_no_crs"


_CHECK_IN_A_CHILD = """
import sys
from app.core.upload_errors import UnsafeUploadError
from app.processing.ingest.pointcloud import inspect_pointcloud
try:
    print(inspect_pointcloud(sys.argv[1]).srid)
except UnsafeUploadError as exc:
    print(exc.code)
"""


def _inspect_in_a_child(path: str) -> str:
    """Inspect ``path`` in a child process, since PROJ blocks holding the GIL."""
    try:
        done = subprocess.run(
            [sys.executable, "-c", _CHECK_IN_A_CHILD, path],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=Path(__file__).resolve().parents[1],
        )
    except subprocess.TimeoutExpired:
        pytest.fail("the check opened the file the WKT names")
    return done.stdout.strip().splitlines()[-1]


@pytest.mark.parametrize("form", ["bound-crs", "proj4-extension"])
def test_a_crs_that_names_a_file_never_opens_it(tmp_path, form) -> None:
    """A grid file named in the WKT is never opened, so a FIFO cannot hang the check."""
    fifo = tmp_path / "shift.gsb"
    os.mkfifo(fifo)
    if form == "bound-crs":
        wkt = _bound_crs(str(fifo))
    else:
        wkt = CRS.from_epsg(26912).to_wkt()[:-1] + (
            f',EXTENSION["PROJ4","+proj=utm +zone=12 +ellps=GRS80 +nadgrids={fifo}"]]'
        )
        wkt = wkt.encode()

    outcome = _inspect_in_a_child(write(tmp_path, copc(wkt=wkt)))

    assert outcome == ("pointcloud_no_crs" if form == "bound-crs" else "26912")


def _pages(*entries):
    """A root page holding the root node and ``entries`` built from the layout."""
    return lambda layout: [[root_entry(layout), *(e(layout) for e in entries)]]


def _two_levels_down(pages) -> bytes:
    """The root node and a node two levels below it, on the pages ``pages`` returns."""
    deeper = compressed_chunk(records(50, span=250))

    def layout(at: Layout):
        return pages(at, (2, 0, 0, 0, at.chunk_offset + at.chunk_size, len(deeper), 50))

    return copc(padding=deeper, pages=layout, header_point_count=150)


def _sibling_on_a_referenced_page() -> bytes:
    """A root page naming the page of cell (1,1,0,0), which holds cell (1,0,0,0)."""
    sibling = compressed_chunk(records(50, span=500))
    return copc(
        padding=sibling,
        pages=lambda at: [
            [root_entry(at), (1, 1, 0, 0, at.page_offset + 64, 32, -1)],
            [(1, 0, 0, 0, at.chunk_offset + at.chunk_size, len(sibling), 50)],
        ],
        header_point_count=150,
    )


@pytest.mark.parametrize(
    ("data", "message"),
    [
        pytest.param(b"PK\x03\x04" + bytes(400), "not a LAS", id="not-las"),
        pytest.param(copc()[:1500], "truncated", id="truncated"),
        pytest.param(copc(header_point_count=0), "no points", id="no-points"),
        pytest.param(copc(header_point_count=99), "don't add up", id="counts"),
        pytest.param(
            patched(copc(), 179, "<d", float("nan")), "usable bounds", id="nan"
        ),
        pytest.param(
            patched(copc(), 179, "<dd", ORIGIN[0], ORIGIN[0] + 1),
            "usable bounds",
            id="min-above-max",
        ),
        pytest.param(patched(copc(), 131, "<d", 0.0), "usable bounds", id="scale-zero"),
        pytest.param(
            patched(copc(), 147, "<d", float("inf")), "usable bounds", id="scale-inf"
        ),
        pytest.param(
            patched(copc(), 155, "<d", float("nan")), "usable bounds", id="offset-nan"
        ),
        pytest.param(
            copc(laszip=lambda record: record[:32] + b"\0\0"),
            "LASzip",
            id="laszip-without-items",
        ),
        pytest.param(
            copc(laszip=lambda record: patched(record, 36, "<H", 31)),
            "LASzip",
            id="laszip-item-size",
        ),
        pytest.param(
            copc(pages=_pages(lambda at: (1, 0, 0, 0, at.page_offset, 64, -1))),
            "more than once",
            id="page-names-itself",
        ),
        pytest.param(
            copc(pages=_pages(lambda at: (1, 0, 0, 0, 0, 32, -1))),
            "outside the hierarchy",
            id="page-outside-hierarchy",
        ),
        pytest.param(
            copc(
                pages=lambda at: [
                    [(0, 0, 0, 0, at.chunk_offset, at.chunk_size + 64, 100)]
                ]
            ),
            "outside the file's point data",
            id="chunk-past-point-data",
        ),
        pytest.param(
            copc(pages=lambda at: [[(0, 0, 0, 0, 0, at.chunk_size, 100)]]),
            "outside the file's point data",
            id="chunk-in-header",
        ),
        pytest.param(
            copc(pages=_pages(lambda at: (25, 0, 0, 0, 0, 0, 0))),
            "outside the octree",
            id="too-deep",
        ),
        pytest.param(
            copc(pages=_pages(lambda at: (1, 2, 0, 0, 0, 0, 0))),
            "outside the octree",
            id="key-outside-octree",
        ),
        pytest.param(
            copc(pages=_pages(lambda at: (1, -1, 0, 0, 0, 0, 0))),
            "outside the octree",
            id="negative-key",
        ),
        pytest.param(
            copc(pages=_pages(lambda at: (-1, 0, 0, 0, 0, 0, 0))),
            "outside the octree",
            id="negative-depth",
        ),
        pytest.param(
            copc(pages=_pages(root_entry)), "malformed or repeated", id="repeated"
        ),
        pytest.param(
            copc(
                pages=lambda at: [
                    [
                        root_entry(at),
                        (2, 0, 0, 0, 0, 0, 0),
                        (1, 0, 0, 0, at.page_offset + 96, 32, -1),
                    ],
                    [(2, 0, 0, 0, 0, 0, 0)],
                ]
            ),
            "malformed or repeated",
            id="repeated-on-another-page",
        ),
        pytest.param(
            copc(
                points=records(100, span=500),
                pages=lambda at: [[(1, 0, 0, 0, at.chunk_offset, at.chunk_size, 100)]],
            ),
            "no root node",
            id="no-root",
        ),
        pytest.param(
            _two_levels_down(lambda at, node: [[root_entry(at), node]]),
            "can't be found from the hierarchy's root",
            id="missing-parent",
        ),
        pytest.param(
            _two_levels_down(
                lambda at, node: [
                    [
                        root_entry(at),
                        (1, 0, 0, 0, at.page_offset + 96, 32, -1),
                        (2, 0, 0, 0, at.page_offset + 128, 32, -1),
                    ],
                    [(1, 0, 0, 0, 0, 0, 0)],
                    [node],
                ]
            ),
            "can't be found from the hierarchy's root",
            id="named-from-the-wrong-page",
        ),
        pytest.param(
            _sibling_on_a_referenced_page(),
            "outside its subtree",
            id="sibling-on-a-referenced-page",
        ),
        pytest.param(
            copc(
                pages=lambda at: [
                    [root_entry(at), (1, 1, 0, 0, at.page_offset + 64, 64, -1)],
                    [(1, 1, 0, 0, 0, 0, 0), (1, 0, 0, 0, 0, 0, 0)],
                ]
            ),
            "outside its subtree",
            id="stray-entry-on-a-referenced-page",
        ),
        pytest.param(
            copc(
                pages=_pages(
                    lambda at: (1, 0, 0, 0, 0, 32, -1), lambda at: (1, 0, 0, 0, 0, 0, 0)
                )
            ),
            "malformed or repeated",
            id="key-twice-on-a-page",
        ),
        pytest.param(
            copc(pages=_pages(lambda at: (1, 0, 0, 0, 0, 0, -2))),
            "malformed or repeated",
            id="negative-count",
        ),
    ],
)
def test_a_damaged_point_cloud_is_refused_as_invalid(tmp_path, data, message) -> None:
    """Every structural fault is pointcloud_invalid, before any point is decoded."""
    refusal = refused(tmp_path, data)

    assert (refusal.code, message in str(refusal)) == ("pointcloud_invalid", True)


@pytest.mark.parametrize(
    "pages",
    [
        pytest.param(
            lambda at, node: [[root_entry(at), (1, 0, 0, 0, 0, 0, 0), node]],
            id="empty-parent",
        ),
        pytest.param(lambda at, node: child_page(at, [node]), id="page-parent"),
        pytest.param(
            lambda at, node: [
                [root_entry(at), (1, 0, 0, 0, at.page_offset + 64, 64, -1)],
                [(1, 0, 0, 0, 0, 0, 0), (2, 0, 0, 0, at.page_offset + 128, 32, -1)],
                [node],
            ],
            id="two-page-chain",
        ),
    ],
)
async def test_a_node_reached_through_an_empty_entry_or_a_page_passes(
    tmp_path, pages
) -> None:
    """An empty entry or a page reference is the entry a reader walks through."""
    path = write(tmp_path, _two_levels_down(pages))

    door, worker = inspect_pointcloud(path), await inspect_every_node(path)

    assert (door.point_count, worker.point_count) == (150, 150)


@pytest.mark.parametrize(
    "data",
    [
        copc(chunk=lambda chunk: bytes(len(chunk))),
        copc(chunk=lambda chunk: chunk[: len(chunk) // 2]),
        copc(points=records(100)[:-30] + struct.pack("<iii", 10**6, 0, 0) + bytes(18)),
    ],
    ids=["zeroed-chunk", "short-chunk", "point-outside-bounds"],
)
def test_a_node_that_does_not_decode_as_declared_is_refused(tmp_path, data) -> None:
    """The top node is decoded, and its points must sit inside the header's bounds."""
    assert refused(tmp_path, data).code == "pointcloud_decode_failed"


@pytest.mark.parametrize(
    ("offset", "fmt", "values"),
    [
        (0, "<d", (float("nan"),)),
        (24, "<d", (0.0,)),
        (24, "<d", (-5.0,)),
        (32, "<d", (0.0,)),
        (32, "<d", (float("inf"),)),
        (56, "<dd", (10.0, 5.0)),
        (56, "<d", (float("nan"),)),
    ],
    ids=[
        "center-nan",
        "halfsize-zero",
        "halfsize-negative",
        "spacing-zero",
        "spacing-inf",
        "gps-range-reversed",
        "gps-time-nan",
    ],
)
def test_a_damaged_copc_info_record_is_refused(tmp_path, offset, fmt, values) -> None:
    """The octree's center, half-size and spacing and the GPS time range must be usable."""
    refusal = refused(tmp_path, patched(copc(), _INFO_AT + offset, fmt, *values))

    assert (refusal.code, "COPC info record" in str(refusal)) == (
        "pointcloud_invalid",
        True,
    )


def test_points_outside_the_octree_are_refused(tmp_path) -> None:
    """Every point must lie in the octree's cube, which a COPC reader splits into nodes."""
    refusal = refused(tmp_path, patched(copc(), _INFO_AT, "<d", ORIGIN[0] + 20))

    assert (refusal.code, "outside its octree" in str(refusal)) == (
        "pointcloud_invalid",
        True,
    )


async def test_a_finite_header_that_scales_past_a_double_is_refused(tmp_path) -> None:
    """A Z scale, Z bound and half-size of 1e308 put inf in the points and NaN in the cells."""
    data = patched(copc(), 147, "<d", 1e308)
    data = patched(data, 211, "<d", 1e308)
    path = write(tmp_path, patched(data, _INFO_AT + 24, "<d", 1e308))

    with pytest.raises(UnsafeUploadError) as door:
        inspect_pointcloud(path)
    with pytest.raises(UnsafeUploadError) as worker:
        await inspect_every_node(path)

    message = "The point cloud's coordinates are too large to represent."
    assert (door.value.code, str(door.value)) == ("pointcloud_invalid", message)
    assert (worker.value.code, str(worker.value)) == ("pointcloud_invalid", message)


def test_an_octree_past_a_double_is_refused(tmp_path) -> None:
    """A half-size of 1e308 overflows the cells, and NaN passes every comparison."""
    refusal = refused(tmp_path, patched(copc(), _INFO_AT + 24, "<d", 1e308))

    assert (refusal.code, str(refusal)) == (
        "pointcloud_invalid",
        "The point cloud's octree is too large to represent.",
    )


async def test_facts_json_cannot_carry_are_refused_last(tmp_path, monkeypatch) -> None:
    """Facts with NaN or inf never leave the checks, whatever produced them."""
    path = write(tmp_path, copc_nodes())
    monkeypatch.setattr(
        pointcloud_module,
        "_crs_facts",
        lambda *args: (26912, None, (float("inf"), 0.0, 1.0, 1.0)),
    )

    with pytest.raises(UnsafeUploadError) as door:
        inspect_pointcloud(path)
    with pytest.raises(UnsafeUploadError) as worker:
        await inspect_every_node(path)

    message = "The point cloud's extent or elevation range isn't finite."
    assert (door.value.code, str(door.value)) == ("pointcloud_invalid", message)
    assert (worker.value.code, str(worker.value)) == ("pointcloud_invalid", message)


def test_an_octree_larger_than_its_points_passes(tmp_path) -> None:
    """A cube that holds the points with room to spare is fine."""
    data = patched(copc(), _INFO_AT + 24, "<d", 50.0)

    assert inspect_pointcloud(write(tmp_path, data)).point_count == 100


def _negated_x_scale(min_x: float, max_x: float) -> bytes:
    """copc() read with a negative X scale, so its points span ORIGIN - 10 to ORIGIN in X."""
    data = patched(copc(), 131, "<d", -SCALE)
    # The octree's cube moves with the points.
    data = patched(data, _INFO_AT, "<d", ORIGIN[0] - 5)
    return patched(data, 179, "<dd", max_x, min_x)


def test_a_negative_scale_with_points_outside_the_bounds_is_refused(tmp_path) -> None:
    """A negative scale turns the raw maximum into the lowest point, and the check follows it."""
    data = _negated_x_scale(ORIGIN[0] - 5, ORIGIN[0] + 5)

    assert refused(tmp_path, data).code == "pointcloud_decode_failed"


def test_a_negative_scale_with_points_inside_the_bounds_passes(tmp_path) -> None:
    """Points a negative scale places inside the declared bounds pass."""
    data = _negated_x_scale(ORIGIN[0] - 10, ORIGIN[0])

    assert inspect_pointcloud(write(tmp_path, data)).point_count == 100


def _lazrs_panic() -> BaseException:
    """The exception a Rust panic inside lazrs raises, caught from a real one."""
    with pytest.raises(BaseException) as panic:
        lazrs.decompress_points_with_chunk_table(
            b"\1" * 64,
            b"\3\0" + bytes(32),
            bytearray(30),
            [(1, 64)],
            lazrs.DecompressionSelection(lazrs.SELECTIVE_DECOMPRESS_ALL),
        )
    assert not isinstance(panic.value, Exception), "lazrs no longer panics here"
    return panic.value


def _lazrs_raising(
    monkeypatch, exc: BaseException, name: str = "decompress_points_with_chunk_table"
) -> None:
    def _raise(*args, **kwargs):
        raise exc

    monkeypatch.setattr(pointcloud_module.lazrs, name, _raise)


def test_a_lazrs_panic_is_a_decode_refusal(tmp_path, monkeypatch) -> None:
    """A Rust panic inside lazrs, which is no Exception, still becomes a refusal."""
    _lazrs_raising(monkeypatch, _lazrs_panic())

    assert refused(tmp_path, copc()).code == "pointcloud_decode_failed"


def test_an_interrupt_during_the_decode_is_not_swallowed(tmp_path, monkeypatch) -> None:
    """Only a panic is turned into a refusal; an interrupt still propagates."""
    _lazrs_raising(monkeypatch, KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        inspect_pointcloud(write(tmp_path, copc()))


@pytest.mark.parametrize(
    ("limit", "value", "data"),
    [
        ("MAX_RECORDS", 1, copc()),
        (
            "MAX_HIERARCHY_ENTRIES",
            1,
            copc(pages=lambda layout: [[root_entry(layout), (1, 0, 0, 0, 0, 0, 0)]]),
        ),
        ("MAX_DECODE_BYTES", 1024, copc()),
        ("MAX_EVLR_BLOCK_BYTES", 64, copc()),
        ("MAX_VLR_BLOCK_BYTES", 400, copc()),
        ("MAX_WKT_BYTES", 64, copc()),
    ],
)
def test_each_bound_refuses_a_file_past_it(tmp_path, monkeypatch, limit, value, data):
    """Each bound on reading the file is a refusal, not a longer read."""
    monkeypatch.setattr(pointcloud_module, limit, value)

    assert refused(tmp_path, data).code in {"pointcloud_invalid", "pointcloud_no_crs"}


def test_a_refusal_names_the_bound_it_hit(tmp_path, monkeypatch) -> None:
    """A capped refusal carries the limit its message states."""
    monkeypatch.setattr(pointcloud_module, "MAX_HIERARCHY_ENTRIES", 1)
    data = copc(pages=lambda layout: [[root_entry(layout), (1, 0, 0, 0, 0, 0, 0)]])

    refusal = refused(tmp_path, data)

    assert refusal_detail(refusal) == {
        "code": "pointcloud_invalid",
        "message": "The hierarchy has more than 1 entries.",
        "limit": 1,
    }


def _lazrs_calls(monkeypatch) -> list:
    """Each call that reaches lazrs, which then fails as a damaged chunk would."""
    calls: list = []

    def _decompress(*args, **kwargs):
        calls.append(args)
        raise lazrs.LazrsError("called")

    monkeypatch.setattr(
        pointcloud_module.lazrs, "decompress_points_with_chunk_table", _decompress
    )
    return calls


@pytest.mark.parametrize(
    "chunk",
    [
        lambda chunk: patched(chunk, 34, "<I", 0xFFFFFFFF),
        lambda chunk: patched(chunk, 30, "<I", 99),
        # Short of the 70-byte chunk header, yet within the decode ratio.
        lambda chunk: chunk[:50],
    ],
    ids=["layer-size-past-the-chunk", "count-differs", "shorter-than-its-header"],
)
def test_a_chunk_whose_header_disagrees_is_refused_before_lazrs(
    tmp_path, monkeypatch, chunk
) -> None:
    """lazrs sizes its buffers from the chunk header, so the header is checked first."""
    data = copc(chunk=chunk)
    calls = _lazrs_calls(monkeypatch)

    assert (refused(tmp_path, data).code, calls) == ("pointcloud_decode_failed", [])


@pytest.mark.parametrize(
    "second",
    [
        lambda at: (1, 0, 0, 0, at.chunk_offset, at.chunk_size, at.count),
        lambda at: (1, 0, 0, 0, at.chunk_offset + 1, at.chunk_size - 1, at.count),
        lambda at: (1, 0, 0, 0, at.chunk_offset - 4, 60, at.count),
    ],
    ids=["same-chunk", "inside-another", "listed-in-reverse"],
)
async def test_nodes_whose_points_overlap_are_refused_before_lazrs(
    tmp_path, monkeypatch, second
) -> None:
    """A chunk two nodes name is refused before any node is decoded."""
    path = write(tmp_path, copc(pages=_pages(second), header_point_count=200))
    calls = _lazrs_calls(monkeypatch)

    with pytest.raises(UnsafeUploadError) as door:
        inspect_pointcloud(path)
    with pytest.raises(UnsafeUploadError) as worker:
        await inspect_every_node(path)

    assert (door.value.code, worker.value.code, calls) == (
        "pointcloud_invalid",
        "pointcloud_invalid",
        [],
    )


async def test_disjoint_nodes_listed_out_of_offset_order_pass(tmp_path) -> None:
    """A hierarchy may list nodes in any order, and disjoint ones pass the overlap check."""
    deeper = compressed_chunk(records(50, span=500))
    data = copc(
        padding=deeper,
        pages=lambda at: [
            [
                (1, 0, 0, 0, at.chunk_offset + at.chunk_size, len(deeper), 50),
                root_entry(at),
            ]
        ],
        header_point_count=150,
    )
    path = write(tmp_path, data)

    door, worker = inspect_pointcloud(path), await inspect_every_node(path)

    assert (door.point_count, worker.point_count) == (150, 150)


def _byte14_items(*sizes: int):
    """A LASzip record rewrite that lists the extra bytes as one BYTE14 item per size."""

    def rewrite(record: bytes) -> bytes:
        items = [record[34:40], *(struct.pack("<HHH", 14, size, 3) for size in sizes)]
        return record[:32] + struct.pack("<H", len(items)) + b"".join(items)

    return rewrite


@pytest.mark.parametrize(
    ("extra_bytes", "sizes"),
    [(0, (0,) * 64), (8, (4, 4))],
    ids=["empty-items", "split-extra-bytes"],
)
def test_extra_bytes_outside_one_item_are_refused_before_lazrs(
    tmp_path, monkeypatch, extra_bytes, sizes
) -> None:
    """lazrs decodes every item for each point, so extra bytes form one non-empty item."""
    data = copc(extra_bytes=extra_bytes, laszip=_byte14_items(*sizes))
    calls = _lazrs_calls(monkeypatch)

    assert (refused(tmp_path, data).code, calls) == ("pointcloud_invalid", [])


def test_extra_bytes_within_the_bound_decode(tmp_path) -> None:
    """Points that carry extra bytes pass the LASzip and chunk checks."""
    cloud = inspect_pointcloud(write(tmp_path, copc(extra_bytes=8)))

    assert cloud.point_count == 100


def test_extra_bytes_past_the_bound_are_refused_before_lazrs(
    tmp_path, monkeypatch
) -> None:
    """lazrs builds models per extra byte before reading a point, so the count is capped."""
    data = copc(extra_bytes=MAX_EXTRA_BYTES + 1)
    calls = _lazrs_calls(monkeypatch)

    detail = refusal_detail(refused(tmp_path, data))

    assert calls == []
    assert detail == {
        "code": "pointcloud_invalid",
        "message": f"The file's points carry more than {MAX_EXTRA_BYTES} extra bytes.",
        "limit": MAX_EXTRA_BYTES,
    }


@pytest.mark.parametrize(
    ("data", "message"),
    [
        pytest.param(
            patched(copc(padding=bytes(100_000)), 703, "<H", 2000),
            "truncated",
            id="record-past-its-block",
        ),
        pytest.param(
            patched(copc(), 235, "<Q", 375),
            "truncated",
            id="evlrs-before-the-point-data",
        ),
        pytest.param(
            patched(copc(), 96, "<I", 2 * 1024 * 1024),
            "truncated",
            id="point-data-past-the-end",
        ),
    ],
)
def test_each_range_check_refuses_its_own_fault(tmp_path, data, message) -> None:
    """A range the header states is refused before anything reads past it."""
    refusal = refused(tmp_path, data)

    assert (refusal.code, message in str(refusal)) == ("pointcloud_invalid", True)


def test_a_node_whose_compressed_size_is_past_the_bound_is_refused(
    tmp_path, monkeypatch
) -> None:
    """The decode bound weighs the compressed bytes as well as the decoded ones."""
    monkeypatch.setattr(pointcloud_module, "MAX_DECODE_BYTES", 2 * 30 + 1)

    refusal = refused(tmp_path, copc(count=2))

    assert (refusal.code, "decode limit" in str(refusal)) == (
        "pointcloud_invalid",
        True,
    )


def _top_node_ratio() -> Fraction:
    """Exactly how many times its stored size copc()'s one node decodes to."""
    return Fraction(100 * 30, len(compressed_chunk(records(100))))


def test_a_node_at_the_decode_ratio_passes(tmp_path, monkeypatch) -> None:
    """A node that decodes to exactly the ratio times its stored size is decoded."""
    monkeypatch.setattr(pointcloud_module, "MAX_DECODE_RATIO", _top_node_ratio())

    assert inspect_pointcloud(write(tmp_path, copc())).point_count == 100


def test_a_node_past_the_decode_ratio_is_refused_before_lazrs(
    tmp_path, monkeypatch
) -> None:
    """A node that decodes to one byte more than the ratio allows never reaches lazrs."""
    stored = len(compressed_chunk(records(100)))
    monkeypatch.setattr(
        pointcloud_module, "MAX_DECODE_RATIO", _top_node_ratio() - Fraction(1, stored)
    )
    calls = _lazrs_calls(monkeypatch)

    assert (refused(tmp_path, copc()).code, calls) == ("pointcloud_invalid", [])


def test_structural_refusals_are_security_events_and_others_are_not(tmp_path) -> None:
    """A plain LAZ or a missing CRS is an ordinary refusal; a damaged file is a security event."""
    with capture_logs() as logs:
        refused(tmp_path, copc(info_first=False))
        refused(tmp_path, copc(wkt=None))
        refused(tmp_path, copc(header_point_count=99))

    assert [(log["log_level"], log.get("event_type")) for log in logs] == [
        ("info", None),
        ("info", None),
        ("warning", "security"),
    ]


# --- The LAZ chunk table -------------------------------------------------


def _pointing_at(data: bytes, table_offset: int) -> bytes:
    """``data`` whose point data opens with ``table_offset`` as its chunk table's offset."""
    return patched(data, struct.unpack_from("<I", data, 96)[0], "<q", table_offset)


def _with_table(data: bytes, table: bytes) -> bytes:
    """``data`` with ``table`` appended as its chunk table."""
    return _pointing_at(data, len(data)) + table


_ROOT_CHUNK = (100, len(compressed_chunk(records(100))))


def _gap_between_chunks() -> bytes:
    """Two nodes seven bytes apart, which a LAZ reader would take as touching."""
    deeper = compressed_chunk(records(50, span=500))
    return copc(
        padding=bytes(7) + deeper,
        pages=lambda at: [
            [
                root_entry(at),
                (1, 0, 0, 0, at.chunk_offset + at.chunk_size + 7, len(deeper), 50),
            ]
        ],
        header_point_count=150,
    )


@pytest.mark.parametrize(
    ("data", "points"),
    [
        pytest.param(copc(), records(100), id="one-node"),
        pytest.param(
            copc_nodes(),
            records(100) + records(120, span=500) + records(150, start=500, span=500),
            id="several-nodes",
        ),
    ],
)
def test_a_built_point_cloud_reads_as_plain_laz(data, points) -> None:
    """lazrs's LAZ reader, which follows the chunk table as laspy does, reads every point."""
    source = io.BytesIO(data)
    source.seek(struct.unpack_from("<I", data, 96)[0])
    decoded = bytearray(len(points))

    lazrs.LasZipDecompressor(source, laszip_record()).decompress_many(decoded)

    assert decoded == points


def test_a_chunk_table_anywhere_after_the_chunks_passes(tmp_path) -> None:
    """A LAZ reader seeks to the chunk table, so one after the EVLRs is read as well."""
    data = _with_table(copc(), chunk_table([_ROOT_CHUNK]))

    assert inspect_pointcloud(write(tmp_path, data)).point_count == 100


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(_pointing_at(copc(), -1), id="missing"),
        pytest.param(_pointing_at(copc(), len(copc())), id="past-the-end"),
        pytest.param(
            _with_table(copc(), patched(chunk_table([_ROOT_CHUNK]), 0, "<I", 1)),
            id="version",
        ),
        pytest.param(
            _with_table(copc(), chunk_table([_ROOT_CHUNK])[:9]), id="truncated"
        ),
        pytest.param(
            _with_table(copc(), struct.pack("<II", 0, 1) + b"\xff" * 16), id="garbage"
        ),
        pytest.param(
            _with_table(copc(), chunk_table([(99, _ROOT_CHUNK[1])])),
            id="count-differs",
        ),
        pytest.param(
            _with_table(copc(), chunk_table([(100, _ROOT_CHUNK[1] + 1)])),
            id="size-differs",
        ),
        pytest.param(_gap_between_chunks(), id="gap-between-chunks"),
    ],
)
def test_a_chunk_table_that_disagrees_with_the_octree_is_refused(
    tmp_path, data
) -> None:
    """A plain LAZ reader follows the chunk table, so it must list the octree's chunks."""
    refusal = refused(tmp_path, data)

    assert (refusal.code, str(refusal)) == (
        "pointcloud_invalid",
        "The file's LAZ chunk table doesn't match its octree.",
    )


def test_a_chunk_table_stating_another_count_is_refused_before_lazrs(
    tmp_path, monkeypatch
) -> None:
    """lazrs allocates a chunk table from its stated count, so the count is checked first."""
    data = _with_table(copc(), patched(chunk_table([_ROOT_CHUNK]), 4, "<I", 2))
    calls: list = []
    read_table = lazrs.read_chunk_table_only

    def _read(*args):
        calls.append(args)
        return read_table(*args)

    monkeypatch.setattr(pointcloud_module.lazrs, "read_chunk_table_only", _read)

    assert (refused(tmp_path, data).code, calls) == ("pointcloud_invalid", [])


def test_a_lazrs_panic_reading_the_chunk_table_is_a_refusal(
    tmp_path, monkeypatch
) -> None:
    """A Rust panic while lazrs reads the chunk table becomes a refusal, as in the decode."""
    _lazrs_raising(monkeypatch, _lazrs_panic(), "read_chunk_table_only")

    assert refused(tmp_path, copc()).code == "pointcloud_invalid"


def test_an_interrupt_reading_the_chunk_table_is_not_swallowed(
    tmp_path, monkeypatch
) -> None:
    """Only a lazrs failure reading the chunk table is a refusal; an interrupt propagates."""
    _lazrs_raising(monkeypatch, KeyboardInterrupt(), "read_chunk_table_only")

    with pytest.raises(KeyboardInterrupt):
        inspect_pointcloud(write(tmp_path, copc()))


# --- The probe reads only what the checks need ---------------------------


@pytest.fixture(params=["local", "s3"])
def storage(request, tmp_path, monkeypatch):
    """The local adapter, or the S3 adapter against a moto bucket."""
    monkeypatch.setattr(settings, "upload_staging_dir", str(tmp_path / "staging"))
    (tmp_path / "staging").mkdir()
    if request.param == "local":
        yield LocalStorageProvider(base_dir=str(tmp_path / "store"))
        return
    credential = uuid.uuid4().hex
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(name, credential)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="pointclouds")
        yield S3StorageProvider(
            bucket="pointclouds",
            region="us-east-1",
            access_key_id=credential,
            secret_access_key=credential,
        )


class _CountingReads:
    def __init__(self, storage) -> None:
        self._storage = storage
        self.bytes_read = 0

    def __getattr__(self, name):
        return getattr(self._storage, name)

    async def get_range(self, key: str, start: int, length: int) -> bytes:
        data = await self._storage.get_range(key, start, length)
        self.bytes_read += len(data)
        return data


def _two_nodes() -> bytes:
    """A root node, and a 2 MB node below it that the checks never read."""
    deep = os.urandom(2 * 1024 * 1024)

    def pages(layout: Layout):
        end = layout.chunk_offset + layout.chunk_size
        return [[root_entry(layout), (1, 0, 0, 0, end, len(deep), 50)]]

    return copc(padding=deep, pages=pages, header_point_count=150)


async def test_a_stored_point_cloud_is_read_without_downloading_it(
    tmp_path: Path, storage
) -> None:
    """The probe reads the header, the hierarchy and the top node, and agrees with a local read."""
    data = _two_nodes()
    await storage.put("staging/job/frozen/c.laz", io.BytesIO(data))
    counting = _CountingReads(storage)

    stored = await inspect_stored_pointcloud(counting, "staging/job/frozen/c.laz")

    assert stored == inspect_pointcloud(write(tmp_path, data))
    assert stored.point_count == 150
    assert counting.bytes_read < 16 * 1024 < len(data)
    assert not any((tmp_path / "staging").iterdir())


@pytest.mark.parametrize(
    "data",
    [
        copc(info_first=False),
        patched(copc(info_first=False), 235, "<QI", 0, 0),
        copc(pages=lambda at: [[root_entry(at), (1, 0, 0, 0, at.page_offset, 64, -1)]]),
        copc(chunk=lambda chunk: bytes(len(chunk))),
        _gap_between_chunks(),
    ],
    ids=[
        "plain-laz",
        "plain-laz-without-evlrs",
        "page-names-itself",
        "decode",
        "chunk-table",
    ],
)
async def test_a_stored_point_cloud_is_refused_as_a_local_one_is(
    tmp_path: Path, storage, data
) -> None:
    """The probe refuses with the same code as a local read, and leaves no probe behind."""
    await storage.put("staging/job/frozen/c.laz", io.BytesIO(data))
    local = refused(tmp_path, data)

    with pytest.raises(UnsafeUploadError) as stored:
        await inspect_stored_pointcloud(storage, "staging/job/frozen/c.laz")

    assert (stored.value.code, str(stored.value)) == (local.code, str(local))
    assert not any((tmp_path / "staging").iterdir())


async def test_the_probe_copies_nothing_past_a_bad_header(
    tmp_path: Path, storage
) -> None:
    """EVLRs claimed to start at byte 0 are refused without copying the file."""
    data = patched(_two_nodes(), 235, "<Q", 0)
    await storage.put("staging/job/frozen/c.laz", io.BytesIO(data))
    counting = _CountingReads(storage)

    with pytest.raises(UnsafeUploadError):
        await inspect_stored_pointcloud(counting, "staging/job/frozen/c.laz")

    assert counting.bytes_read < 16 * 1024 < len(data)


async def test_the_probe_skips_a_node_past_the_decode_bound(
    tmp_path: Path, storage, monkeypatch
) -> None:
    """A top node over the decode bound is refused without being copied."""
    big = 64 * 1024
    data = copc(
        padding=bytes(big),
        pages=lambda at: [
            [(0, 0, 0, 0, at.chunk_offset, at.chunk_size + big, at.count)]
        ],
    )
    await storage.put("staging/job/frozen/c.laz", io.BytesIO(data))
    counting = _CountingReads(storage)
    monkeypatch.setattr(pointcloud_module, "MAX_DECODE_BYTES", 8 * 1024)

    with pytest.raises(UnsafeUploadError, match="decode limit"):
        await inspect_stored_pointcloud(counting, "staging/job/frozen/c.laz")

    assert counting.bytes_read < 8 * 1024 < big


# --- The worker decodes every node ---------------------------------------


def _decoded_chunks(monkeypatch) -> list[int]:
    """The size of each chunk that reaches lazrs, which still decodes it."""
    sizes: list[int] = []
    decompress = lazrs.decompress_points_with_chunk_table

    def _decompress(chunk, *args):
        sizes.append(len(chunk))
        return decompress(chunk, *args)

    monkeypatch.setattr(
        pointcloud_module.lazrs, "decompress_points_with_chunk_table", _decompress
    )
    return sizes


async def test_every_node_of_a_point_cloud_is_decoded(tmp_path, monkeypatch) -> None:
    """Each node holding points reaches lazrs, and the facts match the top node check's."""
    path = write(tmp_path, copc_nodes())
    top_node_only = inspect_pointcloud(path)
    decoded = _decoded_chunks(monkeypatch)

    cloud = await inspect_every_node(path)

    assert cloud == top_node_only
    assert (cloud.point_count, len(decoded)) == (370, 3)


async def test_the_worker_takes_the_extent_from_the_points(tmp_path) -> None:
    """The extent and elevations span every node's points, however far the header's bounds reach."""
    tight = inspect_pointcloud(write(tmp_path, copc_nodes(), "tight.copc.laz"))
    path = write(
        tmp_path, copc_nodes(points=records(100, start=250, span=500), pad=500)
    )
    door = inspect_pointcloud(path)

    cloud = await inspect_every_node(path)

    assert (cloud.extent_bbox, cloud.z_min, cloud.z_max) == (
        tight.extent_bbox,
        1280.0,
        1281.0,
    )
    assert (door.z_min, door.z_max) == (780.0, 1781.0)


async def test_a_point_outside_its_node_cell_is_refused_by_the_worker(
    tmp_path,
) -> None:
    """A node's points must lie in its own octree cell, not only in the octree."""
    data = copc_nodes(
        last_chunk=lambda _: compressed_chunk(records(150, start=498, span=502))
    )
    path = write(tmp_path, data)
    inspect_pointcloud(path)

    with pytest.raises(UnsafeUploadError) as refusal:
        await inspect_every_node(path)

    assert (refusal.value.code, str(refusal.value)) == (
        "pointcloud_invalid",
        "A node's points lie outside its octree cell.",
    )


async def test_points_within_a_scale_unit_of_their_cell_pass(tmp_path) -> None:
    """Points half a scale unit outside their cells, as rounding leaves real files, pass."""
    data = patched(copc_nodes(), _INFO_AT, "<d", ORIGIN[0] + 5.005)

    assert (await inspect_every_node(write(tmp_path, data))).point_count == 370


@pytest.mark.parametrize(
    ("data", "decoded"),
    [
        pytest.param(copc_nodes(last_chunk=scrambled), 3, id="scrambled-layers"),
        pytest.param(copc_nodes(count_error=-1), 2, id="count-differs"),
        pytest.param(copc_nodes(size_error=-1), 2, id="size-differs"),
    ],
)
async def test_a_damaged_node_below_the_top_passes_the_door_and_not_the_worker(
    tmp_path, monkeypatch, data, decoded
) -> None:
    """The door passes it on its top node; the worker refuses it, a disagreeing header before lazrs."""
    path = write(tmp_path, data)
    inspect_pointcloud(path)
    chunks = _decoded_chunks(monkeypatch)

    with pytest.raises(UnsafeUploadError) as refusal:
        await inspect_every_node(path)

    assert (refusal.value.code, len(chunks)) == ("pointcloud_decode_failed", decoded)


async def test_a_node_below_the_top_past_the_decode_bound_is_refused(
    tmp_path, monkeypatch
) -> None:
    """Every node is held to the decode bound, not only the top one."""
    path = write(tmp_path, copc_nodes(counts=(120, 150)))
    monkeypatch.setattr(pointcloud_module, "MAX_DECODE_BYTES", 150 * 30 - 1)
    inspect_pointcloud(path)
    chunks = _decoded_chunks(monkeypatch)

    with pytest.raises(UnsafeUploadError, match="decode limit") as refusal:
        await inspect_every_node(path)

    assert (refusal.value.code, len(chunks)) == ("pointcloud_invalid", 2)


class _Clock:
    """A monotonic clock that moves a fixed step each time it is read."""

    def __init__(self, step: float) -> None:
        self.now, self.step = 0.0, step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


async def test_a_decode_past_its_time_budget_is_refused_between_nodes(
    tmp_path, monkeypatch
) -> None:
    """Once the file's decode budget is spent, no further node is decoded."""
    floor = pointcloud_module.DECODE_FLOOR_SECONDS
    path = write(tmp_path, copc_nodes())
    monkeypatch.setattr(pointcloud_module, "monotonic", _Clock(floor * 2 / 3))
    chunks = _decoded_chunks(monkeypatch)

    with pytest.raises(UnsafeUploadError) as refusal:
        await inspect_every_node(path)

    assert refusal_detail(refusal.value) == {
        "code": "pointcloud_invalid",
        "message": f"The point cloud takes more than {floor} seconds to decode.",
        "limit": floor,
    }
    assert len(chunks) == 2


async def test_a_decode_within_its_time_budget_passes(tmp_path, monkeypatch) -> None:
    """A file whose nodes decode inside its budget passes the check."""
    floor = pointcloud_module.DECODE_FLOOR_SECONDS
    path = write(tmp_path, copc_nodes())
    monkeypatch.setattr(pointcloud_module, "monotonic", _Clock(floor / 3))

    assert (await inspect_every_node(path)).point_count == 370
