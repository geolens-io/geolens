"""fix(#1531): a domain-locked embed token must deliver scoped layers to a browser embed.

Domain locking is enforced in two layers. The ``/m/{token}`` embed shell is
served with ``frame-ancestors 'self' <allowed_origins>``
(``build_embed_frame_ancestors``) — a browser-enforced control keyed on the
PARENT page's actual origin. The API-layer allowlist below it accepted only
``<allowed_origins>``, with no ``'self'`` equivalent.

Measured against the dev stack (Chrome, via the ``/m/`` shell): an API
subresource request issued from inside the embed iframe carries **no Origin
header at all** (it is same-origin to the shell) and a ``Referer`` of the
shell's own URL. The embedder's origin is not on the request; it is visible
only on the navigation that loads the iframe, which is exactly where
``frame-ancestors`` enforces it. So every scoped-layer request resolved to the
GeoLens app's own origin, matched nothing in ``allowed_origins`` (which holds
the CUSTOMER's domain), and was denied — the feature was broken closed.

Two independent readers gate on ``allowed_origins``:
``resolve_embed_scope_for_map`` (shared-map metadata → which layers exist) and
``validate_embed_token_access`` (tiles / bounded GeoJSON → whether they can be
drawn). Every case below is asserted against BOTH; a fix that lands on one path
and leaves the sibling on the old rules is the failure mode these tests exist
to catch.

The vacuity guard is ``TestForeignOriginStillDenied``: it must FAIL in the
opposite direction from the iframe tests. If the self-origin rule were written
so that the request itself supplies "self", the iframe tests would pass and so
would the foreign-origin ones, which would mean nothing was checked at all.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.embed_tokens import service as embed_service

APP_ORIGIN = "https://maps.geolens.example"
CUSTOMER_ORIGIN = "https://customer.example.com"
FOREIGN_ORIGIN = "https://evil.example.net"

MAP_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
DATASET_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
RAW_TOKEN = "et_domain_locked_probe"

# What Chrome actually sent on the shared-map request from inside the shell:
# no Origin, Referer = the shell's own URL. Captured from the dev stack.
SHELL_REFERER = f"{APP_ORIGIN}/m/share-token?et={RAW_TOKEN}"


def _make_request(
    *,
    origin: str | None = None,
    referer: str | None = None,
    client_host: str | None = "10.1.2.3",
    tenant_public_origin: str | None = None,
) -> MagicMock:
    headers: dict[str, str] = {}
    if origin is not None:
        headers["origin"] = origin
    if referer is not None:
        headers["referer"] = referer
    request = MagicMock()
    request.headers = headers
    request.client = (
        SimpleNamespace(host=client_host) if client_host is not None else None
    )
    request.state = SimpleNamespace(tenant_public_origin=tenant_public_origin)
    return request


def _token_row(allowed_origins: list[str] | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        map_id=MAP_ID,
        allowed_origins=allowed_origins,
        scoped_dataset_ids=[str(DATASET_ID)],
        tenant_id=None,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    )


@pytest.fixture(autouse=True)
def _self_origin_is_configured(monkeypatch):
    """Our own public origin comes from configuration, never from the request."""

    async def _fake_get_public_app_url(db, **kwargs):
        assert kwargs.get("request") is None, (
            "fix(#1531): _resolve_self_origins must NOT forward the request to "
            "get_public_app_url. Its unconfigured fallback derives an origin "
            "from the caller's own Origin/Referer, which would make EVERY "
            "origin 'self' and the allowlist vacuous."
        )
        return APP_ORIGIN

    monkeypatch.setattr(
        embed_service, "get_public_app_url", _fake_get_public_app_url, raising=True
    )


# --------------------------------------------------------------------------
# Reader 1: resolve_embed_scope_for_map (shared-map metadata)
# --------------------------------------------------------------------------


def _db_returning(token) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=token)
    db.execute = AsyncMock(return_value=result)
    return db


async def _scope(request, allowed_origins: list[str] | None) -> set[uuid.UUID]:
    return await embed_service.resolve_embed_scope_for_map(
        _db_returning(_token_row(allowed_origins)), RAW_TOKEN, MAP_ID, request
    )


# --------------------------------------------------------------------------
# Reader 2: validate_embed_token_access (tiles / bounded GeoJSON)
# --------------------------------------------------------------------------


async def _validate(request, allowed_origins: list[str] | None, monkeypatch) -> bool:
    """Drive validate_embed_token_access through its cache-hit path."""
    cache = AsyncMock()
    cache.get = AsyncMock(
        return_value={
            "is_valid": True,
            "scoped_dataset_ids": [str(DATASET_ID)],
            "allowed_origins": allowed_origins,
            "map_id": str(MAP_ID),
            "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            "tenant_id": None,
        }
    )
    cache.set = AsyncMock()
    cache.delete = AsyncMock()
    monkeypatch.setattr(embed_service, "get_cache", lambda: cache)
    monkeypatch.setattr(
        embed_service, "map_contains_dataset", AsyncMock(return_value=True)
    )
    return await embed_service.validate_embed_token_access(
        RAW_TOKEN, DATASET_ID, AsyncMock(), request
    )


async def _validate_cache_miss(
    request, allowed_origins: list[str] | None, monkeypatch
) -> bool:
    """Drive the same function through its DB path — the one production hits first."""
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.delete = AsyncMock()
    monkeypatch.setattr(embed_service, "get_cache", lambda: cache)
    monkeypatch.setattr(
        embed_service, "map_contains_dataset", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        embed_service, "_bump_embed_token_usage_detached", AsyncMock(return_value=None)
    )
    return await embed_service.validate_embed_token_access(
        RAW_TOKEN, DATASET_ID, _db_returning(_token_row(allowed_origins)), request
    )


class TestIframeEmbedIsDelivered:
    """The bug: a browser embed carries OUR origin, so the lock denied everything."""

    @pytest.mark.anyio
    async def test_scope_resolution_accepts_the_shell_referer(self):
        request = _make_request(referer=SHELL_REFERER)
        assert await _scope(request, [CUSTOMER_ORIGIN]) == {DATASET_ID}

    @pytest.mark.anyio
    async def test_tile_access_accepts_the_shell_referer(self, monkeypatch):
        request = _make_request(referer=SHELL_REFERER)
        assert await _validate(request, [CUSTOMER_ORIGIN], monkeypatch) is True

    @pytest.mark.anyio
    async def test_tile_access_accepts_the_shell_referer_on_the_db_path(
        self, monkeypatch
    ):
        request = _make_request(referer=SHELL_REFERER)
        assert (
            await _validate_cache_miss(request, [CUSTOMER_ORIGIN], monkeypatch) is True
        )

    @pytest.mark.anyio
    async def test_scope_resolution_accepts_an_explicit_self_origin_header(self):
        """A split app/API deployment makes the same call cross-origin, so the
        browser DOES send Origin — still our own origin, not the embedder's."""
        request = _make_request(origin=APP_ORIGIN)
        assert await _scope(request, [CUSTOMER_ORIGIN]) == {DATASET_ID}

    @pytest.mark.anyio
    async def test_tile_access_accepts_an_explicit_self_origin_header(
        self, monkeypatch
    ):
        request = _make_request(origin=APP_ORIGIN)
        assert await _validate(request, [CUSTOMER_ORIGIN], monkeypatch) is True


class TestDirectApiPathStillWorks:
    """The path the check was always correct for: the customer's own JavaScript
    calls the API directly, so the browser sends the customer's real origin."""

    @pytest.mark.anyio
    async def test_scope_resolution_accepts_the_allowlisted_origin(self):
        request = _make_request(origin=CUSTOMER_ORIGIN)
        assert await _scope(request, [CUSTOMER_ORIGIN]) == {DATASET_ID}

    @pytest.mark.anyio
    async def test_tile_access_accepts_the_allowlisted_origin(self, monkeypatch):
        request = _make_request(origin=CUSTOMER_ORIGIN)
        assert await _validate(request, [CUSTOMER_ORIGIN], monkeypatch) is True


class TestForeignOriginStillDenied:
    """Vacuity guard. These must stay red in the opposite direction from
    TestIframeEmbedIsDelivered: if accepting "self" ever resolves "self" from
    something the caller sends, every one of these flips to a pass and the
    domain lock means nothing."""

    @pytest.mark.anyio
    async def test_scope_resolution_denies_a_foreign_origin(self):
        request = _make_request(origin=FOREIGN_ORIGIN)
        assert await _scope(request, [CUSTOMER_ORIGIN]) == set()

    @pytest.mark.anyio
    async def test_tile_access_denies_a_foreign_origin(self, monkeypatch):
        request = _make_request(origin=FOREIGN_ORIGIN)
        assert await _validate(request, [CUSTOMER_ORIGIN], monkeypatch) is False

    @pytest.mark.anyio
    async def test_scope_resolution_denies_a_foreign_referer(self):
        request = _make_request(referer=f"{FOREIGN_ORIGIN}/attack.html")
        assert await _scope(request, [CUSTOMER_ORIGIN]) == set()

    @pytest.mark.anyio
    async def test_tile_access_denies_a_foreign_referer(self, monkeypatch):
        request = _make_request(referer=f"{FOREIGN_ORIGIN}/attack.html")
        assert await _validate(request, [CUSTOMER_ORIGIN], monkeypatch) is False

    @pytest.mark.anyio
    async def test_scope_resolution_denies_a_headerless_request(self):
        assert await _scope(_make_request(), [CUSTOMER_ORIGIN]) == set()

    @pytest.mark.anyio
    async def test_tile_access_denies_a_headerless_request(self, monkeypatch):
        assert await _validate(_make_request(), [CUSTOMER_ORIGIN], monkeypatch) is False

    @pytest.mark.anyio
    async def test_scope_resolution_denies_when_there_is_no_request(self):
        db = _db_returning(_token_row([CUSTOMER_ORIGIN]))
        scope = await embed_service.resolve_embed_scope_for_map(
            db, RAW_TOKEN, MAP_ID, None
        )
        assert scope == set()

    @pytest.mark.anyio
    async def test_tile_access_denies_when_there_is_no_request(self, monkeypatch):
        assert await _validate(None, [CUSTOMER_ORIGIN], monkeypatch) is False


class TestLocalhostBypassPreserved:
    """Phase 268 H-31 is untouched: the localhost-Origin dev bypass still
    requires the actual TCP peer to be loopback."""

    @pytest.mark.anyio
    async def test_forged_localhost_origin_from_a_remote_peer_is_denied(
        self, monkeypatch
    ):
        request = _make_request(origin="http://localhost:3000", client_host="8.8.8.8")
        assert await _validate(request, [CUSTOMER_ORIGIN], monkeypatch) is False
        assert await _scope(request, [CUSTOMER_ORIGIN]) == set()

    @pytest.mark.anyio
    async def test_localhost_origin_from_a_loopback_peer_is_allowed(self, monkeypatch):
        request = _make_request(origin="http://localhost:3000", client_host="127.0.0.1")
        assert await _validate(request, [CUSTOMER_ORIGIN], monkeypatch) is True
        assert await _scope(request, [CUSTOMER_ORIGIN]) == {DATASET_ID}


class TestUnlockedTokensAreUnaffected:
    """A token with no allowed_origins never consulted the check and still doesn't."""

    @pytest.mark.anyio
    async def test_scope_resolution_ignores_origin_without_a_lock(self):
        request = _make_request(origin=FOREIGN_ORIGIN)
        assert await _scope(request, None) == {DATASET_ID}

    @pytest.mark.anyio
    async def test_tile_access_ignores_origin_without_a_lock(self, monkeypatch):
        request = _make_request(origin=FOREIGN_ORIGIN)
        assert await _validate(request, None, monkeypatch) is True


class TestHostedTenantOrigin:
    """In hosted multi-tenant the shell is served from the tenant host, which the
    fleet-wide PUBLIC_APP_URL cannot represent. The tenant origin comes from
    request.state, which TenantContextMiddleware sets only after the Host
    resolved against the tenant registry — not from a raw header."""

    @pytest.mark.anyio
    async def test_validated_tenant_origin_counts_as_self(self, monkeypatch):
        monkeypatch.setattr(embed_service, "is_multi_tenant", lambda: True)
        request = _make_request(
            referer="https://acme.geolens.cloud/m/share-token",
            tenant_public_origin="https://acme.geolens.cloud",
        )
        assert await _scope(request, [CUSTOMER_ORIGIN]) == {DATASET_ID}

    @pytest.mark.anyio
    async def test_tenant_state_is_ignored_in_single_tenant(self):
        """Single-tenant never populates that attribute; do not start trusting
        it there just because something else could set it."""
        request = _make_request(
            referer="https://acme.geolens.cloud/m/share-token",
            tenant_public_origin="https://acme.geolens.cloud",
        )
        assert await _scope(request, [CUSTOMER_ORIGIN]) == set()


class TestSelfOriginIsServerDerived:
    """The load-bearing property: nothing the caller sends can become "self"."""

    @pytest.mark.anyio
    async def test_resolve_self_origins_does_not_read_request_headers(self):
        request = _make_request(origin=FOREIGN_ORIGIN, referer=f"{FOREIGN_ORIGIN}/x")
        origins = await embed_service._resolve_self_origins(AsyncMock(), request)
        assert origins == {APP_ORIGIN}
        assert FOREIGN_ORIGIN not in origins


class TestUnresolvableSelfOriginFailsClosed:
    """fix(#1548 review P2): the self-origin lookup reads an AppSetting row, so
    it is the one part of this check that can fail for reasons unrelated to the
    decision. It must deny rather than propagate: every other denial here
    returns a bool, and an escaping exception would turn a routine deny into a
    500 on the tile path."""

    @pytest.fixture
    def _lookup_raises(self, monkeypatch):
        async def _boom(db, **kwargs):
            raise RuntimeError("public_app_url lookup failed")

        monkeypatch.setattr(embed_service, "get_public_app_url", _boom, raising=True)

    @pytest.mark.anyio
    async def test_resolve_self_origins_returns_empty_instead_of_raising(
        self, _lookup_raises
    ):
        origins = await embed_service._resolve_self_origins(
            AsyncMock(), _make_request(referer=SHELL_REFERER)
        )
        assert origins == set()

    @pytest.mark.anyio
    async def test_scope_resolution_denies_and_does_not_raise(self, _lookup_raises):
        assert (
            await _scope(_make_request(referer=SHELL_REFERER), [CUSTOMER_ORIGIN])
            == set()
        )

    @pytest.mark.anyio
    async def test_tile_access_denies_and_does_not_raise(
        self, _lookup_raises, monkeypatch
    ):
        request = _make_request(referer=SHELL_REFERER)
        assert await _validate(request, [CUSTOMER_ORIGIN], monkeypatch) is False

    @pytest.mark.anyio
    async def test_a_mock_database_does_not_leak_a_typeerror(self, monkeypatch):
        """The concrete shape that regressed: a unit test passing an AsyncMock
        db reaches _load_public_url_overrides on a cold public-URL cache. That
        used to escape as `TypeError: 'coroutine' object is not iterable` and
        was masked whenever an earlier test had primed the module-global cache,
        making the whole suite order-dependent."""
        from app.core import public_urls

        # Restore the REAL lookup over the autouse fake, and clear the
        # module-global 60s cache so it actually queries. Priming that cache is
        # exactly what used to mask this.
        monkeypatch.setattr(
            embed_service,
            "get_public_app_url",
            public_urls.get_public_app_url,
            raising=True,
        )
        public_urls.invalidate_public_url_cache()
        try:
            origins = await embed_service._resolve_self_origins(
                AsyncMock(), _make_request(referer=SHELL_REFERER)
            )
        finally:
            public_urls.invalidate_public_url_cache()
        assert origins == set()


class TestMisconfiguredDeploymentIsDiagnosable:
    """fix(#1548 review P2): compose injects PUBLIC_APP_URL=http://localhost:8080
    by default, so a self-hoster on https://maps.example.com who never sets it
    resolves the wrong self-origin and their domain-locked embeds stay empty.
    The server cannot correct that without a request-derived origin, which is
    settable by anyone who can point DNS at the deployment. It denies, and says
    why."""

    @pytest.mark.anyio
    async def test_denies_and_logs_the_remediation(self, monkeypatch):
        async def _default_compose_value(db, **kwargs):
            return "http://localhost:8080"

        monkeypatch.setattr(
            embed_service, "get_public_app_url", _default_compose_value, raising=True
        )
        events: list[dict] = []
        monkeypatch.setattr(
            embed_service.logger,
            "warning",
            lambda ev, **kw: events.append({**kw, "event": ev}),
        )

        # Shell served from the real hostname; client is not loopback.
        request = _make_request(referer="https://maps.example.com/m/share-token")
        assert await _scope(request, [CUSTOMER_ORIGIN]) == set()

        assert events, "a domain-lock denial must be diagnosable from the logs"
        event = events[-1]
        assert event["event"] == "embed_token_domain_lock_denied"
        assert event["request_origin"] == "https://maps.example.com"
        assert event["self_origins"] == ["http://localhost:8080"]
        assert "PUBLIC_APP_URL" in event["remediation"]


def test_frame_ancestors_directive_carries_the_self_half():
    """The API check now mirrors the CSP directive it sits under: both accept
    our own origin plus the configured embedder origins."""
    directive = embed_service.build_embed_frame_ancestors(
        is_valid=True, allowed_origins=[CUSTOMER_ORIGIN]
    )
    assert directive == f"frame-ancestors 'self' {CUSTOMER_ORIGIN}"
