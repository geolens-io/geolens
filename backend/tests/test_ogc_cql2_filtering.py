"""Tests for CQL2 text and JSON filtering on OGC collection items endpoint.

Verifies:
  - CQL2 text equality filter works (title = '...')
  - CQL2 text comparison filter works (srid = 4326)
  - CQL2 text LIKE filter works (title LIKE '%...')
  - CQL2 JSON equality filter works
  - CQL2 JSON logical AND filter works
  - Invalid CQL2 expression returns 400 (not 500)
  - Unsupported filter-lang returns 400
  - Default filter-lang is cql2-text when omitted
  - Pagination next/prev links preserve filter and filter-lang params
  - CQL2 filter respects RBAC visibility (private datasets hidden)
"""

import json
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.auth.models import User
from app.datasets.models import Dataset, Record


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
    srid: int = 4326,
    geometry_type: str = "MultiPolygon",
    theme_category: list[str] | None = None,
    source_organization: str | None = None,
) -> Dataset:
    """Insert a Record + Dataset pair for CQL2 filtering tests."""
    table_name = f"ds_{uuid.uuid4().hex[:12]}"
    record = Record(
        title=name,
        summary=f"Test dataset: {name}",
        theme_category=theme_category or ["test"],
        visibility=visibility,
        record_status="published",
        created_by=created_by,
        source_organization=source_organization,
    )
    session.add(record)
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


def _find_link(links: list[dict], rel: str) -> dict | None:
    """Find a link by rel value in a links list."""
    for link in links:
        if link["rel"] == rel:
            return link
    return None


# ---------------------------------------------------------------------------
# CQL2 Text Filtering Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cql2_text_equality_filter(client: AsyncClient, test_db_session):
    """CQL2 text equality filter returns only matching records."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    unique = uuid.uuid4().hex[:8]
    target_name = f"cql2-eq-target-{unique}"
    other_name = f"cql2-eq-other-{unique}"

    await _create_dataset(session, created_by=admin_id, name=target_name)
    await _create_dataset(session, created_by=admin_id, name=other_name)

    resp = await client.get(
        "/collections/datasets/items",
        params={"filter": f"title='{target_name}'", "filter-lang": "cql2-text"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["numberMatched"] >= 1
    titles = [f["properties"]["title"] for f in data["features"]]
    assert target_name in titles
    assert other_name not in titles


@pytest.mark.anyio
async def test_cql2_text_comparison_filter(client: AsyncClient, test_db_session):
    """CQL2 text comparison filter on srid returns only matching records."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    unique = uuid.uuid4().hex[:8]

    await _create_dataset(
        session, created_by=admin_id, name=f"cql2-srid-2263-{unique}", srid=2263
    )
    await _create_dataset(
        session, created_by=admin_id, name=f"cql2-srid-4326-{unique}", srid=4326
    )

    resp = await client.get(
        "/collections/datasets/items",
        params={"filter": "srid=2263", "filter-lang": "cql2-text"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["numberMatched"] >= 1
    for feature in data["features"]:
        crs = feature["properties"].get("crs")
        assert crs == "EPSG:2263", f"Expected EPSG:2263 but got {crs}"


@pytest.mark.anyio
async def test_cql2_text_like_filter(client: AsyncClient, test_db_session):
    """CQL2 text LIKE filter returns partial-match results."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    unique = uuid.uuid4().hex[:8]
    target_name = f"cql2-like-parcels-{unique}"

    await _create_dataset(session, created_by=admin_id, name=target_name)

    resp = await client.get(
        "/collections/datasets/items",
        params={
            "filter": f"title LIKE '%like-parcels-{unique}'",
            "filter-lang": "cql2-text",
        },
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["numberMatched"] >= 1
    titles = [f["properties"]["title"] for f in data["features"]]
    assert target_name in titles


# ---------------------------------------------------------------------------
# CQL2 JSON Filtering Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cql2_json_equality_filter(client: AsyncClient, test_db_session):
    """CQL2 JSON equality filter returns only matching records."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    unique = uuid.uuid4().hex[:8]

    await _create_dataset(
        session, created_by=admin_id, name=f"cql2-json-eq-{unique}", srid=2263
    )
    await _create_dataset(
        session, created_by=admin_id, name=f"cql2-json-neq-{unique}", srid=4326
    )

    json_filter = json.dumps({"op": "=", "args": [{"property": "srid"}, 2263]})
    resp = await client.get(
        "/collections/datasets/items",
        params={"filter": json_filter, "filter-lang": "cql2-json"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["numberMatched"] >= 1
    for feature in data["features"]:
        assert feature["properties"]["crs"] == "EPSG:2263"


@pytest.mark.anyio
async def test_cql2_json_logical_and(client: AsyncClient, test_db_session):
    """CQL2 JSON AND operator combines two conditions correctly."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    unique = uuid.uuid4().hex[:8]

    # Create a dataset matching both conditions
    await _create_dataset(
        session,
        created_by=admin_id,
        name=f"cql2-and-match-{unique}",
        srid=2263,
        geometry_type="Point",
    )
    # Create datasets matching only one condition
    await _create_dataset(
        session,
        created_by=admin_id,
        name=f"cql2-and-partial-{unique}",
        srid=4326,
        geometry_type="Point",
    )

    json_filter = json.dumps(
        {
            "op": "and",
            "args": [
                {"op": "=", "args": [{"property": "srid"}, 2263]},
                {"op": "=", "args": [{"property": "geometry_type"}, "Point"]},
            ],
        }
    )
    resp = await client.get(
        "/collections/datasets/items",
        params={"filter": json_filter, "filter-lang": "cql2-json"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["numberMatched"] >= 1
    for feature in data["features"]:
        assert feature["properties"]["crs"] == "EPSG:2263"
        assert feature["properties"]["geometry_type"] == "Point"


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cql2_invalid_expression_returns_400(client: AsyncClient):
    """Malformed CQL2 expression returns HTTP 400, not 500."""
    resp = await client.get(
        "/collections/datasets/items",
        params={"filter": "!!!INVALID!!!", "filter-lang": "cql2-text"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "Invalid CQL2 expression" in data["detail"]


@pytest.mark.anyio
async def test_cql2_unsupported_filter_lang_returns_400(client: AsyncClient):
    """Unsupported filter-lang returns HTTP 400."""
    resp = await client.get(
        "/collections/datasets/items",
        params={"filter": "title='test'", "filter-lang": "cql2-xml"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "Unsupported filter-lang" in data["detail"]


# ---------------------------------------------------------------------------
# Default Behavior Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cql2_default_filter_lang_is_text(client: AsyncClient, test_db_session):
    """Omitting filter-lang defaults to cql2-text and parses successfully."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    unique = uuid.uuid4().hex[:8]
    target_name = f"cql2-default-{unique}"

    await _create_dataset(session, created_by=admin_id, name=target_name)

    # Send filter WITHOUT filter-lang -- should default to cql2-text
    resp = await client.get(
        "/collections/datasets/items",
        params={"filter": f"title='{target_name}'"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["numberMatched"] >= 1
    titles = [f["properties"]["title"] for f in data["features"]]
    assert target_name in titles


# ---------------------------------------------------------------------------
# Pagination Preservation Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cql2_pagination_preserves_filter(client: AsyncClient, test_db_session):
    """Pagination next link preserves filter and filter-lang params."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    unique = uuid.uuid4().hex[:8]

    # Create enough matching datasets to trigger pagination
    for i in range(3):
        await _create_dataset(
            session,
            created_by=admin_id,
            name=f"cql2-page-{unique}-{i}",
            srid=4326,
        )

    resp = await client.get(
        "/collections/datasets/items",
        params={"filter": "srid=4326", "filter-lang": "cql2-text", "limit": 1},
    )
    assert resp.status_code == 200
    data = resp.json()

    if data["numberMatched"] > 1:
        next_link = _find_link(data["links"], "next")
        assert next_link is not None, "Expected next link with multiple results"

        parsed = urlparse(next_link["href"])
        qs = parse_qs(parsed.query)
        assert "filter" in qs, "Next link must preserve filter param"
        assert qs["filter"][0] == "srid=4326"
        # filter-lang=cql2-text is the default so it should NOT be in the URL
        assert "filter-lang" not in qs, (
            "filter-lang should not be in URL when it is the default cql2-text"
        )


@pytest.mark.anyio
async def test_cql2_pagination_preserves_non_default_filter_lang(
    client: AsyncClient, test_db_session
):
    """Pagination next link includes filter-lang when non-default (cql2-json)."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    unique = uuid.uuid4().hex[:8]

    for i in range(3):
        await _create_dataset(
            session,
            created_by=admin_id,
            name=f"cql2-pagejson-{unique}-{i}",
            srid=4326,
        )

    json_filter = json.dumps({"op": "=", "args": [{"property": "srid"}, 4326]})
    resp = await client.get(
        "/collections/datasets/items",
        params={"filter": json_filter, "filter-lang": "cql2-json", "limit": 1},
    )
    assert resp.status_code == 200
    data = resp.json()

    if data["numberMatched"] > 1:
        next_link = _find_link(data["links"], "next")
        assert next_link is not None
        parsed = urlparse(next_link["href"])
        qs = parse_qs(parsed.query)
        assert "filter" in qs, "Next link must preserve filter param"
        assert "filter-lang" in qs, "Next link must preserve non-default filter-lang"
        assert qs["filter-lang"][0] == "cql2-json"


# ---------------------------------------------------------------------------
# RBAC Visibility Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cql2_filter_respects_visibility(
    client: AsyncClient, test_db_session, admin_auth_header
):
    """CQL2 filter does not expose private datasets to anonymous users."""
    session = test_db_session
    admin_id = await _get_user_id(session, "admin")
    unique = uuid.uuid4().hex[:8]
    private_name = f"cql2-private-{unique}"
    public_name = f"cql2-public-{unique}"

    await _create_dataset(
        session,
        created_by=admin_id,
        name=private_name,
        visibility="private",
        srid=9999,
    )
    await _create_dataset(
        session,
        created_by=admin_id,
        name=public_name,
        visibility="public",
        srid=9999,
    )

    # Anonymous request -- should only see public dataset
    resp = await client.get(
        "/collections/datasets/items",
        params={"filter": "srid=9999", "filter-lang": "cql2-text"},
    )
    assert resp.status_code == 200
    data = resp.json()

    titles = [f["properties"]["title"] for f in data["features"]]
    assert public_name in titles
    assert private_name not in titles, (
        "Private dataset must not be visible to anonymous users"
    )

    # Admin request -- should see both
    resp2 = await client.get(
        "/collections/datasets/items",
        params={"filter": "srid=9999", "filter-lang": "cql2-text"},
        headers=admin_auth_header,
    )
    assert resp2.status_code == 200
    data2 = resp2.json()

    titles2 = [f["properties"]["title"] for f in data2["features"]]
    assert public_name in titles2
    assert private_name in titles2
