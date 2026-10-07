"""Tiles hand Titiler a relay address for a remote raster and refuse a mosaic naming one."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.platform.storage.provider import get_storage
from app.platform.storage.titiler_url import resolve_storage_key

from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.platform.storage.raster_relay import is_relay_url
from app.processing.raster.models import RasterAsset, VrtSourceLink
from app.processing.tiles import router as tile_router

from tests.factories import get_user_id

_REMOTE = "https://stac.example.com/scenes/{}.tif"


async def _raster(
    session,
    *,
    record_type: str = "raster_dataset",
    asset_uri: str | None = None,
    storage_backend: str = "local",
    built_from: dict | None = None,
    visibility: str = "public",
) -> Dataset:
    record = Record(
        title=f"Relay {uuid.uuid4().hex[:6]}",
        visibility=visibility,
        record_status="published",
        created_by=await get_user_id(session, "admin"),
        record_type=record_type,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"relay_{uuid.uuid4().hex[:8]}",
        srid=4326,
        source_format="stac" if storage_backend == "remote" else "geotiff",
    )
    session.add(dataset)
    await session.flush()
    session.add(
        RasterAsset(
            dataset_id=dataset.id,
            asset_uri=asset_uri or f"rasters/{dataset.id}/cog.tif",
            storage_backend=storage_backend,
            band_count=1,
            built_from=built_from,
        )
    )
    await session.commit()
    return dataset


async def _auth_check(client, dataset_id: uuid.UUID):
    return await client.get(
        "/tiles/raster-auth-check/", params={"dataset_id": str(dataset_id)}
    )


async def test_a_remote_raster_is_opened_through_the_relay(client, test_db_session):
    url = _REMOTE.format(uuid.uuid4().hex)
    dataset = await _raster(test_db_session, asset_uri=url, storage_backend="remote")

    titiler = AsyncMock()
    titiler.get.return_value = httpx.Response(
        200, content=b"\x89PNG", headers={"content-type": "image/png"}
    )

    with patch.object(tile_router, "_titiler_client", titiler):
        tile = await client.get(f"/tiles/raster-proxy/{dataset.id}/0/0/0.png")
    response = await _auth_check(client, dataset.id)

    assert tile.status_code == 200
    [called] = titiler.get.call_args_list
    source = httpx.URL(called.args[0]).params["url"]
    assert is_relay_url(source)
    assert "stac.example.com" not in source
    # The relay address is a capability: a caller of the check itself never sees it.
    assert response.status_code == 200
    assert "X-GeoLens-Asset-OpenPath" not in response.headers


async def test_a_managed_raster_keeps_its_storage_path(client, test_db_session):
    dataset = await _raster(test_db_session)

    response = await _auth_check(client, dataset.id)

    assert response.status_code == 200
    assert response.headers["X-GeoLens-Asset-OpenPath"].endswith(
        f"rasters/{dataset.id}/cog.tif"
    )


async def test_a_mosaic_built_from_a_remote_member_is_refused(client, test_db_session):
    member = uuid.uuid4()
    mosaic = await _raster(
        test_db_session,
        record_type="vrt_dataset",
        built_from={str(member): _REMOTE.format(member.hex)},
    )
    titiler = AsyncMock()

    with patch.object(tile_router, "_titiler_client", titiler):
        response = await _auth_check(client, mosaic.id)
        tile = await client.get(f"/tiles/raster-proxy/{mosaic.id}/0/0/0.png")

    assert response.status_code == 409
    assert tile.status_code == 409
    titiler.get.assert_not_called()


async def test_a_mosaic_linked_to_a_remote_member_is_refused(client, test_db_session):
    member = await _raster(
        test_db_session,
        asset_uri=_REMOTE.format(uuid.uuid4().hex),
        storage_backend="remote",
    )
    mosaic = await _raster(test_db_session, record_type="vrt_dataset")
    test_db_session.add(
        VrtSourceLink(vrt_dataset_id=mosaic.id, source_dataset_id=member.id)
    )
    await test_db_session.commit()

    response = await _auth_check(client, mosaic.id)

    assert response.status_code == 409


async def test_a_stranger_gets_404_not_409_for_a_private_mosaic(
    client, test_db_session, editor_auth_header
):
    member = uuid.uuid4()
    mosaic = await _raster(
        test_db_session,
        record_type="vrt_dataset",
        built_from={str(member): _REMOTE.format(member.hex)},
        visibility="private",
    )

    response = await client.get(
        "/tiles/raster-auth-check/",
        params={"dataset_id": str(mosaic.id)},
        headers=editor_auth_header,
    )

    assert response.status_code == 404


_MANAGED_SOURCE = """<SimpleSource>
      <SourceFilename relativeToVRT="1">../../m/cog.tif</SourceFilename>
    </SimpleSource>"""


def _simple_vrt(
    source: str,
    relative: bool = False,
    element: str = "SourceFilename",
    beside_a_managed_source: bool = False,
):
    managed = _MANAGED_SOURCE if beside_a_managed_source else ""
    return f"""<VRTDataset rasterXSize="64" rasterYSize="64">
  <VRTRasterBand dataType="Byte" band="1">
    {managed}
    <SimpleSource>
      <{element} relativeToVRT="{int(relative)}">{source}</{element}>
      <SourceBand>1</SourceBand>
    </SimpleSource>
  </VRTRasterBand>
</VRTDataset>"""


async def _unrecorded_mosaic(
    session, vrt: str, *, sql_null: bool = False, sha256: str | None = None
):
    """A mosaic from before build records, linked to a member that is now managed."""
    member = await _raster(session)
    mosaic = await _raster(
        session,
        record_type="vrt_dataset",
        asset_uri=f"rasters/{uuid.uuid4()}/{uuid.uuid4().hex}/mosaic.vrt",
    )
    session.add(VrtSourceLink(vrt_dataset_id=mosaic.id, source_dataset_id=member.id))
    # The ORM writes JSON null for None; a column added later reads SQL NULL.
    await session.execute(
        text(
            "UPDATE catalog.raster_assets SET sha256 = :sha, built_from = "
            + ("NULL" if sql_null else "'null'::jsonb")
            + " WHERE dataset_id = :d"
        ),
        {"d": mosaic.id, "sha": sha256},
    )
    await session.commit()
    asset_uri = (
        await session.execute(
            text("SELECT asset_uri FROM catalog.raster_assets WHERE dataset_id = :d"),
            {"d": mosaic.id},
        )
    ).scalar_one()
    await get_storage().put(resolve_storage_key(asset_uri), vrt.encode())
    return mosaic


_REMOTE_SOURCE = "/vsicurl/https://stac.example.com/scenes/a.tif"
_NAMESPACED = f"""<VRTDataset xmlns:g="urn:example" rasterXSize="64" rasterYSize="64">
  <VRTRasterBand dataType="Byte" band="1">
    {_MANAGED_SOURCE}
    <SimpleSource><g:SourceFilename>{_REMOTE_SOURCE}</g:SourceFilename></SimpleSource>
  </VRTRasterBand>
</VRTDataset>"""


@pytest.mark.parametrize(
    ("vrt", "sql_null"),
    [
        (_simple_vrt(_REMOTE_SOURCE), False),
        (_simple_vrt(_REMOTE_SOURCE), True),
        (
            _simple_vrt(
                _REMOTE_SOURCE, element="sourcefilename", beside_a_managed_source=True
            ),
            False,
        ),
        (
            _simple_vrt(
                _REMOTE_SOURCE, element="SOURCEFILENAME", beside_a_managed_source=True
            ),
            False,
        ),
        (_NAMESPACED, False),
        (
            _simple_vrt(
                _REMOTE_SOURCE, element="SourceDataset", beside_a_managed_source=True
            ),
            False,
        ),
        (_simple_vrt("../../../../etc/secret.tif", relative=True), False),
        (_simple_vrt("C:/data/secret.tif", relative=True), False),
        (_simple_vrt("..\\..\\secret.tif", relative=True), False),
        ('<VRTDataset rasterXSize="1" rasterYSize="1"/>', False),
    ],
    ids=[
        "remote",
        "remote-sql-null",
        "lower-case",
        "upper-case",
        "namespaced",
        "warped",
        "relative-escape",
        "drive-letter",
        "backslash",
        "no-source",
    ],
)
async def test_an_unrecorded_mosaic_naming_an_unmanaged_source_is_refused(
    client, test_db_session, vrt, sql_null
):
    mosaic = await _unrecorded_mosaic(test_db_session, vrt, sql_null=sql_null)

    response = await _auth_check(client, mosaic.id)

    assert response.status_code == 409


async def test_an_unrecorded_mosaic_of_managed_sources_renders(client, test_db_session):
    absolute = await _unrecorded_mosaic(
        test_db_session,
        _simple_vrt(f"{settings.upload_staging_dir}/rasters/m/cog.tif"),
    )
    relative = await _unrecorded_mosaic(
        test_db_session, _simple_vrt("../../m/cog.tif", relative=True)
    )

    assert (await _auth_check(client, absolute.id)).status_code == 200
    assert (await _auth_check(client, relative.id)).status_code == 200


async def test_a_storage_failure_is_unavailable_and_not_remembered(
    client, test_db_session, monkeypatch
):
    mosaic = await _unrecorded_mosaic(
        test_db_session,
        _simple_vrt("../../m/cog.tif", relative=True),
        sha256=uuid.uuid4().hex * 2,
    )
    storage = get_storage()
    real_get = storage.get
    calls = 0

    async def flaky_get(key):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("storage unavailable")
        return await real_get(key)

    monkeypatch.setattr(storage, "get", flaky_get)

    assert (await _auth_check(client, mosaic.id)).status_code == 503
    assert (await _auth_check(client, mosaic.id)).status_code == 200
    assert (await _auth_check(client, mosaic.id)).status_code == 200
    assert calls == 2


async def test_a_mosaic_of_managed_members_renders(client, test_db_session):
    member = await _raster(test_db_session)
    mosaic = await _raster(
        test_db_session,
        record_type="vrt_dataset",
        built_from={str(member.id): f"rasters/{member.id}/cog.tif"},
    )
    test_db_session.add(
        VrtSourceLink(vrt_dataset_id=mosaic.id, source_dataset_id=member.id)
    )
    await test_db_session.commit()

    response = await _auth_check(client, mosaic.id)

    assert response.status_code == 200


async def _import(client, headers, href: str):
    return await client.post(
        "/services/stac/import",
        json={
            "url": "https://stac.example.com/v1",
            "items": [
                {
                    "id": f"relay-{uuid.uuid4().hex[:8]}",
                    "collection": "scenes",
                    "title": "Relay import",
                    "data_asset_href": href,
                    "bbox": [-1, -1, 1, 1],
                    "epsg": 4326,
                }
            ],
            "visibility": "private",
        },
        headers=headers,
    )


async def _stored(session, href: str) -> int:
    return await session.scalar(
        text("SELECT count(*) FROM catalog.datasets WHERE source_url = :u"),
        {"u": href},
    )


async def test_a_remote_vrt_asset_is_refused_at_import(
    client, admin_auth_header, test_db_session
):
    href = f"https://stac.example.com/mosaics/{uuid.uuid4().hex}.vrt"

    with patch(
        "app.modules.catalog.sources.stac_router.validate_url_for_ssrf",
        AsyncMock(),
    ):
        response = await _import(client, admin_auth_header, href)

    assert response.status_code == 200
    [result] = response.json()["results"]
    assert result["status"] == "error"
    assert "GeoTIFF or COG" in result["error"]
    assert await _stored(test_db_session, href) == 0


async def test_an_asset_that_is_not_a_geotiff_is_refused_at_import(
    client, admin_auth_header, test_db_session
):
    href = _REMOTE.format(uuid.uuid4().hex)

    with (
        patch(
            "app.modules.catalog.sources.stac_router.validate_url_for_ssrf",
            AsyncMock(),
        ),
        patch(
            "app.modules.catalog.sources.stac_router.fetch_cog_info",
            AsyncMock(return_value={"not_geotiff": True}),
        ),
    ):
        response = await _import(client, admin_auth_header, href)

    [result] = response.json()["results"]
    assert result["status"] == "error"
    assert "GeoTIFF or COG" in result["error"]
    assert await _stored(test_db_session, href) == 0
