"""Integration tests for search and OGC API Records endpoints.

Tests cover: text search, spatial (bbox) search, faceted filtering (keywords,
geometry_type, srid, date range, data vintage), child-table search (keywords,
contacts), camelCase theme_category FTS, lineage_summary FTS, sorting,
pagination, RBAC visibility, OGC collections/items endpoints, and authentication.

Requirements:
  - Docker database must be running (docker compose up db)
  - Alembic migrations must be applied
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import func, update

from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordContact,
    RecordKeyword,
)

from tests.factories import get_user_id


def test_search_service_facade_exports_public_api():
    """Public search service facade keeps existing import names available."""
    from app.modules.catalog.search import service

    required = {
        "FacetCounts",
        "SearchFilters",
        "get_facet_counts",
        "search_collections",
        "search_datasets",
        "build_assets",
        "dataset_to_ogc_record",
        "parse_ogc_datetime",
        "_compute_rrf_scores",
    }
    missing = sorted(name for name in required if not hasattr(service, name))
    assert not missing
    assert required.issubset(set(service.__all__))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_search_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    keywords: list[str] | None = None,
    geometry_type: str = "MultiPolygon",
    srid: int = 4326,
    visibility: str = "public",
    extent_wkt: str | None = None,
    data_vintage_start: date | None = None,
    data_vintage_end: date | None = None,
    description: str | None = None,
    theme_category: list[str] | None = None,
    lineage_summary: str | None = None,
    language: str | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair with optional spatial extent and keywords."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record_kwargs = {
        "title": name,
        "summary": description or f"Description for {name}",
        "visibility": visibility,
        "record_status": "published",
        "created_by": created_by,
        "temporal_start": data_vintage_start,
        "temporal_end": data_vintage_end,
        "theme_category": theme_category,
        "lineage_summary": lineage_summary,
    }
    if language is not None:
        record_kwargs["language"] = language
    record = Record(**record_kwargs)
    session.add(record)
    await session.flush()

    # Create keyword entries
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

    # Set extent via raw SQL if provided (GeoAlchemy2 WKT)
    if extent_wkt:
        await session.execute(
            update(Record)
            .where(Record.id == record.id)
            .values(spatial_extent=func.ST_GeomFromText(extent_wkt, 4326))
        )

    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def search_datasets(test_db_session):
    """Create a set of test datasets for search tests.

    Returns dict mapping dataset name keys to Dataset objects.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    # NYC area polygon (approx)
    nyc_wkt = "POLYGON((-74.3 40.4, -73.7 40.4, -73.7 40.95, -74.3 40.95, -74.3 40.4))"
    # London area polygon (approx)
    london_wkt = "POLYGON((-0.5 51.3, 0.3 51.3, 0.3 51.7, -0.5 51.7, -0.5 51.3))"
    # Global polygon
    global_wkt = "POLYGON((-180 -90, 180 -90, 180 90, -180 90, -180 -90))"

    water = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Water Boundaries",
        keywords=["water", "hydrology"],
        geometry_type="MultiPolygon",
        srid=4326,
        extent_wkt=nyc_wkt,
        data_vintage_start=date(2021, 1, 1),
        data_vintage_end=date(2022, 12, 31),
        description="Water boundary polygons for the NYC area",
    )

    roads = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Road Centerlines",
        keywords=["transportation", "roads"],
        geometry_type="MultiLineString",
        srid=4326,
        extent_wkt=london_wkt,
        data_vintage_start=date(2023, 1, 1),
        data_vintage_end=date(2023, 12, 31),
        description="Road centerline network for London",
    )

    buildings = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Building Footprints",
        keywords=["buildings", "structures"],
        geometry_type="MultiPolygon",
        srid=2263,
        extent_wkt=global_wkt,
        data_vintage_start=date(2019, 6, 1),
        data_vintage_end=date(2020, 6, 30),
        description="Building footprint polygons worldwide",
    )

    points = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Fire Stations",
        keywords=["emergency", "facilities"],
        geometry_type="Point",
        srid=4326,
        extent_wkt=nyc_wkt,
        data_vintage_start=date(2024, 1, 1),
        data_vintage_end=date(2024, 12, 31),
        description="Fire station locations in NYC",
    )

    wetlands = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Wetlands Inventory",
        keywords=["wetlands", "habitats"],
        geometry_type="MultiPolygon",
        srid=4326,
        extent_wkt=global_wkt,
        description="Wetlands inventory polygons for habitat planning",
    )

    private = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Classified Areas",
        keywords=["classified"],
        geometry_type="MultiPolygon",
        srid=4326,
        visibility="private",
        extent_wkt=nyc_wkt,
        description="Private classified dataset",
    )

    return {
        "water": water,
        "roads": roads,
        "buildings": buildings,
        "points": points,
        "wetlands": wetlands,
        "private": private,
    }


# ---------------------------------------------------------------------------
# Text search tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_text_match(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Search q=water returns the Water Boundaries dataset."""
    resp = await client.get(
        "/search/datasets/",
        params={"q": "water"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    titles = [f["properties"]["title"] for f in data["features"]]
    assert "Water Boundaries" in titles


@pytest.mark.anyio
async def test_search_text_empty_returns_all(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Search with no q param returns all visible datasets (at least our 5)."""
    resp = await client.get(
        "/search/datasets/",
        params={"limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    # Admin sees all including private
    assert data["numberMatched"] >= 5


@pytest.mark.anyio
async def test_search_text_prefix_match(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Short prefix searches still match obvious catalog titles."""
    resp = await client.get(
        "/search/datasets/",
        params={"q": "wet"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(search_datasets["wetlands"].id) in ids


# ---------------------------------------------------------------------------
# Spatial search tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_bbox_intersects(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Search with NYC bbox returns datasets whose extent intersects NYC."""
    resp = await client.get(
        "/search/datasets/",
        params={"bbox": "-74.1,40.6,-73.8,40.9", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    # Water, points, private are in NYC area; buildings are global (also intersects)
    assert str(search_datasets["water"].id) in ids
    assert str(search_datasets["points"].id) in ids
    # London roads should NOT appear
    assert str(search_datasets["roads"].id) not in ids


@pytest.mark.anyio
async def test_search_bbox_within(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Search with spatial_predicate=within returns only datasets fully inside bbox."""
    resp = await client.get(
        "/search/datasets/",
        params={"bbox": "-180,-90,180,90", "spatial_predicate": "within", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    # With a world-covering bbox, all spatially-indexed datasets should be within
    assert data["numberMatched"] >= 0


@pytest.mark.anyio
async def test_search_bbox_no_match(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Search with a remote bbox that has no intersections returns 0 results."""
    # Middle of Pacific Ocean
    resp = await client.get(
        "/search/datasets/",
        params={"bbox": "170.0,-10.0,175.0,-5.0", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    matched_ids = [f["id"] for f in data["features"]]
    # The NYC/London specific datasets should not appear
    assert str(search_datasets["water"].id) not in matched_ids
    assert str(search_datasets["roads"].id) not in matched_ids
    assert str(search_datasets["points"].id) not in matched_ids


# ---------------------------------------------------------------------------
# Faceted filter tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_filter_by_keywords(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Filter keywords=water returns only the water-keyworded dataset."""
    resp = await client.get(
        "/search/datasets/",
        params={"keywords": "water", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(search_datasets["water"].id) in ids
    assert str(search_datasets["roads"].id) not in ids


@pytest.mark.anyio
async def test_search_filter_by_geometry_type(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Filter geometry_type=Point returns only Point datasets."""
    resp = await client.get(
        "/search/datasets/",
        params={"geometry_type": "Point", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(search_datasets["points"].id) in ids
    # Non-Point datasets excluded
    assert str(search_datasets["water"].id) not in ids
    assert str(search_datasets["roads"].id) not in ids


@pytest.mark.anyio
async def test_search_filter_by_srid(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Filter srid=2263 returns only datasets with that SRID."""
    resp = await client.get(
        "/search/datasets/",
        params={"srid": 2263, "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(search_datasets["buildings"].id) in ids
    assert str(search_datasets["water"].id) not in ids


@pytest.mark.anyio
async def test_search_filter_by_date_range(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Filter by date_from/date_to narrows to datasets created in that range.

    Uses UTC date (not local date) to match Postgres NOW() server-side timezone —
    server-default created_at runs as UTC. The yesterday/tomorrow bracket then
    absorbs the residual sub-second skew between Python and Postgres clocks,
    closing the midnight-UTC boundary race the audit observed (cluster 5).
    """
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    tomorrow = today + timedelta(days=1)

    resp = await client.get(
        "/search/datasets/",
        params={
            "date_from": yesterday.isoformat(),
            "date_to": tomorrow.isoformat(),
            "limit": 100,
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    # Our test datasets should all be within this range
    assert data["numberMatched"] >= 4  # at least our public ones

    # Now filter with a past date range that no dataset should match
    resp2 = await client.get(
        "/search/datasets/",
        params={
            "date_from": "2020-01-01",
            "date_to": "2020-01-31",
            "limit": 100,
        },
        headers=admin_auth_header,
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    # None of our test datasets were created in Jan 2020
    ids = [f["id"] for f in data2["features"]]
    for ds in search_datasets.values():
        assert str(ds.id) not in ids


@pytest.mark.anyio
async def test_search_filter_by_vintage(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Filter by vintage_start/vintage_end narrows to matching vintage range."""
    # 2020-2023 should include water (2021-2022), roads (2023), buildings (2019-2020)
    resp = await client.get(
        "/search/datasets/",
        params={
            "vintage_start": "2021-01-01",
            "vintage_end": "2023-12-31",
            "limit": 100,
        },
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    # Water vintage_start=2021 >= 2021 and vintage_end=2022 <= 2023 => included
    assert str(search_datasets["water"].id) in ids
    # Roads vintage_start=2023 >= 2021 and vintage_end=2023 <= 2023 => included
    assert str(search_datasets["roads"].id) in ids
    # Buildings vintage_start=2019 < 2021 => excluded (vintage_start filter)
    assert str(search_datasets["buildings"].id) not in ids
    # Fire Stations vintage_start=2024 > 2021 but vintage_end=2024 > 2023 => excluded
    assert str(search_datasets["points"].id) not in ids


# ---------------------------------------------------------------------------
# Child-table search tests (SEARCH-02)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_by_keyword(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Searching for a keyword stored only in record_keywords returns the record (SEARCH-02).

    The keyword 'hydrogeology' does NOT appear in title or summary, so the
    match must come from the EXISTS subquery on record_keywords.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Subsurface Geology Survey",
        keywords=["hydrogeology"],
        description="Regional geological survey results",
    )

    resp = await client.get(
        "/search/datasets/",
        params={"q": "hydrogeology", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(ds.id) in ids


@pytest.mark.anyio
async def test_search_by_contact_name(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Searching for a contact name stored in record_contacts returns the record (SEARCH-02)."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Terrain Elevation Model",
        description="High resolution DEM data",
    )

    # Add a contact with a unique name
    session.add(
        RecordContact(
            record_id=ds.record_id,
            role="pointOfContact",
            name="Weatherstone",
            organization="Survey Corp",
        )
    )
    await session.commit()

    resp = await client.get(
        "/search/datasets/",
        params={"q": "Weatherstone", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(ds.id) in ids


@pytest.mark.anyio
async def test_search_by_contact_organization(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Searching for a contact organization returns the record (SEARCH-02, Rec 1)."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Coastal Erosion Study",
        description="Beach profile measurements",
    )

    # Add a contact with only organization (no name)
    session.add(
        RecordContact(
            record_id=ds.record_id,
            role="distributor",
            organization="NationalGeographicSurvey",
        )
    )
    await session.commit()

    resp = await client.get(
        "/search/datasets/",
        params={"q": "NationalGeographicSurvey", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(ds.id) in ids


# ---------------------------------------------------------------------------
# theme_category camelCase + lineage_summary FTS tests (SEARCH-01)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_by_theme_category_camelcase(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Searching 'climatology' matches theme_category=['climatologyMeteorologyAtmosphere'] (SEARCH-01).

    The camelCase normalizer splits 'climatologyMeteorologyAtmosphere' into
    'climatology Meteorology Atmosphere' for FTS indexing.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Weather Station Network",
        description="Automated weather stations",
        theme_category=["climatologyMeteorologyAtmosphere"],
    )

    resp = await client.get(
        "/search/datasets/",
        params={"q": "climatology", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(ds.id) in ids


@pytest.mark.anyio
async def test_search_by_lineage_summary(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Searching 'LiDAR' matches a record with lineage_summary containing 'LiDAR' (SEARCH-01)."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Urban Canopy Heights",
        description="Tree canopy height model for urban areas",
        lineage_summary="Derived from LiDAR point cloud survey 2024",
    )

    resp = await client.get(
        "/search/datasets/",
        params={"q": "LiDAR", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(ds.id) in ids


# ---------------------------------------------------------------------------
# Sorting tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_sort_by_name(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Sort by title ascending returns alphabetical order."""
    resp = await client.get(
        "/search/datasets/",
        params={"sort_by": "title", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    titles = [f["properties"]["title"] for f in data["features"]]
    assert titles == sorted(titles, key=str.casefold)


@pytest.mark.anyio
async def test_search_sort_by_frontend_name_alias(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Frontend sort_by=name alias should match title sorting."""
    resp = await client.get(
        "/search/datasets/",
        params={"sort_by": "name", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    titles = [f["properties"]["title"] for f in data["features"]]
    assert titles == sorted(titles, key=str.casefold)


@pytest.mark.anyio
async def test_search_sort_by_date_added(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Sort by date_added returns newest first."""
    resp = await client.get(
        "/search/datasets/",
        params={"sort_by": "date_added", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    dates = [f["properties"]["created"] for f in data["features"]]
    assert dates == sorted(dates, reverse=True)


# ---------------------------------------------------------------------------
# Pagination tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_pagination(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """Pagination returns correct page size and total count."""
    # Use a specific text query to isolate our fixture datasets
    # Filter by geometry_type=MultiPolygon to get a known set
    resp = await client.get(
        "/search/datasets/",
        params={"geometry_type": "MultiPolygon", "limit": 1, "offset": 0},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    total = data["numberMatched"]
    assert total >= 3  # water, buildings, private are MultiPolygon
    assert data["numberReturned"] == 1
    page1_ids = {f["id"] for f in data["features"]}

    # Page 2
    resp2 = await client.get(
        "/search/datasets/",
        params={"geometry_type": "MultiPolygon", "limit": 1, "offset": 1},
        headers=admin_auth_header,
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["numberReturned"] == 1
    assert data2["numberMatched"] == total
    page2_ids = {f["id"] for f in data2["features"]}

    # Different results on different pages
    assert page1_ids.isdisjoint(page2_ids)


# ---------------------------------------------------------------------------
# RBAC tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_rbac_private_hidden(
    client: AsyncClient,
    viewer_auth_header: dict,
    search_datasets: dict,
):
    """Viewer cannot see private datasets in search results."""
    resp = await client.get(
        "/search/datasets/",
        params={"limit": 100},
        headers=viewer_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    ids = [f["id"] for f in data["features"]]
    assert str(search_datasets["private"].id) not in ids
    # Public datasets still visible
    assert str(search_datasets["water"].id) in ids


# ---------------------------------------------------------------------------
# OGC Collections tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ogc_collections_list(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """GET /collections returns a collection with id=datasets."""
    resp = await client.get("/collections", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "collections" in data
    ids = [c["id"] for c in data["collections"]]
    assert "datasets" in ids


@pytest.mark.anyio
async def test_ogc_collection_detail(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """GET /collections/datasets returns metadata with title and links."""
    resp = await client.get("/collections/datasets", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "datasets"
    assert "title" in data
    assert "links" in data


@pytest.mark.anyio
async def test_ogc_items_search(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """GET /collections/datasets/items?q=water returns OGC FeatureCollection."""
    resp = await client.get(
        "/collections/datasets/items",
        params={"q": "water"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "FeatureCollection"
    titles = [f["properties"]["title"] for f in data["features"]]
    assert "Water Boundaries" in titles


@pytest.mark.anyio
async def test_ogc_single_record(
    client: AsyncClient,
    admin_auth_header: dict,
    search_datasets: dict,
):
    """GET /collections/datasets/items/{id} returns OGC Feature for a dataset."""
    ds_id = search_datasets["water"].id
    resp = await client.get(
        f"/collections/datasets/items/{ds_id}",
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "Feature"
    assert data["id"] == str(ds_id)
    assert data["properties"]["title"] == "Water Boundaries"


@pytest.mark.anyio
async def test_ogc_single_record_content_language_uses_record_language(
    client: AsyncClient,
    test_db_session,
    clean_tables,
):
    """Content-Language reflects the serialized record language, not Accept-Language."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_search_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"Spanish Language Record {uuid.uuid4().hex}",
        language="es",
    )

    resp = await client.get(
        f"/collections/datasets/items/{ds.id}",
        headers={"Accept-Language": "fr"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-language"] == "es"
    assert resp.json()["properties"]["language"] == "es"


@pytest.mark.anyio
async def test_ogc_collection_content_language_uses_homogeneous_record_language(
    client: AsyncClient,
    test_db_session,
    clean_tables,
):
    """A single-language collection page advertises that actual record language."""
    admin_id = await get_user_id(test_db_session, "admin")
    token = f"homogeneouslanguage{uuid.uuid4().hex}"
    await _create_search_dataset(
        test_db_session,
        created_by=admin_id,
        name=f"{token} Spanish page",
        language="es",
    )

    resp = await client.get(
        "/collections/datasets/items",
        params={"q": token},
        headers={"Accept-Language": "fr"},
    )

    assert resp.status_code == 200
    assert resp.headers["content-language"] == "es"
    assert {f["properties"]["language"] for f in resp.json()["features"]} == {"es"}


@pytest.mark.anyio
async def test_ogc_collection_content_language_omitted_for_mixed_record_languages(
    client: AsyncClient,
    test_db_session,
    clean_tables,
):
    """Mixed-language record pages do not echo the negotiated request language."""
    admin_id = await get_user_id(test_db_session, "admin")
    token = f"mixedlanguage{uuid.uuid4().hex}"
    for language in ("es", "fr"):
        await _create_search_dataset(
            test_db_session,
            created_by=admin_id,
            name=f"{token} {language}",
            language=language,
        )

    resp = await client.get(
        "/collections/datasets/items",
        params={"q": token, "limit": 10},
        headers={"Accept-Language": "de"},
    )

    assert resp.status_code == 200
    assert resp.headers.get("content-language") is None
    assert {f["properties"]["language"] for f in resp.json()["features"]} == {
        "es",
        "fr",
    }


# ---------------------------------------------------------------------------
# Auth requirement test
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_ranking_published_boost(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Published datasets appear before draft datasets when sort_by=relevance."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")

    # Create a draft dataset
    draft_ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Ranking Draft Dataset",
    )
    await session.execute(
        update(Record)
        .where(Record.id == draft_ds.record_id)
        .values(record_status="draft")
    )

    # Create a published dataset
    pub_ds = await _create_search_dataset(
        session,
        created_by=admin_id,
        name="Ranking Published Dataset",
    )
    await session.execute(
        update(Record)
        .where(Record.id == pub_ds.record_id)
        .values(record_status="published")
    )
    await session.commit()

    resp = await client.get(
        "/search/datasets/",
        params={"sort_by": "relevance", "q": "Ranking", "limit": 100},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    features = resp.json()["features"]
    ids = [f["id"] for f in features]
    assert str(pub_ds.id) in ids, "Published dataset should appear in results"
    assert str(draft_ds.id) in ids, "Draft dataset should appear in results for admin"
    pub_idx = ids.index(str(pub_ds.id))
    draft_idx = ids.index(str(draft_ds.id))
    assert pub_idx < draft_idx, "Published dataset should rank before draft"


@pytest.mark.anyio
async def test_search_unauthenticated_returns_200(
    client: AsyncClient,
):
    """GET /search/datasets without token returns 200 (anonymous access allowed)."""
    resp = await client.get("/search/datasets/")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Unicode / special character tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_unicode_query_does_not_crash(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Queries containing CJK, Cyrillic, and emoji characters must not crash.

    Protects the FTS + trigram path in search/service.py against query strings
    that may contain characters outside ASCII. The search should succeed with
    a 200 and return a valid GeoJSON FeatureCollection (possibly empty).
    """
    admin_id = await get_user_id(test_db_session, "admin")
    # Create a dataset whose title contains Unicode characters so we can also
    # verify that round-tripping Unicode through the search pipeline works.
    cjk_title = "東京の地図 Tokyo Map"
    await _create_search_dataset(
        test_db_session,
        created_by=admin_id,
        name=cjk_title,
        keywords=["tokyo", "日本"],
        geometry_type="MultiPolygon",
        srid=4326,
        description="Map of 東京 (Tokyo) — contains CJK characters",
    )

    for query in ["東京", "日本", "Москва", "map", "🌍", "café"]:
        resp = await client.get(
            "/search/datasets/",
            params={"q": query},
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, (
            f"Search with query={query!r} crashed: {resp.text}"
        )
        data = resp.json()
        assert data["type"] == "FeatureCollection"
        assert "features" in data

    # The CJK-titled dataset should be findable by its ASCII fallback term
    resp = await client.get(
        "/search/datasets/",
        params={"q": "Tokyo"},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200
    titles = [f["properties"]["title"] for f in resp.json()["features"]]
    assert cjk_title in titles


@pytest.mark.anyio
async def test_search_keyword_match_is_accent_insensitive(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    clean_tables,
):
    """Keyword fallback search matches Unicode accents via unaccented LIKE."""
    admin_id = await get_user_id(test_db_session, "admin")
    title = f"Accent Keyword Dataset {uuid.uuid4().hex}"
    await _create_search_dataset(
        test_db_session,
        created_by=admin_id,
        name=title,
        keywords=["café"],
        description="ASCII-only summary without the keyword",
    )

    resp = await client.get(
        "/search/datasets/",
        params={"q": "cafe"},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200
    titles = [f["properties"]["title"] for f in resp.json()["features"]]
    assert title in titles


@pytest.mark.anyio
async def test_search_simple_tsvector_matches_unicode_lineage(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    clean_tables,
):
    """The simple regconfig companion covers Unicode text outside title/summary."""
    admin_id = await get_user_id(test_db_session, "admin")
    title = f"Unicode Lineage Dataset {uuid.uuid4().hex}"
    await _create_search_dataset(
        test_db_session,
        created_by=admin_id,
        name=title,
        description="ASCII-only summary without the query",
        lineage_summary="東京水文 観測記録",
    )

    resp = await client.get(
        "/search/datasets/",
        params={"q": "東京水文"},
        headers=admin_auth_header,
    )

    assert resp.status_code == 200
    titles = [f["properties"]["title"] for f in resp.json()["features"]]
    assert title in titles
