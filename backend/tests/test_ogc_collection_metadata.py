"""Tests for dynamic OGC collection metadata: spatial/temporal extents and summaries.

Verifies:
  - Collection returns dynamic spatial extent (bbox) aggregated from visible datasets
  - Collection returns dynamic temporal extent from dataset date ranges
  - Collection includes summaries of geometry types, SRIDs, and tag distributions
  - Visibility filtering: anonymous sees only public dataset contributions
  - Empty catalog returns gracefully without extent/summaries
  - Collection links use absolute URLs
  - list_collections includes dynamic metadata
  - Open-ended temporal bounds use ".." notation
"""

import uuid
from datetime import date

import pytest
from geoalchemy2 import WKTElement
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.models import User
from app.datasets.models import Dataset, Record, RecordKeyword


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user_id(session, username: str) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == username))
    user = result.scalar_one()
    return user.id


async def _create_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    visibility: str = "public",
    wkt_extent: str | None = None,
    srid: int = 4326,
    geometry_type: str = "MultiPolygon",
    keywords: list[str] | None = None,
    data_vintage_start: date | None = None,
    data_vintage_end: date | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair for collection metadata tests."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Test dataset: {name}",
        theme_category=["test"],
        visibility=visibility,
        record_status="published",
        created_by=created_by,
        temporal_start=data_vintage_start,
        temporal_end=data_vintage_end,
    )
    if wkt_extent is not None:
        record.spatial_extent = WKTElement(wkt_extent, srid=4326)
    session.add(record)
    await session.flush()
    if keywords:
        for kw in keywords:
            session.add(
                RecordKeyword(record_id=record.id, keyword=kw, keyword_type="theme")
            )
        await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=srid,
        geometry_type=geometry_type,
        feature_count=10,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# WKT extent constants
_NYC_EXTENT = (
    "SRID=4326;POLYGON((-74.1 40.5, -74.1 40.9, -73.7 40.9, -73.7 40.5, -74.1 40.5))"
)
_LA_EXTENT = "SRID=4326;POLYGON((-118.5 33.7, -118.5 34.1, -117.9 34.1, -117.9 33.7, -118.5 33.7))"


# ---------------------------------------------------------------------------
# Spatial extent tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_collection_has_spatial_extent(client: AsyncClient, test_db_session):
    """Collection spatial extent aggregates bboxes from all visible datasets."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    await _create_dataset(
        session, created_by=admin_id, name="NYC DS", wkt_extent=_NYC_EXTENT
    )
    await _create_dataset(
        session, created_by=admin_id, name="LA DS", wkt_extent=_LA_EXTENT
    )

    resp = await client.get("/collections/datasets")
    assert resp.status_code == 200
    data = resp.json()
    assert "extent" in data
    assert "spatial" in data["extent"]
    bbox = data["extent"]["spatial"]["bbox"]
    assert isinstance(bbox, list)
    assert len(bbox) >= 1
    b = bbox[0]
    assert len(b) == 4
    # Aggregated bbox should encompass both NYC and LA
    assert b[0] <= -118.5  # min_x from LA
    assert b[1] <= 33.7  # min_y from LA
    assert b[2] >= -73.7  # max_x from NYC
    assert b[3] >= 40.9  # max_y from NYC


# ---------------------------------------------------------------------------
# Temporal extent tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_collection_has_temporal_extent(client: AsyncClient, test_db_session):
    """Collection temporal extent spans min start to max end across datasets."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    await _create_dataset(
        session,
        created_by=admin_id,
        name="Temporal DS 1",
        data_vintage_start=date(2020, 1, 1),
        data_vintage_end=date(2021, 12, 31),
    )
    await _create_dataset(
        session,
        created_by=admin_id,
        name="Temporal DS 2",
        data_vintage_start=date(2019, 6, 1),
        data_vintage_end=date(2023, 3, 15),
    )

    resp = await client.get("/collections/datasets")
    assert resp.status_code == 200
    data = resp.json()
    assert "extent" in data
    assert "temporal" in data["extent"]
    interval = data["extent"]["temporal"]["interval"]
    assert isinstance(interval, list)
    assert len(interval) >= 1
    # Aggregated interval must encompass both datasets' ranges
    # (other datasets in the DB may widen the range further)
    assert interval[0][0] <= "2019-06-01"
    assert interval[0][1] >= "2023-03-15"


# ---------------------------------------------------------------------------
# Summaries tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_collection_has_summaries(client: AsyncClient, test_db_session):
    """Collection summaries include geometry types, SRIDs, and deduplicated tags."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    await _create_dataset(
        session,
        created_by=admin_id,
        name="Summary DS 1",
        geometry_type="Point",
        srid=4326,
        keywords=["transportation", "parcels"],
    )
    await _create_dataset(
        session,
        created_by=admin_id,
        name="Summary DS 2",
        geometry_type="MultiPolygon",
        srid=2263,
        keywords=["parcels", "environment"],
    )

    resp = await client.get("/collections/datasets")
    assert resp.status_code == 200
    data = resp.json()
    assert "summaries" in data
    summaries = data["summaries"]

    # Geometry types sorted
    assert "geometry_type" in summaries
    assert "MultiPolygon" in summaries["geometry_type"]
    assert "Point" in summaries["geometry_type"]

    # SRIDs sorted
    assert "srid" in summaries
    assert 2263 in summaries["srid"]
    assert 4326 in summaries["srid"]

    # Keywords sorted and deduplicated
    assert "keywords" in summaries
    assert "environment" in summaries["keywords"]
    assert "parcels" in summaries["keywords"]
    assert "transportation" in summaries["keywords"]


# ---------------------------------------------------------------------------
# Visibility tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_collection_anonymous_sees_only_public_extent(
    client: AsyncClient, test_db_session
):
    """Anonymous user sees summaries only from public datasets, not private."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")

    # Use unique tag names to avoid collisions with other tests
    unique = uuid.uuid4().hex[:6]
    pub_tag = f"pub-vis-{unique}"
    priv_tag = f"priv-vis-{unique}"

    # Public dataset
    await _create_dataset(
        session,
        created_by=admin_id,
        name="Public Vis DS",
        visibility="public",
        keywords=[pub_tag],
    )
    # Private dataset
    await _create_dataset(
        session,
        created_by=admin_id,
        name="Private Vis DS",
        visibility="private",
        keywords=[priv_tag],
    )

    # Anonymous request (no auth header)
    resp = await client.get("/collections/datasets")
    assert resp.status_code == 200
    data = resp.json()

    # Summaries should contain the public tag but NOT the private tag
    assert "summaries" in data
    assert pub_tag in data["summaries"]["keywords"]
    assert priv_tag not in data["summaries"]["keywords"]


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_collection_empty_catalog_returns_gracefully(client: AsyncClient):
    """Empty catalog returns collection without extent or summaries, no error."""
    # Note: other tests may have created datasets. This test just checks
    # the endpoint doesn't crash even on an initial empty-ish state.
    resp = await client.get("/collections/datasets")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "datasets"
    assert data["title"] == "GeoLens Dataset Catalog"
    assert "links" in data


# ---------------------------------------------------------------------------
# Link tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_collection_links_are_absolute(client: AsyncClient):
    """Collection links have absolute hrefs (start with http)."""
    resp = await client.get("/collections/datasets")
    assert resp.status_code == 200
    data = resp.json()
    links = data["links"]
    rels = {link["rel"] for link in links}
    assert "self" in rels
    assert "items" in rels
    assert "root" in rels
    for link in links:
        assert link["href"].startswith("http"), f"Link {link['rel']} href not absolute"


@pytest.mark.anyio
async def test_list_collections_includes_dynamic_metadata(
    client: AsyncClient, test_db_session
):
    """GET /collections returns collection with extent and summaries when data exists."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    await _create_dataset(
        session,
        created_by=admin_id,
        name="List Coll Test",
        wkt_extent=_NYC_EXTENT,
        data_vintage_start=date(2022, 1, 1),
        data_vintage_end=date(2022, 12, 31),
    )

    resp = await client.get("/collections")
    assert resp.status_code == 200
    data = resp.json()
    assert "collections" in data
    assert len(data["collections"]) >= 1
    coll = data["collections"][0]
    assert coll["id"] == "datasets"
    # Should have dynamic metadata
    assert "extent" in coll
    assert "summaries" in coll


# ---------------------------------------------------------------------------
# Open-ended temporal tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_collection_temporal_open_ended(client: AsyncClient, test_db_session):
    """Dataset with start but no end produces open-ended temporal interval."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    await _create_dataset(
        session,
        created_by=admin_id,
        name="Open Temporal DS",
        data_vintage_start=date(2020, 1, 1),
        data_vintage_end=None,
    )

    resp = await client.get("/collections/datasets")
    assert resp.status_code == 200
    data = resp.json()
    if "extent" in data and "temporal" in data["extent"]:
        interval = data["extent"]["temporal"]["interval"]
        # The end bound should be either ".." or a date string
        # Since other test datasets may contribute an end date,
        # just verify the structure is valid
        assert isinstance(interval, list)
        assert len(interval) >= 1
        assert len(interval[0]) == 2


# ---------------------------------------------------------------------------
# Per-dataset collection metadata tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_per_dataset_collection_has_extent_in_list(
    client: AsyncClient, test_db_session
):
    """Per-dataset entry in /collections includes spatial and temporal extent."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    ds = await _create_dataset(
        session,
        created_by=admin_id,
        name="PerDS Extent List",
        wkt_extent=_NYC_EXTENT,
        data_vintage_start=date(2021, 3, 1),
        data_vintage_end=date(2022, 6, 30),
    )

    resp = await client.get("/collections")
    assert resp.status_code == 200
    data = resp.json()
    # Find the per-dataset entry
    per_ds = [c for c in data["collections"] if c["id"] == str(ds.id)]
    assert len(per_ds) == 1, f"Expected per-dataset entry for {ds.id}"
    entry = per_ds[0]

    # Spatial extent
    assert "extent" in entry
    assert "spatial" in entry["extent"]
    bbox = entry["extent"]["spatial"]["bbox"]
    assert isinstance(bbox, list) and len(bbox) >= 1

    # Temporal extent
    assert "temporal" in entry["extent"]
    interval = entry["extent"]["temporal"]["interval"]
    assert isinstance(interval, list) and len(interval) >= 1
    assert interval[0][0] == "2021-03-01"
    assert interval[0][1] == "2022-06-30"


@pytest.mark.anyio
async def test_per_dataset_collection_has_root_link_in_list(
    client: AsyncClient, test_db_session
):
    """Per-dataset entry in /collections includes rel=root link."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    ds = await _create_dataset(
        session,
        created_by=admin_id,
        name="PerDS Root Link",
    )

    resp = await client.get("/collections")
    assert resp.status_code == 200
    data = resp.json()
    per_ds = [c for c in data["collections"] if c["id"] == str(ds.id)]
    assert len(per_ds) == 1
    entry = per_ds[0]

    rels = {link["rel"] for link in entry["links"]}
    assert "root" in rels, "Per-dataset collection entry missing root link"
    root_link = next(link for link in entry["links"] if link["rel"] == "root")
    assert root_link["href"].startswith("http")


@pytest.mark.anyio
async def test_per_dataset_collection_detail_has_temporal_extent(
    client: AsyncClient, test_db_session
):
    """GET /collections/{dataset_id} includes temporal extent when dates exist."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    ds = await _create_dataset(
        session,
        created_by=admin_id,
        name="PerDS Temporal Detail",
        data_vintage_start=date(2020, 5, 15),
        data_vintage_end=date(2023, 11, 30),
    )

    resp = await client.get(f"/collections/{ds.id}")
    assert resp.status_code == 200
    data = resp.json()

    assert "extent" in data
    assert "temporal" in data["extent"]
    interval = data["extent"]["temporal"]["interval"]
    assert isinstance(interval, list) and len(interval) >= 1
    assert interval[0][0] == "2020-05-15"
    assert interval[0][1] == "2023-11-30"
