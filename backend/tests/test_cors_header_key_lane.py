"""Header-key CORS: a request that sends X-Api-Key is readable from any origin.

A script that sends a key in a header already holds it, so there is no ambient
credential for CORS to guard. The answer is ``Access-Control-Allow-Origin: *``
with no credentials flag, so a browser never pairs it with cookies, and the
middleware drops any cookie before the request is served. A response gets the
wildcard only when the auth layer looked the key up, so a made-up key opens no
route that never reads one. A read whose only credential is ``?api_key=`` gets
the same answer, limited to read methods, once the auth layer resolved the key.
Bearer tokens, cookies and embed tokens keep the old rule: no wildcard outside
``CORS_ALLOWED_ORIGINS``.
"""

import re
import uuid

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.api.middleware.cors import DynamicCORSMiddleware
from app.platform.request_credential import (
    mark_header_api_key_evaluated,
    mark_query_api_key,
    mark_refused_before_auth,
)
from app.core.config import settings
from tests.conftest import get_auth_header
from tests import test_api_key_scope_875 as _scope_tests

_remove_keys_minted_by_the_test = _scope_tests._remove_keys_minted_by_the_test

_FOREIGN_ORIGIN = "https://notebook.example.org"
_ALLOWED_ORIGIN = "https://app.example.com"


@pytest.fixture
def allow_one_origin(monkeypatch):
    """Only ``_ALLOWED_ORIGIN`` is listed; stubbed so no cached lookup outlives the test."""

    async def _allow(_self, origin):
        return origin == _ALLOWED_ORIGIN

    monkeypatch.setattr(
        "app.api.middleware.cors.DynamicCORSMiddleware._is_origin_allowed", _allow
    )


async def _full_key(client) -> str:
    headers = await get_auth_header(
        client,
        settings.geolens_admin_username,
        settings.geolens_admin_password.get_secret_value(),
    )
    return (await _scope_tests._mint(client, headers))["key"]


def _assert_header_key_answer(response) -> None:
    assert response.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in response.headers
    allowed = {
        h.strip().lower()
        for h in response.headers["access-control-allow-headers"].split(",")
    }
    assert "x-api-key" in allowed
    assert "authorization" not in allowed and "x-embed-token" not in allowed


@pytest.mark.anyio
@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
async def test_a_preflight_asking_for_the_key_header_is_allowed(
    client, allow_one_origin, method
):
    resp = await client.options(
        "/maps/",
        headers={
            "Origin": _FOREIGN_ORIGIN,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "x-api-key, content-type",
        },
    )
    assert resp.status_code == 200
    _assert_header_key_answer(resp)
    assert method in resp.headers["access-control-allow-methods"]


@pytest.mark.anyio
async def test_a_keyed_config_import_can_send_its_preview_token(
    client, allow_one_origin
):
    resp = await client.options(
        "/config-ops/import/",
        headers={
            "Origin": _FOREIGN_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-api-key, content-type, x-config-preview-token",
        },
    )
    _assert_header_key_answer(resp)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "requested",
    [
        "content-type",
        "x-api-key, authorization",
        "x-api-key, x-embed-token",
        "x-api-key, x-custom",
    ],
)
async def test_other_preflights_get_no_wildcard(client, allow_one_origin, requested):
    resp = await client.options(
        "/maps/",
        headers={
            "Origin": _FOREIGN_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": requested,
        },
    )
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
async def test_keyed_reads_and_writes_get_the_wildcard(client, allow_one_origin):
    key = {"X-Api-Key": await _full_key(client), "Origin": _FOREIGN_ORIGIN}

    me = await client.get("/auth/me/", headers=key)
    assert me.status_code == 200, me.text
    _assert_header_key_answer(me)

    made = await client.post(
        "/maps/", json={"name": f"Notebook map {uuid.uuid4().hex[:6]}"}, headers=key
    )
    assert made.status_code == 201, made.text
    _assert_header_key_answer(made)


@pytest.mark.anyio
async def test_an_unkeyed_request_from_an_unlisted_origin_gets_no_wildcard(
    client, allow_one_origin
):
    resp = await client.get("/auth/me/", headers={"Origin": _FOREIGN_ORIGIN})
    assert resp.status_code == 401
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
async def test_an_invalid_key_answers_401_that_the_caller_can_read(
    client, allow_one_origin
):
    resp = await client.get(
        "/auth/me/", headers={"Origin": _FOREIGN_ORIGIN, "X-Api-Key": "not-a-real-key"}
    )
    assert resp.status_code == 401
    _assert_header_key_answer(resp)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "credential",
    [
        {"Authorization": "Bearer not-a-real-token"},
        {"X-Embed-Token": "not-a-real-token"},
    ],
)
async def test_a_key_sent_with_another_credential_gets_no_wildcard(
    client, allow_one_origin, credential
):
    resp = await client.get(
        "/auth/me/",
        headers={"Origin": _FOREIGN_ORIGIN, "X-Api-Key": "x", **credential},
    )
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
async def test_a_made_up_key_opens_no_route_that_never_reads_one(
    client, allow_one_origin
):
    resp = await client.get(
        "/settings/branding/",
        headers={"Origin": _FOREIGN_ORIGIN, "X-Api-Key": "not-a-real-key"},
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
@pytest.mark.parametrize("param", ["api_key", "embed_token"])
async def test_a_header_key_with_a_query_credential_gets_no_wildcard(
    client, allow_one_origin, param
):
    resp = await client.get(
        "/auth/me/",
        params={param: "x"},
        headers={"Origin": _FOREIGN_ORIGIN, "X-Api-Key": await _full_key(client)},
    )
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path,allowed",
    [
        ("/auth/me/", True),
        ("/auth/me", True),
        ("/auth/me/permissions/", True),
        ("/auth/download-token/1", True),
        ("/auth/login", False),
        ("/auth/register/", False),
        ("/auth/oauth/exchange/", False),
        ("/auth/logout/session/", False),
    ],
)
async def test_auth_routes_take_a_keyed_preflight_only_where_a_key_is_read(
    client, allow_one_origin, path, allowed
):
    resp = await client.options(
        path,
        headers={
            "Origin": _FOREIGN_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-api-key, content-type",
        },
    )
    assert ("access-control-allow-origin" in resp.headers) is allowed


@pytest.mark.anyio
async def test_only_a_keyed_answer_varies_on_the_credential_headers(
    client, allow_one_origin
):
    """A public answer stays shareable by a cache; a keyed one never is."""

    def vary(resp) -> set[str]:
        return {
            token.strip().lower()
            for line in resp.headers.get_list("vary")
            for token in line.split(",")
        }

    public = await client.get(
        "/search/datasets/?q=x", headers={"Origin": _FOREIGN_ORIGIN}
    )
    assert "origin" in vary(public)
    assert not {"authorization", "x-api-key", "x-embed-token"} & vary(public)

    keyed = await client.get(
        "/auth/me/", headers={"Origin": _FOREIGN_ORIGIN, "X-Api-Key": "not-a-real-key"}
    )
    assert {"origin", "authorization", "x-api-key", "x-embed-token"} <= vary(keyed)


def test_nothing_that_reads_credentials_runs_before_the_cookie_strip():
    """Only the metrics layers sit outside the CORS middleware."""
    from app.api.main import app

    outer = []
    for middleware in app.user_middleware:
        if middleware.cls is DynamicCORSMiddleware:
            break
        dispatch = middleware.kwargs.get("dispatch")
        outer.append(getattr(dispatch, "__name__", middleware.cls.__name__))
    assert outer == [
        "_hold_scrape_lock_during_metrics_response",
        "PrometheusInstrumentatorMiddleware",
    ]


@pytest.mark.anyio
async def test_a_listed_origin_keeps_its_credentialed_answer(client, allow_one_origin):
    resp = await client.get(
        "/auth/me/",
        headers={"Origin": _ALLOWED_ORIGIN, "X-Api-Key": await _full_key(client)},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert resp.headers["access-control-allow-credentials"] == "true"
    assert "x-api-key" in resp.headers["vary"].lower()

    session = await client.get(
        "/search/datasets/?q=x",
        headers={"Origin": _ALLOWED_ORIGIN, "Cookie": "session=not-a-real-session"},
    )
    assert "cookie" in session.headers["vary"].lower()

    anonymous = await client.get(
        "/search/datasets/?q=x", headers={"Origin": _ALLOWED_ORIGIN}
    )
    assert "x-api-key" not in anonymous.headers["vary"].lower()


@pytest.mark.anyio
async def test_a_keyed_public_search_gets_the_keyed_answer(client, allow_one_origin):
    resp = await client.get(
        "/search/datasets/?q=x",
        headers={"Origin": _FOREIGN_ORIGIN, "X-Api-Key": await _full_key(client)},
    )
    assert resp.status_code == 200
    _assert_header_key_answer(resp)


def _cookie_echo_client(monkeypatch) -> TestClient:
    async def _deny(_self, _origin):
        return False

    monkeypatch.setattr(
        "app.api.middleware.cors.DynamicCORSMiddleware._is_origin_allowed", _deny
    )

    async def echo(request: Request) -> JSONResponse:
        # Stands in for the auth layer reading the key.
        if request.headers.get("x-api-key"):
            mark_header_api_key_evaluated(request.scope)
        elif request.query_params.get("api_key"):
            mark_query_api_key(request.scope, resolved=True)
        return JSONResponse({"cookies": dict(request.cookies)})

    app = Starlette(routes=[Route("/echo", echo, methods=["GET", "POST"])])
    app.add_middleware(DynamicCORSMiddleware)
    return TestClient(app)


def test_a_cookie_sent_with_a_key_is_not_read(monkeypatch):
    client = _cookie_echo_client(monkeypatch)
    resp = client.post(
        "/echo",
        headers={
            "Origin": _FOREIGN_ORIGIN,
            "X-Api-Key": "k",
            "Cookie": "geolens_refresh=secret",
        },
    )
    assert resp.json() == {"cookies": {}}
    assert resp.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in resp.headers


def test_a_cookie_sent_with_a_url_key_is_not_read(monkeypatch):
    client = _cookie_echo_client(monkeypatch)
    resp = client.get(
        "/echo?api_key=k",
        headers={"Origin": _FOREIGN_ORIGIN, "Cookie": "geolens_refresh=secret"},
    )
    assert resp.json() == {"cookies": {}}
    assert resp.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in resp.headers


def test_a_cookie_without_a_key_still_reaches_the_app(monkeypatch):
    """The paired control: only the header-key lane drops cookies."""
    client = _cookie_echo_client(monkeypatch)
    resp = client.post(
        "/echo",
        headers={"Origin": _FOREIGN_ORIGIN, "Cookie": "geolens_refresh=secret"},
    )
    assert resp.json() == {"cookies": {"geolens_refresh": "secret"}}
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
async def test_a_keyed_request_to_a_public_route_keeps_the_public_answer(
    client, allow_one_origin
):
    """STAC and OGC clients send their key everywhere, landing page included."""
    resp = await client.get(
        "/conformance",
        headers={"Origin": _FOREIGN_ORIGIN, "X-Api-Key": "not-a-real-key"},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in resp.headers
    assert "PUT" not in resp.headers["access-control-allow-methods"]


@pytest.mark.anyio
@pytest.mark.parametrize("param", ["api_key", "embed_token"])
async def test_a_keyed_preflight_with_a_query_credential_gets_no_wildcard(
    client, allow_one_origin, param
):
    resp = await client.options(
        f"/maps/?{param}=x",
        headers={
            "Origin": _FOREIGN_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-api-key",
        },
    )
    assert "access-control-allow-origin" not in resp.headers


# The functions that look up a request's key; a dependency calling one reads it.
_KEY_READERS = (
    "_resolve_api_key(",
    "_resolve_optional_identity(",
    "get_optional_user(",
    "get_current_user(",
)


def _key_reading_by_route() -> dict[tuple[str, str], bool]:
    """Whether each (method, path) route's dependencies look up a key."""
    import inspect

    from fastapi.routing import APIRoute, iter_route_contexts

    from app.api.main import app

    def reads_a_key(dependant) -> bool:
        for sub in dependant.dependencies:
            try:
                source = inspect.getsource(sub.call)
            except (OSError, TypeError):
                source = ""
            if any(call in source for call in _KEY_READERS):
                return True
            if reads_a_key(sub):
                return True
        return False

    return {
        (method, ctx.path): reads_a_key(ctx.route.dependant)
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.route, APIRoute)
        for method in ctx.route.methods
    }


def _routes_reading_no_key() -> list[tuple[str, str]]:
    """(method, path) for every route whose dependencies never look up a key."""
    return sorted(
        route for route, reads in _key_reading_by_route().items() if not reads
    )


@pytest.mark.anyio
async def test_an_auth_path_takes_a_keyed_preflight_exactly_when_its_routes_read_a_key(
    client, allow_one_origin
):
    every_method_reads: dict[str, bool] = {}
    for (_method, path), reads in _key_reading_by_route().items():
        if path.startswith("/auth/"):
            every_method_reads[path] = every_method_reads.get(path, True) and reads
    assert any(every_method_reads.values()) and not all(every_method_reads.values())
    for path, reads in every_method_reads.items():
        resp = await client.options(
            re.sub(r"\{[^}]+\}", "1", path),
            headers={
                "Origin": _FOREIGN_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "x-api-key, content-type",
            },
        )
        assert ("access-control-allow-origin" in resp.headers) is reads, path


def test_every_unsafe_route_that_reads_no_key_is_under_auth():
    """The keyed-preflight refusal under /auth/ is what keeps these blind."""
    unsafe = [
        (method, path)
        for method, path in _routes_reading_no_key()
        if method not in {"GET", "HEAD", "OPTIONS"}
    ]
    assert unsafe, "the walk should find the sign-in routes"
    assert not [p for p in unsafe if not p[1].startswith("/auth/")], unsafe


@pytest.mark.anyio
async def test_no_route_that_reads_no_key_gives_a_junk_key_the_key_answer(
    client, allow_one_origin
):
    """Such a route answers a keyed request at most with its public answer."""
    paths = [
        path
        for method, path in _routes_reading_no_key()
        if method == "GET" and "{" not in path
    ]
    assert "/settings/branding/" in paths
    for path in paths:
        resp = await client.get(
            path, headers={"Origin": _FOREIGN_ORIGIN, "X-Api-Key": "not-a-real-key"}
        )
        if "access-control-allow-origin" in resp.headers:
            assert "PUT" not in resp.headers["access-control-allow-methods"], path


@pytest.mark.parametrize("status_code", [413, 429])
@pytest.mark.parametrize("marked", [True, False])
def test_only_a_limit_refusal_before_auth_is_readable_to_a_keyed_caller(
    monkeypatch, status_code, marked
):
    """The limits mark what they refuse; a route's own 413 or 429 isn't marked."""

    async def _deny(_self, _origin):
        return False

    monkeypatch.setattr(
        "app.api.middleware.cors.DynamicCORSMiddleware._is_origin_allowed", _deny
    )

    async def refused(request: Request) -> JSONResponse:
        if marked:
            mark_refused_before_auth(request.scope)
        return JSONResponse({"detail": "limited"}, status_code=status_code)

    app = Starlette(routes=[Route("/limited", refused)])
    app.add_middleware(DynamicCORSMiddleware)
    client = TestClient(app)

    keyed = client.get(
        "/limited", headers={"Origin": _FOREIGN_ORIGIN, "X-Api-Key": "k"}
    )
    assert keyed.status_code == status_code
    assert ("access-control-allow-origin" in keyed.headers) is marked
    assert "access-control-allow-credentials" not in keyed.headers
    plain = client.get("/limited", headers={"Origin": _FOREIGN_ORIGIN})
    assert "access-control-allow-origin" not in plain.headers


@pytest.mark.anyio
async def test_the_body_limit_marks_its_refusal(client, allow_one_origin):
    resp = await client.post(
        "/maps/",
        content=b"{}",
        headers={
            "Origin": _FOREIGN_ORIGIN,
            "X-Api-Key": "not-a-real-key",
            "Content-Type": "application/json",
            "Content-Length": str(1 << 30),
        },
    )
    assert resp.status_code == 413
    assert resp.headers["access-control-allow-origin"] == "*"


@pytest.mark.anyio
async def test_the_global_rate_limit_marks_its_refusal(monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from slowapi.errors import RateLimitExceeded
    from slowapi.util import get_remote_address

    from app.api.main import _rate_limit_handler
    from app.api.middleware.rate_limit import GlobalRateLimitMiddleware
    from app.platform.ratelimit import _FallbackAnnouncingLimiter

    async def _deny(_self, _origin):
        return False

    monkeypatch.setattr(
        "app.api.middleware.cors.DynamicCORSMiddleware._is_origin_allowed", _deny
    )
    app = FastAPI()
    app.state.limiter = _FallbackAnnouncingLimiter(
        key_func=get_remote_address, default_limits=["1/minute"], key_style="endpoint"
    )
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(GlobalRateLimitMiddleware)
    app.add_middleware(DynamicCORSMiddleware)

    @app.get("/limited")
    async def limited() -> dict[str, bool]:  # pragma: no cover - trivial
        return {"ok": True}

    headers = {"Origin": _FOREIGN_ORIGIN, "X-Api-Key": "k"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        await http.get("/limited", headers=headers)
        refused = await http.get("/limited", headers=headers)

    assert refused.status_code == 429
    assert refused.headers["access-control-allow-origin"] == "*"


_URL_KEY_METHODS = "GET, HEAD, OPTIONS"
_CORS_HEADERS = (
    "access-control-allow-origin",
    "access-control-allow-credentials",
    "access-control-allow-methods",
    "access-control-allow-headers",
    "access-control-expose-headers",
    "access-control-max-age",
)


def _cors_answer(resp) -> dict[str, object]:
    """The CORS headers and Vary tokens of a response, Allow-Methods aside."""
    answer: dict[str, object] = {
        name: resp.headers.get(name)
        for name in _CORS_HEADERS
        if name != "access-control-allow-methods"
    }
    answer["vary"] = {
        token.strip().lower()
        for line in resp.headers.get_list("vary")
        for token in line.split(",")
    }
    return answer


def _assert_url_key_answer(url_keyed, header_keyed) -> None:
    """A URL key gets the header-key answer, promising only read methods."""
    _assert_header_key_answer(url_keyed)
    assert _cors_answer(url_keyed) == _cors_answer(header_keyed)
    assert url_keyed.headers["access-control-allow-methods"] == _URL_KEY_METHODS


@pytest.fixture
def fake_export(monkeypatch, tmp_path):
    """Each export writes a small file of its own instead of running ogr2ogr."""

    async def _export(table_name, dataset_name, format_key, **_options):
        out = tmp_path / uuid.uuid4().hex
        out.mkdir()
        path = out / f"{dataset_name}.geojson"
        path.write_bytes(b'{"type":"FeatureCollection","features":[]}')
        return str(path), path.name, "application/geo+json"

    monkeypatch.setattr("app.processing.export.selection.export_dataset", _export)


@pytest.fixture
async def private_dataset(test_db_session, fake_export):
    """A private, published point dataset owned by the admin, with a data table."""
    from tests.factories import create_dataset, get_user_id
    from tests.test_tiles import _cleanup_data_table, _create_data_table

    table = f"cors_url_key_{uuid.uuid4().hex[:8]}"
    dataset = await create_dataset(
        test_db_session,
        created_by=await get_user_id(test_db_session, "admin"),
        table_name=table,
        visibility="private",
        geometry_type="Point",
        feature_count=1,
        column_info=[
            {"name": "gid", "type": "integer"},
            {"name": "name", "type": "text"},
            {"name": "value", "type": "integer"},
            {"name": "geom", "type": "geometry"},
            {"name": "geom_4326", "type": "geometry"},
        ],
    )
    await _create_data_table(test_db_session, table)
    yield dataset
    await test_db_session.rollback()
    await _cleanup_data_table(test_db_session, table)


_KEYED_READS = {
    "items": "/collections/{id}/items",
    "collection": "/collections/{id}",
    "collections": "/collections",
    "export": "/datasets/{id}/export?format=geojson",
    "tile": "/tiles/data.{table}/0/0/0.pbf",
}


@pytest.mark.anyio
@pytest.mark.usefixtures("_init_tile_pool_for_tests")
@pytest.mark.parametrize("target", sorted(_KEYED_READS))
async def test_a_url_key_gets_the_header_key_answer(
    client, allow_one_origin, private_dataset, target
):
    key = await _full_key(client)
    path = _KEYED_READS[target].format(
        id=private_dataset.id, table=private_dataset.table_name
    )
    origin = {"Origin": _FOREIGN_ORIGIN}

    url_keyed = await client.get(path, params={"api_key": key}, headers=origin)
    header_keyed = await client.get(path, headers={**origin, "X-Api-Key": key})

    assert url_keyed.status_code == header_keyed.status_code == 200, header_keyed.text
    _assert_url_key_answer(url_keyed, header_keyed)


@pytest.mark.anyio
async def test_a_url_keyed_read_is_never_shared_cached_and_echoes_no_key(
    client, allow_one_origin, private_dataset
):
    key = await _full_key(client)
    resp = await client.get(
        f"/collections/{private_dataset.id}/items",
        params={"api_key": key},
        headers={"Origin": _FOREIGN_ORIGIN},
    )
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"].startswith("private")
    assert {"origin", "authorization", "x-api-key", "cookie"} <= _cors_answer(resp)[
        "vary"
    ]
    assert not [name for name, value in resp.headers.items() if key in value]


@pytest.mark.anyio
async def test_an_unknown_or_revoked_url_key_gets_no_wildcard(
    client, allow_one_origin, private_dataset
):
    admin = await get_auth_header(
        client,
        settings.geolens_admin_username,
        settings.geolens_admin_password.get_secret_value(),
    )
    minted = await _scope_tests._mint(client, admin)
    revoked = await client.delete(f"/auth/api-keys/{minted['id']}", headers=admin)
    assert revoked.status_code == 204, revoked.text
    path = f"/collections/{private_dataset.id}/items"

    for key in ("not-a-real-key", minted["key"]):
        resp = await client.get(
            path, params={"api_key": key}, headers={"Origin": _FOREIGN_ORIGIN}
        )
        assert resp.status_code == 401
        assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
async def test_a_url_key_on_a_route_refusing_that_form_gets_no_wildcard(
    client, allow_one_origin, private_dataset
):
    """A validate run that refreshes is a write, so a URL key never authenticates it."""
    resp = await client.get(
        f"/datasets/{private_dataset.id}/validate",
        params={"api_key": await _full_key(client), "refresh": "true"},
        headers={"Origin": _FOREIGN_ORIGIN},
    )
    assert resp.status_code == 404
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
async def test_a_url_keyed_write_is_refused_without_a_wildcard(
    client, allow_one_origin
):
    key = await _full_key(client)
    write = await client.post(
        "/maps/",
        params={"api_key": key},
        json={"name": "URL keyed map"},
        headers={"Origin": _FOREIGN_ORIGIN},
    )
    assert write.status_code == 401
    assert "access-control-allow-origin" not in write.headers

    preflight = await client.options(
        f"/maps/?api_key={key}",
        headers={
            "Origin": _FOREIGN_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert "access-control-allow-origin" not in preflight.headers


@pytest.mark.anyio
async def test_a_url_keyed_preflight_gets_the_header_key_answer_for_reads(
    client, allow_one_origin, private_dataset
):
    path = f"/collections/{private_dataset.id}/items"
    preflight = {
        "Origin": _FOREIGN_ORIGIN,
        "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "accept, range",
    }

    url_keyed = await client.options(f"{path}?api_key=x", headers=preflight)
    header_keyed = await client.options(
        path,
        headers={
            **preflight,
            "Access-Control-Request-Headers": "x-api-key, accept, range",
        },
    )

    assert url_keyed.status_code == 200
    _assert_url_key_answer(url_keyed, header_keyed)


@pytest.mark.anyio
async def test_a_url_key_with_a_bearer_token_keeps_todays_answer(
    client, allow_one_origin, private_dataset
):
    admin = await get_auth_header(
        client,
        settings.geolens_admin_username,
        settings.geolens_admin_password.get_secret_value(),
    )
    resp = await client.get(
        f"/collections/{private_dataset.id}/items",
        params={"api_key": await _full_key(client)},
        headers={"Origin": _FOREIGN_ORIGIN, **admin},
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
async def test_a_url_key_from_a_listed_origin_keeps_the_credentialed_answer(
    client, allow_one_origin, private_dataset
):
    resp = await client.get(
        f"/collections/{private_dataset.id}/items",
        params={"api_key": await _full_key(client)},
        headers={"Origin": _ALLOWED_ORIGIN},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert resp.headers["access-control-allow-credentials"] == "true"


@pytest.mark.anyio
async def test_a_url_key_to_a_route_that_never_reads_it_keeps_the_public_answer(
    client, allow_one_origin
):
    """A map client sends its key on every request, conformance included."""
    resp = await client.get(
        "/conformance",
        params={"api_key": "not-a-real-key"},
        headers={"Origin": _FOREIGN_ORIGIN},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in resp.headers
    assert "x-api-key" not in _cors_answer(resp)["vary"]
