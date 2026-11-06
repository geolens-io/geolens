"""A VRT over members without overviews carries an overview image of its own."""

from __future__ import annotations

import shutil
from pathlib import Path
from xml.etree.ElementTree import parse

import numpy as np
import pytest
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin

from tests.test_raster_replace_1221 import raster_storage as raster_storage
from app.processing.raster.vrt import (
    add_vrt_overview,
    build_vrt,
    overview_key_for,
    overview_keys_for,
)

needs_gdal_cli = pytest.mark.skipif(
    shutil.which("gdal_translate") is None or shutil.which("gdalbuildvrt") is None,
    reason="GDAL command-line tools are not installed",
)


def _member(path: Path, *, west: float, overviews: bool, size: int = 500) -> str:
    profile = {
        "driver": "GTiff",
        "dtype": "uint8",
        "width": size,
        "height": size,
        "count": 1,
        "crs": "EPSG:4326",
        "transform": from_origin(west, 10.0, 0.001, 0.001),
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }
    data = np.random.default_rng(1).integers(0, 200, (size, size), dtype="uint8")
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(data, 1)
        if overviews:
            dst.build_overviews([2, 4], Resampling.nearest)
    return str(path)


def _titiler_env() -> rasterio.Env:
    """The GDAL settings TiTiler opens a VRT with."""
    return rasterio.Env(
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", VRT_VIRTUAL_OVERVIEWS="NO"
    )


def _vrt(tmp_path: Path, *, overviews: bool) -> tuple[str, list[str]]:
    members = [
        _member(tmp_path / "a.tif", west=0.0, overviews=overviews),
        _member(tmp_path / "b.tif", west=0.5, overviews=overviews),
    ]
    vrt_path = str(tmp_path / "source.vrt")
    build_vrt("mosaic", members, vrt_path, "finest")
    return vrt_path, members


def test_overview_key_sits_beside_the_vrt() -> None:
    assert (
        overview_key_for("rasters/x/generations/g/source.vrt")
        == "rasters/x/generations/g/source.ovr.tif"
    )


@needs_gdal_cli
def test_members_without_overviews_get_an_overview_the_vrt_reads(
    tmp_path: Path,
) -> None:
    vrt_path, members = _vrt(tmp_path, overviews=False)
    with _titiler_env(), rasterio.open(vrt_path) as src:
        assert src.overviews(1) == []

    overview_paths = add_vrt_overview(vrt_path, members)

    assert overview_paths == [str(tmp_path / "source.ovr.tif")]
    assert Path(overview_paths[0]).exists()
    band = parse(vrt_path).getroot().find("VRTRasterBand")
    name = band.find("Overview/SourceFilename")
    assert name.text == "source.ovr.tif"
    assert name.get("relativeToVRT") == "1"
    assert band.find("Overview/SourceBand").text == "1"
    with _titiler_env(), rasterio.open(vrt_path) as src:
        assert src.overviews(1)


@needs_gdal_cli
def test_members_with_overviews_leave_the_vrt_alone(tmp_path: Path) -> None:
    vrt_path, members = _vrt(tmp_path, overviews=True)
    before = Path(vrt_path).read_bytes()

    assert add_vrt_overview(vrt_path, members) is None

    assert Path(vrt_path).read_bytes() == before
    assert not (tmp_path / "source.ovr.tif").exists()


@needs_gdal_cli
def test_one_member_without_overviews_is_enough(tmp_path: Path) -> None:
    vrt_path, members = _vrt(tmp_path, overviews=True)
    members.append(_member(tmp_path / "c.tif", west=1.0, overviews=False))
    build_vrt("mosaic", members, vrt_path, "finest")

    assert add_vrt_overview(vrt_path, members) is not None


@needs_gdal_cli
def test_a_failed_overview_build_leaves_the_vrt_as_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vrt_path, members = _vrt(tmp_path, overviews=False)
    before = Path(vrt_path).read_bytes()

    class _Failed:
        returncode = 1
        stderr = "no space left"

    monkeypatch.setattr("app.processing.raster.vrt.run_gdal", lambda *a, **k: _Failed())

    assert add_vrt_overview(vrt_path, members) is None
    assert Path(vrt_path).read_bytes() == before


@needs_gdal_cli
def test_a_timed_out_overview_build_leaves_the_vrt_as_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vrt_path, members = _vrt(tmp_path, overviews=False)
    before = Path(vrt_path).read_bytes()

    def _timeout(*args, **kwargs):
        (tmp_path / "source.ovr.tif").write_bytes(b"partial")
        raise RuntimeError("gdal_translate timed out after 3600s")

    monkeypatch.setattr("app.processing.raster.vrt.run_gdal", _timeout)

    assert add_vrt_overview(vrt_path, members) is None
    assert Path(vrt_path).read_bytes() == before
    assert not (tmp_path / "source.ovr.tif").exists()


def test_the_stale_generation_sweep_names_the_overview() -> None:
    import uuid

    from app.platform.jobs.sweep import _stale_generation_storage_keys

    vrt_id, generation_id = uuid.uuid4(), uuid.uuid4()
    keys = _stale_generation_storage_keys([(generation_id, vrt_id)])

    assert f"rasters/{vrt_id}/generations/{generation_id}/source.ovr.tif" in keys


pytestmark_db = pytest.mark.anyio


@pytest.mark.anyio
@needs_gdal_cli
async def test_regeneration_swaps_the_overview_and_reaps_the_old_one(
    client, admin_auth_header, test_db_session, raster_storage, monkeypatch
) -> None:
    from sqlalchemy import select

    from app.modules.auth.models import User
    from app.processing.raster.models import RasterAsset
    from tests.test_raster_replace_1221 import (
        _make_live_raster,
        _make_vrt_parent,
        _purge_vrt,
        _run_regeneration,
    )

    monkeypatch.setattr(
        "app.processing.ingest.tasks_vrt.get_storage",
        lambda: raster_storage,
        raising=True,
    )
    admin_id = (
        await test_db_session.execute(select(User.id).where(User.username == "admin"))
    ).scalar_one()
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    parent = await _make_vrt_parent(
        test_db_session, raster_storage, created_by=admin_id, member=member
    )
    ids = (
        parent.dataset.id,
        parent.dataset.record_id,
        member.dataset.id,
        member.dataset.record_id,
    )
    stale_overview = overview_key_for(parent.cog_key)
    from io import BytesIO

    await raster_storage.put(stale_overview, BytesIO(b"old-overview"))

    try:
        await _run_regeneration(test_db_session, parent=parent, user_id=admin_id)
        test_db_session.expire_all()
        asset = (
            await test_db_session.execute(
                select(RasterAsset).where(RasterAsset.dataset_id == ids[0])
            )
        ).scalar_one()

        assert await raster_storage.exists(overview_key_for(asset.asset_uri))
        assert not await raster_storage.exists(stale_overview)
    finally:
        await _purge_vrt(test_db_session, ids=ids)


@pytest.mark.anyio
async def test_a_live_vrts_overview_counts_as_referenced(
    client, admin_auth_header, test_db_session, raster_storage
) -> None:
    from sqlalchemy import select

    from app.modules.auth.models import User
    from app.platform.jobs.sweep import _live_referenced_storage_keys
    from tests.test_raster_replace_1221 import (
        _make_live_raster,
        _make_vrt_parent,
        _purge_vrt,
    )

    admin_id = (
        await test_db_session.execute(select(User.id).where(User.username == "admin"))
    ).scalar_one()
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    parent = await _make_vrt_parent(
        test_db_session, raster_storage, created_by=admin_id, member=member
    )
    ids = (
        parent.dataset.id,
        parent.dataset.record_id,
        member.dataset.id,
        member.dataset.record_id,
    )
    overview = overview_key_for(parent.cog_key)
    try:
        level = overview_keys_for(parent.cog_key)[2]
        live = await _live_referenced_storage_keys(
            (overview, level, "rasters/other/source.ovr.tif")
        )
        assert live == {overview, level}
    finally:
        await _purge_vrt(test_db_session, ids=ids)


async def _overview_rows(session, dataset_id) -> list[int]:
    from sqlalchemy import text

    result = await session.execute(
        text(
            "SELECT size_bytes FROM catalog.dataset_assets "
            "WHERE dataset_id = :id AND key = 'vrt_overview'"
        ),
        {"id": dataset_id},
    )
    return [row[0] for row in result.all()]


async def _create_vrt(session, storage, admin_id):
    from tests.test_raster_replace_1221 import _make_live_raster, _run_vrt_creation

    member = await _make_live_raster(session, storage, created_by=admin_id)
    vrt_id, record_id = await _run_vrt_creation(
        session, storage, member=member, user_id=admin_id
    )
    return member, vrt_id, record_id


async def _admin(session):
    from sqlalchemy import select

    from app.modules.auth.models import User

    return (
        await session.execute(select(User.id).where(User.username == "admin"))
    ).scalar_one()


async def _cleanup(session, member, vrt_id, record_id) -> None:
    from tests.test_raster_replace_1221 import _purge_vrt

    await _purge_vrt(
        session,
        ids=(vrt_id, record_id, member.dataset.id, member.dataset.record_id),
    )


@pytest.mark.anyio
@needs_gdal_cli
async def test_a_vrt_overview_is_recorded_and_counted(
    client, admin_auth_header, test_db_session, raster_storage, monkeypatch
) -> None:
    from app.modules.quota.service import get_user_quota_usage

    monkeypatch.setattr(
        "app.processing.ingest.tasks_vrt.get_storage", lambda: raster_storage
    )
    admin_id = await _admin(test_db_session)
    before = (await get_user_quota_usage(test_db_session, admin_id)).bytes_used
    member, vrt_id, record_id = await _create_vrt(
        test_db_session, raster_storage, admin_id
    )
    try:
        sizes = await _overview_rows(test_db_session, vrt_id)
        assert len(sizes) == 1 and sizes[0] > 0
        after = (await get_user_quota_usage(test_db_session, admin_id)).bytes_used
        assert after - before >= sizes[0]
    finally:
        await _cleanup(test_db_session, member, vrt_id, record_id)


@pytest.mark.anyio
@needs_gdal_cli
async def test_an_overview_over_the_cap_is_dropped_and_the_vrt_still_publishes(
    client, admin_auth_header, test_db_session, raster_storage, monkeypatch
) -> None:
    from sqlalchemy import select

    from app.modules.quota.service import get_user_quota_usage
    from app.processing.raster.models import RasterAsset
    from tests.test_raster_replace_1221 import _capped, _make_live_raster

    monkeypatch.setattr(
        "app.processing.ingest.tasks_vrt.get_storage", lambda: raster_storage
    )
    admin_id = await _admin(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    used = (await get_user_quota_usage(test_db_session, admin_id)).bytes_used
    from tests.test_raster_replace_1221 import _run_vrt_creation

    vrt_id = record_id = None
    try:
        with _capped(storage_cap=used + 10):
            vrt_id, record_id = await _run_vrt_creation(
                test_db_session, raster_storage, member=member, user_id=admin_id
            )
        asset = (
            await test_db_session.execute(
                select(RasterAsset).where(RasterAsset.dataset_id == vrt_id)
            )
        ).scalar_one()
        assert asset.status == "ready"
        assert await _overview_rows(test_db_session, vrt_id) == []
        assert not await raster_storage.exists(overview_key_for(asset.asset_uri))
    finally:
        if vrt_id is not None:
            await _cleanup(test_db_session, member, vrt_id, record_id)


@pytest.mark.anyio
@needs_gdal_cli
async def test_regeneration_replaces_the_overview_row(
    client, admin_auth_header, test_db_session, raster_storage, monkeypatch
) -> None:
    from io import BytesIO

    from sqlalchemy import text

    from tests.test_raster_replace_1221 import (
        _make_live_raster,
        _make_vrt_parent,
        _purge_vrt,
        _run_regeneration,
    )

    monkeypatch.setattr(
        "app.processing.ingest.tasks_vrt.get_storage", lambda: raster_storage
    )
    admin_id = await _admin(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    parent = await _make_vrt_parent(
        test_db_session, raster_storage, created_by=admin_id, member=member
    )
    ids = (
        parent.dataset.id,
        parent.dataset.record_id,
        member.dataset.id,
        member.dataset.record_id,
    )
    stale_href = f"rasters/{ids[0]}/older-release/source.ovr.tif"
    await raster_storage.put(stale_href, BytesIO(b"stale"))
    await test_db_session.execute(
        text(
            "INSERT INTO catalog.dataset_assets (dataset_id, key, href, size_bytes) "
            "VALUES (:id, 'vrt_overview', :href, 1)"
        ),
        {"id": ids[0], "href": stale_href},
    )
    await test_db_session.commit()
    try:
        await _run_regeneration(test_db_session, parent=parent, user_id=admin_id)
        test_db_session.expire_all()
        sizes = await _overview_rows(test_db_session, ids[0])
        assert len(sizes) == 1 and sizes[0] > 1
        assert not await raster_storage.exists(stale_href)
    finally:
        await _purge_vrt(test_db_session, ids=ids)


def _band_stack(tmp_path: Path, nodata: tuple[int, int]) -> tuple[str, list[str]]:
    members = []
    for index, value in enumerate(nodata):
        path = tmp_path / f"band{index}.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            dtype="uint8",
            width=100,
            height=100,
            count=1,
            crs="EPSG:4326",
            transform=from_origin(0.0, 10.0, 0.001, 0.001),
            nodata=value,
        ) as dst:
            dst.write(np.full((100, 100), 5, dtype="uint8"), 1)
        members.append(str(path))
    vrt_path = str(tmp_path / "stack.vrt")
    build_vrt("band_stack", members, vrt_path, "finest")
    return vrt_path, members


@needs_gdal_cli
def test_bands_with_different_nodata_get_no_overview(tmp_path: Path) -> None:
    vrt_path, members = _band_stack(tmp_path, (0, 255))
    before = Path(vrt_path).read_bytes()

    assert add_vrt_overview(vrt_path, members) is None

    assert Path(vrt_path).read_bytes() == before


@needs_gdal_cli
def test_bands_with_the_same_nodata_still_get_an_overview(tmp_path: Path) -> None:
    vrt_path, members = _band_stack(tmp_path, (0, 0))

    assert add_vrt_overview(vrt_path, members) is not None


@needs_gdal_cli
def test_a_masked_mosaic_gets_no_overview(tmp_path: Path) -> None:
    members = []
    for index in range(2):
        path = tmp_path / f"m{index}.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            dtype="uint8",
            width=100,
            height=100,
            count=1,
            crs="EPSG:4326",
            transform=from_origin(index * 0.1, 10.0, 0.001, 0.001),
        ) as dst:
            dst.write(np.full((100, 100), 5, dtype="uint8"), 1)
            dst.write_mask(np.full((100, 100), 255, dtype="uint8"))
        members.append(str(path))
    vrt_path = str(tmp_path / "masked.vrt")
    build_vrt("mosaic", members, vrt_path, "finest")
    assert parse(vrt_path).getroot().find(".//MaskBand") is not None

    assert add_vrt_overview(vrt_path, members) is None
    assert not (tmp_path / "masked.ovr.tif").exists()


@pytest.mark.anyio
@needs_gdal_cli
async def test_the_overview_build_runs_under_the_scratch_root(
    client, admin_auth_header, test_db_session, raster_storage, monkeypatch, tmp_path
) -> None:
    from app.processing.ingest import tasks_vrt
    from tests.test_raster_replace_1221 import (
        _make_live_raster,
        _make_vrt_parent,
        _purge_vrt,
        _run_regeneration,
    )

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tasks_vrt, "_scratch_dir", lambda: str(scratch))
    monkeypatch.setattr(
        "app.processing.ingest.tasks_vrt.get_storage", lambda: raster_storage
    )
    built_in: list[str] = []
    real = tasks_vrt.add_vrt_overview

    def _spy(vrt_path, source_paths):
        built_in.append(vrt_path)
        return real(vrt_path, source_paths)

    monkeypatch.setattr(tasks_vrt, "add_vrt_overview", _spy)
    admin_id = await _admin(test_db_session)
    member = await _make_live_raster(
        test_db_session, raster_storage, created_by=admin_id
    )
    parent = await _make_vrt_parent(
        test_db_session, raster_storage, created_by=admin_id, member=member
    )
    ids = (
        parent.dataset.id,
        parent.dataset.record_id,
        member.dataset.id,
        member.dataset.record_id,
    )
    try:
        await _run_regeneration(test_db_session, parent=parent, user_id=admin_id)
        assert built_in and built_in[0].startswith(str(scratch))
    finally:
        await _purge_vrt(test_db_session, ids=ids)


def _big_member(
    path: Path, values: tuple[int, int] = (0, 200), size: int = 2048
) -> str:
    rng = np.random.default_rng(7)
    data = np.where(rng.random((size, size)) > 0.5, values[1], values[0]).astype(
        "uint8"
    )
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        dtype="uint8",
        width=size,
        height=size,
        count=1,
        crs="EPSG:4326",
        transform=from_origin(0.0, 10.0, 0.005, 0.005),
        tiled=True,
        blockxsize=256,
        blockysize=256,
    ) as dst:
        dst.write(data, 1)
    return str(path)


@needs_gdal_cli
def test_integer_classes_keep_their_values_in_every_overview_level(
    tmp_path: Path,
) -> None:
    members = [_big_member(tmp_path / "classes.tif")]
    vrt_path = str(tmp_path / "source.vrt")
    build_vrt("mosaic", members, vrt_path, "finest")

    overview_path = add_vrt_overview(vrt_path, members)[0]

    with rasterio.open(overview_path) as cog:
        levels = cog.overviews(1)
        assert levels
        assert set(np.unique(cog.read(1))) <= {0, 200}
        for level in levels:
            shape = (cog.height // level, cog.width // level)
            assert set(np.unique(cog.read(1, out_shape=shape))) <= {0, 200}


@needs_gdal_cli
def test_bands_with_different_data_types_get_no_overview(tmp_path: Path) -> None:
    members = []
    for index, dtype in enumerate(("uint8", "float32")):
        path = tmp_path / f"t{index}.tif"
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            dtype=dtype,
            width=100,
            height=100,
            count=1,
            crs="EPSG:4326",
            transform=from_origin(0.0, 10.0, 0.001, 0.001),
        ) as dst:
            dst.write(np.full((100, 100), 5, dtype=dtype), 1)
        members.append(str(path))
    vrt_path = str(tmp_path / "stack.vrt")
    build_vrt("band_stack", members, vrt_path, "finest")
    before = Path(vrt_path).read_bytes()

    assert add_vrt_overview(vrt_path, members) is None

    assert Path(vrt_path).read_bytes() == before


@needs_gdal_cli
def test_a_reprojected_read_picks_a_coarse_overview_level(tmp_path: Path) -> None:
    from rasterio.vrt import WarpedVRT

    members = [_big_member(tmp_path / "classes.tif", size=4096)]
    vrt_path = str(tmp_path / "source.vrt")
    build_vrt("mosaic", members, vrt_path, "finest")
    paths = add_vrt_overview(vrt_path, members)
    assert [Path(p).name for p in paths] == [
        "source.ovr.tif",
        "source.ovr4.tif",
        "source.ovr8.tif",
    ]
    for value, path in zip((10, 20, 30), paths, strict=True):
        with rasterio.open(path, "r+", IGNORE_COG_LAYOUT_BREAK="YES") as level:
            level.write(np.full((level.height, level.width), value, dtype="uint8"), 1)

    with _titiler_env(), rasterio.open(vrt_path) as src:
        assert src.overviews(1) == [2, 4, 8]
        with WarpedVRT(src, crs="EPSG:3857") as warped:
            reduced = warped.read(
                1, out_shape=(warped.height // 16, warped.width // 16)
            )
    assert set(np.unique(reduced)) <= {0, 30}
    assert 30 in set(np.unique(reduced))


def test_an_unreadable_member_counts_as_lacking_overviews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.processing.raster import probe
    from app.processing.raster.vrt import members_lack_overviews

    def _unreadable(path):
        raise probe.RasterProbeError("open", timeout=1.0)

    monkeypatch.setattr(probe, "read_raster_metadata", _unreadable)

    assert members_lack_overviews(["/missing.tif"]) is True


@needs_gdal_cli
def test_a_failed_vrt_rewrite_leaves_the_vrt_and_no_overview_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vrt_path, members = _vrt(tmp_path, overviews=False)
    before = Path(vrt_path).read_bytes()

    def _full_disk(src, dst):
        raise OSError("no space left on device")

    monkeypatch.setattr("app.processing.raster.vrt.os.replace", _full_disk)

    assert add_vrt_overview(vrt_path, members) is None
    assert Path(vrt_path).read_bytes() == before
    assert (
        sorted(
            p.name for p in tmp_path.iterdir() if "ovr" in p.name or "staged" in p.name
        )
        == []
    )


@needs_gdal_cli
def test_an_overview_larger_than_the_free_space_is_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from collections import namedtuple

    vrt_path, members = _vrt(tmp_path, overviews=False)
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(
        "app.processing.raster.vrt.shutil.disk_usage",
        lambda path: usage(10, 10, 10),
    )

    assert add_vrt_overview(vrt_path, members) is None
    assert not any("ovr" in p.name for p in tmp_path.iterdir())


@pytest.mark.anyio
@needs_gdal_cli
async def test_a_reservation_refused_before_hashing_publishes_without_an_overview(
    client, admin_auth_header, test_db_session, raster_storage, monkeypatch
) -> None:
    from sqlalchemy import select

    from app.modules.quota import service
    from app.modules.quota.service import StorageQuotaExceededError
    from app.processing.raster.models import RasterAsset

    monkeypatch.setattr(
        "app.processing.ingest.tasks_vrt.get_storage", lambda: raster_storage
    )
    real = service.reserve_storage_bytes
    calls: list[int] = []

    async def _refuse_once(db, user_id, incoming):
        calls.append(incoming)
        if len(calls) == 1:
            raise StorageQuotaExceededError("a concurrent upload took the room")
        await real(db, user_id, incoming)

    monkeypatch.setattr(service, "reserve_storage_bytes", _refuse_once)
    admin_id = await _admin(test_db_session)
    member, vrt_id, record_id = await _create_vrt(
        test_db_session, raster_storage, admin_id
    )
    try:
        asset = (
            await test_db_session.execute(
                select(RasterAsset).where(RasterAsset.dataset_id == vrt_id)
            )
        ).scalar_one()
        assert asset.status == "ready"
        assert await _overview_rows(test_db_session, vrt_id) == []
        stored = (await raster_storage.get(asset.asset_uri)).decode()
        assert "<Overview>" not in stored
    finally:
        await _cleanup(test_db_session, member, vrt_id, record_id)
