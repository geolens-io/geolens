"""Header-key CORS: a request that sends X-Api-Key is readable from any origin.

A script that sends a key in a header already holds it, so there is no ambient
credential for CORS to guard. The answer is ``Access-Control-Allow-Origin: *``
with no credentials flag, so a browser never pairs it with cookies, and the
middleware drops any cookie before the request is served. A response gets the
wildcard only when the auth layer looked the key up, so a made-up key opens no
route that never reads one. Bearer tokens, cookies, embed tokens and
query-string credentials keep the old rule: no wildcard outside
``CORS_ALLOWED_ORIGINS``.
"""

import uuid

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.api.middleware.cors import DynamicCORSMiddleware
from app.platform.request_credential import mark_header_api_key_evaluated
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
@pytest.mark.parametrize(
    "requested",
    [
        "content-type",
        "x-api-key, authorization",
        "x-api-key, x-embed-token",
        "x-api-key, x-config-preview-token",
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
        ("/auth/login", False),
        ("/auth/register/", False),
        ("/auth/oauth/exchange/", False),
    ],
)
async def test_auth_routes_take_a_keyed_preflight_only_for_me(
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
async def test_every_answer_varies_on_the_credential_headers(client, allow_one_origin):
    resp = await client.get(
        "/search/datasets/?q=x", headers={"Origin": _FOREIGN_ORIGIN}
    )
    vary = {
        token.strip().lower()
        for line in resp.headers.get_list("vary")
        for token in line.split(",")
    }
    assert {"origin", "authorization", "x-api-key", "x-embed-token"} <= vary


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
async def test_a_query_string_key_gets_no_wildcard(client, allow_one_origin):
    resp = await client.get(
        "/auth/me/",
        params={"api_key": await _full_key(client)},
        headers={"Origin": _FOREIGN_ORIGIN},
    )
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.anyio
async def test_a_listed_origin_keeps_its_credentialed_answer(client, allow_one_origin):
    resp = await client.get(
        "/auth/me/",
        headers={"Origin": _ALLOWED_ORIGIN, "X-Api-Key": await _full_key(client)},
    )
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == _ALLOWED_ORIGIN
    assert resp.headers["access-control-allow-credentials"] == "true"


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


def _routes_reading_no_key() -> list[tuple[str, str]]:
    """(method, path) for every route whose dependencies never look up a key."""
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

    return sorted(
        {
            (method, ctx.path)
            for ctx in iter_route_contexts(app.routes)
            if isinstance(ctx.route, APIRoute) and not reads_a_key(ctx.route.dependant)
            for method in ctx.route.methods
        }
    )


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
