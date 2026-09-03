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

# fix(#1548 review P2): the two halves of the shipped-default misconfiguration.
# docker-compose.yml and docker-compose.prod.yml both inject
# ${PUBLIC_APP_URL:-http://localhost:8080}, so an operator who never sets it
# resolves the first while being reached at the second.
COMPOSE_DEFAULT_APP_URL = "http://localhost:8080"
SELF_HOSTED_ORIGIN = "https://maps.example.com"

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

    async def _fake_get_configured_public_app_url(db, **kwargs):
        assert not kwargs, (
            "fix(#1531/#1548 r9): _resolve_self_origins must pass nothing but the "
            "session. A request-derived origin is one every caller satisfies, "
            "which would make the allowlist vacuous."
        )
        return APP_ORIGIN

    monkeypatch.setattr(
        embed_service,
        "get_configured_public_app_url",
        _fake_get_configured_public_app_url,
        raising=True,
    )


def test_the_self_origin_lookup_cannot_be_told_about_the_request():
    """fix(#1548 review r9): the #1531 invariant, now structural.

    It used to be asserted by a fixture watching for a ``request=`` kwarg, which
    the switch to ``get_configured_public_app_url`` quietly made vacuous — that
    function has no such parameter to pass. Assert the real property instead:
    the accessor the service depends on takes the session and nothing else, so
    there is no argument through which a caller-controlled origin could reach
    it, and it is not the resolver that has those fallbacks.
    """
    import inspect

    from app.core import public_urls

    params = list(
        inspect.signature(public_urls.get_configured_public_app_url).parameters
    )
    assert params == ["db"], (
        "get_configured_public_app_url must take only the session; a request or "
        f"fallback parameter reopens the vacuous-self trap. Got: {params}"
    )
    # Read the import from source: the autouse fixture above has replaced the
    # live attribute, so an identity check here would only inspect the stub.
    from pathlib import Path

    service_src = Path(embed_service.__file__).read_text(encoding="utf-8")
    assert "get_configured_public_app_url" in service_src, (
        "the embed service must depend on the explicit accessor"
    )
    assert "import get_public_app_url" not in service_src, (
        "the embed service must NOT import the resolver: its fallbacks name an "
        "/api-stripped PUBLIC_API_URL or the caller's own headers, neither of "
        "which is the origin our embed shell is served from"
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


_TEST_GENERATION = 3


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
            # fix(#1778 codex r3): a positive entry now carries the revocation
            # generation it was minted under, and one whose stamp is stale (or
            # missing) is refused and re-read from the database. This module is
            # about the ORIGIN check on the cache-hit path, so it pins the
            # generation and stamps the entry it primes with the same value.
            "generation": _TEST_GENERATION,
        }
    )
    cache.set = AsyncMock()
    cache.delete = AsyncMock()
    monkeypatch.setattr(embed_service, "get_cache", lambda: cache)
    monkeypatch.setattr(
        embed_service,
        "current_revocation_generation",
        AsyncMock(return_value=_TEST_GENERATION),
    )
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
        embed_service,
        "current_revocation_generation",
        AsyncMock(return_value=_TEST_GENERATION),
    )
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

        monkeypatch.setattr(
            embed_service, "get_configured_public_app_url", _boom, raising=True
        )

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
            "get_configured_public_app_url",
            public_urls.get_configured_public_app_url,
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
            embed_service,
            "get_configured_public_app_url",
            _default_compose_value,
            raising=True,
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


class TestDomainLockIsRefusedWhenUnenforceable:
    """fix(#1548 review P2): the #1531 fix is inert in the SHIPPED configuration.

    ``docker-compose.yml`` and ``docker-compose.prod.yml`` both inject
    ``${PUBLIC_APP_URL:-http://localhost:8080}`` and ``.env.example`` ships the
    line commented out, so a self-hoster reached at https://maps.example.com who
    never set it resolves a self-origin of ``http://localhost:8080``. Their
    domain-locked embeds stay empty and nothing is said at the moment they
    turned the lock on. ``assert_domain_lock_is_enforceable`` refuses there
    instead, naming ``PUBLIC_APP_URL``.

    The refusal is deliberately narrow — a real, non-loopback creating origin
    against an all-loopback set of self-origins — because that pair PROVES
    unenforceability. ``test_a_correctly_configured_deployment_is_never_refused``
    is the guard on the other side: a wider "the two origins simply disagree"
    rule would block an operator whose config is fine.
    """

    @pytest.fixture(autouse=True)
    def _enterprise(self, monkeypatch):
        """Domain locking is an advanced-sharing control, so the gate only
        applies where the feature exists."""
        monkeypatch.setattr(embed_service, "is_enterprise", lambda: True)

    @staticmethod
    def _self_origin_is(monkeypatch, value: str | None) -> None:
        """Override the module-level fixture's configured self-origin.

        ``value=None`` stands in for a lookup that fails outright, which
        ``_resolve_self_origins`` swallows into an empty set.
        """

        async def _fake_get_configured_public_app_url(db, **kwargs):
            if value is None:
                raise RuntimeError("AppSetting lookup failed")
            return value

        monkeypatch.setattr(
            embed_service,
            "get_configured_public_app_url",
            _fake_get_configured_public_app_url,
            raising=True,
        )

    # -- the reported bug -------------------------------------------------

    @pytest.mark.anyio
    async def test_the_shipped_default_is_refused(self, monkeypatch):
        """codex #1548 P2, verbatim: PUBLIC_APP_URL left at the compose default
        while the deployment is reached through a real hostname."""
        self._self_origin_is(monkeypatch, COMPOSE_DEFAULT_APP_URL)
        request = _make_request(origin=SELF_HOSTED_ORIGIN)

        with pytest.raises(embed_service.DomainLockNotEnforceableError) as exc:
            await embed_service.assert_domain_lock_is_enforceable(
                AsyncMock(), request, [CUSTOMER_ORIGIN]
            )

        message = str(exc.value)
        assert "PUBLIC_APP_URL" in message, "name the variable to set"
        assert COMPOSE_DEFAULT_APP_URL in message, "name what it resolved to"
        assert SELF_HOSTED_ORIGIN in message, "name where the request arrived"

    @pytest.mark.anyio
    async def test_the_refused_configuration_really_would_deliver_nothing(
        self, monkeypatch
    ):
        """Vacuity guard: tie the 422 to the runtime behaviour it stands in for.

        If this deployment issued the token anyway, the shell's own request —
        the exact one #1531 taught the check to accept — is still denied,
        because the self-origin it is compared against is localhost. Without
        this, the gate above could be refusing a configuration that in fact
        works, and every assertion in it would still pass.
        """
        self._self_origin_is(monkeypatch, COMPOSE_DEFAULT_APP_URL)
        shell_request = _make_request(
            referer=f"{SELF_HOSTED_ORIGIN}/m/share-token?et={RAW_TOKEN}"
        )
        assert await _scope(shell_request, [CUSTOMER_ORIGIN]) == set()

    @pytest.mark.anyio
    async def test_an_unresolvable_public_url_is_refused(self, monkeypatch):
        """A garbage or unreadable setting resolves to no self-origin at all,
        which is equally unenforceable."""
        self._self_origin_is(monkeypatch, None)
        with pytest.raises(embed_service.DomainLockNotEnforceableError) as exc:
            await embed_service.assert_domain_lock_is_enforceable(
                AsyncMock(), _make_request(origin=SELF_HOSTED_ORIGIN), [CUSTOMER_ORIGIN]
            )
        assert "nothing usable" in str(exc.value)

    # -- everything the refusal must NOT touch ----------------------------

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "creating_origin",
        [SELF_HOSTED_ORIGIN, APP_ORIGIN, "https://internal.corp:8443"],
        ids=["same-host", "configured-host", "internal-admin-host"],
    )
    async def test_a_correctly_configured_deployment_is_never_refused(
        self, monkeypatch, creating_origin
    ):
        """The guard against over-refusing.

        Once PUBLIC_APP_URL names a real origin the lock works, and WHICH
        hostname the owner happened to administer through does not change that:
        the embed snippet, like every other public link, is built from
        PUBLIC_APP_URL, so viewers load the shell from the configured origin.
        A rule of "the creating origin differs from the configured one" would
        fail the third case here on a perfectly healthy install.
        """
        self._self_origin_is(monkeypatch, SELF_HOSTED_ORIGIN)
        await embed_service.assert_domain_lock_is_enforceable(
            AsyncMock(), _make_request(origin=creating_origin), [CUSTOMER_ORIGIN]
        )

    @pytest.mark.anyio
    async def test_a_localhost_install_reached_at_localhost_is_not_refused(
        self, monkeypatch
    ):
        """The default stack, used as intended.

        ``client_host`` is deliberately NOT loopback: in the shipped compose
        stack nginx proxies to the api container, so ``request.client.host`` is
        a bridge IP even for a browser on the host. A gate that leaned on the
        H-31 loopback bypass to recognize this case would refuse every default
        install.
        """
        self._self_origin_is(monkeypatch, COMPOSE_DEFAULT_APP_URL)
        await embed_service.assert_domain_lock_is_enforceable(
            AsyncMock(),
            _make_request(origin=COMPOSE_DEFAULT_APP_URL, client_host="172.18.0.5"),
            [CUSTOMER_ORIGIN],
        )

    @pytest.mark.anyio
    async def test_a_vite_dev_origin_is_not_refused(self, monkeypatch):
        """Frontend dev runs on :5174 against the same backend. Not the install
        this gate is aimed at."""
        self._self_origin_is(monkeypatch, COMPOSE_DEFAULT_APP_URL)
        await embed_service.assert_domain_lock_is_enforceable(
            AsyncMock(),
            _make_request(origin="http://localhost:5174", client_host="172.18.0.5"),
            [CUSTOMER_ORIGIN],
        )

    @pytest.mark.anyio
    async def test_a_hosted_tenant_origin_satisfies_the_gate(self, monkeypatch):
        """Hosted multi-tenant resolves its origin from the tenant registry, so
        the fleet-wide PUBLIC_APP_URL being the localhost default is irrelevant
        there. ``_resolve_self_origins`` already contributes the tenant origin;
        this pins that the gate reads it rather than only the app URL."""
        self._self_origin_is(monkeypatch, COMPOSE_DEFAULT_APP_URL)
        monkeypatch.setattr(embed_service, "is_multi_tenant", lambda: True)
        await embed_service.assert_domain_lock_is_enforceable(
            AsyncMock(),
            _make_request(
                origin=SELF_HOSTED_ORIGIN, tenant_public_origin=SELF_HOSTED_ORIGIN
            ),
            [CUSTOMER_ORIGIN],
        )

    @pytest.mark.anyio
    async def test_clearing_a_lock_is_never_refused(self, monkeypatch):
        self._self_origin_is(monkeypatch, COMPOSE_DEFAULT_APP_URL)
        request = _make_request(origin=SELF_HOSTED_ORIGIN)
        await embed_service.assert_domain_lock_is_enforceable(
            AsyncMock(), request, None
        )
        await embed_service.assert_domain_lock_is_enforceable(AsyncMock(), request, [])

    @pytest.mark.anyio
    async def test_a_non_browser_caller_is_not_refused(self, monkeypatch):
        """A CLI or SDK caller sends neither Origin nor Referer, so there is
        nothing to compare. Blocking would be a guess; the runtime denial log
        covers that case instead."""
        self._self_origin_is(monkeypatch, COMPOSE_DEFAULT_APP_URL)
        await embed_service.assert_domain_lock_is_enforceable(
            AsyncMock(), _make_request(), [CUSTOMER_ORIGIN]
        )

    @pytest.mark.anyio
    async def test_community_keeps_the_edition_message(self, monkeypatch):
        """On Community, create/update is about to reject this with
        ADVANCED_SHARING_ERROR. Pointing the operator at PUBLIC_APP_URL instead
        would name the wrong problem."""
        self._self_origin_is(monkeypatch, COMPOSE_DEFAULT_APP_URL)
        monkeypatch.setattr(embed_service, "is_enterprise", lambda: False)
        await embed_service.assert_domain_lock_is_enforceable(
            AsyncMock(), _make_request(origin=SELF_HOSTED_ORIGIN), [CUSTOMER_ORIGIN]
        )

    # -- wiring -----------------------------------------------------------

    def test_both_write_handlers_call_the_gate(self):
        """The two handlers that accept allowed_origins are the same
        two-readers-of-one-policy shape that produced the original bug. Assert
        both are wired, not just the one fixed first."""
        import ast
        import inspect

        from app.modules.embed_tokens import router as embed_router

        tree = ast.parse(inspect.getsource(embed_router))
        gated = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
            and any(
                isinstance(call.func, ast.Name)
                and call.func.id == "assert_domain_lock_is_enforceable"
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
            )
        }
        assert gated == {
            "create_embed_token_endpoint",
            "update_embed_token_endpoint",
        }, f"handlers accepting allowed_origins must all gate; gated={sorted(gated)}"


@pytest.mark.anyio
async def test_the_refusal_message_matches_the_frontend_matcher(monkeypatch):
    """fix(#1548 review P2): the 422 must not be mute in the builder.

    ``frontend/src/lib/error-map.ts`` collapses an unmapped 422 detail to the
    generic ``errors.validationFailed`` toast, and the whole point of this
    refusal is its prose — which variable to set, and to what. The frontend
    matches the message by regex to render a localized remediation, so the
    wording is a contract spanning two languages, which is exactly the shape
    that produced the bug this PR fixes. Assert it from the Python side too, so
    reworded prose fails here rather than silently degrading the toast.
    """
    import re
    from pathlib import Path

    error_map = (
        Path(__file__)
        .resolve()
        .parents[2]
        .joinpath("frontend", "src", "lib", "error-map.ts")
    )
    if not error_map.is_file():
        pytest.skip("frontend tree not present in this checkout")

    async def _fake_get_configured_public_app_url(db, **kwargs):
        return COMPOSE_DEFAULT_APP_URL

    monkeypatch.setattr(embed_service, "is_enterprise", lambda: True)
    monkeypatch.setattr(
        embed_service,
        "get_configured_public_app_url",
        _fake_get_configured_public_app_url,
        raising=True,
    )

    with pytest.raises(embed_service.DomainLockNotEnforceableError) as exc:
        await embed_service.assert_domain_lock_is_enforceable(
            AsyncMock(), _make_request(origin=SELF_HOSTED_ORIGIN), [CUSTOMER_ORIGIN]
        )
    message = str(exc.value)

    declaration = re.search(
        r"const domainLockUnenforceable = message\.match\(\s*/(.+?)/[a-z]*,?\s*\);",
        error_map.read_text(encoding="utf-8"),
        re.S,
    )
    assert declaration, (
        "frontend/src/lib/error-map.ts must keep a `domainLockUnenforceable` "
        "matcher for this refusal; without it the builder shows the generic "
        "'validation failed' toast and the remediation never reaches the operator."
    )
    js_regex = declaration.group(1).replace("\\/", "/").strip()
    match = re.match(js_regex, message)
    assert match, (
        "the backend refusal message no longer matches the frontend matcher, so "
        "the builder would fall back to the generic 422 toast.\n"
        f"  message: {message}\n  pattern: {js_regex}"
    )
    assert match.group(1) == COMPOSE_DEFAULT_APP_URL, "group 1 is the resolved URL"
    assert match.group(2) == SELF_HOSTED_ORIGIN, "group 2 is the origin to set"


def test_mock_db_suites_that_exercise_a_domain_lock_stub_the_lookup():
    """fix(#1548 review P2): cover the class, not just the one file.

    The self-origin lookup reads an AppSetting row, so a test that drives a
    domain-locked token against a mock database reaches it and gets a
    ``TypeError`` on a cold public-URL cache. That used to surface as an error;
    now that the service fails closed it surfaces as a *silent* deny, so such a
    test would assert "foreign origin rejected" and pass without exercising the
    rule at all. Any suite in that shape must stub ``get_configured_public_app_url``.
    """
    from pathlib import Path

    readers = ("validate_embed_token_access", "resolve_embed_scope_for_map")
    offenders: list[str] = []
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        if not any(r in text for r in readers):
            continue
        mocks_the_db = "AsyncMock()" in text or "MagicMock()" in text
        # A non-empty allowed_origins is what routes execution to the lookup;
        # `allowed_origins=None` / `"allowed_origins": None` never reaches it.
        sets_a_lock = "allowed_origins" in text and any(
            marker in text
            for marker in (
                'allowed_origins": ["',
                'allowed_origins=["',
                "allowed_origins, [",
            )
        )
        if mocks_the_db and sets_a_lock and "get_configured_public_app_url" not in text:
            offenders.append(path.name)

    assert not offenders, (
        "These suites drive a domain-locked embed token against a mock database "
        "without stubbing get_configured_public_app_url, so the self-origin lookup fails and "
        "the check denies for the wrong reason. Add a fixture that patches "
        "embed_service.get_configured_public_app_url (see test_embed_tokens_origin_bypass.py):\n"
        + "\n".join(f"  {name}" for name in offenders)
    )
