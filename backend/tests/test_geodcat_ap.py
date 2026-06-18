"""Tests for the GeoDCAT-AP 2.0.0 export endpoints.

Verifies:
  - Single record GeoDCAT-AP has correct @context (geospatial namespaces),
    @type, @id, and ISO field mappings.
  - Catalog feed includes visible datasets and excludes private ones.
  - Distribution URLs are absolute; nested catalog entries omit @context.
  - ISO 19115 fields map to GeoDCAT-AP terms (lineage, constraints, CRS,
    maintenance frequency, responsible-party roles, extents).
  - Structural validation report shape + a round-trip
    (create -> edit -> GeoDCAT-AP output passes validation).
"""

import uuid
from datetime import date

import pytest
from geoalchemy2 import WKTElement
from httpx import AsyncClient
from sqlalchemy import text

from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordContact,
    RecordDistribution,
    RecordKeyword,
)
from app.standards.geodcat_ap import (
    GEODCAT_AP_SCHEMA_VERSION,
)
from tests.factories import get_user_id

_NYC_EXTENT = (
    "SRID=4326;POLYGON((-74.1 40.5, -74.1 40.9, -73.7 40.9, -73.7 40.5, -74.1 40.5))"
)


async def _create_geodcat_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str = "GeoDCAT Test Dataset",
    visibility: str = "public",
    with_contact: bool = True,
    contact_role: str = "pointOfContact",
    with_keyword: bool = True,
    with_distribution: bool = True,
    with_spatial: bool = True,
    with_temporal: bool = True,
    srid: int = 4326,
) -> Dataset:
    """Insert a Record + Dataset with full ISO metadata for GeoDCAT-AP tests."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Description for {name}",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
        license="https://creativecommons.org/licenses/by/4.0/",
        source_organization="GeoOrg Publishing",
        lineage_summary="Derived from open data sources",
        update_frequency="annually",
        access_constraints="Public access, no limitations",
        usage_constraints="Attribution required",
        theme_category=["environment", "geoscience"],
    )
    if with_spatial:
        record.spatial_extent = WKTElement(_NYC_EXTENT, srid=4326)
    if with_temporal:
        record.temporal_start = date(2020, 1, 1)
        record.temporal_end = date(2024, 12, 31)
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=table_name,
        srid=srid,
        geometry_type="MultiPolygon",
        feature_count=100,
        source_format="geojson",
        source_filename="test.geojson",
    )
    session.add(dataset)
    await session.flush()

    if with_contact:
        session.add(
            RecordContact(
                record_id=record.id,
                role=contact_role,
                name="Jane Doe",
                email="jane@example.com",
                organization="GeoOrg",
            )
        )

    if with_keyword:
        session.add(RecordKeyword(record_id=record.id, keyword="hydrology"))

    if with_distribution:
        session.add(
            RecordDistribution(
                record_id=record.id,
                distribution_type="download",
                format="gpkg",
                url=f"/datasets/{dataset.id}/export?format=gpkg",
                title="Download as GPKG",
                media_type="application/geopackage+sqlite3",
                is_primary=True,
                auto_generated=True,
            )
        )

    await session.commit()
    await session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# Single record GeoDCAT-AP tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_single_record_geodcat_ap_has_geospatial_context(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """@context includes DCAT + GeoDCAT-AP geospatial namespace prefixes."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_geodcat_dataset(session, created_by=admin_id)

    resp = await client.get(f"/datasets/{ds.id}/geodcat-ap/", headers=admin_auth_header)
    assert resp.status_code == 200
    assert "application/ld+json" in resp.headers["content-type"]
    data = resp.json()
    ctx = data["@context"]
    for prefix in ["dcat", "dcterms", "foaf", "skos", "gsp", "geodcat", "prov"]:
        assert prefix in ctx, f"Missing namespace prefix: {prefix}"
    assert ctx["gsp"] == "http://www.opengis.net/ont/geosparql#"
    assert ctx["geodcat"] == "http://data.europa.eu/930/"


@pytest.mark.anyio
async def test_single_record_geodcat_ap_type_id_title(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """@type is dcat:Dataset; @id + title/description map correctly."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_geodcat_dataset(session, created_by=admin_id, name="GD Title")

    resp = await client.get(f"/datasets/{ds.id}/geodcat-ap/", headers=admin_auth_header)
    data = resp.json()
    assert data["@type"] == "dcat:Dataset"
    assert str(ds.id) in data["@id"]
    assert data["dcterms:title"] == {"@value": "GD Title", "@language": "en"}
    assert data["dcterms:description"]["@value"] == "Description for GD Title"
    assert data["dcterms:identifier"] == str(ds.id)


@pytest.mark.anyio
async def test_single_record_geodcat_ap_iso_field_mapping(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """ISO 19115 fields map to the expected GeoDCAT-AP terms."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_geodcat_dataset(session, created_by=admin_id, srid=4326)

    resp = await client.get(f"/datasets/{ds.id}/geodcat-ap/", headers=admin_auth_header)
    data = resp.json()

    # Lineage -> provenance
    assert data["dcterms:provenance"]["@type"] == "dcterms:ProvenanceStatement"
    assert (
        data["dcterms:provenance"]["rdfs:label"]["@value"]
        == "Derived from open data sources"
    )
    # Maintenance frequency
    assert data["dcterms:accrualPeriodicity"] == "annually"
    # Constraints
    assert data["dcterms:accessRights"]["rdfs:label"] == "Public access, no limitations"
    assert data["dcterms:rights"]["rdfs:label"] == "Attribution required"
    # CRS / reference system -> conformsTo OGC EPSG URI
    assert data["dcterms:conformsTo"] == {
        "@id": "http://www.opengis.net/def/crs/EPSG/0/4326"
    }
    # Theme categories
    assert data["dcat:theme"][0]["@type"] == "skos:Concept"
    assert data["dcat:theme"][0]["skos:prefLabel"]["@value"] == "environment"


@pytest.mark.anyio
async def test_single_record_geodcat_ap_extents(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Temporal PeriodOfTime + spatial GeoSPARQL WKT bbox serialize correctly."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_geodcat_dataset(session, created_by=admin_id)

    resp = await client.get(f"/datasets/{ds.id}/geodcat-ap/", headers=admin_auth_header)
    data = resp.json()
    temporal = data["dcterms:temporal"]
    assert temporal["@type"] == "dcterms:PeriodOfTime"
    assert temporal["dcat:startDate"] == "2020-01-01"
    assert temporal["dcat:endDate"] == "2024-12-31"

    spatial = data["dcterms:spatial"]
    assert spatial["@type"] == "dcterms:Location"
    bbox = spatial["dcat:bbox"]
    assert bbox["@type"] == "gsp:wktLiteral"
    assert "CRS84" in bbox["@value"]
    assert "POLYGON((" in bbox["@value"]


@pytest.mark.anyio
async def test_single_record_geodcat_ap_pointofcontact_role(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """A pointOfContact CI_RoleCode maps to dcat:contactPoint vcard:Kind."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_geodcat_dataset(
        session, created_by=admin_id, contact_role="pointOfContact"
    )

    resp = await client.get(f"/datasets/{ds.id}/geodcat-ap/", headers=admin_auth_header)
    data = resp.json()
    contacts = data["dcat:contactPoint"]
    assert contacts[0]["@type"] == "vcard:Kind"
    assert contacts[0]["vcard:fn"] == "Jane Doe"
    assert contacts[0]["vcard:hasEmail"] == "mailto:jane@example.com"


@pytest.mark.anyio
async def test_single_record_geodcat_ap_custodian_role(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """A custodian CI_RoleCode maps to the geodcat:custodian property."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_geodcat_dataset(
        session, created_by=admin_id, contact_role="custodian"
    )

    resp = await client.get(f"/datasets/{ds.id}/geodcat-ap/", headers=admin_auth_header)
    data = resp.json()
    assert "geodcat:custodian" in data
    custodian = data["geodcat:custodian"]
    assert custodian["@type"] == "foaf:Agent"
    assert custodian["foaf:name"] == "Jane Doe"
    assert custodian["foaf:mbox"] == "mailto:jane@example.com"
    # custodian is not a contactPoint
    assert "dcat:contactPoint" not in data


@pytest.mark.anyio
async def test_single_record_geodcat_ap_distribution_absolute_url(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """dcat:distribution has absolute accessURL/downloadURL."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_geodcat_dataset(session, created_by=admin_id)

    resp = await client.get(f"/datasets/{ds.id}/geodcat-ap/", headers=admin_auth_header)
    data = resp.json()
    dist = data["dcat:distribution"][0]
    assert dist["@type"] == "dcat:Distribution"
    assert dist["dcat:accessURL"]["@id"].startswith("http")
    assert dist["dcat:downloadURL"]["@id"].startswith("http")
    assert str(ds.id) in dist["dcat:accessURL"]["@id"]


@pytest.mark.anyio
async def test_geodcat_ap_service_distribution_emits_data_service(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Service-like distributions expose dcat:DataService metadata."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_geodcat_dataset(session, created_by=admin_id)
    session.add(
        RecordDistribution(
            record_id=ds.record_id,
            distribution_type="api",
            format="ogcapi-features",
            url=f"/ogc/collections/{ds.id}/items",
            title="OGC API Features endpoint",
            media_type="application/geo+json",
            is_primary=False,
            auto_generated=True,
        )
    )
    await session.commit()

    resp = await client.get(f"/datasets/{ds.id}/geodcat-ap/", headers=admin_auth_header)
    data = resp.json()
    services = [
        d["dcat:accessService"]
        for d in data["dcat:distribution"]
        if "dcat:accessService" in d
    ]
    assert services
    assert services[0]["@type"] == "dcat:DataService"
    assert services[0]["dcterms:title"] == "OGC API Features endpoint"
    assert services[0]["dcat:endpointURL"]["@id"].startswith("http")


@pytest.mark.anyio
async def test_single_record_geodcat_ap_404_for_missing(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """GET /datasets/{random_uuid}/geodcat-ap/ returns 404."""
    random_id = uuid.uuid4()
    resp = await client.get(
        f"/datasets/{random_id}/geodcat-ap/", headers=admin_auth_header
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Catalog GeoDCAT-AP tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_catalog_geodcat_ap_has_context(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """GET /datasets/geodcat-ap/ returns a dcat:Catalog with @context."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    await _create_geodcat_dataset(session, created_by=admin_id)

    resp = await client.get("/datasets/geodcat-ap/", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "@context" in data
    assert data["@type"] == "dcat:Catalog"
    assert "dcat:dataset" in data


@pytest.mark.anyio
async def test_catalog_geodcat_ap_includes_visible_datasets(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Catalog feed contains the visible dataset in dcat:dataset."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_geodcat_dataset(
        session, created_by=admin_id, name="GeoDCAT Visible"
    )

    resp = await client.get("/datasets/geodcat-ap/", headers=admin_auth_header)
    data = resp.json()
    dataset_ids = [d["@id"] for d in data["dcat:dataset"]]
    assert any(str(ds.id) in did for did in dataset_ids)


@pytest.mark.anyio
async def test_catalog_geodcat_ap_excludes_private_datasets(
    client: AsyncClient,
    test_db_session,
):
    """Unauthenticated GeoDCAT-AP catalog excludes private datasets."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_geodcat_dataset(
        session,
        created_by=admin_id,
        name="Private GeoDCAT",
        visibility="private",
    )

    resp = await client.get("/datasets/geodcat-ap/")
    assert resp.status_code == 200
    data = resp.json()
    dataset_ids = [d["@id"] for d in data["dcat:dataset"]]
    assert not any(str(ds.id) in did for did in dataset_ids)


@pytest.mark.anyio
async def test_catalog_geodcat_ap_nested_entries_no_context(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Individual datasets in the catalog feed do NOT repeat @context."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    await _create_geodcat_dataset(session, created_by=admin_id)

    resp = await client.get("/datasets/geodcat-ap/", headers=admin_auth_header)
    data = resp.json()
    for entry in data["dcat:dataset"]:
        assert "@context" not in entry


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_single_record_geodcat_ap_validation_passes(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Validation report passes for a complete dataset."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_geodcat_dataset(session, created_by=admin_id)

    resp = await client.get(
        f"/datasets/{ds.id}/geodcat-ap/validation/", headers=admin_auth_header
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report == {
        "schema": "Dataset",
        "valid": True,
        "error_count": 0,
        "errors": [],
    }


@pytest.mark.anyio
async def test_single_record_geodcat_ap_validation_reports_gaps(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Validation reports missing mandatory description instead of hiding it."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_geodcat_dataset(
        session, created_by=admin_id, visibility="private"
    )
    # Strip the summary so dcterms:description goes missing.
    await session.execute(
        text(
            "UPDATE catalog.records SET summary = NULL "
            "WHERE id = (SELECT record_id FROM catalog.datasets WHERE id = :id)"
        ),
        {"id": str(ds.id)},
    )
    await session.commit()

    resp = await client.get(
        f"/datasets/{ds.id}/geodcat-ap/validation/", headers=admin_auth_header
    )
    assert resp.status_code == 200
    report = resp.json()
    assert report["schema"] == "Dataset"
    assert report["valid"] is False
    assert report["error_count"] >= 1
    assert any(
        error["validator"] == "required" and "dcterms:description" in error["message"]
        for error in report["errors"]
    )


@pytest.mark.anyio
async def test_catalog_geodcat_ap_validation_passes(
    client: AsyncClient,
    test_db_session,
):
    """Catalog validation report uses the visible GeoDCAT-AP payload."""
    session = test_db_session
    # Truncate so this validates only its own dataset under pytest -n 4.
    for _table in ("catalog.datasets", "catalog.records", "catalog.collections"):
        await session.execute(text(f"TRUNCATE TABLE {_table} CASCADE"))
    await session.commit()
    admin_id = await get_user_id(session, "admin")
    await _create_geodcat_dataset(session, created_by=admin_id)

    resp = await client.get("/datasets/geodcat-ap/validation/")
    assert resp.status_code == 200
    report = resp.json()
    assert report["schema"] == "Catalog"
    assert report["valid"] is True
    assert report["error_count"] == 0


# ---------------------------------------------------------------------------
# Round-trip: create -> edit -> GeoDCAT-AP output passes validation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_geodcat_ap_round_trip_after_edit(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Editing ISO metadata is reflected in the GeoDCAT-AP output + validates."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_geodcat_dataset(
        session, created_by=admin_id, name="RoundTrip Original"
    )

    # Edit the record metadata directly (simulating a metadata update).
    await session.execute(
        text(
            "UPDATE catalog.records "
            "SET title = :title, lineage_summary = :lineage, "
            "    update_frequency = :freq "
            "WHERE id = (SELECT record_id FROM catalog.datasets WHERE id = :id)"
        ),
        {
            "title": "RoundTrip Edited",
            "lineage": "Re-derived after edit",
            "freq": "monthly",
            "id": str(ds.id),
        },
    )
    await session.commit()

    resp = await client.get(f"/datasets/{ds.id}/geodcat-ap/", headers=admin_auth_header)
    data = resp.json()
    assert data["dcterms:title"]["@value"] == "RoundTrip Edited"
    assert data["dcterms:provenance"]["rdfs:label"]["@value"] == "Re-derived after edit"
    assert data["dcterms:accrualPeriodicity"] == "monthly"

    # The edited output still validates.
    val = await client.get(
        f"/datasets/{ds.id}/geodcat-ap/validation/", headers=admin_auth_header
    )
    assert val.json()["valid"] is True


@pytest.mark.anyio
async def test_geodcat_ap_version_pinned():
    """The targeted GeoDCAT-AP version is pinned at 2.0.0."""
    assert GEODCAT_AP_SCHEMA_VERSION == "2.0.0"
