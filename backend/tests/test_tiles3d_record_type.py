"""A tiles3d_dataset row is stored, refused every capability, searchable and counted."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.record_types import capabilities
from app.modules.auth.models import User
from app.modules.catalog.datasets.domain.models import Dataset, Record
from app.modules.quota.service import get_user_quota_usage, get_user_quota_usage_bulk


@pytest.fixture
async def tiles3d_dataset(test_db_session):
    """A published public tileset, inserted directly with the new values."""
    owner = User(username=f"tiles3d-{uuid.uuid4().hex[:8]}", password_hash="x")
    test_db_session.add(owner)
    await test_db_session.flush()
    record = Record(
        title=f"Campus tileset {uuid.uuid4().hex[:8]}",
        record_type="tiles3d_dataset",
        visibility="public",
        record_status="published",
        created_by=owner.id,
    )
    test_db_session.add(record)
    await test_db_session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=f"tiles3d_{uuid.uuid4().hex[:12]}",
        source_format="3dtiles",
    )
    test_db_session.add(dataset)
    await test_db_session.commit()
    await test_db_session.refresh(dataset, ["record"])
    record_id, owner_id = record.id, owner.id
    yield dataset
    # A committed tiles3d row blocks every later downgrade past 0065 in this
    # worker's database (see tests/alembic_helpers.py).
    await test_db_session.rollback()
    await test_db_session.execute(
        text("DELETE FROM catalog.records WHERE id = :id"), {"id": record_id}
    )
    await test_db_session.execute(
        text("DELETE FROM catalog.users WHERE id = :id"), {"id": owner_id}
    )
    await test_db_session.commit()


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
