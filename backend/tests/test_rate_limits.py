"""Tests for SEC-S10 and SEC-S11 per-route rate limiting.

Phase 1062 Plan 02: per-route @limiter.limit decorators on:
  - /search/datasets/   (SEC-S11, caps OpenAI embedding cost-DoS)
  - /search/facets/     (SEC-S11, one bucket shared with /search/datasets/)
  - /datasets/{id}/related/  (SEC-S11, same embedding cost surface)
  - /settings/basemaps/      (SEC-S10, caps commercial-tier basemap key replay)

The conftest.py `client` fixture globally disables the limiter
(``limiter.enabled = False``) to keep all other tests fast. Rate-limit
tests MUST re-enable the limiter within the test, reset its storage
afterwards, and then disable it again to avoid leaking state.

Per-test pattern:
    1. Set the rate-limit counter directly in _sync_rate_limit_cache
       (monkeypatching the low-level sync cache is cleaner than patching
       the PersistentConfig — it does not require an async DB round-trip).
    2. Enable the limiter.
    3. Fire N+1 requests; the last N-threshold should be 429.
    4. Re-disable the limiter and reset storage.
"""

import uuid

import fakeredis
import pytest
from httpx import AsyncClient

from app.core.config import settings
from app.core.db.tenant_session import current_tenant_var
from app.core.persistent_config import (
    _sync_rate_limit_cache,
    get_cached_semantic_search_rate_limit,
    get_cached_basemap_proxy_rate_limit,
)
from app.modules.catalog.search import service_semantic
from app.platform import ratelimit_claims
from app.platform.ratelimit import limiter

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Task 1: Default value tests (no HTTP required)
# ---------------------------------------------------------------------------


def test_default_semantic_search_limit_is_30():
    """get_cached_semantic_search_rate_limit() returns 30 when cache is empty.

    Clears the cache entry before calling to avoid interference from other
    tests that may have set a low monkeypatched value.
    """
    _sync_rate_limit_cache.pop("semantic_search_rate_limit", None)
    assert get_cached_semantic_search_rate_limit() == 30


def test_default_basemap_proxy_limit_is_120():
    """get_cached_basemap_proxy_rate_limit() returns 120 when cache is empty."""
    _sync_rate_limit_cache.pop("basemap_proxy_rate_limit", None)
    assert get_cached_basemap_proxy_rate_limit() == 120


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_cache_limit(key: str, value: int) -> None:
    """Inject a low limit into the sync cache so the slowapi callable picks it up."""
    import time

    _sync_rate_limit_cache[key] = (value, time.monotonic())


def _clear_cache_limit(key: str) -> None:
    _sync_rate_limit_cache.pop(key, None)


def _worker_claim_store(
    server: fakeredis.FakeServer,
) -> ratelimit_claims.SharedClaimStore:
    """One worker's view of a shared store: its own client, the same server."""
    return ratelimit_claims.SharedClaimStore(
        fakeredis.FakeStrictRedis(server=server, decode_responses=True)
    )


@pytest.fixture(params=["process_local", "shared_store"])
def claim_backend(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Run a #1903 counting test against both claim backends.

    fix(#2018): the shared arm runs on fakeredis rather than a live Valkey.
    What the port has to preserve is the counting invariant, and that is
    decided by SET NX EX and GETDEL semantics, which fakeredis implements.
    """
    store = (
        _worker_claim_store(fakeredis.FakeServer())
        if request.param == "shared_store"
        else None
    )
    monkeypatch.setattr(ratelimit_claims, "_store", store)
    monkeypatch.setattr(ratelimit_claims, "_store_resolved", True)
    return request.param


def _reset_limiter_storage() -> None:
    """Reset slowapi in-memory storage to clear counters from prior test runs.

    limiter._storage.reset() is a synchronous call on MemoryStorage.
    """
    if hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"):
        limiter._storage.reset()


# ---------------------------------------------------------------------------
# Task 2: /search/datasets/ and /search/facets/ rate limiting (SEC-S11)
# ---------------------------------------------------------------------------


async def test_semantic_search_rate_limit_returns_429(client: AsyncClient):
    """GET /search/datasets/?q=<unique-N> returns 429 after threshold is exceeded.

    Uses a monkeypatched low limit (5/min) to keep the test fast.
    Sends 7 unique queries; at least 2 must be 429.

    Note: slowapi storage is process-wide. We re-enable/reset/disable the
    limiter within this test to avoid contaminating other tests.
    """
    _set_cache_limit("semantic_search_rate_limit", 5)
    limiter.enabled = True
    _reset_limiter_storage()

    try:
        statuses = []
        for i in range(7):
            resp = await client.get(
                f"/search/datasets/?q=sec-ratelimit-test-unique-{uuid.uuid4().hex}"
            )
            statuses.append(resp.status_code)

        rate_limited = [s for s in statuses if s == 429]
        assert len(rate_limited) >= 2, (
            f"Expected >= 2 rate-limited responses with threshold=5/7 requests, "
            f"got {len(rate_limited)}. Statuses: {statuses}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()


async def test_search_facets_rate_limited(client: AsyncClient):
    """GET /search/facets/?q=<unique-N> returns 429 after threshold is exceeded.

    fix(#1855): facets embed the query to count over the same candidate set as
    /search/datasets/, so an unlimited /search/facets/ would be a way around
    the SEC-S11 embedding-cost cap. The endpoint carries the same limit.
    """
    _set_cache_limit("semantic_search_rate_limit", 5)
    limiter.enabled = True
    _reset_limiter_storage()

    try:
        statuses = []
        for i in range(7):
            resp = await client.get(
                f"/search/facets/?q=sec-facets-ratelimit-{uuid.uuid4().hex}"
            )
            statuses.append(resp.status_code)

        rate_limited = [s for s in statuses if s == 429]
        assert len(rate_limited) >= 2, (
            f"Expected >= 2 rate-limited responses with threshold=5/7 requests, "
            f"got {len(rate_limited)}. Statuses: {statuses}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()


@pytest.mark.parametrize("first", ["/search/datasets/", "/search/facets/"])
async def test_search_datasets_and_facets_share_one_bucket(
    client: AsyncClient, first: str
):
    """Alternating the two search routes cannot embed twice the advertised cap.

    fix(#1855): both routes embed a novel ``q``, and slowapi scopes a plain
    ``@limiter.limit`` to the handler, so two buckets let a caller alternate
    them for 2x the limit. With one shared bucket the (limit + 1)th call is a
    429 whichever route it lands on, and the same 429 starting from either.
    """
    routes = ["/search/datasets/", "/search/facets/"]
    if first != routes[0]:
        routes.reverse()
    _set_cache_limit("semantic_search_rate_limit", 5)
    limiter.enabled = True
    _reset_limiter_storage()

    try:
        statuses = []
        for i in range(6):
            resp = await client.get(
                f"{routes[i % 2]}?q=sec-shared-bucket-{uuid.uuid4().hex}"
            )
            statuses.append(resp.status_code)
        assert statuses == [200] * 5 + [429], (
            f"one shared 5/min bucket must 429 the sixth call across both routes "
            f"(starting from {first}); got {statuses}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()


@pytest.mark.parametrize("first_route", ["/search/datasets/", "/search/facets/"])
async def test_paired_query_claims_the_bucket_once_whichever_route_is_first(
    client: AsyncClient, first_route: str, claim_backend: str
):
    """fix(#1903): the SPA's unordered paired request spends one token, not two.

    The SPA fires /search/datasets/ and /search/facets/ together on every
    query change with neither awaiting the other, so which one reaches its
    rate-limit gate first is a race -- proven here by running the pair in
    BOTH orders for the same ``q`` against a 1-token bucket: the second call,
    whichever route it lands on, must be exempt. A facets call for a
    genuinely novel query still spends the (already-empty) bucket, so the
    shared-bucket cap is not weakened for a facets-only caller.
    """
    routes = ["/search/datasets/", "/search/facets/"]
    if first_route != routes[0]:
        routes.reverse()
    second_route = routes[1]
    q = f"sec-1903-{uuid.uuid4().hex}"
    _set_cache_limit("semantic_search_rate_limit", 1)
    limiter.enabled = True
    _reset_limiter_storage()
    service_semantic._query_claims_clear()

    try:
        first = await client.get(f"{first_route}?q={q}")
        assert first.status_code == 200, (
            f"expected the first call ({first_route}) to spend the bucket, "
            f"got {first.status_code}"
        )

        second = await client.get(f"{second_route}?q={q}")
        assert second.status_code == 200, (
            f"the paired call ({second_route}) for the same query should be "
            f"exempt from the spent bucket, got {second.status_code}"
        )

        novel_q = f"sec-1903-novel-{uuid.uuid4().hex}"
        third = await client.get(f"/search/facets/?q={novel_q}")
        assert third.status_code == 429, (
            "a facets call for an uncached query must still hit the spent "
            f"bucket, got {third.status_code}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()
        service_semantic._query_claims_clear()


async def test_same_route_repeat_does_not_ride_a_cross_route_claim(
    client: AsyncClient, claim_backend: str
):
    """fix(#1903): a same-route burst still pays per request.

    A claim is a single-use, cross-route consume, not a standing amnesty for
    the whole coordination window: a concurrent burst against ONE route for
    the same query would otherwise ride free after the first call, even
    though none of those requests can have a cache hit yet (the first
    embed hasn't landed), so each would still bill the provider. Proven
    with a 2-token bucket: two /search/facets/ calls for the SAME query
    spend both tokens; a third is a 429, not a third exemption.
    """
    q = f"sec-1903-burst-{uuid.uuid4().hex}"
    _set_cache_limit("semantic_search_rate_limit", 2)
    limiter.enabled = True
    _reset_limiter_storage()
    service_semantic._query_claims_clear()

    try:
        first = await client.get(f"/search/facets/?q={q}")
        assert first.status_code == 200, (
            f"expected the first call to spend a token, got {first.status_code}"
        )

        second = await client.get(f"/search/facets/?q={q}")
        assert second.status_code == 200, (
            "a second same-route call is not the cross-route pair and must "
            f"spend its own token, got {second.status_code}"
        )

        third = await client.get(f"/search/facets/?q={q}")
        assert third.status_code == 429, (
            "a third same-route call for the same query must hit the "
            f"now-spent bucket, got {third.status_code}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()
        service_semantic._query_claims_clear()


async def test_rejected_request_does_not_seed_a_claim(
    client: AsyncClient, claim_backend: str
):
    """fix(#1903): a 429'd request must not create an exemption.

    exempt_when runs before the limiter's own admit/reject check, so it
    fires for a request that gets rejected too. Exhaust the bucket on an
    unrelated query, then send a NEW query to /search/datasets/ while the
    bucket is spent (rejected). A /search/facets/ call for that SAME new
    query must also be rejected -- nothing was admitted to claim it.
    """
    q = f"sec-1903-rejected-{uuid.uuid4().hex}"
    _set_cache_limit("semantic_search_rate_limit", 1)
    limiter.enabled = True
    _reset_limiter_storage()
    service_semantic._query_claims_clear()

    try:
        spend = await client.get(
            f"/search/datasets/?q=sec-1903-spend-{uuid.uuid4().hex}"
        )
        assert spend.status_code == 200, (
            f"expected the spend call to succeed, got {spend.status_code}"
        )

        rejected = await client.get(f"/search/datasets/?q={q}")
        assert rejected.status_code == 429, (
            f"expected the bucket to already be spent, got {rejected.status_code}"
        )

        second = await client.get(f"/search/facets/?q={q}")
        assert second.status_code == 429, (
            "a facets call following a REJECTED datasets call for the same "
            f"query must not be exempt, got {second.status_code}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()
        service_semantic._query_claims_clear()


async def test_claim_is_scoped_to_the_requesting_client(
    client: AsyncClient, claim_backend: str
):
    """fix(#1903): a claim is scoped to the client that made it.

    The SEC-S11 bucket is per-IP, so two different clients requesting the
    same query must not be able to consume each other's claim: client B's
    own bucket has full capacity regardless of what client A just did.
    Proven by having client A admit a query, then client B request the
    SAME query -- B must spend its OWN token (not ride A's claim), so a
    second B call for a different query must then find B's bucket spent.
    """
    from httpx import ASGITransport, AsyncClient as _AsyncClient

    from app.api.main import app

    q = f"sec-1903-crossclient-{uuid.uuid4().hex}"
    _set_cache_limit("semantic_search_rate_limit", 1)
    limiter.enabled = True
    _reset_limiter_storage()
    service_semantic._query_claims_clear()

    other_transport = ASGITransport(app=app, client=("10.0.0.9", 12345))
    try:
        async with _AsyncClient(
            transport=other_transport, base_url="http://test"
        ) as other_client:
            first = await client.get(f"/search/datasets/?q={q}")
            assert first.status_code == 200, (
                f"expected client A's call to spend A's bucket, got {first.status_code}"
            )

            second = await other_client.get(f"/search/facets/?q={q}")
            assert second.status_code == 200, (
                "client B has its own untouched bucket for the same query, "
                f"got {second.status_code}"
            )

            third = await other_client.get(
                f"/search/facets/?q=sec-1903-crossclient-novel-{uuid.uuid4().hex}"
            )
            assert third.status_code == 429, (
                "client B's own token must have been spent by its first "
                f"call, not exempted via client A's claim, got {third.status_code}"
            )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()
        service_semantic._query_claims_clear()


async def test_claim_functions_degrade_without_crashing_when_tenant_unscoped(
    monkeypatch: pytest.MonkeyPatch, claim_backend: str
):
    """fix(#1903): an unscoped multi-tenant request must not 500.

    ``tenant_cache_key()`` raises when multi-tenant mode has no verified
    tenant context (a trusted unscoped host). ``exempt_when`` runs
    synchronously inside slowapi's rate-limit check, so an uncaught
    exception there would turn every search request with ``q`` into a 500
    on such a host. The claim functions check availability first instead.
    """
    monkeypatch.setattr(settings, "geolens_tenancy_mode", "multi_tenant")
    token = current_tenant_var.set(None)
    try:
        assert (
            service_semantic.consume_paired_query_claim(
                "203.0.113.5", "unscoped query", "datasets"
            )
            is False
        )
        # Must not raise.
        service_semantic.record_paired_query_claim(
            "203.0.113.5", "unscoped query", "datasets"
        )
        assert (
            service_semantic.consume_paired_query_claim(
                "203.0.113.5", "unscoped query", "facets"
            )
            is False
        ), "no claim should have been recorded without a tenant context"
    finally:
        current_tenant_var.reset(token)
        service_semantic._query_claims_clear()


async def test_four_request_chain_for_one_query_spends_exactly_two_tokens(
    client: AsyncClient, claim_backend: str
):
    """fix(#1903): datasets, facets, datasets, facets for one q spends
    exactly two tokens -- an exempted request never records a claim, so it
    cannot seed the next exemption.

    With a 2-token bucket, all four calls in the chain must succeed (two
    charged, two exempt); a fifth call for the same query must then hit
    the exhausted bucket.
    """
    q = f"sec-1903-chain-{uuid.uuid4().hex}"
    _set_cache_limit("semantic_search_rate_limit", 2)
    limiter.enabled = True
    _reset_limiter_storage()
    service_semantic._query_claims_clear()

    try:
        statuses = []
        for route in (
            "/search/datasets/",
            "/search/facets/",
            "/search/datasets/",
            "/search/facets/",
        ):
            resp = await client.get(f"{route}?q={q}")
            statuses.append(resp.status_code)
        assert statuses == [200, 200, 200, 200], (
            f"expected the full chain to succeed on a 2-token bucket, got {statuses}"
        )

        fifth = await client.get(f"/search/datasets/?q={q}")
        assert fifth.status_code == 429, (
            f"the chain must have spent exactly two tokens, got {fifth.status_code}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()
        service_semantic._query_claims_clear()


async def test_a_pair_split_across_two_workers_still_spends_one_token(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """fix(#2018): the exemption survives the pair landing on two workers.

    A second uvicorn process cannot be built in-process, so the boundary is
    modelled the way the code meets it: the sibling has its own client on the
    same store and an EMPTY process-local registry. Clearing that registry is
    also the counterfactual -- before #2018 the claim lived nowhere else, so
    the facets call below was a 429 against the spent bucket.
    """
    server = fakeredis.FakeServer()
    q = f"sec-2018-split-{uuid.uuid4().hex}"
    _set_cache_limit("semantic_search_rate_limit", 1)
    limiter.enabled = True
    _reset_limiter_storage()
    service_semantic._query_claims_clear()
    monkeypatch.setattr(ratelimit_claims, "_store_resolved", True)
    monkeypatch.setattr(ratelimit_claims, "_store", _worker_claim_store(server))

    try:
        first = await client.get(f"/search/datasets/?q={q}")
        assert first.status_code == 200, (
            f"expected worker A's call to spend the shared bucket, "
            f"got {first.status_code}"
        )

        monkeypatch.setattr(ratelimit_claims, "_store", _worker_claim_store(server))
        service_semantic._query_claims_clear()

        second = await client.get(f"/search/facets/?q={q}")
        assert second.status_code == 200, (
            "worker B holds no local claim and must redeem worker A's from the "
            f"shared store, got {second.status_code}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()
        service_semantic._query_claims_clear()


async def test_a_claim_store_outage_falls_back_to_the_process_local_registry(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
):
    """fix(#2018): a store that answers nothing must not answer "exempt".

    Both halves of one pair run against a store whose every call raises. The
    pair still coordinates, because the local registry is still there; a
    request for a novel query still pays, because the fallback is the
    pre-#2018 behaviour and not a blanket exemption. The store's cooldown is
    the claim's own lifetime, which is what keeps a recovering store from
    shadowing a claim the local registry holds and it cannot see.
    """

    class _DeadClient:
        def set(self, *_args, **_kwargs):
            raise ConnectionError("claim store unreachable")

        def getdel(self, *_args, **_kwargs):
            raise ConnectionError("claim store unreachable")

    q = f"sec-2018-outage-{uuid.uuid4().hex}"
    _set_cache_limit("semantic_search_rate_limit", 1)
    limiter.enabled = True
    _reset_limiter_storage()
    service_semantic._query_claims_clear()
    monkeypatch.setattr(ratelimit_claims, "_store_resolved", True)
    monkeypatch.setattr(
        ratelimit_claims, "_store", ratelimit_claims.SharedClaimStore(_DeadClient())
    )

    try:
        first = await client.get(f"/search/datasets/?q={q}")
        assert first.status_code == 200, first.status_code

        second = await client.get(f"/search/facets/?q={q}")
        assert second.status_code == 200, (
            "the local registry still coordinates the pair when the store is "
            f"unreachable, got {second.status_code}"
        )

        novel = await client.get(f"/search/facets/?q=sec-2018-novel-{uuid.uuid4().hex}")
        assert novel.status_code == 429, (
            "an unreachable store must not exempt an unclaimed query, "
            f"got {novel.status_code}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()
        service_semantic._query_claims_clear()


# ---------------------------------------------------------------------------
# Task 3: /datasets/{id}/related/ rate limiting (SEC-S11)
# ---------------------------------------------------------------------------


async def test_related_datasets_rate_limit_returns_429(client: AsyncClient):
    """GET /datasets/{id}/related/ returns 429 after threshold is exceeded.

    Uses a random UUID for the dataset ID — the rate limiter fires before the
    handler body reads from the DB, so a 404 from an unknown dataset ID means
    the limiter did not fire (count < threshold). Once the limiter fires, the
    response is 429 regardless of whether the dataset exists.
    """
    _set_cache_limit("semantic_search_rate_limit", 5)
    limiter.enabled = True
    _reset_limiter_storage()

    dataset_id = uuid.uuid4()
    try:
        statuses = []
        for _ in range(7):
            resp = await client.get(f"/datasets/{dataset_id}/related/")
            statuses.append(resp.status_code)

        rate_limited = [s for s in statuses if s == 429]
        assert len(rate_limited) >= 2, (
            f"Expected >= 2 rate-limited responses with threshold=5/7 requests, "
            f"got {len(rate_limited)}. Statuses: {statuses}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("semantic_search_rate_limit")
        _reset_limiter_storage()


# ---------------------------------------------------------------------------
# Task 4: /settings/basemaps/ rate limiting (SEC-S10)
# ---------------------------------------------------------------------------


async def test_basemap_proxy_rate_limit_returns_429(client: AsyncClient):
    """GET /settings/basemaps/ returns 429 after threshold is exceeded.

    /settings/basemaps/ is unauthenticated by design (frontend SPA boot path).
    The rate limiter fires before the handler reads from DB, so an empty basemap
    list (in test environment) still triggers 429 once threshold is exceeded.

    Sends 10 requests with threshold=5; at least 5 must be 429.
    """
    _set_cache_limit("basemap_proxy_rate_limit", 5)
    limiter.enabled = True
    _reset_limiter_storage()

    try:
        statuses = []
        for _ in range(10):
            resp = await client.get("/settings/basemaps/")
            statuses.append(resp.status_code)

        rate_limited = [s for s in statuses if s == 429]
        assert len(rate_limited) >= 5, (
            f"Expected >= 5 rate-limited responses with threshold=5/10 requests, "
            f"got {len(rate_limited)}. Statuses: {statuses}"
        )
    finally:
        limiter.enabled = False
        _clear_cache_limit("basemap_proxy_rate_limit")
        _reset_limiter_storage()
