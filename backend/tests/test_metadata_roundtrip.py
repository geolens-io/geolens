"""Round-trip + filter-the-feed tests for catalog standards output (issue #203).

Verifies two guarantees of the DCAT-US metadata-completeness conformance work:

1. **Round-trip:** ingest -> PATCH editable metadata -> each edited field
   SURFACES in every standards serialization GeoLens emits: W3C DCAT 3,
   DCAT-US 3.0, GeoDCAT-AP 2.0.0, STAC, and the OGC API Records GeoJSON output.

2. **Filter-the-feed:** an INCOMPLETE record (missing a property mandatory for
   the profile) is EXCLUDED from the DCAT 3 / DCAT-US / GeoDCAT-AP catalog
   feeds, while a COMPLETE record is INCLUDED. The per-dataset endpoints still
   serialize the requested record as-is regardless of completeness.
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
from app.standards.stac.serializer import ogc_record_to_stac_item
from tests.factories import get_user_id

_NYC_EXTENT = (
    "SRID=4326;POLYGON((-74.1 40.5, -74.1 40.9, -73.7 40.9, -73.7 40.5, -74.1 40.5))"
)


async def _create_complete_dataset(
    session,
    *,
    created_by: uuid.UUID,
    name: str = "RoundTrip Dataset",
    visibility: str = "public",
    with_contact: bool = True,
) -> Dataset:
    """Insert a Record + Dataset that passes every profile's validator."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Description for {name}",
        visibility=visibility,
        record_status="published",
        created_by=created_by,
        license="https://creativecommons.org/licenses/by/4.0/",
        source_organization="Original Org",
        lineage_summary="Original lineage",
        update_frequency="annually",
        access_constraints="Public access",
        usage_constraints="Attribution required",
        theme_category=["environment"],
    )
    record.spatial_extent = WKTElement(_NYC_EXTENT, srid=4326)
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
    session.add(RecordKeyword(record_id=record.id, keyword="hydrology"))
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
# Round-trip: PATCH editable metadata -> surfaces in every standards output
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_edited_metadata_surfaces_in_all_standards_outputs(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """PATCH editable fields, then assert each edit surfaces in DCAT-3, DCAT-US,
    GeoDCAT-AP, STAC, and OGC Record outputs."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    ds = await _create_complete_dataset(
        session, created_by=admin_id, name="RoundTrip Original"
    )

    # --- Edit editable metadata via the public PATCH API (real round-trip) ---
    patch = {
        "title": "RoundTrip Edited Title",
        "summary": "RoundTrip edited description",
        "license": "https://creativecommons.org/licenses/by-sa/4.0/",
        "source_organization": "Edited Org",
        "lineage_summary": "Re-derived after edit",
        "update_frequency": "monthly",
        "theme_category": ["geoscience"],
    }
    resp = await client.patch(
        f"/datasets/{ds.id}", json=patch, headers=admin_auth_header
    )
    assert resp.status_code == 200, resp.text

    # --- DCAT 3 ---
    dcat = (
        await client.get(f"/datasets/{ds.id}/dcat/", headers=admin_auth_header)
    ).json()
    assert dcat["dcterms:title"]["@value"] == "RoundTrip Edited Title"
    assert dcat["dcterms:description"]["@value"] == "RoundTrip edited description"
    assert dcat["dcterms:license"] == patch["license"]
    assert dcat["dcterms:publisher"]["foaf:name"] == "Edited Org"
    assert dcat["dcterms:provenance"]["@value"] == "Re-derived after edit"
    assert dcat["dcterms:accrualPeriodicity"] == "monthly"

    # --- DCAT-US 3.0 ---
    dcat_us = (
        await client.get(f"/datasets/{ds.id}/dcat-us/3.0/", headers=admin_auth_header)
    ).json()
    assert dcat_us["title"] == "RoundTrip Edited Title"
    assert dcat_us["description"] == "RoundTrip edited description"
    assert dcat_us["publisher"]["name"] == "Edited Org"
    assert dcat_us["provenance"] == ["Re-derived after edit"]
    assert dcat_us["accrualPeriodicity"] == "monthly"

    # --- GeoDCAT-AP 2.0.0 ---
    geodcat = (
        await client.get(f"/datasets/{ds.id}/geodcat-ap/", headers=admin_auth_header)
    ).json()
    assert geodcat["dcterms:title"]["@value"] == "RoundTrip Edited Title"
    assert geodcat["dcterms:description"]["@value"] == "RoundTrip edited description"
    assert geodcat["dcterms:license"] == patch["license"]
    assert geodcat["dcterms:provenance"]["rdfs:label"]["@value"] == (
        "Re-derived after edit"
    )
    assert geodcat["dcterms:accrualPeriodicity"] == "monthly"

    # --- OGC API Records (GeoJSON Feature) ---
    ogc = (
        await client.get(
            f"/collections/datasets/items/{ds.id}", headers=admin_auth_header
        )
    ).json()
    props = ogc["properties"]
    assert props["title"] == "RoundTrip Edited Title"
    assert props["description"] == "RoundTrip edited description"
    assert props["license"] == patch["license"]
    assert props["source_organization"] == "Edited Org"
    assert props["lineage"] == "Re-derived after edit"
    assert props["update_frequency"] == "monthly"

    # --- STAC (serializer over the same OGC record) ---
    stac_item = ogc_record_to_stac_item(ogc, stac_api_url="http://testserver/stac")
    assert stac_item["properties"]["title"] == "RoundTrip Edited Title"
    assert stac_item["properties"]["description"] == "RoundTrip edited description"


# ---------------------------------------------------------------------------
# Filter-the-feed: incomplete record excluded, complete record included
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_incomplete_record_excluded_complete_included_in_feeds(
    client: AsyncClient,
    test_db_session,
):
    """A record missing a mandatory property is dropped from the DCAT-3 /
    DCAT-US / GeoDCAT-AP catalog feeds, while a complete record stays."""
    session = test_db_session
    # Isolate this worker's view of the anonymous catalog (pytest -n 4).
    for _table in ("catalog.datasets", "catalog.records", "catalog.collections"):
        await session.execute(text(f"TRUNCATE TABLE {_table} CASCADE"))
    await session.commit()

    admin_id = await get_user_id(session, "admin")
    complete = await _create_complete_dataset(
        session, created_by=admin_id, name="Complete Feed Record"
    )
    # Incomplete: missing summary (DCAT-3 / GeoDCAT-AP description) AND no
    # contact (DCAT-US mandatory contactPoint).
    incomplete = await _create_complete_dataset(
        session, created_by=admin_id, name="Incomplete Feed Record", with_contact=False
    )
    await session.execute(
        text(
            "UPDATE catalog.records SET summary = NULL "
            "WHERE id = (SELECT record_id FROM catalog.datasets WHERE id = :id)"
        ),
        {"id": str(incomplete.id)},
    )
    await session.commit()

    for path, key in (
        ("/datasets/dcat/", "dcat:dataset"),
        ("/datasets/dcat-us/3.0/", "dataset"),
        ("/datasets/geodcat-ap/", "dcat:dataset"),
    ):
        resp = await client.get(path)
        assert resp.status_code == 200, path
        ids = " ".join(d["@id"] for d in resp.json()[key])
        assert str(complete.id) in ids, f"complete missing from {path}"
        assert str(incomplete.id) not in ids, f"incomplete leaked into {path}"


@pytest.mark.anyio
async def test_incomplete_record_still_served_by_per_dataset_endpoint(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """Per-dataset endpoints serialize the record as-is even when incomplete."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    incomplete = await _create_complete_dataset(
        session, created_by=admin_id, name="Incomplete Single", with_contact=False
    )
    await session.execute(
        text(
            "UPDATE catalog.records SET summary = NULL "
            "WHERE id = (SELECT record_id FROM catalog.datasets WHERE id = :id)"
        ),
        {"id": str(incomplete.id)},
    )
    await session.commit()

    # The DCAT-3 per-dataset endpoint still returns the record (not filtered).
    resp = await client.get(
        f"/datasets/{incomplete.id}/dcat/", headers=admin_auth_header
    )
    assert resp.status_code == 200
    assert resp.json()["dcterms:title"]["@value"] == "Incomplete Single"

    # ...and its validation report flags the missing description.
    val = await client.get(
        f"/datasets/{incomplete.id}/dcat/validation/", headers=admin_auth_header
    )
    assert val.status_code == 200
    report = val.json()
    assert report["schema"] == "Dataset"
    assert report["valid"] is False
    assert any(
        e["validator"] == "required" and "dcterms:description" in e["message"]
        for e in report["errors"]
    )


@pytest.mark.anyio
async def test_dcat3_catalog_validation_endpoint(
    client: AsyncClient,
    test_db_session,
):
    """The new DCAT-3 catalog validation endpoint reports a conformant feed."""
    session = test_db_session
    for _table in ("catalog.datasets", "catalog.records", "catalog.collections"):
        await session.execute(text(f"TRUNCATE TABLE {_table} CASCADE"))
    await session.commit()
    admin_id = await get_user_id(session, "admin")
    await _create_complete_dataset(session, created_by=admin_id)

    resp = await client.get("/datasets/dcat/validation/")
    assert resp.status_code == 200
    report = resp.json()
    assert report["schema"] == "Catalog"
    assert report["valid"] is True
    assert report["error_count"] == 0


# ---------------------------------------------------------------------------
# Clear-to-null: explicit nulls in the PATCH actually clear fields
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_patch_explicit_null_clears_field(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
):
    """fix(#458 E-04): an explicit null clears the field; absent fields keep
    PATCH semantics; title (NOT NULL) ignores a null."""
    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_complete_dataset(
        test_db_session, created_by=admin_id, name="ClearToNull Dataset"
    )

    resp = await client.patch(
        f"/datasets/{ds.id}",
        json={"summary": None, "lineage_summary": None, "title": None},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text

    got = await client.get(f"/datasets/{ds.id}", headers=admin_auth_header)
    assert got.status_code == 200
    body = got.json()
    assert body["summary"] is None
    assert body["lineage_summary"] is None
    # title is non-clearable: the explicit null is dropped, not applied
    assert body["title"] == "ClearToNull Dataset"
    # absent fields stay untouched (PATCH semantics)
    assert body["source_organization"] == "Original Org"
    assert body["usage_constraints"] == "Attribution required"
