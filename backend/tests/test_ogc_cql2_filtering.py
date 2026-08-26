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
from app.modules.catalog.datasets.domain.models import Dataset

from tests.factories import create_dataset, get_user_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
    return await create_dataset(
        session,
        created_by=created_by,
        name=name,
        description=f"Test dataset: {name}",
        theme_category=theme_category or ["test"],
        visibility=visibility,
        srid=srid,
        geometry_type=geometry_type,
        feature_count=10,
        source_organization=source_organization,
    )


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
    admin_id = await get_user_id(session, "admin")
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
    admin_id = await get_user_id(session, "admin")
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
    admin_id = await get_user_id(session, "admin")
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
    admin_id = await get_user_id(session, "admin")
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
    admin_id = await get_user_id(session, "admin")
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


@pytest.mark.anyio
async def test_search_datasets_unsupported_filter_lang_returns_400(client: AsyncClient):
    """(#315) /search/datasets/ rejects a bogus filter-lang with 400 (was silently ignored)."""
    resp = await client.get(
        "/search/datasets/",
        params={"filter": "title=x", "filter-lang": "bogus"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert "Unsupported filter-lang" in data["detail"]


# ---------------------------------------------------------------------------
# feat(#1614): feature collections validate filter (rejection replaced fix(#315))
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize(
    "filter_value,expected_status,detail_fragment",
    [
        pytest.param("name='x'", 503, "temporarily unavailable", id="no-table-503"),
        pytest.param("!!!INVALID!!!", 400, "Invalid CQL2", id="malformed"),
        pytest.param("", 400, "Invalid CQL2", id="empty-string"),
    ],
)
async def test_feature_items_filter_check_ordering(
    client: AsyncClient,
    test_db_session,
    filter_value: str,
    expected_status: int,
    detail_fragment: str,
):
    """feat(#1614) replaced the fix(#315) presence-based rejection.

    ``filter`` on per-dataset feature collections is now parsed and validated
    server-side, with a deliberate check order: a parse failure is the
    caller's bug and 400s with no database access, while a valid filter
    against this dataset (which has no backing table) reports the same
    retryable 503 as an unfiltered items request — never an unknown-property
    400 derived from the missing table's empty schema (codex r2). The full
    filtering surface is covered in test_ogc_features_filter.py.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    unique = uuid.uuid4().hex[:8]
    dataset = await _create_dataset(
        session, created_by=admin_id, name=f"b4-feature-filter-{unique}"
    )

    resp = await client.get(
        f"/collections/{dataset.id}/items",
        params={"filter": filter_value},
    )
    assert resp.status_code == expected_status
    data = resp.json()
    assert detail_fragment in data["detail"]


# ---------------------------------------------------------------------------
# Default Behavior Tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cql2_default_filter_lang_is_text(client: AsyncClient, test_db_session):
    """Omitting filter-lang defaults to cql2-text and parses successfully."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
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
    admin_id = await get_user_id(session, "admin")
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
    admin_id = await get_user_id(session, "admin")
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
    admin_id = await get_user_id(session, "admin")
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


# ---------------------------------------------------------------------------
# fix(#1666): keywords and filter-lang over the wire, on both search routes.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/search/datasets/", "/collections/datasets/items"])
async def test_repeated_keywords_filter_as_a_query_parameter(
    client: AsyncClient, test_db_session, path: str
):
    """Repeated ?keywords= narrows results on both search routes.

    The contract used to declare `keywords` as a GET request body, so a
    generated client sent it as one and silently got everything back. This
    pins the wire form the handlers actually read.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    unique = uuid.uuid4().hex[:8]
    # `keywords` filters RecordKeyword rows, not theme_category.
    await create_dataset(
        session,
        created_by=admin_id,
        name=f"kw-hit-{unique}",
        description="keyword wire-form fixture",
        visibility="public",
        keywords=[f"theme{unique}"],
    )
    await _create_dataset(session, created_by=admin_id, name=f"kw-miss-{unique}")
    await session.commit()

    hit = await client.get(path, params={"keywords": f"theme{unique}", "limit": 100})
    assert hit.status_code == 200
    miss = await client.get(path, params={"keywords": f"absent{unique}", "limit": 100})
    assert miss.status_code == 200

    assert hit.json()["numberMatched"] >= 1
    assert miss.json()["numberMatched"] == 0, (
        "keywords was ignored — it is being read from somewhere other than the "
        "query string."
    )


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/search/datasets/", "/collections/datasets/items"])
async def test_empty_filter_lang_is_treated_as_not_supplied(
    client: AsyncClient, path: str
):
    """`?filter-lang=` keeps defaulting to cql2-text rather than 400ing.

    fix(#1666) moved the check off the raw query string and onto the bound
    value. The raw read skipped its check on any falsy value, so preserving
    that means an explicitly empty parameter is still "not supplied".
    """
    resp = await client.get(path, params={"filter": "srid=4326", "filter-lang": ""})
    assert resp.status_code == 200, resp.text


@pytest.mark.anyio
async def test_validation_failure_returns_the_declared_problem_body(
    client: AsyncClient,
):
    """A validation failure answers problem+json, as the contract now declares."""
    resp = await client.get("/search/datasets/", params={"limit": "notanumber"})
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert set(body) >= {"title", "status", "detail"}
    assert isinstance(body["detail"], str), (
        "detail is a flattened string, not FastAPI's error array."
    )


# ---------------------------------------------------------------------------
# compat(#1666 codex P2): the pre-fix contract published `filter-lang` under
# the field's Python name, so every SDK generated before the fix sends
# `cql2_filter_lang` — and under the old `Depends()` binding that was the only
# spelling that actually bound. Both are accepted; only the correct one is
# published.
# ---------------------------------------------------------------------------

_JSON_FILTER = '{"op":"=","args":[{"property":"srid"},4326]}'
_FILTER_LANG_SPELLINGS = ["filter-lang", "cql2_filter_lang"]


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/search/datasets/", "/collections/datasets/items"])
@pytest.mark.parametrize("name", _FILTER_LANG_SPELLINGS)
async def test_cql2_json_parses_under_either_filter_lang_spelling(
    client: AsyncClient, path: str, name: str
):
    """A CQL2-JSON filter parses under both spellings.

    This is the discriminating case: a JSON filter string is not valid
    cql2-text, so if the spelling were ignored the request would fail rather
    than quietly return the wrong rows.
    """
    resp = await client.get(
        path, params={"filter": _JSON_FILTER, name: "cql2-json", "limit": 1}
    )
    assert resp.status_code == 200, f"?{name}=cql2-json -> {resp.text[:200]}"


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/search/datasets/", "/collections/datasets/items"])
@pytest.mark.parametrize("name", _FILTER_LANG_SPELLINGS)
async def test_bogus_filter_lang_rejected_under_either_spelling(
    client: AsyncClient, path: str, name: str
):
    """An unsupported value is a 400 whichever spelling carried it."""
    resp = await client.get(path, params={"filter": "srid=4326", name: "bogus"})
    assert resp.status_code == 400, f"?{name}=bogus -> {resp.status_code}"


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/search/datasets/", "/collections/datasets/items"])
async def test_published_filter_lang_wins_over_the_legacy_spelling(
    client: AsyncClient, path: str
):
    """When both are sent, the published name decides."""
    # The correct name says cql2-json, which parses the JSON filter. The legacy
    # name says cql2-text, under which that same string does not parse — so a
    # 200 can only mean the correct name won.
    resp = await client.get(
        path,
        params=[
            ("filter", _JSON_FILTER),
            ("filter-lang", "cql2-json"),
            ("cql2_filter_lang", "cql2-text"),
        ],
    )
    assert resp.status_code == 200, resp.text[:200]


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/search/datasets/", "/collections/datasets/items"])
async def test_legacy_keywords_json_body_still_filters(
    client: AsyncClient, test_db_session, path: str
):
    """compat(#1666 codex P2): an old SDK's GET-body keywords still filter.

    The pre-fix contract declared `keywords` as an `application/json` request
    body on a GET — the generated Python client's parameter was named `body` —
    and the old `Depends()` binding consumed it. The corrected query-parameter
    binding reads the opposite one, so without this shim an unchanged client
    would silently receive UNFILTERED results.
    """
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    unique = uuid.uuid4().hex[:8]
    await create_dataset(
        session,
        created_by=admin_id,
        name=f"legacy-body-{unique}",
        description="legacy GET-body keywords fixture",
        visibility="public",
        keywords=[f"legacy{unique}"],
    )
    await session.commit()

    hit = await client.request("GET", path, json=[f"legacy{unique}"])
    assert hit.status_code == 200, hit.text[:200]
    assert hit.json()["numberMatched"] >= 1

    miss = await client.request("GET", path, json=[f"absent{unique}"])
    assert miss.status_code == 200, miss.text[:200]
    assert miss.json()["numberMatched"] == 0, (
        "the legacy GET body was ignored — an unchanged old SDK client would "
        "silently get unfiltered results."
    )


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/search/datasets/", "/collections/datasets/items"])
async def test_query_keywords_win_over_the_legacy_body(
    client: AsyncClient, test_db_session, path: str
):
    """The published form decides when a client somehow sends both."""
    session = test_db_session
    admin_id = await get_user_id(session, "admin")
    unique = uuid.uuid4().hex[:8]
    await create_dataset(
        session,
        created_by=admin_id,
        name=f"both-forms-{unique}",
        description="query-wins fixture",
        visibility="public",
        keywords=[f"query{unique}"],
    )
    await session.commit()

    resp = await client.request(
        "GET",
        path,
        params={"keywords": f"query{unique}", "limit": 100},
        json=[f"absent{unique}"],
    )
    assert resp.status_code == 200, resp.text[:200]
    assert resp.json()["numberMatched"] >= 1, (
        "the legacy body overrode the query parameter."
    )


@pytest.mark.anyio
async def test_non_keyword_json_body_is_ignored_on_search(client: AsyncClient):
    """The shim recognises one shape and ignores anything else, without failing.

    Scoped to `/search/datasets/` on purpose. `/collections/datasets/items`
    keeps `Depends()`, so FastAPI still BINDS and VALIDATES the legacy body
    there and answers 400 for a malformed one — pre-existing behaviour that
    this PR removes from the published contract but cannot remove from the
    runtime without the query-model form that route cannot use.
    """
    for payload in ({"not": "a list"}, [1, 2, 3], []):
        resp = await client.request("GET", "/search/datasets/", json=payload)
        assert resp.status_code == 200, f"{payload!r} -> {resp.status_code}"


@pytest.mark.anyio
async def test_malformed_legacy_body_still_validates_on_collection_items(
    client: AsyncClient,
):
    """Pin the runtime/contract asymmetry rather than leave it undiscovered.

    `_repair_depends_bound_query_model` drops the phantom body from the
    published schema, but `Depends()` keeps binding it at runtime, so a caller
    sending a malformed JSON body sees a 400 the contract does not describe.
    Every client that sends no body — which is every correct one — is
    unaffected. If this ever starts returning 200, the binding changed and the
    keyword compatibility shim above needs to cover this route too.
    """
    resp = await client.request(
        "GET", "/collections/datasets/items", json={"not": "a list"}
    )
    assert resp.status_code == 400, resp.status_code
