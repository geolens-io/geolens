"""The global rate limit is keyed on the handler, not on the URL (#1778).

slowapi's default is ``key_style="url"``: ``_check_request_limit`` sets
``_endpoint_key = request["path"]`` and ``__evaluate_limits`` then counts under
``(key_func(request), _endpoint_key)``. With ``key_func=get_remote_address``
that is (client IP, URL), so every distinct URL carried its own copy of the
admin-editable "Global Rate Limit (per second)". On a path-parameterised route
the caller picks the URL, so the caller picked how many budgets to have: one
per dataset id, one per z/x/y, one per record id. openapi.json lists 46
anonymous parameterised operations, and the expensive ones are among them
(``/datasets/{dataset_id}/export`` runs an ogr2ogr conversion,
``/collections/{dataset_id}/items`` returns up to 1000 features a page).

``key_style="endpoint"`` counts under (client IP, ``module.function``) instead.
The route table decides how many handlers exist, so the multiplier is fixed at
deploy time.

These tests read the property off the live app rather than off the constructor
argument: the argument is one line, and what it is worth is that two URLs
served by one handler draw on one bucket.
"""

import uuid

import pytest
from httpx import AsyncClient
from slowapi.wrappers import LimitGroup

from app.platform.ratelimit import limiter

# The signin-alias test below reuses the ArcGIS sign-in module's fixtures
# (allow_ssrf and its per-test portal host) rather than duplicating them.
pytest_plugins = ["tests.test_arcgis_signin"]

pytestmark = pytest.mark.anyio


def _one_per_minute():
    """A default-limit group of 1/minute, in slowapi's positional shape."""
    return [
        LimitGroup(
            "1/minute", limiter._key_func, None, False, None, None, None, 1, False
        )
    ]


def test_limiter_is_constructed_with_endpoint_key_style():
    """The unit half: without this the behavioural test below cannot pass."""
    assert limiter._key_style == "endpoint"


async def test_two_urls_on_one_handler_share_one_bucket(client: AsyncClient):
    """Three URLs, one handler, one 1/minute allowance between them.

    ``/collections/{dataset_id}/items`` is anonymous, carries a path parameter
    and has a trailing-slash alias registered against the same function, so it
    exercises both multipliers the old keying handed out for free: a fresh
    budget per dataset id, and a second one for the alias.

    The dataset ids are random and resolve to nothing. That is deliberate: the
    limit is evaluated in ``SlowAPIMiddleware`` before the handler runs, so a
    404 consumes the bucket exactly as a 200 does, and the test needs no
    fixture data to make its point.
    """
    original_enabled = limiter.enabled
    original_limits = limiter._default_limits
    try:
        limiter.enabled = True
        limiter._default_limits = _one_per_minute()
        limiter._storage.reset()

        first = await client.get(f"/collections/{uuid.uuid4()}/items")
        second = await client.get(f"/collections/{uuid.uuid4()}/items")
        alias = await client.get(f"/collections/{uuid.uuid4()}/items/")

        assert first.status_code != 429, (
            f"the first request must be inside the allowance; got {first.status_code}"
        )
        assert second.status_code == 429, (
            "a second dataset id is a second URL but the same handler, so it "
            "must draw on the allowance the first request spent. Keyed by URL "
            f"it gets a budget of its own; got {second.status_code}"
        )
        assert alias.status_code == 429, (
            "the trailing-slash alias is registered against the same function, "
            f"so it shares that one bucket too; got {alias.status_code}"
        )
    finally:
        limiter.enabled = original_enabled
        limiter._default_limits = original_limits
        limiter._storage.reset()


async def test_a_different_handler_keeps_its_own_bucket(client: AsyncClient):
    """The control: endpoint keying is not one global counter.

    Without this, a limiter that 429'd everything after one request would pass
    the test above.
    """
    original_enabled = limiter.enabled
    original_limits = limiter._default_limits
    try:
        limiter.enabled = True
        limiter._default_limits = _one_per_minute()
        limiter._storage.reset()

        spent = await client.get(f"/collections/{uuid.uuid4()}/items")
        exhausted = await client.get(f"/collections/{uuid.uuid4()}/items")
        other_handler = await client.get("/conformance")

        assert spent.status_code != 429
        assert exhausted.status_code == 429, "precondition: the bucket is spent"
        assert other_handler.status_code != 429, (
            "a different handler has a different key, so its own allowance is "
            f"untouched; got {other_handler.status_code}"
        )
    finally:
        limiter.enabled = original_enabled
        limiter._default_limits = original_limits
        limiter._storage.reset()


# ---------------------------------------------------------------------------
# The per-route limits the key style also governs
# ---------------------------------------------------------------------------
#
# A `@limiter.limit` decorator carries its own `key_func` but no `scope`, so
# `__evaluate_limits` falls back to `lim.scope or endpoint` and counts under
# (key_func(request), _endpoint_key). The key style therefore decides the
# SECOND half of every per-route limit too, not just the global default.
#
# `POST /services/arcgis/signin/` (#1758) is where that matters most on the
# current route table: it sends a password to a third party, so its comment
# enumerates five controls and control 2 is "three attempts per fifteen
# minutes". The route is dual-shape, so under URL keying the two spellings
# were two buckets and control 2 admitted six requests per worker to the
# database-backed control 4 behind it. Both key functions carry the user id
# and were never the leak.


async def test_the_arcgis_signin_aliases_share_one_bucket(
    client: AsyncClient, admin_auth_header: dict, allow_ssrf, monkeypatch
):
    """Control 2 of #1758 admits three requests per worker, not six.

    The database-backed budget (control 4) and the per-portal limit are raised
    out of the way so the only thing that can refuse is the per-user slowapi
    limit whose scope this change moves.
    """
    from app.modules.catalog.sources import router as sources_router, signin_guard

    from tests.test_arcgis_signin import (
        _Exchange,
        _body,
        _info_payload,
        _install,
        _json_response,
        _token_payload,
    )

    monkeypatch.setattr(signin_guard, "_ARCGIS_SIGNIN_ATTEMPT_LIMIT", 100)
    monkeypatch.setattr(sources_router, "_ARCGIS_SIGNIN_PORTAL_LIMIT", "100/15minutes")
    exchange = _Exchange(
        {
            "info": _json_response(_info_payload()),
            "generateToken": _json_response(_token_payload()),
        }
    )

    original_enabled = limiter.enabled
    try:
        limiter.enabled = True
        limiter._storage.reset()
        with _install(exchange):
            statuses = [
                (
                    await client.post(path, json=_body(), headers=admin_auth_header)
                ).status_code
                for path in (
                    "/services/arcgis/signin/",
                    "/services/arcgis/signin",
                    "/services/arcgis/signin/",
                    "/services/arcgis/signin",
                    "/services/arcgis/signin/",
                    "/services/arcgis/signin",
                )
            ]
    finally:
        limiter.enabled = original_enabled
        limiter._storage.reset()

    assert statuses == [200, 200, 200, 429, 429, 429], (
        "alternating the two spellings of one handler must not buy a second "
        f"three-attempt budget; got {statuses}"
    )
    assert len(exchange.posts) == 3, (
        "and the refused half must never reach the portal; "
        f"{len(exchange.posts)} sign-in POSTs went out"
    )
