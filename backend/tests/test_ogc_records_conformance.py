"""Regression tests for OGC API Records Part 1 conformance fixes.

Covers all 10 conformance gaps:
  1. Pagination uses rel="prev" (per OGC API Features 1.0 Section 7.14.2)
  2. No STAC-specific keys in record responses
  3. Themes include scheme URI from keyword vocabulary_uri
  4. Contacts include email and phone fields
  5. FeatureCollection includes timeStamp
  6. sortby OGC parameter with +/-field syntax
  7. sortby rejects unknown fields with 400
  8. type query parameter accepted as alias for record_type
  9. /collections/datasets includes schema link
  10. Raster records show raster formats, vector records show vector formats
"""

import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.models import User
from app.datasets.models import Dataset, Record, RecordContact, RecordKeyword


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_admin_id(session) -> uuid.UUID:
    result = await session.execute(select(User).where(User.username == "admin"))
    return result.scalar_one().id


async def _create_dataset(
    session,
    *,
    admin_id: uuid.UUID,
    name: str | None = None,
    record_type: str = "vector_dataset",
    keywords: list[tuple[str, str | None]] | None = None,
    contacts: list[dict] | None = None,
) -> Dataset:
    """Create a Record + Dataset pair with optional keywords and contacts."""
    _name = name or f"ogc-conf-{uuid.uuid4().hex[:8]}"
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=_name,
        summary=f"Test: {_name}",
        theme_category=["test"],
        visibility="public",
        record_status="published",
        record_type=record_type,
        created_by=admin_id,
    )
    session.add(record)
    await session.flush()

    if keywords:
        for kw_text, vocab_uri in keywords:
            session.add(
                RecordKeyword(
                    record_id=record.id,
                    keyword=kw_text,
                    keyword_type="theme",
                    vocabulary_uri=vocab_uri,
                )
            )
        await session.flush()

    if contacts:
        for c in contacts:
            session.add(RecordContact(record_id=record.id, **c))
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


def _find_link(links: list[dict], rel: str) -> dict | None:
    for link in links:
        if link.get("rel") == rel:
            return link
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_pagination_uses_prev_rel(client: AsyncClient, test_db_session):
    """Gap 1: Pagination links use rel='prev' (per OGC API Features 1.0 / IANA)."""
    admin_id = await _get_admin_id(test_db_session)
    prefix = uuid.uuid4().hex[:6]
    for i in range(3):
        await _create_dataset(
            test_db_session, admin_id=admin_id, name=f"prev-rel-{prefix}-{i}"
        )

    resp = await client.get(
        "/collections/datasets/items", params={"offset": 1, "limit": 1}
    )
    assert resp.status_code == 200
    data = resp.json()

    prev_link = _find_link(data["links"], "prev")
    assert prev_link is not None, "Expected rel='prev' link"


@pytest.mark.anyio
async def test_no_stac_bleedthrough(client: AsyncClient, test_db_session):
    """Gap 2: OGC records must not contain STAC-specific keys."""
    admin_id = await _get_admin_id(test_db_session)
    await _create_dataset(
        test_db_session, admin_id=admin_id, name=f"stac-clean-{uuid.uuid4().hex[:6]}"
    )

    resp = await client.get("/collections/datasets/items", params={"limit": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["features"]) > 0

    feature = data["features"][0]
    for stac_key in ("stac_version", "stac_extensions", "stac_assets"):
        assert stac_key not in feature, (
            f"STAC key '{stac_key}' should not be in OGC record"
        )
    # conformsTo is a valid OGC Records Part 1 field, not STAC
    assert "conformsTo" in feature, "OGC record should include conformsTo"


@pytest.mark.anyio
async def test_themes_include_scheme(client: AsyncClient, test_db_session):
    """Gap 3: Themes include scheme URI when keyword has vocabulary_uri."""
    admin_id = await _get_admin_id(test_db_session)
    ds = await _create_dataset(
        test_db_session,
        admin_id=admin_id,
        name=f"theme-scheme-{uuid.uuid4().hex[:6]}",
        keywords=[
            ("hydrology", "https://example.org/vocab/water"),
            ("rivers", "https://example.org/vocab/water"),
            ("general", None),
        ],
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    data = resp.json()
    themes = data["properties"]["themes"]
    assert themes is not None

    # Find theme with scheme
    scheme_themes = sorted(
        [t for t in themes if "scheme" in t], key=lambda t: t["scheme"]
    )
    assert len(scheme_themes) >= 1, "Expected at least one theme with scheme URI"
    assert scheme_themes[0]["scheme"] == "https://example.org/vocab/water"
    concept_ids = [c["id"] for c in scheme_themes[0]["concepts"]]
    assert "hydrology" in concept_ids
    assert "rivers" in concept_ids


@pytest.mark.anyio
async def test_contacts_include_email_phone(client: AsyncClient, test_db_session):
    """Gap 4: Contacts include email and phone when present."""
    admin_id = await _get_admin_id(test_db_session)
    ds = await _create_dataset(
        test_db_session,
        admin_id=admin_id,
        name=f"contact-fields-{uuid.uuid4().hex[:6]}",
        contacts=[
            {
                "role": "pointOfContact",
                "name": "Jane Doe",
                "organization": "ACME",
                "email": "jane@acme.org",
                "phone": "+1-555-0100",
            }
        ],
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    data = resp.json()
    contacts = data["properties"]["contacts"]
    assert contacts is not None
    assert len(contacts) >= 1
    contacts = sorted(contacts, key=lambda c: c.get("email", ""))
    assert contacts[0]["email"] == "jane@acme.org"
    assert contacts[0]["phone"] == "+1-555-0100"


@pytest.mark.anyio
async def test_contacts_null_fields_omitted(client: AsyncClient, test_db_session):
    """Gap 4b: Contacts with null email/phone omit those keys (not null values)."""
    admin_id = await _get_admin_id(test_db_session)
    ds = await _create_dataset(
        test_db_session,
        admin_id=admin_id,
        name=f"contact-nulls-{uuid.uuid4().hex[:6]}",
        contacts=[
            {
                "role": "pointOfContact",
                "name": "No Email Person",
                "organization": "ACME",
                "email": None,
                "phone": None,
            }
        ],
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    data = resp.json()
    contacts = data["properties"]["contacts"]
    assert contacts is not None
    assert len(contacts) >= 1
    contact = contacts[0]
    assert "email" not in contact, "null email should be omitted, not included as null"
    assert "phone" not in contact, "null phone should be omitted, not included as null"
    assert contact["name"] == "No Email Person"
    assert contact["role"] == "pointOfContact"


@pytest.mark.anyio
async def test_feature_collection_has_timestamp(client: AsyncClient, test_db_session):
    """Gap 6: FeatureCollection response includes timeStamp."""
    admin_id = await _get_admin_id(test_db_session)
    await _create_dataset(
        test_db_session, admin_id=admin_id, name=f"timestamp-{uuid.uuid4().hex[:6]}"
    )

    resp = await client.get("/collections/datasets/items", params={"limit": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert "timeStamp" in data, "FeatureCollection must include timeStamp"
    # Validate ISO 8601 format
    ts = data["timeStamp"]
    assert ts.endswith("Z"), "timeStamp must end with Z"
    datetime.fromisoformat(ts.replace("Z", "+00:00"))  # should not raise


@pytest.mark.anyio
async def test_sortby_ogc_syntax(client: AsyncClient, test_db_session):
    """Gap 7: sortby with OGC +/-field syntax returns 200 and honors direction."""
    admin_id = await _get_admin_id(test_db_session)
    prefix = uuid.uuid4().hex[:6]
    await _create_dataset(test_db_session, admin_id=admin_id, name=f"aaa-sort-{prefix}")
    await _create_dataset(test_db_session, admin_id=admin_id, name=f"zzz-sort-{prefix}")

    # Ascending by title (use %2B for literal +, since + is decoded as space in query strings)
    resp_asc = await client.get(
        "/collections/datasets/items",
        params={"sortby": "+title", "limit": 100, "q": prefix},
    )
    assert resp_asc.status_code == 200
    titles_asc = [f["properties"]["title"] for f in resp_asc.json()["features"]]
    assert len(titles_asc) >= 2, "Need at least 2 results to verify order"
    assert titles_asc == sorted(titles_asc, key=str.lower), (
        "Expected ascending title order"
    )

    # Descending by title
    resp_desc = await client.get(
        "/collections/datasets/items",
        params={"sortby": "-title", "limit": 100, "q": prefix},
    )
    assert resp_desc.status_code == 200
    titles_desc = [f["properties"]["title"] for f in resp_desc.json()["features"]]
    assert len(titles_desc) >= 2, "Need at least 2 results to verify order"
    assert titles_desc == sorted(titles_desc, key=str.lower, reverse=True), (
        "Expected descending title order"
    )

    # Ascending and descending should be opposite
    assert titles_asc != titles_desc, (
        "Ascending and descending should produce different order"
    )

    # +created should also work
    resp2 = await client.get(
        "/collections/datasets/items", params={"sortby": "+created", "limit": 5}
    )
    assert resp2.status_code == 200


@pytest.mark.anyio
async def test_sortby_invalid_field_returns_400(client: AsyncClient):
    """Gap 7b: sortby with unknown field returns 400."""
    resp = await client.get("/collections/datasets/items", params={"sortby": "+bogus"})
    assert resp.status_code == 400
    data = resp.json()
    assert "InvalidParameterValue" in data.get("code", "")


@pytest.mark.anyio
async def test_type_query_param(client: AsyncClient, test_db_session):
    """Gap 8: type query param accepted as alias for record_type."""
    admin_id = await _get_admin_id(test_db_session)
    await _create_dataset(
        test_db_session,
        admin_id=admin_id,
        name=f"type-param-{uuid.uuid4().hex[:6]}",
        record_type="vector_dataset",
    )

    resp = await client.get(
        "/collections/datasets/items",
        params={"type": "vector_dataset", "limit": 5},
    )
    assert resp.status_code == 200


@pytest.mark.anyio
async def test_collection_has_schema_link(client: AsyncClient, test_db_session):
    """Gap 9: /collections/datasets metadata includes schema link."""
    admin_id = await _get_admin_id(test_db_session)
    await _create_dataset(
        test_db_session, admin_id=admin_id, name=f"schema-link-{uuid.uuid4().hex[:6]}"
    )

    resp = await client.get("/collections/datasets")
    assert resp.status_code == 200
    data = resp.json()
    schema_link = _find_link(
        data["links"], "http://www.opengis.net/def/rel/ogc/1.0/schema"
    )
    assert schema_link is not None, "Missing schema link on /collections/datasets"
    assert "schema" in schema_link["href"]
    assert schema_link["type"] == "application/schema+json"


@pytest.mark.anyio
async def test_raster_record_formats(client: AsyncClient, test_db_session):
    """Gap 10: Raster records get raster formats, not vector formats."""
    admin_id = await _get_admin_id(test_db_session)
    ds = await _create_dataset(
        test_db_session,
        admin_id=admin_id,
        name=f"raster-fmt-{uuid.uuid4().hex[:6]}",
        record_type="raster_dataset",
    )

    resp = await client.get(f"/collections/datasets/items/{ds.id}")
    assert resp.status_code == 200
    data = resp.json()
    formats = data["properties"]["formats"]
    assert any("geotiff" in f for f in formats), (
        "Raster record must have geotiff format"
    )
    assert not any("geopackage" in f for f in formats), (
        "Raster record must not have vector formats"
    )
