"""Scope gates match the full route template, including routes from nested routers.

A router included into another router keeps only its own path on
``scope["route"]``. The scope gates compare (method, template) pairs against
full templates, so they must read the template FastAPI records on the matched
route context instead.
"""

import uuid

import pytest
from fastapi import APIRouter, FastAPI, Request
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from httpx import AsyncClient

from app.modules.auth import dependencies
from app.modules.auth.dependencies import _route_template
from tests import test_api_key_scope_875 as _scope_tests

_remove_keys_minted_by_the_test = _scope_tests._remove_keys_minted_by_the_test


def test_fastapi_records_the_full_template_on_the_route_context():
    """Pins the private scope key the gate reads, so an upgrade that drops it fails here."""
    inner = APIRouter()

    @inner.get("/{item_id}/leaf/")
    async def leaf(request: Request) -> dict:
        context = request.scope["fastapi"]["effective_route_context"]
        return {
            "local": request.scope["route"].path,
            "context": context.path,
            "template": _route_template(request),
        }

    outer = APIRouter(prefix="/outer")
    outer.include_router(inner)
    app = FastAPI()
    app.include_router(outer)

    resp = TestClient(app).get("/outer/abc/leaf/")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "local": "/{item_id}/leaf/",
        "context": "/outer/{item_id}/leaf/",
        "template": "/outer/{item_id}/leaf/",
    }


def test_the_app_still_has_nested_routes():
    """Otherwise the live tests below would prove nothing."""
    from app.api.main import app

    nested = {
        ctx.path
        for ctx in iter_route_contexts(app.routes)
        if isinstance(ctx.route, APIRoute) and ctx.route.path != ctx.path
    }
    assert "/maps/{map_id}/share/" in nested
    assert "/maps/{map_id}/style.json" in nested


@pytest.mark.anyio
async def test_an_exemption_naming_a_nested_route_lets_a_read_only_key_through(
    client: AsyncClient, admin_auth_header, monkeypatch
):
    raw_key = (await _scope_tests._mint(client, admin_auth_header, scope="read_only"))[
        "key"
    ]
    url = f"/maps/{uuid.uuid4()}/share/"

    refused = await client.post(url, headers={"X-Api-Key": raw_key})
    assert refused.status_code == 403, refused.text

    monkeypatch.setattr(
        dependencies,
        "_READ_ONLY_KEY_EXEMPT_ROUTES",
        dependencies._READ_ONLY_KEY_EXEMPT_ROUTES | {("POST", "/maps/{map_id}/share/")},
    )
    allowed = await client.post(url, headers={"X-Api-Key": raw_key})
    assert allowed.status_code == 404, allowed.text


@pytest.mark.anyio
async def test_a_writing_get_on_a_nested_route_is_refused_to_a_read_only_key(
    client: AsyncClient, admin_auth_header, monkeypatch
):
    """The writing-GET table is a denylist, so a short template would fail open."""
    raw_key = (await _scope_tests._mint(client, admin_auth_header, scope="read_only"))[
        "key"
    ]
    monkeypatch.setattr(
        dependencies,
        "_READ_ONLY_KEY_WRITING_GET_ROUTES",
        {
            **dependencies._READ_ONLY_KEY_WRITING_GET_ROUTES,
            "/maps/{map_id}/style.json": "refresh",
        },
    )
    url = f"/maps/{uuid.uuid4()}/style.json"

    resp = await client.get(
        url, params={"refresh": "true"}, headers={"X-Api-Key": raw_key}
    )
    assert resp.status_code == 403, resp.text
    read = await client.get(url, headers={"X-Api-Key": raw_key})
    assert read.status_code == 404, read.text
