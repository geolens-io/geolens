"""A CQL2-JSON filter that decodes and parses but is malformed answers 400, never 500."""

import json
import random

import pytest
from httpx import AsyncClient

from app.modules.catalog.datasets.domain.models import Dataset

from tests.test_ogc_features_filter import (  # noqa: F401  (pytest fixture)
    _items_url,
    filter_dataset,
)

_PAST_INT_STR_LIMIT = "1" + "0" * 4400

REGRESSIONS = {
    "in-member-list-not-a-list": '{"op":"in","args":[{"property":"name"},1]}',
    "property-name-not-a-string": '{"op":"=","args":[{"property":[]},"x"]}',
    "integer-literal-past-the-digit-limit": (
        '{"op":"=","args":[{"property":"cat"},' + _PAST_INT_STR_LIMIT + "]}"
    ),
    "timestamp-in-member-list-not-a-list": (
        '{"op":"in","args":[{"property":"created"},1]}'
    ),
}

_OPS = [
    "=", "<>", "<", ">=", "in", "between", "like", "isNull", "not", "and", "or",
    "s_intersects", "t_after", "a_contains", "casei", "nope", 7, None, [],
]  # fmt: skip
_PROPS = ["name", "created", "updated", "geometry", "cat", "", [], {}, 1, None, True]
_LITERALS = [
    1, -1.5, "x", "", True, None, [], {}, [1], [[]], {"x": 1}, {"timestamp": 5},
    {"bbox": [1, 2]}, {"type": "Point"}, {"date": "nope"}, {"interval": [1]},
    {"function": 1}, 10**30, 1e308,
]  # fmt: skip


def _generated_expressions() -> list[str]:
    rng = random.Random(4172)
    out: list[str] = []
    for _ in range(90):
        op = rng.choice(_OPS)
        args: object
        shape = rng.randrange(5)
        if shape == 0:
            args = rng.choice(_LITERALS)
        elif shape == 1:
            args = []
        else:
            args = [
                {"property": rng.choice(_PROPS)}
                if rng.random() < 0.6
                else rng.choice(_LITERALS)
                for _ in range(rng.randrange(1, 4))
            ]
            if rng.random() < 0.4:
                args.append(rng.choice(_LITERALS))
        node: dict = {"op": op, "args": args}
        if rng.random() < 0.25:
            node = {"op": rng.choice(["and", "or", "not"]), "args": [node, node]}
        out.append(json.dumps(node))
    # Nesting well inside the depth limit, with a malformed leaf.
    leaf = {"op": "in", "args": [{"property": "name"}, 1]}
    for _ in range(40):
        leaf = {"op": "not", "args": [leaf]}
    out.append(json.dumps(leaf))
    return out


def _routes(dataset: Dataset) -> dict[str, str]:
    return {
        "search": "/search/datasets/",
        "records": "/collections/datasets/items",
        "features": _items_url(dataset),
    }


@pytest.mark.anyio
@pytest.mark.parametrize("name", REGRESSIONS)
@pytest.mark.parametrize("route", ["search", "records", "features"])
async def test_malformed_filter_is_a_400(
    client: AsyncClient,
    filter_dataset: Dataset,  # noqa: F811
    route: str,
    name: str,
):
    resp = await client.get(
        _routes(filter_dataset)[route],
        params={"filter-lang": "cql2-json", "filter": REGRESSIONS[name]},
    )

    assert resp.status_code in (400, 422), resp.text
    assert "detail" in resp.json()


@pytest.mark.anyio
@pytest.mark.parametrize("route", ["search", "records", "features"])
async def test_generated_malformed_filters_never_answer_500(
    client: AsyncClient,
    filter_dataset: Dataset,  # noqa: F811
    route: str,
):
    url = _routes(filter_dataset)[route]
    failures = []
    for expr in _generated_expressions():
        try:
            resp = await client.get(
                url, params={"filter-lang": "cql2-json", "filter": expr}
            )
        except Exception as e:  # broad: the test client re-raises an unhandled 500
            failures.append((type(e).__name__, expr[:120]))
            continue
        if resp.status_code >= 500:
            failures.append((resp.status_code, expr[:120]))

    assert not failures


@pytest.mark.anyio
@pytest.mark.parametrize("route", ["search", "records"])
@pytest.mark.parametrize(
    "expr",
    [
        '{"op":"and","args":[true,{"op":"=","args":[{"property":"title"},"x"]}]}',
        '{"op":"or","args":[{"op":"not","args":[false]},{"op":"=","args":[{"property":"title"},"x"]}]}',
    ],
)
async def test_a_boolean_literal_operand_is_still_accepted(
    client: AsyncClient, route: str, expr: str
):
    url = {"search": "/search/datasets/", "records": "/collections/datasets/items"}[
        route
    ]
    resp = await client.get(url, params={"filter-lang": "cql2-json", "filter": expr})

    assert resp.status_code == 200, resp.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "stamp", ["9999-12-31T23:59:59-01:00", "0001-01-01T00:00:00+01:00"]
)
async def test_a_timestamp_past_the_supported_years_in_utc_is_a_400(
    client: AsyncClient,
    filter_dataset: Dataset,  # noqa: F811
    stamp: str,
):
    expr = json.dumps(
        {"op": "=", "args": [{"property": "built"}, {"timestamp": stamp}]}
    )
    resp = await client.get(
        _items_url(filter_dataset),
        params={"filter-lang": "cql2-json", "filter": expr},
    )

    assert resp.status_code == 400, resp.text
