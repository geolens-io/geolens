"""Integration tests for /search/facets endpoint and facet counting."""

import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.auth.models import User
from app.collections.models import Collection
from app.datasets.models import Dataset, Record, RecordKeyword


# ---------------------------------------------------------------------------
# Helpers (duplicated from test_search.py for isolation)
# ---------------------------------------------------------------------------


async def _get_user_id(session, username: str) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


async def _create_search_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    keywords: list[str] | None = None,
    geometry_type: str = "MultiPolygon",
    srid: int = 4326,
    visibility: str = "public",
    description: str | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=description or f"Description for {name}",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
    )
    session.add(record)
    await session.flush()

    for kw in keywords or []:
        session.add(
            RecordKeyword(record_id=record.id, keyword=kw, keyword_type="theme")
        )

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=srid,
        geometry_type=geometry_type,
        feature_count=100,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()
    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def facet_datasets(test_db_session):
    """Create datasets with different record types for facet tests."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")

    vector_ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Vector Parks Facet",
        keywords=["parks"],
        description="Vector park boundaries for facet testing",
    )

    raster_ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Raster Elevation Facet",
        description="Raster elevation model for facet testing",
    )
    # Update record_type to raster_dataset
    await session.execute(
        update(Record)
        .where(Record.id == raster_ds.record_id)
        .values(record_type="raster_dataset")
    )

    vrt_ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="VRT Mosaic Facet",
        description="VRT mosaic dataset for facet testing",
    )
    # Update record_type to vrt_dataset
    await session.execute(
        update(Record)
        .where(Record.id == vrt_ds.record_id)
        .values(record_type="vrt_dataset")
    )

    await session.commit()

    return {"vector": vector_ds, "raster": raster_ds, "vrt": vrt_ds}


# ---------------------------------------------------------------------------
# Facet endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_facets_returns_all_types(
    client: AsyncClient,
    admin_auth_header: dict,
    facet_datasets: dict,
):
    """GET /search/facets returns counts for all record types present."""
    resp = await client.get(
        "/search/facets/",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "record_type" in data
    counts = data["record_type"]
    assert counts.get("vector_dataset", 0) >= 1
    assert counts.get("raster_dataset", 0) >= 1
    assert counts.get("vrt_dataset", 0) >= 1


@pytest.mark.anyio
async def test_facets_with_text_filter(
    client: AsyncClient,
    admin_auth_header: dict,
    facet_datasets: dict,
):
    """GET /search/facets?q=Parks filters counts to matching datasets."""
    resp = await client.get(
        "/search/facets/",
        params={"q": "Vector Parks Facet"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    counts = data["record_type"]
    assert counts.get("vector_dataset", 0) >= 1
    # Raster and VRT should not match the text "Vector Parks Facet"
    assert counts.get("raster_dataset", 0) == 0
    assert counts.get("vrt_dataset", 0) == 0


@pytest.mark.anyio
async def test_facets_with_srid_filter(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """GET /search/facets?srid=3857 returns only datasets with that SRID."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")

    # Create dataset with SRID 3857
    await _create_search_dataset(
        session,
        created_by=admin_id,
        name="SRID3857 Facet Dataset",
        srid=3857,
        description="Dataset with SRID 3857 for facet test",
    )

    resp = await client.get(
        "/search/facets/",
        params={"srid": 3857},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    counts = data["record_type"]
    assert counts.get("vector_dataset", 0) >= 1
    # Count should be smaller than unfiltered total
    resp_all = await client.get(
        "/search/facets/",
        headers=admin_auth_header,
    )
    all_counts = resp_all.json()["record_type"]
    total_filtered = sum(counts.values())
    total_all = sum(all_counts.values())
    assert total_filtered <= total_all


@pytest.mark.anyio
async def test_facets_includes_collection_count(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """GET /search/facets returns a 'collection' count when collections exist."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")

    # Create a collection
    coll = Collection(
        name="Test Facet Collection",
        description="A collection for facet count testing",
        created_by=admin_id,
    )
    session.add(coll)
    await session.commit()

    resp = await client.get(
        "/search/facets/",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    counts = data["record_type"]
    assert counts.get("collection", 0) >= 1


@pytest.mark.anyio
async def test_facets_returns_keyword_groups(
    client: AsyncClient,
    admin_auth_header: dict,
    facet_datasets: dict,
):
    """GET /search/facets returns keywords, source_organization, srid groups."""
    resp = await client.get("/search/facets/", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "record_type" in data
    assert "keywords" in data
    assert "source_organization" in data
    assert "srid" in data
    # keywords should be list of {value, count}
    assert isinstance(data["keywords"], list)
    if len(data["keywords"]) > 0:
        assert "value" in data["keywords"][0]
        assert "count" in data["keywords"][0]
    # srid should be list of {value, count}
    assert isinstance(data["srid"], list)
    if len(data["srid"]) > 0:
        assert "value" in data["srid"][0]
        assert "count" in data["srid"][0]
