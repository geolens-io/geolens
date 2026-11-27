"""Query values PostgreSQL cannot take are refused before the database."""

import json

import pytest
from httpx import AsyncClient

_PAST_INT8 = "99999999999999999999"

# (path, query, expected status): standards paths answer 400, native routes 422.
_NUL_ROUTES = [
    ("/search/datasets/", "q=a%00b", 422),
    ("/search/datasets/", "keywords=a%00b", 422),
    ("/search/facets/", "q=a%00b", 422),
    ("/collections/datasets/items", "q=a%00b", 400),
    ("/maps/", "search=a%00b", 422),
    ("/datasets/00000000-0000-4000-8000-000000000001/rows/", "filter[name]=a%00b", 422),
]

_OFFSET_ROUTES = [
    ("/search/datasets/", 422),
    ("/collections/datasets/items", 400),
    ("/collections", 400),
    ("/datasets/dcat/", 400),
]


@pytest.mark.anyio
@pytest.mark.parametrize(("path", "query", "status"), _NUL_ROUTES)
async def test_nul_byte_in_query_is_refused(
    client: AsyncClient, path: str, query: str, status: int
):
    resp = await client.get(f"{path}?{query}")

    assert resp.status_code == status, resp.text
    assert "NUL" in resp.text


@pytest.mark.anyio
@pytest.mark.parametrize(("path", "status"), _OFFSET_ROUTES)
async def test_offset_past_int8_is_refused(client: AsyncClient, path: str, status: int):
    resp = await client.get(path, params={"offset": _PAST_INT8})

    assert resp.status_code == status, resp.text


@pytest.mark.anyio
@pytest.mark.parametrize("path", [p for p, _ in _OFFSET_ROUTES])
async def test_offset_at_int8_max_still_answers(client: AsyncClient, path: str):
    resp = await client.get(path, params={"offset": str(2**63 - 1)})

    assert resp.status_code == 200, resp.text


def _cql2_json_equals(value: str) -> str:
    return json.dumps({"op": "=", "args": [{"property": "title"}, value]})


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("path", "status"),
    [("/search/datasets/", 400), ("/collections/datasets/items", 400)],
)
async def test_escaped_nul_in_cql2_json_is_refused(
    client: AsyncClient, path: str, status: int
):
    resp = await client.get(
        path,
        params={
            "filter-lang": "cql2-json",
            "filter": _cql2_json_equals("a\x00b"),
        },
    )

    assert resp.status_code == status, resp.text
    assert "NUL" in resp.text


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/search/datasets/", "/collections/datasets/items"])
async def test_escaped_backslash_u0000_in_cql2_json_is_literal_text(
    client: AsyncClient, path: str
):
    resp = await client.get(
        path,
        params={
            "filter-lang": "cql2-json",
            "filter": _cql2_json_equals("a\\u0000b"),
        },
    )

    assert resp.status_code == 200, resp.text


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/search/datasets/", "/collections/datasets/items"])
@pytest.mark.parametrize(
    "cql2_json",
    [
        "[{}]",
        '["a\\u0000b"]',
        "[]",
        '["x"]',
        json.dumps(_cql2_json_equals("a\x00b")),
        '{"filter": []}',
        '{"filter": true}',
        '{"filter": "x"}',
        '{"property": "title"}',
        '{"filter": {"property": "title"}}',
    ],
)
async def test_a_top_level_cql2_json_array_is_refused(
    client: AsyncClient, path: str, cql2_json: str
):
    resp = await client.get(
        path, params={"filter-lang": "cql2-json", "filter": cql2_json}
    )

    assert resp.status_code == 400, resp.text


@pytest.mark.anyio
@pytest.mark.parametrize("path", ["/search/datasets/", "/collections/datasets/items"])
async def test_a_boolean_cql2_json_filter_does_not_fail(client: AsyncClient, path: str):
    resp = await client.get(path, params={"filter-lang": "cql2-json", "filter": "true"})

    assert resp.status_code < 500, resp.text
