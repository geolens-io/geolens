"""STAC items offer a stored raster's data files only to callers the COG download route serves.

A key on local or Azure storage has no URL of its own, so the ``data`` asset
points at the COG download route and the quicklooks at the quicklook route; on
S3 each is a signed URL. Anonymous callers get public datasets, authenticated
ones also need the export capability. The Azure cases run on the test's local
store: neither can sign a URL, and both serve an object's bytes to those routes.

Requirements: the test database (``set -a && source ../.env.test && set +a``).
"""

import copy
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

import app.modules.catalog.authorization as authorization
import app.standards.stac.router as stac_router
from app.core.config import settings
from app.modules.auth.permissions import DEFAULT_ROLE_PERMISSIONS
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.platform.storage.provider import get_storage
from app.processing.raster.models import DatasetAsset, RasterAsset

from tests.factories import create_raster_dataset, get_user_id

pytestmark = pytest.mark.anyio


class _FakeS3Provider:
    def generate_presigned_get_url(self, key: str, expiration: int = 3600) -> str:
        return f"https://s3.example.com/{key}?sig=abc"


def _use_s3(monkeypatch) -> None:
    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr(stac_router, "get_storage", _FakeS3Provider)


@pytest.fixture
async def viewer_without_export(client: AsyncClient, admin_auth_header: dict):
    matrix = copy.deepcopy(DEFAULT_ROLE_PERMISSIONS)
    matrix["viewer"]["export"] = False
    resp = await client.put(
        "/settings/",
        json={"settings": {"role_permissions": matrix}},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    yield
    resp = await client.post(
        "/settings/reset/",
        json={"keys": ["role_permissions"]},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text


async def _published_raster_with_assets(
    session, record_type: str = "raster_dataset"
) -> str:
    admin_id = await get_user_id(session, "admin")
    dataset = await create_raster_dataset(
        session,
        created_by=admin_id,
        name="STAC local COG assets",
        visibility="public",
        record_status="published",
        record_type=record_type,
        create_raster_asset=True,
    )
    base = f"rasters/{dataset.id}/abc"
    primary = (
        ("vrt", f"{base}/source.vrt", "application/xml")
        if record_type == "vrt_dataset"
        else ("data", f"{base}/source.cog.tif", "image/tiff; application=geotiff")
    )
    for key, href, media_type in (
        primary,
        ("thumbnail", f"{base}/quicklook_256.png", "image/png"),
        ("overview", f"{base}/quicklook_512.png", "image/png"),
    ):
        session.add(
            DatasetAsset(
                dataset_id=dataset.id,
                key=key,
                href=href,
                media_type=media_type,
                roles=["data" if key == "vrt" else key],
            )
        )
    await session.commit()
    return str(dataset.id)


async def _page_of_one_raster(client, session, surface: str, headers: dict) -> dict:
    dataset_id = await _published_raster_with_assets(session)
    if surface == "search":
        resp = await client.get(
            "/stac/search", params={"ids": dataset_id}, headers=headers
        )
    else:
        collection = Collection(name=f"STAC page {dataset_id}", description="Page")
        session.add(collection)
        await session.flush()
        session.add(
            CollectionDataset(
                collection_id=collection.id, dataset_id=uuid.UUID(dataset_id)
            )
        )
        await session.commit()
        resp = await client.get(
            f"/stac/collections/{collection.id}/items", headers=headers
        )
    assert resp.status_code == 200, resp.text
    [feature] = resp.json()["features"]
    assert feature["id"] == dataset_id
    return feature["assets"]


@pytest.mark.parametrize("backend", ["local", "azure"])
async def test_anonymous_item_points_at_the_serving_routes(
    client: AsyncClient, test_db_session, monkeypatch, backend: str
):
    dataset_id = await _published_raster_with_assets(test_db_session)
    monkeypatch.setattr(settings, "storage_provider", backend)

    resp = await client.get(f"/stac/items/{dataset_id}")

    assert resp.status_code == 200, resp.text
    assets = resp.json()["assets"]
    assert assets["data"]["href"].endswith(f"/datasets/{dataset_id}/download/cog")
    for key, size in (("thumbnail", 256), ("overview", 512)):
        href = assets[key]["href"]
        assert f"/datasets/{dataset_id}/quicklook?size={size}&" in href
        # Versioned like the tile template, so a replaced raster's images
        # are not served from the public cache.
        assert "pv=" in href
    assert not [a for a in assets.values() if "/assets/" in a["href"]]


@pytest.mark.parametrize("backend", ["local", "azure"])
async def test_item_links_serve_the_stored_files(
    client: AsyncClient, test_db_session, monkeypatch, backend: str
):
    dataset_id = await _published_raster_with_assets(test_db_session)
    cog_key = f"rasters/{dataset_id}/abc123/source.cog.tif"
    quicklook_key = f"rasters/{dataset_id}/abc/quicklook_256.png"
    await test_db_session.execute(
        update(RasterAsset)
        .where(RasterAsset.dataset_id == uuid.UUID(dataset_id))
        .values(asset_uri=cog_key, quicklook_256_uri=quicklook_key)
    )
    await test_db_session.commit()
    cog, png = b"II*\x00stored cog", b"\x89PNG\r\n\x1a\nstored quicklook"
    await get_storage().put(cog_key, cog)
    await get_storage().put(quicklook_key, png)
    monkeypatch.setattr(settings, "storage_provider", backend)

    item = await client.get(f"/stac/items/{dataset_id}")

    assert item.status_code == 200, item.text
    assets = item.json()["assets"]
    for key, body in (("data", cog), ("thumbnail", png)):
        href = assets[key]["href"]
        served = await client.get(href[href.index("/datasets/") :])
        assert served.status_code == 200, f"{key}: {served.text}"
        assert served.content == body


@pytest.mark.parametrize("backend", ["local", "azure"])
async def test_ogc_record_points_at_the_quicklook_route_without_data(
    client: AsyncClient, test_db_session, monkeypatch, backend: str
):
    dataset_id = await _published_raster_with_assets(test_db_session)
    monkeypatch.setattr(settings, "storage_provider", backend)

    resp = await client.get(f"/collections/datasets/items/{dataset_id}")

    assert resp.status_code == 200, resp.text
    assets = resp.json()["assets"]
    for key, size in (("thumbnail", 256), ("overview", 512)):
        assert f"/datasets/{dataset_id}/quicklook?size={size}&" in assets[key]["href"]
    # The record carries no per-caller download check, so it never offers data.
    assert "data" not in assets
    assert not [a for a in assets.values() if "source.cog.tif" in a["href"]]


async def test_anonymous_item_of_a_public_raster_on_s3_signs_data(
    client: AsyncClient, test_db_session, monkeypatch
):
    dataset_id = await _published_raster_with_assets(test_db_session)
    _use_s3(monkeypatch)

    resp = await client.get(f"/stac/items/{dataset_id}")

    assert resp.status_code == 200, resp.text
    assets = resp.json()["assets"]
    base = f"https://s3.example.com/rasters/{dataset_id}/abc"
    assert assets["data"]["href"] == f"{base}/source.cog.tif?sig=abc"
    assert assets["thumbnail"]["href"] == f"{base}/quicklook_256.png?sig=abc"


async def test_reader_with_export_on_s3_gets_signed_data(
    client: AsyncClient, test_db_session, viewer_auth_header: dict, monkeypatch
):
    dataset_id = await _published_raster_with_assets(test_db_session)
    _use_s3(monkeypatch)

    resp = await client.get(f"/stac/items/{dataset_id}", headers=viewer_auth_header)

    assert resp.status_code == 200, resp.text
    assert resp.json()["assets"]["data"]["href"] == (
        f"https://s3.example.com/rasters/{dataset_id}/abc/source.cog.tif?sig=abc"
    )


async def test_vrt_item_on_s3_omits_the_vrt_file_even_with_export(
    client: AsyncClient, test_db_session, admin_auth_header: dict, monkeypatch
):
    dataset_id = await _published_raster_with_assets(
        test_db_session, record_type="vrt_dataset"
    )
    _use_s3(monkeypatch)

    resp = await client.get(f"/stac/items/{dataset_id}", headers=admin_auth_header)

    assert resp.status_code == 200, resp.text
    assets = resp.json()["assets"]
    assert "vrt" not in assets
    assert not [a for a in assets.values() if "source.vrt" in a["href"]]
    assert assets["overview"]["href"] == (
        f"https://s3.example.com/rasters/{dataset_id}/abc/quicklook_512.png?sig=abc"
    )


@pytest.mark.parametrize("backend", ["local", "s3", "azure"])
async def test_reader_without_export_gets_no_data_asset(
    client: AsyncClient,
    test_db_session,
    viewer_auth_header: dict,
    viewer_without_export,
    monkeypatch,
    backend: str,
):
    dataset_id = await _published_raster_with_assets(test_db_session)
    if backend == "s3":
        _use_s3(monkeypatch)
    else:
        monkeypatch.setattr(settings, "storage_provider", backend)

    resp = await client.get(f"/stac/items/{dataset_id}", headers=viewer_auth_header)
    assert resp.status_code == 200, resp.text
    assets = resp.json()["assets"]
    assert "data" not in assets
    assert "thumbnail" in assets
    assert "overview" in assets
    assert not [a for a in assets.values() if "source.cog.tif" in a["href"]]

    cog = await client.get(
        f"/datasets/{dataset_id}/download/cog", headers=viewer_auth_header
    )
    assert cog.status_code == 403


@pytest.mark.parametrize("surface", ["collection_items", "search"])
async def test_s3_pages_withhold_data_from_a_reader_without_export(
    client: AsyncClient,
    test_db_session,
    viewer_auth_header: dict,
    viewer_without_export,
    monkeypatch,
    surface: str,
):
    _use_s3(monkeypatch)

    assets = await _page_of_one_raster(
        client, test_db_session, surface, viewer_auth_header
    )

    assert "data" not in assets
    assert assets["thumbnail"]["href"].startswith("https://s3.example.com/")
    assert not [a for a in assets.values() if "source.cog.tif" in a["href"]]


@pytest.mark.parametrize("surface", ["collection_items", "search"])
async def test_s3_pages_sign_data_for_a_reader_with_export(
    client: AsyncClient,
    test_db_session,
    viewer_auth_header: dict,
    monkeypatch,
    surface: str,
):
    _use_s3(monkeypatch)

    assets = await _page_of_one_raster(
        client, test_db_session, surface, viewer_auth_header
    )

    assert assets["data"]["href"].startswith("https://s3.example.com/rasters/")
    assert assets["data"]["href"].endswith("/abc/source.cog.tif?sig=abc")


async def test_a_page_resolves_the_export_capability_once(
    client: AsyncClient, test_db_session, viewer_auth_header: dict, monkeypatch
):
    ids = [await _published_raster_with_assets(test_db_session) for _ in range(3)]
    reads = 0
    original = authorization.get_effective_permissions

    async def _counting_read(db):
        nonlocal reads
        reads += 1
        return await original(db)

    monkeypatch.setattr(authorization, "get_effective_permissions", _counting_read)

    resp = await client.get(
        "/stac/search", params={"ids": ",".join(ids)}, headers=viewer_auth_header
    )

    assert resp.status_code == 200, resp.text
    features = resp.json()["features"]
    assert len(features) == 3
    assert all("data" in feature["assets"] for feature in features)
    assert reads == 1


async def test_a_page_without_rasters_skips_the_export_capability(
    client: AsyncClient, viewer_auth_header: dict, monkeypatch
):
    reads = 0
    original = authorization.get_effective_permissions

    async def _counting_read(db):
        nonlocal reads
        reads += 1
        return await original(db)

    monkeypatch.setattr(authorization, "get_effective_permissions", _counting_read)

    resp = await client.get(
        "/stac/search", params={"ids": str(uuid.uuid4())}, headers=viewer_auth_header
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["features"] == []
    assert reads == 0
