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

    overview_path = add_vrt_overview(vrt_path, members)

    assert overview_path == str(tmp_path / "source.ovr.tif")
    assert Path(overview_path).exists()
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
        live = await _live_referenced_storage_keys(
            (overview, "rasters/other/source.ovr.tif")
        )
        assert live == {overview}
    finally:
        await _purge_vrt(test_db_session, ids=ids)
