"""A COPC upload is checked from its header, VLRs, hierarchy and top node alone."""

from __future__ import annotations

import io
import os
import struct
import subprocess
import sys
import uuid
from pathlib import Path

import boto3
import lazrs
import pytest
from moto import mock_aws
from rasterio.crs import CRS

from app.core.config import settings
from app.core.upload_errors import CodedUploadError, refusal_detail
from app.platform.storage.local import LocalStorageProvider
from app.platform.storage.s3 import S3StorageProvider
from app.processing.ingest import pointcloud as pointcloud_module
from app.processing.ingest.pointcloud import (
    inspect_pointcloud,
    inspect_stored_pointcloud,
)
from tests.pointcloud_files import Layout, copc, records, root_entry


def write(tmp_path: Path, data: bytes, name: str = "cloud.copc.laz") -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def refused(tmp_path: Path, data: bytes) -> CodedUploadError:
    with pytest.raises(CodedUploadError) as refusal:
        inspect_pointcloud(write(tmp_path, data))
    return refusal.value


def patched(data: bytes, offset: int, fmt: str, *values) -> bytes:
    out = bytearray(data)
    struct.pack_into(fmt, out, offset, *values)
    return bytes(out)


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
from app.core.upload_errors import CodedUploadError
from app.processing.ingest.pointcloud import inspect_pointcloud
try:
    print(inspect_pointcloud(sys.argv[1]).srid)
except CodedUploadError as exc:
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
                    [(0, 0, 0, 0, at.chunk_offset, at.chunk_size + 9, 100)]
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
            copc(pages=_pages(root_entry)), "malformed or repeated", id="repeated"
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


def test_a_lazrs_panic_is_a_decode_refusal(tmp_path, monkeypatch) -> None:
    """A Rust panic inside lazrs, which is no Exception, still becomes a refusal."""
    no_items = copc(laszip=lambda record: record[:32] + b"\0\0")
    with pytest.raises(BaseException) as panic:
        lazrs.decompress_points_with_chunk_table(
            b"\1" * 64,
            b"\3\0" + bytes(32),
            bytearray(30),
            [(1, 64)],
            lazrs.DecompressionSelection(lazrs.SELECTIVE_DECOMPRESS_ALL),
        )
    assert not isinstance(panic.value, Exception), "lazrs no longer panics here"
    monkeypatch.setattr(pointcloud_module, "_check_laszip", lambda data, header: None)

    assert refused(tmp_path, no_items).code == "pointcloud_decode_failed"


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
    ],
    ids=["plain-laz", "plain-laz-without-evlrs", "page-names-itself", "decode"],
)
async def test_a_stored_point_cloud_is_refused_as_a_local_one_is(
    tmp_path: Path, storage, data
) -> None:
    """The probe refuses with the same code as a local read, and leaves no probe behind."""
    await storage.put("staging/job/frozen/c.laz", io.BytesIO(data))
    local = refused(tmp_path, data)

    with pytest.raises(CodedUploadError) as stored:
        await inspect_stored_pointcloud(storage, "staging/job/frozen/c.laz")

    assert (stored.value.code, str(stored.value)) == (local.code, str(local))
    assert not any((tmp_path / "staging").iterdir())
