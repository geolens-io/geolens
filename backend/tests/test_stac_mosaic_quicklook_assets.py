"""A mosaic's STAC item and OGC record link its stored quicklooks through the quicklook route.

A mosaic has no ``dataset_assets`` rows for its quicklooks; they are named only
by its raster asset. The route is the one href it gets on every store, because
the route refuses a mosaic that reaches past one of its members.

Requirements: the test database (``set -a && source ../.env.test && set +a``).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

import app.standards.stac.router as stac_router
from app.core.config import settings
from app.modules.catalog.collections.models import Collection, CollectionDataset
from app.platform.storage.provider import get_storage
from app.processing.raster.models import DatasetAsset, RasterAsset

from tests.test_vrt_source_authz_1172 import (
    _create_raster_dataset,
    _create_vrt_dataset,
    _get_admin_id,
    _link_source,
    _make_editor,
)

pytestmark = pytest.mark.anyio

_PNG_256 = b"\x89PNG\r\n\x1a\nmosaic quicklook 256"
_PNG_512 = b"\x89PNG\r\n\x1a\nmosaic quicklook 512"


class _FakeS3Provider:
    def generate_presigned_get_url(self, key: str, expiration: int = 3600) -> str:
        return f"https://s3.example.com/{key}?sig=abc"


async def _mosaic(
    session,
    *,
    vrt_owner: uuid.UUID,
    member_owner: uuid.UUID,
    visibility: str = "public",
    member_visibility: str = "public",
) -> uuid.UUID:
    """A published mosaic of one member, with both quicklooks stored."""
    member = await _create_raster_dataset(
        session, created_by=member_owner, visibility=member_visibility
    )
    vrt_id = await _create_vrt_dataset(
        session, created_by=vrt_owner, visibility=visibility
    )
    await _link_source(session, vrt_id, member, 0)
    base = f"rasters/{vrt_id}/abc"
    await session.execute(
        update(RasterAsset)
        .where(RasterAsset.dataset_id == vrt_id)
        .values(
            quicklook_256_uri=f"{base}/quicklook_256.png",
            quicklook_512_uri=f"{base}/quicklook_512.png",
        )
    )
    await session.commit()
    await get_storage().put(f"{base}/quicklook_256.png", _PNG_256)
    await get_storage().put(f"{base}/quicklook_512.png", _PNG_512)
    return vrt_id


def _path(href: str) -> str:
    return href[href.index("/datasets/") :]


async def _assets(client, surface: str, vrt_id: uuid.UUID, session, headers=None):
    if surface == "stac_item":
        resp = await client.get(f"/stac/items/{vrt_id}", headers=headers)
    elif surface == "stac_search":
        resp = await client.get(
            "/stac/search", params={"ids": str(vrt_id)}, headers=headers
        )
    elif surface == "stac_collection_items":
        collection = Collection(name=f"Mosaic page {vrt_id}", description="Page")
        session.add(collection)
        await session.flush()
        session.add(CollectionDataset(collection_id=collection.id, dataset_id=vrt_id))
        await session.commit()
        resp = await client.get(
            f"/stac/collections/{collection.id}/items", headers=headers
        )
    else:
        resp = await client.get(
            f"/collections/datasets/items/{vrt_id}", headers=headers
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    if "features" in body:
        [body] = body["features"]
    assert body["id"] == str(vrt_id)
    return body["assets"]


@pytest.mark.parametrize(
    "surface",
    ["stac_item", "stac_search", "stac_collection_items", "ogc_record"],
)
async def test_a_mosaic_item_links_quicklooks_that_serve_png(
    client: AsyncClient, test_db_session, surface: str
):
    admin_id = await _get_admin_id(test_db_session)
    vrt_id = await _mosaic(test_db_session, vrt_owner=admin_id, member_owner=admin_id)

    assets = await _assets(client, surface, vrt_id, test_db_session)

    for key, size, body in (("thumbnail", 256, _PNG_256), ("overview", 512, _PNG_512)):
        asset = assets[key]
        assert f"/datasets/{vrt_id}/quicklook?size={size}&" in asset["href"]
        assert "pv=" in asset["href"]
        assert asset["type"] == "image/png"
        assert asset["roles"] == [key]
        served = await client.get(_path(asset["href"]))
        assert served.status_code == 200, served.text
        assert served.headers["content-type"] == "image/png"
        assert served.content == body


async def test_a_mosaic_links_only_the_quicklooks_it_has(
    client: AsyncClient, test_db_session
):
    admin_id = await _get_admin_id(test_db_session)
    vrt_id = await _mosaic(test_db_session, vrt_owner=admin_id, member_owner=admin_id)
    await test_db_session.execute(
        update(RasterAsset)
        .where(RasterAsset.dataset_id == vrt_id)
        .values(quicklook_512_uri=None)
    )
    await test_db_session.commit()

    assets = await _assets(client, "stac_item", vrt_id, test_db_session)

    assert "thumbnail" in assets
    assert "overview" not in assets


async def test_a_private_mosaic_thumbnail_answers_like_its_item(
    client: AsyncClient, test_db_session, admin_auth_header: dict
):
    admin_id = await _get_admin_id(test_db_session)
    vrt_id = await _mosaic(
        test_db_session,
        vrt_owner=admin_id,
        member_owner=admin_id,
        visibility="private",
        member_visibility="private",
    )

    assets = await _assets(
        client, "stac_item", vrt_id, test_db_session, headers=admin_auth_header
    )
    thumbnail = _path(assets["thumbnail"]["href"])

    assert (await client.get(f"/stac/items/{vrt_id}")).status_code == 404
    assert (await client.get(thumbnail)).status_code == 404
    owner = await client.get(thumbnail, headers=admin_auth_header)
    assert owner.status_code == 200, owner.text
    assert owner.content == _PNG_256


async def test_a_mosaic_wider_than_a_member_does_not_show_it_through_the_thumbnail(
    client: AsyncClient, test_db_session, admin_auth_header: dict, monkeypatch
):
    admin_id = await _get_admin_id(test_db_session)
    _, editor_id = await _make_editor(client, admin_auth_header)
    vrt_id = await _mosaic(
        test_db_session,
        vrt_owner=admin_id,
        member_owner=editor_id,
        member_visibility="private",
    )
    # A row that names the stored image must not become a signed URL either.
    test_db_session.add(
        DatasetAsset(
            dataset_id=vrt_id,
            key="thumbnail",
            href=f"rasters/{vrt_id}/abc/quicklook_256.png",
            media_type="image/png",
            roles=["thumbnail"],
        )
    )
    await test_db_session.commit()
    monkeypatch.setattr(settings, "storage_provider", "s3")
    monkeypatch.setattr(stac_router, "get_storage", _FakeS3Provider)

    assets = await _assets(client, "stac_item", vrt_id, test_db_session)

    assert "s3.example.com" not in str(assets)
    for key in ("thumbnail", "overview"):
        served = await client.get(_path(assets[key]["href"]))
        assert served.status_code == 409, served.text
        assert served.content != _PNG_256
