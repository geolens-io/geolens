"""Round-trip + complete-feed tests for catalog standards output (issue #203).

Verifies two guarantees of the DCAT-US metadata-completeness conformance work:

1. **Round-trip:** ingest -> PATCH editable metadata -> each edited field
   SURFACES in every standards serialization GeoLens emits: W3C DCAT 3,
   DCAT-US 3.0, GeoDCAT-AP 2.0.0, STAC, and the OGC API Records GeoJSON output.

2. **Complete feeds:** minimally populated published records stay visible in
   DCAT 3 / DCAT-US / GeoDCAT-AP. Deterministic required-field fallbacks make
   the feed and per-dataset validators agree, and coverage counts are exposed.
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
# Complete feeds: minimally populated records are visible and conformant
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_minimal_published_record_remains_visible_and_conformant_in_feeds(
    client: AsyncClient,
    test_db_session,
    monkeypatch,
):
    """Required-field gaps use observable fallbacks instead of feed filtering."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "dcat_contact_email", "metadata@example.gov")
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

    for path, validation_path, key in (
        ("/datasets/dcat/", "/datasets/dcat/validation/", "dcat:dataset"),
        (
            "/datasets/dcat-us/3.0/",
            "/datasets/dcat-us/3.0/validation/",
            "dataset",
        ),
        (
            "/datasets/geodcat-ap/",
            "/datasets/geodcat-ap/validation/",
            "dcat:dataset",
        ),
    ):
        resp = await client.get(path)
        assert resp.status_code == 200, path
        ids = " ".join(d["@id"] for d in resp.json()[key])
        assert str(complete.id) in ids, f"complete missing from {path}"
        assert str(incomplete.id) in ids, f"minimal record missing from {path}"
        assert resp.headers["x-geolens-source-dataset-count"] == "2"
        assert resp.headers["x-geolens-serialized-dataset-count"] == "2"
        assert resp.headers["x-geolens-excluded-dataset-count"] == "0"
        assert resp.headers["x-geolens-metadata-fallback-dataset-count"] == "1"

        validation = await client.get(validation_path)
        assert validation.status_code == 200, validation_path
        report = validation.json()
        assert report["valid"] is True, report
        assert report["source_dataset_count"] == 2
        assert report["serialized_dataset_count"] == 2
        assert report["excluded_dataset_count"] == 0
        assert report["metadata_fallback_dataset_count"] == 1


@pytest.mark.anyio
async def test_minimal_record_per_dataset_fallbacks_pass_all_validators(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
):
    """Per-dataset output uses the same conformant fallbacks as catalog feeds."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "dcat_contact_email", "metadata@example.gov")
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

    for export_suffix, validation_suffix, description_path, expected_fields in (
        (
            "dcat/",
            "dcat/validation/",
            ("dcterms:description", "@value"),
            ["dcterms:description"],
        ),
        (
            "dcat-us/3.0/",
            "dcat-us/3.0/validation/",
            ("description",),
            ["description", "contactPoint"],
        ),
        (
            "geodcat-ap/",
            "geodcat-ap/validation/",
            ("dcterms:description", "@value"),
            ["dcterms:description"],
        ),
    ):
        resp = await client.get(
            f"/datasets/{incomplete.id}/{export_suffix}",
            headers=admin_auth_header,
        )
        assert resp.status_code == 200, resp.text
        value = resp.json()
        for key in description_path:
            value = value[key]
        assert value == "Incomplete Single"
        assert resp.headers["x-geolens-metadata-fallback-fields"].split(",") == (
            expected_fields
        )

        val = await client.get(
            f"/datasets/{incomplete.id}/{validation_suffix}",
            headers=admin_auth_header,
        )
        assert val.status_code == 200
        report = val.json()
        assert report["schema"] == "Dataset"
        assert report["valid"] is True, report
        assert report["metadata_fallback_fields"] == expected_fields


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

    # fix(#458 E-04, codex review): the audit event must record the cleared
    # fields (exclude_unset, not exclude_none) so history reflects the change.
    from sqlalchemy import select

    from app.modules.audit.models import AuditLog

    row = (
        await test_db_session.execute(
            select(AuditLog)
            .where(
                AuditLog.resource_id == ds.id,
                AuditLog.action == "metadata.edit",
            )
            .order_by(AuditLog.created_at.desc())
        )
    ).scalar_one()
    assert "summary" in row.details
    assert row.details["summary"] is None
    assert "lineage_summary" in row.details


@pytest.mark.anyio
async def test_patch_clear_text_field_requeues_embedding(
    client: AsyncClient,
    admin_auth_header: dict,
    test_db_session,
    monkeypatch,
):
    """fix(#458 E-04, codex review): clearing summary/lineage must re-defer the
    embedding (model_fields_set), not skip it because the value is None."""
    from app.modules.catalog.datasets.domain import service_metadata

    deferred: list = []

    async def _capture(record_id, dataset_id):
        deferred.append(record_id)

    monkeypatch.setattr(service_metadata, "_maybe_defer_embedding", _capture)

    admin_id = await get_user_id(test_db_session, "admin")
    ds = await _create_complete_dataset(
        test_db_session, created_by=admin_id, name="ReembedOnClear Dataset"
    )

    resp = await client.patch(
        f"/datasets/{ds.id}",
        json={"summary": None},
        headers=admin_auth_header,
    )
    assert resp.status_code == 200, resp.text
    assert len(deferred) == 1
