"""Anonymous OGC, STAC and search reads run under the shorter anonymous
statement deadline; authenticated reads keep the API-wide one."""

from __future__ import annotations

import importlib
import uuid

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from httpx import AsyncClient
from sqlalchemy import func, literal_column, select, text

from app.core.statement_timeout import (
    anonymous_read_timeout_ms,
    install_api_statement_timeout,
)

_SLEEP = text("SELECT pg_sleep(1.5)")

# Each read path, and the function on it that takes the request session first.
_READS = [
    pytest.param(
        "app.standards.ogc.router",
        "_get_visible_dataset",
        "GET",
        f"/collections/{uuid.uuid4()}/items",
        None,
        404,
        id="ogc-features-items",
    ),
    pytest.param(
        "app.modules.catalog.search.router",
        "_handle_search",
        "GET",
        "/collections/datasets/items",
        None,
        200,
        id="ogc-records-items",
    ),
    pytest.param(
        "app.modules.catalog.search.router",
        "_handle_search",
        "GET",
        "/search/datasets",
        None,
        200,
        id="catalog-search",
    ),
    pytest.param(
        "app.standards.stac.router",
        "_execute_search",
        "POST",
        "/stac/search",
        {"limit": 1},
        200,
        id="stac-search",
    ),
]
_READ_ARGS = ("module", "function", "method", "path", "body", "authenticated_status")


def _assert_uncached_timeout(resp) -> None:
    assert resp.status_code == 503, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    assert resp.json()["status"] == 503
    assert "etag" not in resp.headers
    cache_control = resp.headers.get("cache-control", "")
    assert "public" not in cache_control and "max-age" not in cache_control


@pytest.fixture
def slow_read(client, monkeypatch):
    """Make *function* in *module* sleep on its session before it answers, with
    the API's deadline listener on the test engine and a 1 s anonymous limit."""
    import app.core.db as db_module
    from app.core.config import settings

    monkeypatch.setattr(settings, "db_anonymous_read_timeout_seconds", 1)
    install_api_statement_timeout(db_module.engine)

    def install(module_name: str, function: str) -> None:
        module = importlib.import_module(module_name)
        original = getattr(module, function)

        async def sleeping(db, *args, **kwargs):
            await db.execute(_SLEEP)
            return await original(db, *args, **kwargs)

        monkeypatch.setattr(module, function, sleeping)

    return install


@pytest.mark.anyio
@pytest.mark.parametrize(_READ_ARGS, _READS)
async def test_an_anonymous_read_past_the_deadline_gets_an_uncached_503(
    client: AsyncClient,
    slow_read,
    module,
    function,
    method,
    path,
    body,
    authenticated_status,
):
    slow_read(module, function)

    _assert_uncached_timeout(await client.request(method, path, json=body))


@pytest.mark.anyio
@pytest.mark.parametrize(_READ_ARGS, _READS)
async def test_the_same_read_with_credentials_keeps_the_api_deadline(
    client: AsyncClient,
    admin_auth_header,
    slow_read,
    module,
    function,
    method,
    path,
    body,
    authenticated_status,
):
    slow_read(module, function)

    resp = await client.request(method, path, json=body, headers=admin_auth_header)

    assert resp.status_code == authenticated_status, resp.text


@pytest.mark.anyio
async def test_an_anonymous_request_leaves_the_next_one_unbound(
    client: AsyncClient, admin_auth_header, slow_read
):
    slow_read("app.modules.catalog.search.router", "_handle_search")

    _assert_uncached_timeout(await client.get("/search/datasets"))
    resp = await client.get("/search/datasets", headers=admin_auth_header)

    assert resp.status_code == 200, resp.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("module", "path"),
    [
        ("app.standards.ogc.router", "/"),
        ("app.modules.catalog.search.router", "/collections/datasets/queryables"),
        ("app.modules.catalog.search.router", "/collections/datasets/schema"),
        ("app.modules.catalog.search.router", "/collections/datasets/sortables"),
    ],
)
async def test_a_read_that_resolves_no_caller_is_bound_for_everyone(
    client: AsyncClient, admin_auth_header, slow_read, module, path
):
    slow_read(module, "get_public_api_url")

    _assert_uncached_timeout(await client.get(path))
    _assert_uncached_timeout(await client.get(path, headers=admin_auth_header))


# ---------------------------------------------------------------------------
# A transaction the request begins after a commit stays bound
# ---------------------------------------------------------------------------


@pytest.mark.anyio
@pytest.mark.parametrize("provider_fails", [False, True], ids=["embedded", "fallback"])
async def test_a_semantic_search_stays_bound_after_the_embedding_releases_its_connection(
    client: AsyncClient,
    admin_auth_header,
    test_db_session,
    slow_read,
    monkeypatch,
    provider_fails,
):
    from app.modules.catalog.search import service_candidates, service_semantic
    from app.processing.embeddings import helpers
    from tests.factories import get_user_id
    from tests.test_hybrid_search import (
        RecordEmbedding,
        _create_search_dataset,
        _get_embedding_dim,
        _make_vector,
        _set_semantic_search,
    )

    session = test_db_session
    dim = await _get_embedding_dim(session)
    dataset = await _create_search_dataset(
        session,
        created_by=await get_user_id(session, "admin"),
        name="Bound Rivers",
        description="rivers",
    )
    session.add(
        RecordEmbedding(
            record_id=dataset.record_id,
            embedding=_make_vector(0.9, dim=dim),
            model_name="text-embedding-3-small",
            content_hash=f"bound_{uuid.uuid4().hex}",
        )
    )
    await session.commit()
    await _set_semantic_search(session, True)
    helpers._has_embeddings_cache.clear()

    released: list[bool] = []
    release = service_semantic.release_connection

    async def recording_release(db):
        await release(db)
        released.append(not db.in_transaction())

    async def provider(*_args, **_kwargs):
        if provider_fails:
            raise RuntimeError("provider down")
        return _make_vector(0.9, dim=dim)

    resolve_arm = service_candidates.resolve_semantic_arm

    async def arm_then_sleep(db, *args, **kwargs):
        arm = await resolve_arm(db, *args, **kwargs)
        await db.execute(_SLEEP)
        return arm

    monkeypatch.setattr(service_semantic, "release_connection", recording_release)
    monkeypatch.setattr(service_semantic, "_embed_with_deadline", provider)
    monkeypatch.setattr(service_candidates, "resolve_semantic_arm", arm_then_sleep)

    for headers, check in ((None, _assert_uncached_timeout), (admin_auth_header, None)):
        service_semantic._embedding_cache_clear()
        service_semantic._embedding_inflight_clear()
        released.clear()
        resp = await client.get(
            "/search/datasets/",
            params={"q": f"bound rivers {uuid.uuid4().hex[:6]}"},
            headers=headers,
        )
        assert released and all(released), "the embedding path ended no transaction"
        if check is not None:
            check(resp)
        else:
            assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# The OGC Records collection document
# ---------------------------------------------------------------------------


def _replace_extent_query(monkeypatch, replacement):
    from app.modules.catalog.search import router

    original = router.apply_visibility_filter

    def filtered(stmt, *args, **kwargs):
        if "st_extent" in str(stmt).lower():
            return replacement
        return original(stmt, *args, **kwargs)

    monkeypatch.setattr(router, "apply_visibility_filter", filtered)


@pytest.mark.anyio
async def test_a_timed_out_collection_document_is_a_503_and_is_not_cached(
    client: AsyncClient, slow_read, monkeypatch
):
    from app.modules.catalog.search.router import _COLLECTION_META_CACHE

    _COLLECTION_META_CACHE.clear()
    _replace_extent_query(monkeypatch, select(func.pg_sleep(1.5)))

    _assert_uncached_timeout(await client.get("/collections/datasets"))
    assert not _COLLECTION_META_CACHE


@pytest.mark.anyio
async def test_a_collection_document_still_degrades_on_other_errors(
    client: AsyncClient, monkeypatch
):
    from app.modules.catalog.search.router import _COLLECTION_META_CACHE

    _COLLECTION_META_CACHE.clear()
    _replace_extent_query(monkeypatch, select(literal_column("1/0")))

    resp = await client.get("/collections/datasets")

    assert resp.status_code == 200, resp.text
    assert _COLLECTION_META_CACHE
    _COLLECTION_META_CACHE.clear()


# ---------------------------------------------------------------------------
# Settings and structure
# ---------------------------------------------------------------------------


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


def _bound_routes():
    """Every OGC Features, OGC Records, STAC and catalog search read route, with
    the deadline dependencies and caller resolvers in its tree."""
    from app.api.main import app
    from app.core.statement_timeout import bound_anonymous_reads, bound_every_read
    from app.modules.auth.dependencies import (
        get_optional_user,
        get_optional_user_no_security_schema,
    )

    # The schema-free variant calls get_optional_user directly, not as a dependency.
    resolvers = {get_optional_user, get_optional_user_no_security_schema}

    def calls(dependant):
        for dep in dependant.dependencies:
            yield dep.call
            yield from calls(dep)

    for ctx in iter_route_contexts(app.routes):
        if not isinstance(ctx.route, APIRoute):
            continue
        path = ctx.path
        surface = (
            path in ("/", "/conformance")
            or path.startswith(("/collections", "/stac"))
            or (path.startswith("/search") and not path.startswith("/search/saved"))
        )
        if not surface:
            continue
        tree = set(calls(ctx.route.dependant))
        resolves = bool(tree & resolvers)
        yield (
            path,
            ctx.route.methods,
            bound_anonymous_reads in tree and resolves,
            bound_every_read in tree,
            resolves,
        )


def test_every_read_route_carries_exactly_one_deadline_mechanism():
    """A route either resolves its caller under the anonymous opt-in, or binds
    every request; one that resolves a caller must not bind everyone."""
    routes = list(_bound_routes())
    assert len(routes) > 30
    for path, methods, by_caller, every, resolves in routes:
        assert by_caller != every, (path, methods)
        if every:
            assert not resolves, (path, methods)


def test_only_read_routes_carry_the_deadline():
    """GET or HEAD, or the STAC POST search."""
    paths = set()
    for path, methods, by_caller, every, _ in _bound_routes():
        paths.add(path)
        if methods - {"GET", "HEAD"}:
            assert (path, methods) == ("/stac/search", {"POST"})
    for expected in (
        "/",
        "/collections/{dataset_id}/items",
        "/collections/datasets/items",
        "/collections/datasets/queryables",
        "/search/datasets/",
        "/search/facets/",
        "/stac/search",
        "/stac/conformance",
    ):
        assert expected in paths, expected


@pytest.mark.anyio
@pytest.mark.parametrize("dependency", ["bound_anonymous_reads", "bound_every_read"])
async def test_the_deadline_ends_with_its_dependency(dependency):
    from types import SimpleNamespace

    from app.core import statement_timeout

    db = SimpleNamespace(in_transaction=lambda: False)
    if dependency == "bound_anonymous_reads":
        steps = statement_timeout.bound_anonymous_reads(
            SimpleNamespace(state=SimpleNamespace())
        )
    else:
        steps = statement_timeout.bound_every_read()
    await steps.__anext__()
    await statement_timeout.hold_to_anonymous_read_deadline(db)
    assert statement_timeout._anonymous_read.get() is True
    with pytest.raises(StopAsyncIteration):
        await steps.__anext__()
    assert statement_timeout._anonymous_read.get() is False
