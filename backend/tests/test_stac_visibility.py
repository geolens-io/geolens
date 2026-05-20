"""Tests for STAC visibility filter coverage (Phase 1061 SEC-S01).

Mirrors test_ogc_public_access.py: anonymous users see only public+published
raster records; authenticated owners can see their own private records via
STAC item endpoints; non-owners cannot.

The STAC /stac/items/{item_id} endpoint uses Dataset.id (not record_id) as the
path parameter. Tests construct datasets directly with record_type="raster_dataset"
to ensure they are eligible for STAC (only raster_dataset / vrt_dataset are served).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.catalog.datasets.domain.models import Dataset, Record

from .conftest import _create_test_user
from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Factory helper — raster dataset eligible for STAC
# ---------------------------------------------------------------------------


async def _create_raster_dataset(
    session: AsyncSession,
    *,
    created_by: uuid.UUID,
    name: str = "STAC Visibility Test DS",
    visibility: str = "public",
    record_status: str = "published",
) -> Dataset:
    """Create a raster Record + Dataset pair directly (STAC requires raster_dataset type)."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Test raster dataset for STAC visibility: {name}",
        visibility=visibility,
        record_status=record_status,
        record_type="raster_dataset",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        source_format="geotiff",
        source_filename="test.tif",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Anonymous access — single item
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stac_item_no_auth_private_returns_404(
    client: AsyncClient,
    test_db_session: AsyncSession,
):
    """Anonymous GET /stac/items/{id} returns 404 for a private raster record."""
    admin_id = await get_user_id(test_db_session, "admin")
    priv = await _create_raster_dataset(
        test_db_session,
        created_by=admin_id,
        name="STAC Private Item",
        visibility="private",
    )
    resp = await client.get(f"/stac/items/{priv.id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_stac_item_no_auth_public_returns_200(
    client: AsyncClient,
    test_db_session: AsyncSession,
):
    """Anonymous GET /stac/items/{id} returns 200 for a public raster record."""
    admin_id = await get_user_id(test_db_session, "admin")
    pub = await _create_raster_dataset(
        test_db_session,
        created_by=admin_id,
        name="STAC Public Item",
        visibility="public",
    )
    resp = await client.get(f"/stac/items/{pub.id}")
    assert resp.status_code == 200
    body = resp.json()
    # STAC item id may be the dataset id or record id depending on serializer
    assert str(pub.id) in (body.get("id", ""), str(body.get("id", "")))


# ---------------------------------------------------------------------------
# Anonymous access — /stac/search
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stac_search_no_auth_excludes_private(
    client: AsyncClient,
    test_db_session: AsyncSession,
):
    """Anonymous GET /stac/search?ids=... does not return a private raster in features."""
    admin_id = await get_user_id(test_db_session, "admin")
    priv = await _create_raster_dataset(
        test_db_session,
        created_by=admin_id,
        name="STAC Search Private",
        visibility="private",
    )
    pub = await _create_raster_dataset(
        test_db_session,
        created_by=admin_id,
        name="STAC Search Public",
        visibility="public",
    )
    # Search by both ids — only the public one should appear
    resp = await client.get(f"/stac/search?ids={priv.id},{pub.id}&limit=10")
    assert resp.status_code == 200
    body = resp.json()
    feature_ids = [f["id"] for f in body.get("features", [])]
    assert str(priv.id) not in feature_ids
    assert str(pub.id) in feature_ids


# ---------------------------------------------------------------------------
# Anonymous access — /stac/collections/{coll_id}/items
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stac_collection_items_no_auth_excludes_private(
    client: AsyncClient,
    test_db_session: AsyncSession,
    admin_auth_header: dict,
):
    """Anonymous GET /stac/collections/{id}/items does not include private records."""
    from app.modules.catalog.collections.models import Collection, CollectionDataset

    admin_id = await get_user_id(test_db_session, "admin")

    # Create a STAC collection
    coll = Collection(name=f"Test STAC Vis Coll {uuid.uuid4().hex[:6]}", description="test")
    test_db_session.add(coll)
    await test_db_session.flush()

    priv = await _create_raster_dataset(
        test_db_session,
        created_by=admin_id,
        name="STAC Coll Private",
        visibility="private",
    )
    pub = await _create_raster_dataset(
        test_db_session,
        created_by=admin_id,
        name="STAC Coll Public",
        visibility="public",
    )

    # Add both to the collection
    test_db_session.add(CollectionDataset(collection_id=coll.id, dataset_id=priv.id))
    test_db_session.add(CollectionDataset(collection_id=coll.id, dataset_id=pub.id))
    await test_db_session.commit()

    resp = await client.get(f"/stac/collections/{coll.id}/items?limit=100")
    assert resp.status_code == 200
    body = resp.json()
    feature_ids = [f["id"] for f in body.get("features", [])]
    assert str(priv.id) not in feature_ids
    assert str(pub.id) in feature_ids


# ---------------------------------------------------------------------------
# Authenticated access — owner can read their own private record
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stac_item_owner_can_read_private(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
):
    """Authenticated owner GET /stac/items/{id} returns 200 for their own private raster."""
    # Create a user who owns a private dataset
    owner_headers, owner_id_str = await _create_test_user(
        client, admin_auth_header, "editor"
    )
    owner_id = uuid.UUID(owner_id_str)

    priv = await _create_raster_dataset(
        test_db_session,
        created_by=owner_id,
        name="STAC Owner Private",
        visibility="private",
    )

    # Owner can read their own private item
    resp = await client.get(f"/stac/items/{priv.id}", headers=owner_headers)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Authenticated access — non-owner cannot read a private record
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_stac_item_non_owner_cannot_read_private(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session: AsyncSession,
):
    """Non-owner GET /stac/items/{id} returns 404 for another user's private raster."""
    admin_id = await get_user_id(test_db_session, "admin")

    # Create a second user (the non-owner)
    other_headers, _ = await _create_test_user(client, admin_auth_header, "editor")

    # Dataset is owned by admin
    priv = await _create_raster_dataset(
        test_db_session,
        created_by=admin_id,
        name="STAC Non-Owner Private",
        visibility="private",
    )

    # Non-owner (other editor) cannot read it
    resp = await client.get(f"/stac/items/{priv.id}", headers=other_headers)
    assert resp.status_code == 404
