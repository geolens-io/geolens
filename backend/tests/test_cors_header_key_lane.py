"""Header-key CORS: a request that sends X-Api-Key is readable from any origin.

A script that sends a key in a header already holds it, so there is no ambient
credential for CORS to guard. The answer is ``Access-Control-Allow-Origin: *``
with no credentials flag, so a browser never pairs it with cookies, and the
middleware drops any cookie before the request is served. Bearer tokens,
cookies, embed tokens and query-string keys keep the old rule: no wildcard
outside ``CORS_ALLOWED_ORIGINS``.
"""

import uuid

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.api.middleware.cors import DynamicCORSMiddleware
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
