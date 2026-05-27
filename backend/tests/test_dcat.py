"""Tests for DCAT 3 JSON-LD export endpoints.

Verifies:
  - Single record DCAT has correct @context, @type, @id, and namespace prefixes
  - Catalog DCAT feed includes visible datasets and excludes private ones
  - Distribution URLs are absolute
  - Individual datasets in catalog feed do NOT repeat @context
  - Contacts, keywords, temporal, spatial serialized correctly
"""

import uuid
from datetime import date

import pytest
from geoalchemy2 import WKTElement
from httpx import AsyncClient
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordContact,
    RecordDistribution,
    RecordKeyword,
)

from tests.factories import get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NYC_EXTENT = (
    "SRID=4326;POLYGON((-74.1 40.5, -74.1 40.9, -73.7 40.9, -73.7 40.5, -74.1 40.5))"
)


async def _create_dcat_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str = "DCAT Test Dataset",
    visibility: str = "public",
    with_contact: bool = True,
    with_keyword: bool = True,
    with_distribution: bool = True,
    with_spatial: bool = True,
    with_temporal: bool = True,
) -> Dataset:
    """Insert a Record + Dataset with full metadata for DCAT tests."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Description for {name}",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
        license="CC-BY-4.0",
        lineage_summary="Derived from open data sources",
        update_frequency="annually",
        access_constraints="Public access",
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
        srid=4326,
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
                role="pointOfContact",
                name="Jane Doe",
                email="jane@example.com",
                organization="GeoOrg",
            )
        )

    if with_keyword:
        session.add(
            RecordKeyword(
                record_id=record.id,
                keyword="hydrology",
            )
        )

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
# Single record DCAT tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_single_record_dcat_has_context(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """GET /datasets/{id}/dcat/ returns JSON with @context containing all 6 namespace prefixes."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(session, created_by=admin_id)

    resp = await client.get(f"/datasets/{ds.id}/dcat/", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "@context" in data
    ctx = data["@context"]
    for prefix in ["dcat", "dcterms", "foaf", "skos", "vcard", "xsd"]:
        assert prefix in ctx, f"Missing namespace prefix: {prefix}"


@pytest.mark.anyio
async def test_single_record_dcat_has_type_and_id(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """@type is dcat:Dataset, @id contains the dataset UUID."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(session, created_by=admin_id)

    resp = await client.get(f"/datasets/{ds.id}/dcat/", headers=admin_auth_header)
    data = resp.json()
    assert data["@type"] == "dcat:Dataset"
    assert str(ds.id) in data["@id"]


@pytest.mark.anyio
async def test_single_record_dcat_has_title_and_description(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """dcterms:title matches record title, dcterms:description matches summary."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(
        session, created_by=admin_id, name="Title Desc Test"
    )

    resp = await client.get(f"/datasets/{ds.id}/dcat/", headers=admin_auth_header)
    data = resp.json()
    assert data["dcterms:title"] == {"@value": "Title Desc Test", "@language": "en"}
    assert data["dcterms:description"] == {
        "@value": "Description for Title Desc Test",
        "@language": "en",
    }


@pytest.mark.anyio
async def test_single_record_dcat_has_keywords(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """dcat:keyword is a list of keyword strings."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(session, created_by=admin_id)

    resp = await client.get(f"/datasets/{ds.id}/dcat/", headers=admin_auth_header)
    data = resp.json()
    assert "dcat:keyword" in data
    keywords = data["dcat:keyword"]
    assert isinstance(keywords, list)
    assert "hydrology" in keywords


@pytest.mark.anyio
async def test_single_record_dcat_has_contacts(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """dcat:contactPoint is a list with vcard properties."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(session, created_by=admin_id)

    resp = await client.get(f"/datasets/{ds.id}/dcat/", headers=admin_auth_header)
    data = resp.json()
    assert "dcat:contactPoint" in data
    contacts = data["dcat:contactPoint"]
    assert isinstance(contacts, list)
    assert len(contacts) >= 1
    c = contacts[0]
    assert c["@type"] == "vcard:Kind"
    assert c["vcard:fn"] == "Jane Doe"
    assert c["vcard:hasEmail"] == "jane@example.com"
    assert c["vcard:organization-name"] == "GeoOrg"


@pytest.mark.anyio
async def test_single_record_dcat_has_distributions(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """dcat:distribution is a list with absolute URLs in dcat:accessURL."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(session, created_by=admin_id)

    resp = await client.get(f"/datasets/{ds.id}/dcat/", headers=admin_auth_header)
    data = resp.json()
    assert "dcat:distribution" in data
    dists = data["dcat:distribution"]
    assert isinstance(dists, list)
    assert len(dists) >= 1
    d = dists[0]
    assert d["@type"] == "dcat:Distribution"
    assert d["dcat:accessURL"].startswith("http"), "Distribution URL must be absolute"
    assert str(ds.id) in d["dcat:accessURL"]


@pytest.mark.anyio
async def test_single_record_dcat_has_provenance(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """dcterms:provenance matches lineage_summary."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(session, created_by=admin_id)

    resp = await client.get(f"/datasets/{ds.id}/dcat/", headers=admin_auth_header)
    data = resp.json()
    assert data["dcterms:provenance"] == {
        "@value": "Derived from open data sources",
        "@language": "en",
    }


@pytest.mark.anyio
async def test_single_record_dcat_has_temporal(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """dcterms:temporal has @type and date fields."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(session, created_by=admin_id)

    resp = await client.get(f"/datasets/{ds.id}/dcat/", headers=admin_auth_header)
    data = resp.json()
    assert "dcterms:temporal" in data
    temporal = data["dcterms:temporal"]
    assert temporal["@type"] == "dcterms:PeriodOfTime"
    assert temporal["dcat:startDate"] == "2020-01-01"
    assert temporal["dcat:endDate"] == "2024-12-31"


@pytest.mark.anyio
async def test_single_record_dcat_media_type(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Response Content-Type is application/ld+json."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(session, created_by=admin_id)

    resp = await client.get(f"/datasets/{ds.id}/dcat/", headers=admin_auth_header)
    assert resp.status_code == 200
    assert "application/ld+json" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# Catalog DCAT tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_catalog_dcat_has_context(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """GET /datasets/dcat/ returns JSON with @context, @type is dcat:Catalog."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    await _create_dcat_dataset(session, created_by=admin_id)

    resp = await client.get("/datasets/dcat/", headers=admin_auth_header)
    assert resp.status_code == 200
    data = resp.json()
    assert "@context" in data
    assert data["@type"] == "dcat:Catalog"
    assert "dcat:dataset" in data


@pytest.mark.anyio
async def test_catalog_dcat_includes_visible_datasets(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Catalog feed contains the test dataset in dcat:dataset array."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(
        session, created_by=admin_id, name="Catalog Visible"
    )

    resp = await client.get("/datasets/dcat/", headers=admin_auth_header)
    data = resp.json()
    dataset_ids = [d["@id"] for d in data["dcat:dataset"]]
    matching = [did for did in dataset_ids if str(ds.id) in did]
    assert len(matching) >= 1, f"Dataset {ds.id} not found in catalog feed"


@pytest.mark.anyio
async def test_catalog_dcat_excludes_private_datasets(
    client: AsyncClient,
    test_db_session,
):
    """Unauthenticated GET /datasets/dcat/ does NOT include private datasets."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(
        session,
        created_by=admin_id,
        name="Private DCAT",
        visibility="private",
    )

    # Unauthenticated request
    resp = await client.get("/datasets/dcat/")
    assert resp.status_code == 200
    data = resp.json()
    dataset_ids = [d["@id"] for d in data["dcat:dataset"]]
    matching = [did for did in dataset_ids if str(ds.id) in did]
    assert len(matching) == 0, (
        "Private dataset should NOT appear in unauthenticated catalog"
    )


@pytest.mark.anyio
async def test_catalog_datasets_no_context(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Individual datasets within dcat:dataset array do NOT have @context key."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    await _create_dcat_dataset(session, created_by=admin_id)

    resp = await client.get("/datasets/dcat/", headers=admin_auth_header)
    data = resp.json()
    for ds_entry in data["dcat:dataset"]:
        assert "@context" not in ds_entry, (
            "Individual catalog entries must not repeat @context"
        )


@pytest.mark.anyio
async def test_single_record_dcat_us3_has_required_profile_fields(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """GET /datasets/{id}/dcat-us/3.0/ returns DCAT-US 3.0 field names."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(session, created_by=admin_id)

    resp = await client.get(
        f"/datasets/{ds.id}/dcat-us/3.0/", headers=admin_auth_header
    )

    assert resp.status_code == 200
    assert "application/ld+json" in resp.headers["content-type"]
    data = resp.json()
    assert data["@context"] == "https://resources.data.gov/dcat-us/3.0.0"
    assert data["@type"] == "Dataset"
    assert data["identifier"] == str(ds.id)
    assert data["title"] == "DCAT Test Dataset"
    assert data["description"] == "Description for DCAT Test Dataset"
    assert data["publisher"] == {"@type": "Organization", "name": "GeoLens"}
    assert data["contactPoint"][0]["@type"] == "Kind"
    assert data["contactPoint"][0]["fn"] == "Jane Doe"
    assert data["contactPoint"][0]["hasEmail"] == "mailto:jane@example.com"
    assert data["temporal"] == [
        {
            "@type": "PeriodOfTime",
            "startDate": "2020-01-01",
            "endDate": "2024-12-31",
        }
    ]
    assert data["spatial"]["@type"] == "Location"
    assert data["spatial"]["bbox"].startswith("POLYGON((")
    assert data["theme"] == [
        {"@type": "Concept", "prefLabel": "environment"},
        {"@type": "Concept", "prefLabel": "geoscience"},
    ]
    assert data["distribution"][0]["@type"] == "Distribution"
    assert data["distribution"][0]["downloadURL"].startswith("http")


@pytest.mark.anyio
async def test_catalog_dcat_us3_includes_visible_datasets(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Catalog feed contains visible datasets in the DCAT-US dataset array."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(
        session, created_by=admin_id, name="DCAT-US Visible"
    )

    resp = await client.get("/datasets/dcat-us/3.0/", headers=admin_auth_header)

    assert resp.status_code == 200
    data = resp.json()
    assert data["@type"] == "Catalog"
    dataset_ids = [d["@id"] for d in data["dataset"]]
    assert any(str(ds.id) in dataset_id for dataset_id in dataset_ids)


@pytest.mark.anyio
async def test_catalog_dcat_us3_excludes_private_datasets(
    client: AsyncClient,
    test_db_session,
):
    """Unauthenticated DCAT-US catalog feed excludes private datasets."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(
        session,
        created_by=admin_id,
        name="Private DCAT-US",
        visibility="private",
    )

    resp = await client.get("/datasets/dcat-us/3.0/")

    assert resp.status_code == 200
    data = resp.json()
    dataset_ids = [d["@id"] for d in data["dataset"]]
    assert not any(str(ds.id) in dataset_id for dataset_id in dataset_ids)


@pytest.mark.anyio
async def test_dcat_us3_service_distribution_emits_data_service(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Service-like distributions can expose DCAT-US DataService metadata."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(session, created_by=admin_id)
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

    resp = await client.get(
        f"/datasets/{ds.id}/dcat-us/3.0/", headers=admin_auth_header
    )

    assert resp.status_code == 200
    data = resp.json()
    services = [
        service
        for dist in data["distribution"]
        for service in dist.get("accessService", [])
    ]
    assert services
    assert services[0]["@type"] == "DataService"
    assert services[0]["title"] == "OGC API Features endpoint"
    assert services[0]["endpointURL"][0].startswith("http")
    assert services[0]["contactPoint"][0]["hasEmail"] == "mailto:jane@example.com"


@pytest.mark.anyio
async def test_single_record_dcat_404_for_missing(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """GET /datasets/{random_uuid}/dcat/ returns 404."""
    random_id = uuid.uuid4()
    resp = await client.get(f"/datasets/{random_id}/dcat/", headers=admin_auth_header)
    assert resp.status_code == 404
