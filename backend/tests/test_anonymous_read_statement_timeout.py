"""Anonymous OGC, STAC and search reads run under the shorter anonymous
statement deadline; authenticated reads keep the API-wide one."""

from __future__ import annotations

import uuid

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from httpx import AsyncClient
from sqlalchemy import text

from app.core.statement_timeout import anonymous_read_timeout_ms

_SLEEP = text("SELECT pg_sleep(1.5)")

# Each read path, and the function on it that takes the request session first.
_READS = [
    pytest.param(
        "app.standards.ogc.router",
        "_get_visible_dataset",
        "GET",
        f"/collections/{uuid.uuid4()}/items",
        None,
        id="ogc-features-items",
    ),
    pytest.param(
        "app.modules.catalog.search.router",
        "_handle_search",
        "GET",
        "/collections/datasets/items",
        None,
        id="ogc-records-items",
    ),
    pytest.param(
        "app.modules.catalog.search.router",
        "_handle_search",
        "GET",
        "/search/datasets",
        None,
        id="catalog-search",
    ),
    pytest.param(
        "app.standards.stac.router",
        "_execute_search",
        "POST",
        "/stac/search",
        {"limit": 1},
        id="stac-search",
    ),
]


@pytest.fixture
def slow_read(monkeypatch):
    """Make *function* in *module* sleep on its session before it answers."""
    import importlib

    from app.core.config import settings

    monkeypatch.setattr(settings, "db_anonymous_read_timeout_seconds", 1)

    def install(module_name: str, function: str) -> None:
        module = importlib.import_module(module_name)
        original = getattr(module, function)

        async def sleeping(db, *args, **kwargs):
            await db.execute(_SLEEP)
            return await original(db, *args, **kwargs)

        monkeypatch.setattr(module, function, sleeping)

    return install


@pytest.mark.anyio
@pytest.mark.parametrize(("module", "function", "method", "path", "body"), _READS)
async def test_an_anonymous_read_past_the_deadline_gets_an_uncached_503(
    client: AsyncClient, slow_read, module, function, method, path, body
):
    slow_read(module, function)

    resp = await client.request(method, path, json=body)

    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["status"] == 503
    assert "etag" not in resp.headers
    cache_control = resp.headers.get("cache-control", "")
    assert "public" not in cache_control and "max-age" not in cache_control


@pytest.mark.anyio
@pytest.mark.parametrize(("module", "function", "method", "path", "body"), _READS)
async def test_the_same_read_with_credentials_keeps_the_api_deadline(
    client: AsyncClient,
    admin_auth_header,
    slow_read,
    module,
    function,
    method,
    path,
    body,
):
    slow_read(module, function)

    resp = await client.request(method, path, json=body, headers=admin_auth_header)

    expected = 404 if path.endswith("/items") and "datasets" not in path else 200
    assert resp.status_code == expected, resp.text


@pytest.mark.parametrize(
    ("anonymous", "api", "expected"),
    [(30, 300, 30_000), (600, 300, 300_000), (0, 300, 0), (30, 0, 30_000)],
)
def test_the_anonymous_deadline_never_exceeds_the_api_one(
    monkeypatch, anonymous, api, expected
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "db_anonymous_read_timeout_seconds", anonymous)
    monkeypatch.setattr(settings, "db_statement_timeout_seconds", api)
    assert anonymous_read_timeout_ms() == expected


def test_the_default_is_thirty_seconds():
    from app.core.config import Settings

    assert Settings.model_fields["db_anonymous_read_timeout_seconds"].default == 30


def test_only_read_routes_carry_the_anonymous_deadline():
    """Every route that opts in reads: GET or HEAD, or the STAC POST search."""
    from app.api.main import app
    from app.modules.auth.dependencies import bound_anonymous_reads

    def opted_in(dependant) -> bool:
        return any(
            dep.call is bound_anonymous_reads or opted_in(dep)
            for dep in dependant.dependencies
        )

    routes = [
        (ctx.path, ctx.route.methods)
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.route, APIRoute) and opted_in(ctx.route.dependant)
    ]
    paths = {path for path, _ in routes}
    for expected in (
        "/collections/{dataset_id}/items",
        "/collections/datasets/items",
        "/search/datasets/",
        "/search/facets/",
        "/stac/search",
        "/stac/collections",
    ):
        assert expected in paths, expected
    for path, methods in routes:
        if methods - {"GET", "HEAD"}:
            assert (path, methods) == ("/stac/search", {"POST"})
