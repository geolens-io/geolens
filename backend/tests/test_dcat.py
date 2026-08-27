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
from sqlalchemy import text
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordContact,
    RecordDistribution,
    RecordKeyword,
    RecordTranslation,
)

from tests.factories import get_user_id


@pytest.fixture(autouse=True)
def _configured_dcat_contact(monkeypatch):
    """Model the required deployment mailbox unless a test removes it."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "dcat_contact_email", "catalog@example.gov")


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


async def _create_dcat_raster_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str = "DCAT Raster Dataset",
    record_type: str = "raster_dataset",
    source_format: str = "geotiff",
    storage_key: str | None = None,
) -> Dataset:
    """Insert a raster-family Record + Dataset shaped like the ingest tails.

    ``storage_key`` models the row ``tasks_raster``/``tasks_vrt``/the swap
    write: ``url`` is the object-storage KEY of the COG, with no title and no
    media type. Left None for the STAC-import shape, which writes no
    distribution row at all.
    """
    record = Record(
        title=name,
        summary=f"Description for {name}",
        record_type=record_type,
        visibility="public",
        record_status="published",
        created_by=created_by,
        license="CC-BY-4.0",
        spatial_extent=WKTElement(_NYC_EXTENT, srid=4326),
    )
    session.add(record)
    await session.flush()

    dataset = Dataset(
        record_id=record.id,
        table_name=f"ras_{uuid.uuid4().hex[:12]}",
        srid=4326,
        geometry_type=None,
        source_format=source_format,
        source_filename=f"{name}.tif",
    )
    session.add(dataset)
    await session.flush()

    if storage_key is not None:
        session.add(
            RecordDistribution(
                record_id=record.id,
                distribution_type="download",
                format="vrt" if record_type == "vrt_dataset" else "geotiff",
                url=storage_key,
            )
        )

    await session.commit()
    await session.refresh(dataset)
    return dataset


def _access_urls(document: object, key: str = "dcat:accessURL") -> list[str]:
    """Every access URL anywhere in a JSON-LD document.

    Handles both spellings the profiles use: a bare string (DCAT 3, DCAT-US)
    and a ``{"@id": ...}`` node reference (GeoDCAT-AP).
    """
    found: list[str] = []

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for found_key, nested in value.items():
                if found_key == key:
                    if isinstance(nested, str):
                        found.append(nested)
                    elif isinstance(nested, dict) and isinstance(
                        nested.get("@id"), str
                    ):
                        found.append(nested["@id"])
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(document)
    return found


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

    resp = await client.get(
        f"/datasets/{ds.id}/dcat/",
        headers={**admin_auth_header, "Accept-Language": "fr"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-language"] == "en"
    data = resp.json()
    assert "@context" in data
    ctx = data["@context"]
    for prefix in ["dcat", "dcterms", "foaf", "skos", "vcard", "xsd"]:
        assert prefix in ctx, f"Missing namespace prefix: {prefix}"


@pytest.mark.anyio
async def test_dcat_invalid_limit_uses_standards_problem_detail(client: AsyncClient):
    response = await client.get("/datasets/dcat/", params={"limit": 0})

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 400


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
async def test_record_language_headers_match_each_serialized_profile(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_dcat_dataset(test_db_session, created_by=admin_id)
    ds.record.language = "pt-BR"
    await test_db_session.commit()

    dcat = await client.get(f"/datasets/{ds.id}/dcat/", headers=admin_auth_header)
    assert dcat.status_code == 200
    assert dcat.json()["dcterms:title"]["@language"] == "pt-BR"
    assert dcat.json()["dcterms:language"]["@id"].endswith("/POR")
    assert dcat.headers["content-language"] == "pt-BR"

    dcat_us = await client.get(
        f"/datasets/{ds.id}/dcat-us/3.0/", headers=admin_auth_header
    )
    assert dcat_us.status_code == 200
    assert dcat_us.json()["language"] == "pt"
    assert dcat_us.headers["content-language"] == "pt"


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
async def test_single_record_dcat_negotiates_stored_translation(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_dcat_dataset(
        test_db_session, created_by=admin_id, name="English Rivers"
    )
    test_db_session.add(
        RecordTranslation(
            record_id=ds.record_id,
            language="de",
            title="Deutsche Flüsse",
            summary="Deutsche Zusammenfassung",
        )
    )
    await test_db_session.commit()

    resp = await client.get(
        f"/datasets/{ds.id}/dcat/",
        headers={**admin_auth_header, "Accept-Language": "de-DE, en;q=0.5"},
    )
    assert resp.status_code == 200
    assert "content-language" not in resp.headers
    assert "Accept-Language" in resp.headers["vary"]
    assert resp.json()["dcterms:title"] == {
        "@value": "Deutsche Flüsse",
        "@language": "de",
    }
    assert resp.json()["dcterms:description"] == {
        "@value": "Deutsche Zusammenfassung",
        "@language": "de",
    }


@pytest.mark.anyio
async def test_dcat_title_only_regional_translation_preserves_field_languages(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_dcat_dataset(
        test_db_session, created_by=admin_id, name="English Wetlands"
    )
    test_db_session.add(
        RecordTranslation(
            record_id=ds.record_id,
            language="pt-BR",
            title="Zonas úmidas brasileiras",
            summary=None,
        )
    )
    await test_db_session.commit()

    resp = await client.get(
        f"/datasets/{ds.id}/dcat/",
        headers={**admin_auth_header, "Accept-Language": "pt-BR"},
    )

    assert resp.status_code == 200
    assert "content-language" not in resp.headers
    assert "Accept-Language" in resp.headers["vary"]
    data = resp.json()
    assert data["dcterms:title"] == {
        "@value": "Zonas úmidas brasileiras",
        "@language": "pt-BR",
    }
    assert data["dcterms:description"] == {
        "@value": "Description for English Wetlands",
        "@language": "en",
    }
    assert data["dcterms:language"]["@id"].endswith("/POR")
    assert data["dcterms:provenance"]["@language"] == "en"
    assert all(
        theme["skos:prefLabel"]["@language"] == "en" for theme in data["dcat:theme"]
    )


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
async def test_single_record_dcat_us3_validation_report_passes(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Validation report passes for a dataset with required DCAT-US metadata."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(session, created_by=admin_id)

    resp = await client.get(
        f"/datasets/{ds.id}/dcat-us/3.0/validation/",
        headers=admin_auth_header,
    )

    assert resp.status_code == 200
    report = resp.json()
    assert report == {
        "schema": "Dataset",
        "valid": True,
        "error_count": 0,
        "errors": [],
        "uses_metadata_fallback": False,
        "metadata_fallback_fields": [],
    }


@pytest.mark.anyio
async def test_single_record_dcat_us3_validation_reports_metadata_gaps(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
):
    """Missing record and configured contacts are explicit, never filtered."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "dcat_contact_email", None)
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_dataset(
        session,
        created_by=admin_id,
        visibility="private",
        with_contact=False,
    )

    resp = await client.get(
        f"/datasets/{ds.id}/dcat-us/3.0/validation/",
        headers=admin_auth_header,
    )

    assert resp.status_code == 200
    report = resp.json()
    assert report["schema"] == "Dataset"
    assert report["valid"] is False
    assert report["error_count"] >= 1
    assert any(
        error["path"] == "$"
        and error["validator"] == "required"
        and "contactPoint" in error["message"]
        for error in report["errors"]
    )

    export = await client.get(
        f"/datasets/{ds.id}/dcat-us/3.0/",
        headers=admin_auth_header,
    )
    assert export.status_code == 503
    assert "application/problem+json" in export.headers["content-type"]
    assert "DCAT_CONTACT_EMAIL" in export.json()["detail"]

    catalog = await client.get(
        "/datasets/dcat-us/3.0/",
        headers=admin_auth_header,
    )
    assert catalog.status_code == 503
    assert "application/problem+json" in catalog.headers["content-type"]

    catalog_validation = await client.get(
        "/datasets/dcat-us/3.0/validation/",
        headers=admin_auth_header,
    )
    catalog_report = catalog_validation.json()
    assert catalog_report["valid"] is False
    assert catalog_report["source_dataset_count"] >= 1
    assert (
        catalog_report["serialized_dataset_count"]
        == catalog_report["source_dataset_count"]
    )
    assert catalog_report["excluded_dataset_count"] == 0


@pytest.mark.anyio
async def test_dcat_us3_configured_catalog_contact_is_conformant_fallback(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
):
    """A monitored organization mailbox fills contactPoint without fake PII."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "dcat_contact_email", "metadata@example.gov")
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_dcat_dataset(
        test_db_session,
        created_by=admin_id,
        with_contact=False,
    )
    ds.record.source_organization = "USGS"
    await test_db_session.commit()

    export = await client.get(
        f"/datasets/{ds.id}/dcat-us/3.0/",
        headers=admin_auth_header,
    )
    assert export.status_code == 200, export.text
    assert export.headers["x-geolens-metadata-fallback-fields"] == "contactPoint"
    contact = export.json()["contactPoint"][0]
    assert export.json()["publisher"]["name"] == "USGS"
    assert contact == {
        "@type": "Kind",
        "fn": "Catalog metadata contact",
        "hasEmail": "mailto:metadata@example.gov",
    }

    validation = await client.get(
        f"/datasets/{ds.id}/dcat-us/3.0/validation/",
        headers=admin_auth_header,
    )
    report = validation.json()
    assert report["valid"] is True, report
    assert report["metadata_fallback_fields"] == ["contactPoint"]


@pytest.mark.anyio
async def test_catalog_dcat_us3_validation_report_passes(
    client: AsyncClient,
    test_db_session,
):
    """Catalog validation report uses the visible DCAT-US catalog payload."""
    session = test_db_session
    # The catalog validation endpoint validates the entire anonymous-visible
    # catalog. Under `pytest -n 4` the shared per-worker DB can carry public
    # non-conforming datasets left by sibling tests, flipping valid->False.
    # Truncate catalog tables first so this validates only its own dataset.
    for _table in ("catalog.datasets", "catalog.records", "catalog.collections"):
        await session.execute(text(f"TRUNCATE TABLE {_table} CASCADE"))
    await session.commit()
    admin_id = await get_user_id(session, "admin")
    await _create_dcat_dataset(session, created_by=admin_id)

    resp = await client.get("/datasets/dcat-us/3.0/validation/")

    assert resp.status_code == 200
    report = resp.json()
    assert report["schema"] == "Catalog"
    assert report["valid"] is True
    assert report["error_count"] == 0


@pytest.mark.anyio
async def test_single_record_dcat_404_for_missing(
    client: AsyncClient,
    admin_auth_header: dict,
):
    """GET /datasets/{random_uuid}/dcat/ returns 404."""
    random_id = uuid.uuid4()
    resp = await client.get(f"/datasets/{random_id}/dcat/", headers=admin_auth_header)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Raster distributions (#1469)
# ---------------------------------------------------------------------------

_STORAGE_KEY = (
    "rasters/6e9ca821-3345-4c30-bcf8-935bc6dbd61f/1954d0c080b1/source.cog.tif"
)


def _raster_tile_distributions(entry: dict, dataset_id: uuid.UUID) -> list[dict]:
    return [
        d
        for d in entry.get("dcat:distribution", [])
        if f"/raster-tiles/{dataset_id}/tiles/" in d.get("dcat:accessURL", "")
    ]


@pytest.mark.anyio
async def test_dcat_feed_never_exposes_a_storage_key(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """No accessURL in the feed is an object-storage key.

    The COG-backed and VRT ingest tails write a distribution row whose url is
    the storage key. DCAT 3 emitted it verbatim; the DCAT-US and GeoDCAT-AP
    profiles glued it onto the API origin, which resolves to nothing and
    exposes the same layout. All three now drop it.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    await _create_dcat_raster_dataset(
        session, created_by=admin_id, name="COG Raster", storage_key=_STORAGE_KEY
    )
    await _create_dcat_raster_dataset(
        session,
        created_by=admin_id,
        name="VRT Mosaic",
        record_type="vrt_dataset",
        storage_key="vrt/3d1b/mosaic.vrt",
    )

    for path, key in (
        ("/datasets/dcat/", "dcat:accessURL"),
        ("/datasets/dcat-us/3.0/", "accessURL"),
        ("/datasets/geodcat-ap/", "dcat:accessURL"),
    ):
        resp = await client.get(path, headers=admin_auth_header)
        assert resp.status_code == 200, path
        urls = _access_urls(resp.json(), key)
        assert urls, f"{path} published no access URLs at all"
        assert not [u for u in urls if u.startswith("rasters/")], path
        assert not [u for u in urls if "source.cog.tif" in u], path
        assert all(u.startswith("http") for u in urls), path


@pytest.mark.anyio
async def test_dcat_feed_gives_every_dataset_a_distribution(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Including STAC-origin rasters, which carry no distribution row.

    Scoped to the datasets this test creates rather than asserted over the
    whole feed. "Every dataset has a distribution" is a property of datasets
    created through the real creation paths (which call
    ``generate_distributions``), not of the table: under ``pytest -n 4`` the
    shared per-worker DB carries public datasets that sibling tests inserted
    as bare ORM rows, and a feed-wide assertion fails on those instead — 56
    of them, on the first CI run of this test.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    created = {
        "vector": await _create_dcat_dataset(
            session, created_by=admin_id, name="Vector"
        ),
        "COG-backed raster": await _create_dcat_raster_dataset(
            session, created_by=admin_id, name="COG Raster", storage_key=_STORAGE_KEY
        ),
        "STAC-origin raster": await _create_dcat_raster_dataset(
            session, created_by=admin_id, name="Sentinel-2 Scene", source_format="stac"
        ),
    }

    resp = await client.get("/datasets/dcat/", headers=admin_auth_header)
    entries = {e["dcterms:identifier"]: e for e in resp.json()["dcat:dataset"]}
    for label, dataset in created.items():
        entry = entries.get(str(dataset.id))
        assert entry is not None, f"{label} missing from the feed"
        assert entry.get("dcat:distribution"), f"{label} has no access method"


@pytest.mark.anyio
@pytest.mark.parametrize("source_format", ["geotiff", "stac"])
async def test_dcat_raster_advertises_the_tile_template(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    source_format: str,
):
    """Both raster origins advertise the template STAC already publishes.

    The COG-backed case has a storage-key row to replace; the STAC-origin
    case has no row at all and no local COG to point at, so the template is
    the only access surface it can offer.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_raster_dataset(
        session,
        created_by=admin_id,
        name=f"Raster {source_format}",
        source_format=source_format,
        storage_key=_STORAGE_KEY if source_format == "geotiff" else None,
    )

    resp = await client.get(f"/datasets/{ds.id}/dcat/", headers=admin_auth_header)
    assert resp.status_code == 200
    tiles = _raster_tile_distributions(resp.json(), ds.id)
    assert len(tiles) == 1, resp.json().get("dcat:distribution")
    assert tiles[0]["dcterms:title"] == "Raster Tiles"
    assert tiles[0]["dcat:mediaType"] == "image/png"
    assert tiles[0]["dcat:accessURL"].startswith("http")
    assert "{z}/{x}/{y}.png" in tiles[0]["dcat:accessURL"]


@pytest.mark.anyio
@pytest.mark.parametrize("record_type", ["raster_dataset", "vrt_dataset"])
async def test_dcat_raster_does_not_advertise_the_cog_download_url(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    record_type: str,
):
    """DCAT does not advertise ``/download/cog`` as a raster distribution URL.

    fix(anon-raster-download): a public+published raster (this fixture's
    shape) is now directly downloadable by an anonymous caller with no
    minted token, matching ``/export``'s anonymous-access contract. But a
    private/restricted/unpublished raster still is not, and DCAT's feed has
    no per-caller way to express that distinction in a single accessURL —
    advertising the download link unconditionally would still publish one
    that 404s for a generic DCAT client crawling a catalog that also lists
    non-public datasets.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_dcat_raster_dataset(
        session,
        created_by=admin_id,
        name=f"Raster {record_type}",
        record_type=record_type,
        storage_key=_STORAGE_KEY,
    )

    resp = await client.get(f"/datasets/{ds.id}/dcat/", headers=admin_auth_header)
    dists = resp.json()["dcat:distribution"]
    assert len(_raster_tile_distributions(resp.json(), ds.id)) == 1
    assert not [d for d in dists if "/download/cog" in d["dcat:accessURL"]]
