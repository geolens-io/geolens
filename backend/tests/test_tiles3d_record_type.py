"""A tiles3d_dataset row is stored, searchable and counted, with no capability or vector export."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.record_types import capabilities
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.quota.service import get_user_quota_usage, get_user_quota_usage_bulk


async def _owned_dataset(
    session, record_type: str, source_format: str, geometry_type: str | None
):
    """Commit a published public dataset of *record_type*, owned by a new user."""
    owner = User(username=f"tiles3d-{uuid.uuid4().hex[:8]}", password_hash="x")
    session.add(owner)
    await session.flush()
    record = Record(
        title=f"{record_type} {uuid.uuid4().hex[:8]}",
        record_type=record_type,
        visibility="public",
        record_status="published",
        created_by=owner.id,
    )
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"t3d_{uuid.uuid4().hex[:12]}",
        source_format=source_format,
        geometry_type=geometry_type,
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset, ["record"])
    return dataset, record.id, owner.id


async def _remove(session, record_id, owner_id) -> None:
    await session.rollback()
    await session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
    )
    await session.execute(
        text("DELETE FROM catalog.users WHERE id = :id"), {"id": owner_id}
    )
    await session.commit()


@pytest.fixture
async def tiles3d_dataset(test_db_session):
    """A published public tileset, inserted directly with the new values."""
    dataset, record_id, owner_id = await _owned_dataset(
        test_db_session, "tiles3d_dataset", "3dtiles", None
    )
    yield dataset
    # A committed tiles3d row blocks every later downgrade past 0065 in this
    # worker's database (see tests/alembic_helpers.py).
    await _remove(test_db_session, record_id, owner_id)


@pytest.fixture
async def vector_dataset(test_db_session):
    """A published public vector dataset, inserted the same way."""
    dataset, record_id, owner_id = await _owned_dataset(
        test_db_session, "vector_dataset", "geojson", "POLYGON"
    )
    yield dataset
    await _remove(test_db_session, record_id, owner_id)


async def test_a_stored_tileset_has_no_capability(tiles3d_dataset) -> None:
    """The stored row keeps both new values and gets the closed capability record."""
    assert tiles3d_dataset.source_format == "3dtiles"
    caps = capabilities(tiles3d_dataset.record.record_type)
    assert tiles3d_dataset.record.record_type == "tiles3d_dataset"
    assert caps.feature_table is False
    assert caps.map_layer_type is None
    assert caps.tile_token is None
    assert caps.ogc_item_type is None


async def test_quota_counts_a_tileset_as_a_dataset(
    test_db_session, tiles3d_dataset
) -> None:
    """Both quota aggregates count the tileset toward its owner's datasets."""
    owner_id = tiles3d_dataset.record.created_by

    single = await get_user_quota_usage(test_db_session, owner_id)
    bulk = await get_user_quota_usage_bulk(test_db_session, [owner_id])

    assert single.dataset_count == 1
    assert bulk[owner_id] == single


async def test_search_filters_and_counts_tilesets(
    client: AsyncClient, admin_auth_header: dict, tiles3d_dataset
) -> None:
    """The record_type filter accepts tiles3d_dataset and the facets count it."""
    resp = await client.get(
        "/search/datasets/",
        params={"record_type": "tiles3d_dataset"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert str(tiles3d_dataset.id) in [f["id"] for f in resp.json()["features"]]

    facets = await client.get("/search/facets/", headers=admin_auth_header)
    assert facets.status_code == 200, facets.text
    assert facets.json()["record_type"]["tiles3d_dataset"] >= 1


async def test_only_a_feature_table_advertises_vector_exports(
    client: AsyncClient, admin_auth_header: dict, tiles3d_dataset, vector_dataset
) -> None:
    """A vector record lists the seven vector exports; a tileset's lists none."""
    vector = await client.get(
        f"/collections/datasets/items/{vector_dataset.id}", headers=admin_auth_header
    )
    tileset = await client.get(
        f"/collections/datasets/items/{tiles3d_dataset.id}", headers=admin_auth_header
    )
    assert vector.status_code == 200, vector.text
    assert tileset.status_code == 200, tileset.text

    assert len(vector.json()["properties"]["formats"]) == 7
    assert "download_gpkg" in vector.json()["assets"]
    assert tileset.json()["properties"]["formats"] == []
    vector_assets = {"vector_tiles", "ogc_features"}
    assert not [
        key
        for key in tileset.json()["assets"]
        if key.startswith("download_") or key in vector_assets
    ]
