"""Tests for OGC record enrichment: assets, bbox, navigation links, conformance.

Verifies:
  - Each record includes assets dict with download, tile, and feature entries
  - Assets have required fields (href, type, roles) with correct media types
  - Records with spatial extent include bbox array
  - Records without extent omit bbox
  - Navigation links (self, collection, root) use absolute URLs
  - Collection-level response includes navigation links
  - Conformance declares OGC Records Core class
  - Existing record fields preserved after enrichment
"""

import uuid

import pytest
from geoalchemy2 import WKTElement
from httpx import AsyncClient
from app.modules.catalog.datasets.domain.models import Dataset, Record

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str,
    visibility: str = "public",
    wkt_extent: str | None = None,
    lineage_summary: str | None = None,
    update_frequency: str | None = None,
    usage_constraints: str | None = None,
    access_constraints: str | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair for enrichment tests."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Test dataset: {name}",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
        lineage_summary=lineage_summary,
        update_frequency=update_frequency,
        usage_constraints=usage_constraints,
        access_constraints=access_constraints,
    )
    if wkt_extent is not None:
        record.spatial_extent = WKTElement(wkt_extent, srid=4326)
    session.add(record)
    await session.flush()
    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=4326,
        geometry_type="MultiPolygon",
        feature_count=10,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.commit()
    await session.refresh(dataset)
    return dataset


# NYC area extent for spatial tests
_NYC_EXTENT = (
    "SRID=4326;POLYGON((-74.1 40.5, -74.1 40.9, -73.7 40.9, -73.7 40.5, -74.1 40.5))"
)


# ---------------------------------------------------------------------------
# Asset tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_has_assets_dict(client: AsyncClient, test_db_session):
    """GET a single record returns an assets dict with 6 entries."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Assets Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "assets" in data
    assets = data["assets"]
    assert isinstance(assets, dict)
    for key in [
        "download_gpkg",
        "download_geojson",
        "download_shp",
        "download_csv",
        "vector_tiles",
        "ogc_features",
    ]:
        assert key in assets, f"Missing asset key: {key}"


@pytest.mark.anyio
async def test_assets_have_required_fields(client: AsyncClient, test_db_session):
    """Each asset has href (absolute), type, and roles (list)."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Asset Fields Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assets = resp.json()["assets"]
    for key, asset in assets.items():
        assert "href" in asset, f"{key} missing href"
        assert "type" in asset, f"{key} missing type"
        assert "roles" in asset, f"{key} missing roles"
        assert asset["href"].startswith("http"), (
            f"{key} href not absolute: {asset['href']}"
        )
        assert isinstance(asset["roles"], list), f"{key} roles not a list"


@pytest.mark.anyio
async def test_download_assets_have_correct_media_types(
    client: AsyncClient, test_db_session
):
    """Download assets have the correct media types."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Media Type Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assets = resp.json()["assets"]

    assert assets["download_gpkg"]["type"] == "application/geopackage+sqlite3"
    assert assets["download_geojson"]["type"] == "application/geo+json"
    assert assets["download_shp"]["type"] == "application/x-shapefile"
    assert assets["download_csv"]["type"] == "text/csv"


@pytest.mark.anyio
async def test_download_asset_href_contains_export_path(
    client: AsyncClient, test_db_session
):
    """Each download asset href contains /datasets/ and /export?format=."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Export Path Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assets = resp.json()["assets"]

    for fmt in ["gpkg", "geojson", "shp", "csv"]:
        href = assets[f"download_{fmt}"]["href"]
        assert "/datasets/" in href, f"download_{fmt} href missing /datasets/"
        assert f"/export?format={fmt}" in href, (
            f"download_{fmt} href missing export path"
        )


@pytest.mark.anyio
async def test_tile_asset_href_contains_table_name(
    client: AsyncClient, test_db_session
):
    """vector_tiles asset href contains the dataset table_name and tile path pattern."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Tile URL Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assets = resp.json()["assets"]
    href = assets["vector_tiles"]["href"]
    assert ds.table_name in href
    assert "/{z}/{x}/{y}.pbf" in href


@pytest.mark.anyio
async def test_feature_asset_href_contains_table_name(
    client: AsyncClient, test_db_session
):
    """ogc_features asset href contains the dataset ID and /features path."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Feature URL Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assets = resp.json()["assets"]
    href = assets["ogc_features"]["href"]
    assert str(ds.id) in href
    assert "/features" in href


@pytest.mark.anyio
async def test_tile_and_feature_asset_roles(client: AsyncClient, test_db_session):
    """vector_tiles roles is ['visual'], ogc_features roles is ['data']."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Roles Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assets = resp.json()["assets"]
    assert assets["vector_tiles"]["roles"] == ["visual"]
    assert assets["ogc_features"]["roles"] == ["data"]


# ---------------------------------------------------------------------------
# Bbox tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_has_bbox_when_extent_exists(client: AsyncClient, test_db_session):
    """Record with extent includes bbox as a 4-element float list matching the extent."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(
        session,
        created_by=admin_id,
        name="Bbox Test",
        wkt_extent=_NYC_EXTENT,
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    data = resp.json()
    assert "bbox" in data
    bbox = data["bbox"]
    assert isinstance(bbox, list)
    assert len(bbox) == 4
    # Approximate match to NYC extent: [-74.1, 40.5, -73.7, 40.9]
    assert abs(bbox[0] - (-74.1)) < 0.01
    assert abs(bbox[1] - 40.5) < 0.01
    assert abs(bbox[2] - (-73.7)) < 0.01
    assert abs(bbox[3] - 40.9) < 0.01


@pytest.mark.anyio
async def test_record_has_no_bbox_when_no_extent(client: AsyncClient, test_db_session):
    """Record without extent omits bbox key entirely (not null)."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="No Bbox Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    data = resp.json()
    assert "bbox" not in data


# ---------------------------------------------------------------------------
# Link tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_links_include_self_collection_root(
    client: AsyncClient, test_db_session
):
    """Record links include self, collection, and root relations."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Links Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    links = resp.json()["links"]
    rels = {link["rel"] for link in links}
    assert "self" in rels
    assert "collection" in rels
    assert "root" in rels


@pytest.mark.anyio
async def test_record_links_are_absolute_urls(client: AsyncClient, test_db_session):
    """All link href values start with http."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Abs URL Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    links = resp.json()["links"]
    for link in links:
        assert link["href"].startswith("http"), f"Link {link['rel']} href not absolute"


@pytest.mark.anyio
async def test_self_link_points_to_record(client: AsyncClient, test_db_session):
    """Self link href ends with /collections/datasets/items/{record_id}."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Self Link Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    links = resp.json()["links"]
    self_link = next(link for link in links if link["rel"] == "self")
    assert self_link["href"].endswith(f"/collections/datasets/items/{ds.id}")


@pytest.mark.anyio
async def test_collection_link_points_to_collection(
    client: AsyncClient, test_db_session
):
    """Collection link href ends with /collections/datasets."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Coll Link Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    links = resp.json()["links"]
    coll_link = next(link for link in links if link["rel"] == "collection")
    assert coll_link["href"].endswith("/collections/datasets")


@pytest.mark.anyio
async def test_root_link_points_to_root(client: AsyncClient, test_db_session):
    """Root link href ends with / or equals the base URL."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Root Link Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    links = resp.json()["links"]
    root_link = next(link for link in links if link["rel"] == "root")
    # Root should end with "/" (the base path)
    assert root_link["href"].endswith("/")


@pytest.mark.anyio
async def test_collection_items_response_has_links(client: AsyncClient):
    """GET /collections/datasets/items response has top-level links with self, collection, root."""
    resp = await client.get("/collections/datasets/items")
    assert resp.status_code == 200
    data = resp.json()
    assert "links" in data
    rels = {link["rel"] for link in data["links"]}
    assert "self" in rels
    assert "collection" in rels
    assert "root" in rels


# ---------------------------------------------------------------------------
# Conformance test
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_conformance_includes_records_core(client: AsyncClient):
    """GET /conformance includes OGC API Records Core conformance classes."""
    resp = await client.get("/conformance")
    assert resp.status_code == 200
    data = resp.json()
    records_classes = [cls for cls in data["conformsTo"] if "ogcapi-records-1" in cls]
    assert len(records_classes) >= 1, "Expected at least one Records conformance class"


# ---------------------------------------------------------------------------
# Regression test
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_existing_record_fields_preserved(client: AsyncClient, test_db_session):
    """Existing record fields (type, id, geometry, properties.*) still present after enrichment."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Regression Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    data = resp.json()

    # Top-level GeoJSON fields
    assert data["type"] == "Feature"
    assert data["id"] == str(ds.id)
    assert "geometry" in data
    assert "properties" in data

    # Properties fields
    props = data["properties"]
    assert props["title"] == "Regression Test"
    assert props["description"] == "Test dataset: Regression Test"
    assert props["keywords"] is None  # no record_keywords inserted
    assert props["type"] == "dataset"
    assert "created" in props
    assert "updated" in props
    assert props["crs"] == "EPSG:4326"
    assert props["geometry_type"] == "MultiPolygon"
    assert props["feature_count"] == 10

    # New enrichment fields coexist
    assert "links" in data
    assert "assets" in data


# ---------------------------------------------------------------------------
# Distribution tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_has_distributions_list(client: AsyncClient, test_db_session):
    """Record with distributions includes them in properties.distributions."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="Dist Test")
    # Add a distribution via the DB
    from app.modules.catalog.datasets.domain.models import RecordDistribution

    dist = RecordDistribution(
        record_id=ds.record_id,
        distribution_type="download",
        format="gpkg",
        url=f"/datasets/{ds.id}/export?format=gpkg",
        title="Download as GPKG",
        media_type="application/geopackage+sqlite3",
        is_primary=True,
        auto_generated=True,
    )
    session.add(dist)
    await session.commit()

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert "distributions" in props
    dists = props["distributions"]
    assert isinstance(dists, list)
    assert len(dists) == 1
    dists = sorted(dists, key=lambda d: d["format"])
    assert dists[0]["format"] == "gpkg"
    assert dists[0]["type"] == "download"
    assert dists[0]["url"].startswith("http")  # absolute URL
    assert dists[0]["is_primary"] is True


@pytest.mark.anyio
async def test_record_distributions_empty_when_none(
    client: AsyncClient, test_db_session
):
    """Record without distributions has empty distributions list."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="No Dist Test")

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert props["distributions"] == []


# ---------------------------------------------------------------------------
# Lineage tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_has_lineage(client: AsyncClient, test_db_session):
    """Record with lineage_summary includes it in properties.lineage."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(
        session,
        created_by=admin_id,
        name="Lineage Test",
        lineage_summary="Derived from Census 2020 TIGER/Line files",
    )
    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    props = resp.json()["properties"]
    assert props["lineage"] == "Derived from Census 2020 TIGER/Line files"


# ---------------------------------------------------------------------------
# Update frequency tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_has_update_frequency(client: AsyncClient, test_db_session):
    """Record with update_frequency includes it in properties."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(
        session,
        created_by=admin_id,
        name="Freq Test",
        update_frequency="annually",
    )
    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    props = resp.json()["properties"]
    assert props["update_frequency"] == "annually"


# ---------------------------------------------------------------------------
# Constraints tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_record_has_constraints(client: AsyncClient, test_db_session):
    """Record with constraints includes combined object."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(
        session,
        created_by=admin_id,
        name="Constraints Test",
        usage_constraints="Attribution required",
        access_constraints="Public access",
    )
    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    props = resp.json()["properties"]
    assert props["constraints"] == {
        "usage": "Attribution required",
        "access": "Public access",
    }


@pytest.mark.anyio
async def test_record_constraints_null_when_none(client: AsyncClient, test_db_session):
    """Record without constraints has null constraints."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dataset(session, created_by=admin_id, name="No Constraints")
    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    props = resp.json()["properties"]
    assert props["constraints"] is None
