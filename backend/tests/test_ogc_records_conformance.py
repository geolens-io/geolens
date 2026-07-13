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
from urllib.parse import urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.modules.auth.models import User
from app.modules.catalog.collections.models import Collection
from app.modules.catalog.datasets.domain.models import (
    Dataset,
    Record,
    RecordContact,
    RecordKeyword,
)


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
    source_format: str = "geojson",
    source_filename: str = "test.geojson",
    source_url: str | None = None,
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
        source_format=source_format,
        source_filename=source_filename,
        source_url=source_url,
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
    assert contact["roles"] == ["pointOfContact"]


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
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert data["status"] == 400
    assert "Unknown sortby field" in data["detail"]


@pytest.mark.anyio
async def test_type_query_param(client: AsyncClient, test_db_session):
    """Gap 8: type uses the public Records resource type, not an internal subtype."""
    admin_id = await _get_admin_id(test_db_session)
    await _create_dataset(
        test_db_session,
        admin_id=admin_id,
        name=f"type-param-{uuid.uuid4().hex[:6]}",
        record_type="vector_dataset",
    )

    resp = await client.get(
        "/collections/datasets/items",
        params={"type": "dataset", "limit": 5},
    )
    assert resp.status_code == 200

    internal_type = await client.get(
        "/collections/datasets/items",
        params={"type": "vector_dataset", "limit": 5},
    )
    assert internal_type.status_code == 200
    assert internal_type.json()["numberMatched"] == 0


@pytest.mark.anyio
async def test_records_array_query_parameters(client: AsyncClient, test_db_session):
    """Records arrays accept comma-separated values and retain collection shape."""
    admin_id = await _get_admin_id(test_db_session)
    first = await _create_dataset(
        test_db_session,
        admin_id=admin_id,
        name=f"ids-first-{uuid.uuid4().hex[:6]}",
    )
    second = await _create_dataset(
        test_db_session,
        admin_id=admin_id,
        name=f"ids-second-{uuid.uuid4().hex[:6]}",
    )

    resp = await client.get(
        "/collections/datasets/items",
        params={
            "type": "dataset,service",
            "ids": f"{first.id},{second.id}",
            "limit": 10,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert body["numberMatched"] == 2
    assert {feature["id"] for feature in body["features"]} == {
        str(first.id),
        str(second.id),
    }
    self_link = next(link for link in body["links"] if link["rel"] == "self")
    assert "type=dataset%2Cservice" in self_link["href"]
    assert "ids=" in self_link["href"]
    assert 'rel="self"' in resp.headers["link"]


@pytest.mark.anyio
async def test_records_ids_filter_collection_resources(
    client: AsyncClient, test_db_session
):
    admin_id = await _get_admin_id(test_db_session)
    token = f"collection-ids-{uuid.uuid4().hex[:8]}"
    requested = Collection(
        name=f"{token} requested",
        description="Collection selected by the OGC ids filter",
        created_by=admin_id,
    )
    excluded = Collection(
        name=f"{token} excluded",
        description="Collection omitted by the OGC ids filter",
        created_by=admin_id,
    )
    test_db_session.add_all([requested, excluded])
    await test_db_session.commit()
    await test_db_session.refresh(requested)

    for params in (
        {"q": token, "type": "collection", "ids": str(requested.id)},
        {"type": "collection", "ids": str(requested.id)},
    ):
        resp = await client.get("/collections/datasets/items", params=params)

        assert resp.status_code == 200
        body = resp.json()
        assert body["numberMatched"] == 1
        assert body["numberReturned"] == 1
        assert [feature["id"] for feature in body["features"]] == [str(requested.id)]
        assert body["features"][0]["properties"]["type"] == "collection"


@pytest.mark.anyio
async def test_records_explicit_collection_types_are_paginated(
    client: AsyncClient, test_db_session, clean_tables
):
    admin_id = await _get_admin_id(test_db_session)
    token = uuid.uuid4().hex[:8]
    collections = [
        Collection(
            name=f"explicit-type-{token}-{index}",
            description="Collection selected by the OGC type filter",
            created_by=admin_id,
        )
        for index in range(3)
    ]
    test_db_session.add_all(collections)
    await test_db_session.commit()
    dataset = await _create_dataset(
        test_db_session,
        admin_id=admin_id,
        name=f"explicit-type-dataset-{token}",
    )

    collection_ids = {str(collection.id) for collection in collections}
    for resource_type, expected_types, expected_ids in (
        ("collection", {"collection"}, collection_ids),
        (
            "dataset,collection",
            {"dataset", "collection"},
            collection_ids | {str(dataset.id)},
        ),
    ):
        response = await client.get(
            "/collections/datasets/items",
            params={"type": resource_type, "limit": 2},
        )
        seen_ids: set[str] = set()
        number_matched: int | None = None

        while True:
            assert response.status_code == 200
            body = response.json()
            if number_matched is None:
                number_matched = body["numberMatched"]
            assert body["numberMatched"] == number_matched
            assert body["numberReturned"] == len(body["features"])
            assert body["numberReturned"] <= 2
            assert {
                feature["properties"]["type"] for feature in body["features"]
            } <= expected_types

            page_ids = {feature["id"] for feature in body["features"]}
            assert seen_ids.isdisjoint(page_ids)
            seen_ids.update(page_ids)

            next_link = _find_link(body["links"], "next")
            if next_link is None:
                break
            assert len(seen_ids) < number_matched
            parsed = urlparse(next_link["href"])
            response = await client.get(f"{parsed.path}?{parsed.query}")

        assert len(seen_ids) == number_matched
        assert expected_ids <= seen_ids


@pytest.mark.anyio
async def test_records_plural_external_ids(client: AsyncClient, test_db_session):
    admin_id = await _get_admin_id(test_db_session)
    source_item_id = f"external-item-{uuid.uuid4().hex[:8]}"
    dataset = await _create_dataset(
        test_db_session,
        admin_id=admin_id,
        name=f"external-ids-{uuid.uuid4().hex[:6]}",
        source_format="stac",
        source_filename=source_item_id,
    )

    resp = await client.get(
        "/collections/datasets/items",
        params={"externalIds": f"{source_item_id},does-not-exist"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert [feature["id"] for feature in body["features"]] == [str(dataset.id)]
    assert body["features"][0]["properties"]["externalIds"] == [source_item_id]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("params", "detail"),
    [
        ({"limit": 0}, "limit"),
        ({"filter-lang": "not-cql"}, "filter-lang"),
    ],
)
async def test_records_invalid_parameters_use_problem_400(
    client: AsyncClient,
    params: dict[str, object],
    detail: str,
):
    resp = await client.get("/collections/datasets/items", params=params)
    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == 400
    assert detail in body["detail"]


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
