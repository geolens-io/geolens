"""Pin SEC-S11: /search/datasets/ enforces its OWN per-route rate limit,
never the global one -- against an isolated app instance with both limits
set to known values.

fix(#1778 review round 5): e2e/sec-audit.spec.ts's S11 test spent four
rounds trying to prove this by bursting the live, shared dev stack --
impossible to pin reliably there, since the e2e suite cannot set
semantic_search_rate_limit or global_rate_limit and cannot isolate itself
from other concurrent traffic hitting the same stack. That test is now a
smoke check only (one request, either a 200 or a 429 naming a per-minute
limit -- both prove the route and its decorator are wired end to end). The
actual discriminating assertions -- exact threshold, and that a 429's body
names the per-route limit rather than the global one -- live here instead,
against the `client` fixture's dedicated test app and engine
(conftest.py), with slowapi's process-wide limiter enabled/reset/disabled
within the test per test_rate_limits.py's established pattern.

Also pins that @limiter.limit(_semantic_search_rate_limit) is still present
on search_datasets_endpoint at all (a "decorator present" structural check):
without it, a PR that accidentally removed the decorator would only be
caught if it also happened to break something else visibly.
"""

import time
import uuid

import pytest
from httpx import AsyncClient

from app.core.persistent_config import _sync_rate_limit_cache
from app.modules.catalog.search.router import search_datasets_endpoint
from app.platform.ratelimit import limiter

pytestmark = pytest.mark.anyio


def _set_cache_limit(key: str, value: int) -> None:
    """Inject a known limit into the sync cache so the slowapi callable picks it up."""
    _sync_rate_limit_cache[key] = (value, time.monotonic())


def _clear_cache_limit(key: str) -> None:
    _sync_rate_limit_cache.pop(key, None)


def _reset_limiter_storage() -> None:
    if hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"):
        limiter._storage.reset()


def test_semantic_search_rate_limit_decorator_present():
    """search_datasets_endpoint still carries its own per-route limiter.

    slowapi registers a callable limit_value (our _semantic_search_rate_limit)
    in Limiter._dynamic_route_limits, keyed by "<module>.<qualname>" (see
    extension.py's __limit_decorator). override_defaults defaults to True
    (slowapi's own default, and search/router.py does not override it), which
    EXCLUDES the global default_limits for this route entirely --
    extension.py's __evaluate_limits only adds default_limits back in when
    `combined_defaults = all(not limit.override_defaults for limit in
    route_limits)` is True, i.e. only when EVERY route limit opted out of
    override_defaults. That is why the global limiter cannot structurally
    answer a /search/datasets/ request: this route only ever evaluates its
    own dynamic limit.
    """
    key = f"{search_datasets_endpoint.__module__}.{search_datasets_endpoint.__name__}"
    dynamic_limits = limiter._dynamic_route_limits.get(key, [])
    assert dynamic_limits, (
        f"expected a dynamic rate limit registered for {key} -- "
        "@limiter.limit(_semantic_search_rate_limit) may have been removed "
        "from search_datasets_endpoint"
    )
    assert all(group.override_defaults for group in dynamic_limits), (
        "search_datasets_endpoint's rate limit must keep override_defaults=True "
        "(slowapi's default -- search/router.py passes no explicit value) so "
        "the global default_limits never apply alongside it. If this is ever "
        "changed deliberately, the 'never per 1 second' assertion in "
        "test_semantic_search_rate_limit_pins_per_route_not_global needs "
        "revisiting too."
    )


async def test_semantic_search_rate_limit_pins_per_route_not_global(
    client: AsyncClient,
):
    """A 429 from /search/datasets/ names the per-route per-minute limit,
    never the global per-second one, and firing lands exactly at the
    configured per-route threshold.

    Sets semantic_search_rate_limit=5 and global_rate_limit=1000 (so the
    global limiter, even if it somehow did apply, could never plausibly fire
    first within this test) via the sync cache the slowapi callables read
    directly, sends 6 unique-query requests, and asserts:
      - requests 1-5 succeed (200)
      - request 6 is rate-limited (429)
      - the 429 body's `detail` is exactly "5 per 1 minute" (slowapi's
        str(limits.RateLimitItem) format for a per-route Limit(5, MINUTE) --
        see api/main.py's _rate_limit_handler, which round-trips
        exc.detail unchanged into the ProblemDetail body)
      - detail never contains "per 1 second" (the global limiter's format
        for the same RateLimitItem stringification), confirming the global
        limiter did not answer
    """
    _set_cache_limit("semantic_search_rate_limit", 5)
    _set_cache_limit("global_rate_limit", 1000)
    limiter.enabled = True
    _reset_limiter_storage()

    try:
        statuses: list[int] = []
        rate_limited_bodies: list[dict] = []
        for _ in range(6):
            resp = await client.get(
                f"/search/datasets/?q=sec-s11-pin-{uuid.uuid4().hex}"
            )
            statuses.append(resp.status_code)
            if resp.status_code == 429:
                rate_limited_bodies.append(resp.json())

        assert statuses[:5] == [200] * 5, (
            f"expected the first 5 requests (at the configured limit) to succeed, "
            f"got statuses={statuses}"
        )
        assert statuses[5] == 429, (
            f"expected the 6th request (over the configured limit) to be "
            f"rate-limited, got statuses={statuses}"
        )

        assert rate_limited_bodies, "no 429 response body was captured"
        for body in rate_limited_bodies:
            detail = body.get("detail")
            assert detail == "5 per 1 minute", (
                f"expected the 429 body to name the per-route per-minute limit "
                f"exactly ('5 per 1 minute'), got {detail!r} -- a body reading "
                f"'... per 1 second' would mean the GLOBAL limiter answered "
                f"instead of the per-route one under test"
            )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _clear_cache_limit("global_rate_limit")
        _reset_limiter_storage()
