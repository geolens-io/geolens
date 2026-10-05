"""A dataset quicklook is publicly cacheable only when the dataset is public and published.

A public vector quicklook is redrawn under the same URL when its data is
replaced, so caches revalidate it by ETag; a raster's keeps an hour in a browser
and a minute in a shared cache.
"""

import hashlib
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.modules.catalog.datasets.api.router as datasets_router
from app.core.config import settings
from app.modules.auth.models import Role
from app.modules.catalog.datasets.domain.models import Dataset, DatasetGrant
from app.modules.catalog.maps.models import Map, MapLayer
from tests.factories import create_dataset, create_raster_dataset, get_user_id

pytestmark = pytest.mark.anyio

PNG = b"\x89PNG\r\n\x1a\nquicklook"
PNG_ETAG = '"' + hashlib.sha256(PNG).hexdigest() + '"'
PUBLIC = "public, no-cache"
PUBLIC_RASTER = "public, max-age=3600, s-maxage=60"
PRIVATE = "private, no-store"


class _Storage:
    async def get(self, key: str) -> bytes:
        return PNG


@pytest.fixture(autouse=True)
def _stored_quicklook(monkeypatch):
    monkeypatch.setattr(datasets_router, "get_storage", _Storage)


async def _dataset_with_quicklook(
    session, *, visibility: str, record_status: str = "published"
) -> Dataset:
    owner = await get_user_id(session, settings.geolens_admin_username)
    dataset = await create_dataset(
        session,
        created_by=owner,
        name=f"Quicklook {uuid.uuid4().hex[:8]}",
        visibility=visibility,
        record_status=record_status,
    )
    dataset.quicklook_256_uri = f"vectors/{dataset.id}/quicklook_256.png"
    await session.commit()
    return dataset


async def _api_key(client: AsyncClient, headers: dict) -> str:
    resp = await client.post(
        "/auth/api-keys/", json={"name": "quicklook"}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["key"]


def _cache_control(resp) -> str:
    assert resp.status_code == 200, resp.text
    assert resp.content == PNG
    return resp.headers["cache-control"]


async def test_a_public_published_dataset_is_publicly_cacheable(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    dataset = await _dataset_with_quicklook(test_db_session, visibility="public")

    anonymous = await client.get(f"/datasets/{dataset.id}/quicklook")
    signed_in = await client.get(
        f"/datasets/{dataset.id}/quicklook", headers=admin_auth_header
    )

    assert _cache_control(anonymous) == PUBLIC
    assert _cache_control(signed_in) == PUBLIC
    assert anonymous.headers["etag"] == signed_in.headers["etag"] == PNG_ETAG


async def test_a_held_public_vector_quicklook_is_not_sent_again(
    client: AsyncClient, test_db_session
):
    dataset = await _dataset_with_quicklook(test_db_session, visibility="public")

    resp = await client.get(
        f"/datasets/{dataset.id}/quicklook", headers={"If-None-Match": PNG_ETAG}
    )

    assert resp.status_code == 304
    assert resp.content == b""
    assert resp.headers["etag"] == PNG_ETAG
    assert resp.headers["cache-control"] == PUBLIC


async def test_a_public_raster_quicklook_stays_fresh_for_an_hour(
    client: AsyncClient, test_db_session
):
    owner = await get_user_id(test_db_session, settings.geolens_admin_username)
    dataset = await create_raster_dataset(
        test_db_session,
        created_by=owner,
        name=f"Raster quicklook {uuid.uuid4().hex[:8]}",
        create_raster_asset=True,
        raster_asset_kwargs={"quicklook_256_uri": "rasters/x/quicklook_256.png"},
    )

    resp = await client.get(
        f"/datasets/{dataset.id}/quicklook", headers={"If-None-Match": PNG_ETAG}
    )

    assert _cache_control(resp) == PUBLIC_RASTER
    assert "etag" not in resp.headers


@pytest.mark.parametrize(
    "visibility,record_status",
    [
        ("private", "published"),
        ("internal", "published"),
        ("restricted", "published"),
        ("public", "draft"),
    ],
)
async def test_a_dataset_anyone_may_not_fetch_is_private(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    visibility: str,
    record_status: str,
):
    dataset = await _dataset_with_quicklook(
        test_db_session, visibility=visibility, record_status=record_status
    )

    resp = await client.get(
        f"/datasets/{dataset.id}/quicklook", headers=admin_auth_header
    )

    assert _cache_control(resp) == PRIVATE


async def test_a_group_shared_dataset_is_private(
    client: AsyncClient, viewer_auth_header: dict, test_db_session
):
    dataset = await _dataset_with_quicklook(test_db_session, visibility="restricted")
    viewer_role = (
        await test_db_session.execute(select(Role).where(Role.name == "viewer"))
    ).scalar_one()
    test_db_session.add(DatasetGrant(dataset_id=dataset.id, role_id=viewer_role.id))
    await test_db_session.commit()

    resp = await client.get(
        f"/datasets/{dataset.id}/quicklook", headers=viewer_auth_header
    )

    assert _cache_control(resp) == PRIVATE


async def test_an_api_key_opens_a_private_quicklook_with_a_private_policy(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    dataset = await _dataset_with_quicklook(test_db_session, visibility="private")
    key = await _api_key(client, admin_auth_header)

    by_header = await client.get(
        f"/datasets/{dataset.id}/quicklook", headers={"X-Api-Key": key}
    )
    # The query-string key carries no Authorization header for a cache to see.
    by_query = await client.get(f"/datasets/{dataset.id}/quicklook?api_key={key}")

    assert _cache_control(by_header) == PRIVATE
    assert _cache_control(by_query) == PRIVATE


async def test_an_embed_token_opens_no_private_quicklook(
    client: AsyncClient, admin_auth_header: dict, test_db_session
):
    dataset = await _dataset_with_quicklook(test_db_session, visibility="private")
    owner = await get_user_id(test_db_session, settings.geolens_admin_username)
    map_obj = Map(name=f"Quicklook map {uuid.uuid4().hex[:6]}", created_by=owner)
    test_db_session.add(map_obj)
    await test_db_session.flush()
    test_db_session.add(
        MapLayer(map_id=map_obj.id, dataset_id=dataset.id, sort_order=0)
    )
    await test_db_session.commit()
    minted = await client.post(
        f"/maps/{map_obj.id}/embed-tokens/",
        json={"name": "quicklook"},
        headers=admin_auth_header,
    )
    assert minted.status_code == 201, minted.text
    assert str(dataset.id) in minted.json()["scoped_dataset_ids"]

    resp = await client.get(
        f"/datasets/{dataset.id}/quicklook",
        headers={"X-Embed-Token": minted.json()["raw_token"]},
    )

    assert resp.status_code == 404
