"""Tests for tenant session GUC wiring (ISO-01).

Plan 1208-01: ContextVar + after_begin engine hook + dual-entrypoint wiring.

Test coverage:
  A — current_tenant_var exists with default None; exported from app.core.db
  B — multi_tenant + var set → GUC equals the tenant id in a real transaction
  C — multi_tenant + var unset (None) → GUC is empty/unset (hook is no-op when var is None)
  D — single_tenant + var set → GUC is NEVER set (hook is unconditional no-op)
  E — set_config uses a BOUND param (no f-string injection)
  F — middleware bridge sets current_tenant_var in multi_tenant, never in single_tenant
  G — worker tenant_job_context helper sets + resets the var
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import jwt
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_settings():
    import app.core.config as cfg_mod

    # Host-routing tests use the canonical example suffix explicitly; production
    # multi-tenant deployments must set TENANT_BASE_DOMAIN themselves.
    overrides = (
        {"tenant_base_domain": "geolens.app"}
        if os.environ.get("GEOLENS_TENANCY_MODE") == "multi_tenant"
        and not os.environ.get("TENANT_BASE_DOMAIN")
        else {}
    )
    cfg_mod.settings = cfg_mod.Settings(**overrides)  # type: ignore[attr-defined]
    # tenant_context keeps the Settings singleton as a module-level import.
    # Mirror application startup semantics after this test-only reload.
    if "app.api.middleware.tenant_context" in sys.modules:
        sys.modules["app.api.middleware.tenant_context"].settings = cfg_mod.settings
    return cfg_mod.settings


@pytest.fixture
def fresh_engine():
    """Create a NullPool async engine per test to avoid cross-loop connection issues.

    NullPool never keeps idle connections open, so each async test function
    (which has its own event loop in asyncio strict mode) starts clean.
    The test database URL is read from the already-loaded settings.
    """
    from app.core.config import settings
    from app.core.db.tenant_session import install_tenant_session_hook

    engine = create_async_engine(
        settings.database_url,
        poolclass=NullPool,
    )
    install_tenant_session_hook(engine)
    return engine


# ---------------------------------------------------------------------------
# A: current_tenant_var — existence, default, export
# ---------------------------------------------------------------------------


class TestCurrentTenantVar:
    def test_var_exists_in_tenant_session_module(self):
        """current_tenant_var ContextVar must exist in app.core.db.tenant_session."""
        from app.core.db.tenant_session import current_tenant_var

        assert current_tenant_var is not None

    def test_var_default_is_none(self):
        """current_tenant_var default value is None."""
        from app.core.db.tenant_session import current_tenant_var

        assert current_tenant_var.get() is None

    def test_var_exported_from_core_db(self):
        """current_tenant_var is re-exported from app.core.db."""
        from app.core.db import current_tenant_var  # noqa: F401  — import proves it

        assert current_tenant_var is not None

    def test_var_is_contextvars_ContextVar(self):
        """current_tenant_var is a contextvars.ContextVar instance."""
        from contextvars import ContextVar

        from app.core.db.tenant_session import current_tenant_var

        assert isinstance(current_tenant_var, ContextVar)

    def test_var_set_and_reset(self):
        """Setting the var returns a token and reset() restores None."""
        from app.core.db.tenant_session import current_tenant_var

        tid = str(uuid.uuid4())
        token = current_tenant_var.set(tid)
        assert current_tenant_var.get() == tid
        current_tenant_var.reset(token)
        assert current_tenant_var.get() is None


# ---------------------------------------------------------------------------
# B: multi_tenant + var set → GUC equals tenant id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guc_set_in_multi_tenant_when_var_is_set(fresh_engine):
    """In multi_tenant mode, a transaction reads back the expected GUC value."""
    tid = str(uuid.uuid4())

    with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
        _reload_settings()

        from app.core.db.tenant_session import current_tenant_var

        token = current_tenant_var.set(tid)
        try:
            async with AsyncSession(fresh_engine) as session:
                async with session.begin():
                    result = await session.execute(
                        text("SELECT current_setting('app.current_tenant', true)")
                    )
                    guc_val = result.scalar_one()

            assert guc_val == tid, (
                f"Expected GUC 'app.current_tenant' == {tid!r}, got {guc_val!r}"
            )
        finally:
            current_tenant_var.reset(token)
            _reload_settings()

    await fresh_engine.dispose()


# ---------------------------------------------------------------------------
# C: multi_tenant + var unset → GUC is empty/NULL (no-op when var is None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guc_unset_in_multi_tenant_when_var_is_none(fresh_engine):
    """In multi_tenant with var=None the hook is a no-op; GUC stays unset."""
    with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
        _reload_settings()

        from app.core.db.tenant_session import current_tenant_var

        # Ensure var is None
        assert current_tenant_var.get() is None

        try:
            async with AsyncSession(fresh_engine) as session:
                async with session.begin():
                    result = await session.execute(
                        text("SELECT current_setting('app.current_tenant', true)")
                    )
                    guc_val = result.scalar_one()

            # When var is None the hook does not run set_config → GUC is unset.
            # Postgres returns "" (empty string) for missing settings with missing_ok=true.
            assert guc_val in (None, ""), (
                f"Expected GUC unset (None or '') but got {guc_val!r}"
            )
        finally:
            _reload_settings()

    await fresh_engine.dispose()


# ---------------------------------------------------------------------------
# D: single_tenant + var set → GUC NEVER set (unconditional no-op)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guc_never_set_in_single_tenant(fresh_engine):
    """In single_tenant the GUC must never be set regardless of var value."""
    tid = str(uuid.uuid4())

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("GEOLENS_TENANCY_MODE", None)
        _reload_settings()

        from app.core.db.tenant_session import current_tenant_var

        token = current_tenant_var.set(tid)
        try:
            async with AsyncSession(fresh_engine) as session:
                async with session.begin():
                    result = await session.execute(
                        text("SELECT current_setting('app.current_tenant', true)")
                    )
                    guc_val = result.scalar_one()

            assert guc_val in (None, ""), (
                f"single_tenant: GUC must be unset but got {guc_val!r}"
            )
        finally:
            current_tenant_var.reset(token)

    await fresh_engine.dispose()


# ---------------------------------------------------------------------------
# E: parametrized SQL (bound param, not f-string injection)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guc_bound_param_no_sql_injection(fresh_engine):
    """set_config uses a bound param: a value with a single quote must not raise."""
    # If the tenant id were f-string'd into SQL, a single-quote would break parsing.
    # A bound param passes cleanly through the driver.
    malicious_tid = "tenant-x'; SELECT 1; --"

    with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
        _reload_settings()

        from app.core.db.tenant_session import current_tenant_var

        token = current_tenant_var.set(malicious_tid)
        try:
            # Should not raise — proves bound-param safety
            async with AsyncSession(fresh_engine) as session:
                async with session.begin():
                    result = await session.execute(
                        text("SELECT current_setting('app.current_tenant', true)")
                    )
                    guc_val = result.scalar_one()

            # The exact value round-trips cleanly through the bound param
            assert guc_val == malicious_tid, (
                f"Expected {malicious_tid!r} but got {guc_val!r}"
            )
        finally:
            current_tenant_var.reset(token)
            _reload_settings()

    await fresh_engine.dispose()


# ---------------------------------------------------------------------------
# F: middleware bridge — sets var in multi_tenant, NO-OP in single_tenant
# ---------------------------------------------------------------------------


class TestMiddlewareBridge:
    """TenantContextMiddleware sets current_tenant_var in multi_tenant only."""

    def test_middleware_resolves_slug_and_bridges_uuid_in_multi_tenant(self):
        """multi_tenant: the slug signal is resolved to a UUID, which is bridged.

        Regression for the Gap-A Codex finding (PR #256): the middleware must
        hand current_tenant_var a tenant UUID, not the raw subdomain slug — the
        RLS GUC casts ::uuid. We patch the resolver to keep this a fast unit
        test and assert (a) the extracted slug reaches the resolver and (b) the
        resolved UUID is what lands in current_tenant_var.
        """
        from starlette.applications import Starlette
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        resolved_uuid = str(uuid.uuid4())

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()

            import app.api.middleware.tenant_context as tc
            from app.core.db.tenant_session import current_tenant_var

            captured: list[str | None] = []
            seen_signal: list[str | None] = []

            async def _fake_resolve(signal):
                seen_signal.append(signal)
                return resolved_uuid

            def _probe(request: StarletteRequest) -> JSONResponse:
                captured.append(current_tenant_var.get())
                return JSONResponse({"ok": True})

            app = Starlette(routes=[Route("/probe", _probe)])
            app.add_middleware(tc.TenantContextMiddleware)

            with patch.object(tc, "_resolve_tenant_uuid", _fake_resolve):
                client = TestClient(app, raise_server_exceptions=True)
                resp = client.get("/probe", headers={"host": "acme.geolens.app"})

            assert resp.status_code == 200
            # The extracted subdomain slug must reach the resolver…
            assert seen_signal == ["acme"], (
                f"Expected resolver called with slug 'acme' but got {seen_signal!r}"
            )
            # …and the RESOLVED UUID (not the slug) must be bridged to the var.
            assert captured and captured[0] == resolved_uuid, (
                f"Expected var={resolved_uuid!r} during request but got {captured[0]!r}"
            )

        _reload_settings()

    def test_middleware_does_not_set_var_in_single_tenant(self):
        """In single_tenant mode the middleware never touches current_tenant_var."""
        from starlette.applications import Starlette
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEOLENS_TENANCY_MODE", None)
            _reload_settings()

            from app.api.middleware.tenant_context import TenantContextMiddleware
            from app.core.db.tenant_session import current_tenant_var

            captured: list[str | None] = []

            def _probe(request: StarletteRequest) -> JSONResponse:
                captured.append(current_tenant_var.get())
                return JSONResponse({"ok": True})

            app = Starlette(routes=[Route("/probe", _probe)])
            app.add_middleware(TenantContextMiddleware)
            client = TestClient(app, raise_server_exceptions=True)

            resp = client.get(
                "/probe",
                headers={"host": "acme.geolens.app"},
            )
            assert resp.status_code == 200
            # In single_tenant the var must never be set
            assert captured and captured[0] is None, (
                f"Expected var=None in single_tenant but got {captured[0]!r}"
            )

    def test_var_reset_after_request_no_leak(self):
        """After a multi_tenant request the var is None (no cross-request bleed)."""
        from starlette.applications import Starlette
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()

            import app.api.middleware.tenant_context as tc
            from app.core.db.tenant_session import current_tenant_var

            async def _fake_resolve(signal):
                return str(uuid.uuid4())

            def _probe(request: StarletteRequest) -> JSONResponse:
                return JSONResponse({"ok": True})

            app = Starlette(routes=[Route("/probe", _probe)])
            app.add_middleware(tc.TenantContextMiddleware)

            with patch.object(tc, "_resolve_tenant_uuid", _fake_resolve):
                client = TestClient(app, raise_server_exceptions=True)
                # First request sets the var; after it completes it must be None
                client.get("/probe", headers={"host": "acme.geolens.app"})
            assert current_tenant_var.get() is None, (
                "current_tenant_var leaked across requests"
            )

        _reload_settings()


class TestResolveTenantUuid:
    """Host UUIDs and slugs must both resolve through catalog.tenants."""

    @pytest.mark.asyncio
    async def test_none_signal_returns_none(self):
        from app.api.middleware.tenant_context import _resolve_tenant_uuid

        assert await _resolve_tenant_uuid(None) is None

    @pytest.mark.asyncio
    async def test_uuid_host_signal_must_exist_in_registry(self):
        """A UUID-shaped Host label is untrusted until the registry confirms it."""
        import app.core.db as core_db
        from app.api.middleware.tenant_context import _resolve_tenant_uuid

        tid = uuid.uuid4()
        session = MagicMock()
        session.scalar = AsyncMock(return_value=tid)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(core_db, "async_session", return_value=cm):
            assert await _resolve_tenant_uuid(str(tid)) == str(tid)

        statement = session.scalar.await_args.args[0]
        parameters = session.scalar.await_args.args[1]
        assert "WHERE id = :tenant_id" in str(statement)
        assert parameters == {"tenant_id": tid}

    @pytest.mark.asyncio
    async def test_slug_resolved_to_uuid_via_db(self):
        """A subdomain slug is looked up in catalog.tenants and returns its UUID."""
        import app.core.db as core_db
        from app.api.middleware.tenant_context import _resolve_tenant_uuid

        target = uuid.uuid4()
        session = MagicMock()
        session.scalar = AsyncMock(return_value=target)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(core_db, "async_session", return_value=cm):
            result = await _resolve_tenant_uuid("acme")

        assert result == str(target)
        session.scalar.assert_awaited_once()
        statement = session.scalar.await_args.args[0]
        assert "WHERE slug = :slug" in str(statement)
        assert "LIMIT" not in str(statement).upper()

    @pytest.mark.asyncio
    async def test_unknown_slug_returns_none(self):
        import app.core.db as core_db
        from app.api.middleware.tenant_context import _resolve_tenant_uuid

        session = MagicMock()
        session.scalar = AsyncMock(return_value=None)
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(return_value=session)
        cm.__aexit__ = AsyncMock(return_value=False)

        with patch.object(core_db, "async_session", return_value=cm):
            assert await _resolve_tenant_uuid("ghost-tenant") is None

    @pytest.mark.asyncio
    async def test_db_error_resolves_none_not_raise(self):
        """A DB failure during slug resolution must not 500 — returns None."""
        import app.core.db as core_db
        from app.api.middleware.tenant_context import _resolve_tenant_uuid

        with patch.object(
            core_db, "async_session", side_effect=RuntimeError("db down")
        ):
            assert await _resolve_tenant_uuid("acme") is None


class TestVerifiedJwtTenantClaim:
    """JWT fallback may scope RLS only from a verified GeoLens access token."""

    @staticmethod
    def _token(*, tenant_id: uuid.UUID, secret: str | None = None, **overrides) -> str:
        from app.core.config import settings

        now = datetime.now(UTC)
        payload = {
            "sub": str(uuid.uuid4()),
            "username": "tenant-user",
            "tid": str(tenant_id),
            "jti": uuid.uuid4().hex,
            "token_version": 1,
            "iat": now,
            "exp": now + timedelta(minutes=5),
            **overrides,
        }
        return jwt.encode(
            payload,
            secret or settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
        )

    def test_accepts_verified_tenant_claim(self):
        from app.api.middleware.tenant_context import _extract_jwt_tenant_claim

        tenant_id = uuid.uuid4()
        token = self._token(tenant_id=tenant_id)
        assert _extract_jwt_tenant_claim(f"Bearer {token}") == str(tenant_id)

    def test_rejects_token_signed_with_another_key(self):
        from app.api.middleware.tenant_context import _extract_jwt_tenant_claim

        token = self._token(
            tenant_id=uuid.uuid4(),
            secret="not-the-geolens-key-with-at-least-32-bytes",
        )
        assert _extract_jwt_tenant_claim(f"Bearer {token}") is None

    def test_rejects_expired_token(self):
        from app.api.middleware.tenant_context import _extract_jwt_tenant_claim

        token = self._token(
            tenant_id=uuid.uuid4(), exp=datetime.now(UTC) - timedelta(seconds=1)
        )
        assert _extract_jwt_tenant_claim(f"Bearer {token}") is None

    @pytest.mark.parametrize(
        "overrides",
        [
            {"tid": "not-a-uuid"},
            {"sub": "not-a-uuid"},
            {"token_version": True},
        ],
    )
    def test_rejects_invalid_required_claims(self, overrides):
        from app.api.middleware.tenant_context import _extract_jwt_tenant_claim

        token = self._token(tenant_id=uuid.uuid4(), **overrides)
        assert _extract_jwt_tenant_claim(f"Bearer {token}") is None

    def test_rejects_malformed_or_non_bearer_header(self):
        from app.api.middleware.tenant_context import _extract_jwt_tenant_claim

        assert _extract_jwt_tenant_claim("Bearer definitely-not-a-jwt") is None
        assert _extract_jwt_tenant_claim("Basic abc123") is None

    def test_middleware_uses_verified_jwt_fallback(self):
        from starlette.applications import Starlette
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        tenant_id = uuid.uuid4()
        token = self._token(tenant_id=tenant_id)

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()

            import app.api.middleware.tenant_context as tc
            from app.core.db.tenant_session import current_tenant_var

            captured: list[str | None] = []

            def _probe(_request: StarletteRequest) -> JSONResponse:
                captured.append(current_tenant_var.get())
                return JSONResponse({"ok": True})

            app = Starlette(routes=[Route("/probe", _probe)])
            app.add_middleware(tc.TenantContextMiddleware)
            response = TestClient(app).get(
                "/probe",
                headers={
                    "host": "api.geolens.app",
                    "authorization": f"Bearer {token}",
                },
            )

        _reload_settings()
        assert response.status_code == 200
        assert captured == [str(tenant_id)]

    def test_middleware_rejects_host_and_verified_token_tenant_mismatch(self):
        from starlette.applications import Starlette
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        host_tenant_id = uuid.uuid4()
        token_tenant_id = uuid.uuid4()
        token = self._token(tenant_id=token_tenant_id)

        async def _resolve(signal: str | None) -> str | None:
            if signal == "acme":
                return str(host_tenant_id)
            return signal

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()

            import app.api.middleware.tenant_context as tc

            def _probe(_request: StarletteRequest) -> JSONResponse:
                return JSONResponse({"ok": True})

            app = Starlette(routes=[Route("/probe", _probe)])
            app.add_middleware(tc.TenantContextMiddleware)
            with patch.object(tc, "_resolve_tenant_uuid", side_effect=_resolve):
                response = TestClient(app).get(
                    "/probe",
                    headers={
                        "host": "acme.geolens.app",
                        "authorization": f"Bearer {token}",
                    },
                )

        _reload_settings()
        assert response.status_code == 403
        assert response.json()["detail"] == ("Tenant host does not match bearer token")

    def test_middleware_scopes_refresh_style_request_from_tenant_host(self):
        """Non-bearer refresh requests rely on the same-origin tenant host."""
        from starlette.applications import Starlette
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        tenant_id = uuid.uuid4()
        captured: list[str | None] = []

        async def _resolve(signal: str | None) -> str | None:
            return str(tenant_id) if signal == "acme" else signal

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()

            import app.api.middleware.tenant_context as tc
            from app.core.db.tenant_session import current_tenant_var

            def _probe(_request: StarletteRequest) -> JSONResponse:
                captured.append(current_tenant_var.get())
                return JSONResponse({"ok": True})

            app = Starlette(routes=[Route("/auth/refresh", _probe)])
            app.add_middleware(tc.TenantContextMiddleware)
            with patch.object(tc, "_resolve_tenant_uuid", side_effect=_resolve):
                response = TestClient(app).get(
                    "/auth/refresh", headers={"host": "acme.geolens.app"}
                )

        _reload_settings()
        assert response.status_code == 200
        assert captured == [str(tenant_id)]


class TestMultiTenantRuntimeRoleGuard:
    """Multi-tenant boot must never use a PostgreSQL role that bypasses RLS."""

    @pytest.mark.asyncio
    async def test_single_tenant_is_a_hard_noop(self):
        from app.core.db.rls import assert_multi_tenant_runtime_role

        conn = AsyncMock()
        with patch("app.core.tenancy.is_multi_tenant", return_value=False):
            await assert_multi_tenant_runtime_role(conn)
        conn.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_accepts_dedicated_non_bypass_runtime_login(self):
        from app.core.db.rls import assert_multi_tenant_runtime_role

        conn = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = (
            "geolens_app",
            "geolens_app",
            *(False for _ in range(15)),
        )
        conn.execute.return_value = result

        with patch("app.core.tenancy.is_multi_tenant", return_value=True):
            await assert_multi_tenant_runtime_role(conn)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("unsafe_index", range(2, 17))
    async def test_rejects_every_superuser_bypass_and_membership_path(
        self, unsafe_index: int
    ):
        from app.core.db.rls import assert_multi_tenant_runtime_role

        values: list[object] = [
            "geolens_app",
            "geolens_app",
            *(False for _ in range(15)),
        ]
        values[unsafe_index] = True
        conn = AsyncMock()
        result = MagicMock()
        result.fetchone.return_value = tuple(values)
        conn.execute.return_value = result

        with (
            patch("app.core.tenancy.is_multi_tenant", return_value=True),
            pytest.raises(RuntimeError, match="least-privilege runtime credential"),
        ):
            await assert_multi_tenant_runtime_role(conn)


@pytest.mark.asyncio
async def test_runtime_role_guard_rejects_live_tenant_schema_owner(monkeypatch):
    """A non-superuser runtime login still fails if it owns tenant storage."""
    import asyncpg
    from sqlalchemy.engine import make_url

    from app.core.config import settings
    from app.core.db.rls import assert_multi_tenant_runtime_role

    suffix = uuid.uuid4().hex
    role = f"oc_runtime_owner_{suffix[:12]}"
    password = f"OcRuntime{suffix}"
    schema = f"data_t_{uuid.uuid4().hex[:8]}_0000_0000_0000_000000000000"
    admin_dsn = settings.test_database_url.replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    admin = await asyncpg.connect(admin_dsn)
    engine = None
    try:
        if not await admin.fetchval(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        ):
            pytest.skip("Live ownership regression requires the test DB superuser")
        await admin.execute(
            f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            f"NOREPLICATION NOBYPASSRLS PASSWORD '{password}'"
        )
        await admin.execute(f"CREATE SCHEMA {schema} AUTHORIZATION {role}")

        login_url = make_url(settings.test_database_url).set(
            username=role, password=password
        )
        engine = create_async_engine(login_url, poolclass=NullPool)
        monkeypatch.setattr("app.core.tenancy.is_multi_tenant", lambda: True)
        async with engine.connect() as conn:
            with pytest.raises(RuntimeError, match="must not own"):
                await assert_multi_tenant_runtime_role(conn)
    finally:
        if engine is not None:
            await engine.dispose()
        await admin.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        await admin.execute(f"DROP ROLE IF EXISTS {role}")
        await admin.close()


# ---------------------------------------------------------------------------
# G: worker tenant_job_context helper — sets + resets the var
# ---------------------------------------------------------------------------


class TestTenantJobContext:
    def test_job_context_sets_and_resets_var(self):
        """tenant_job_context sets current_tenant_var for the block and resets after."""
        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()

            from app.core.db.tenant_session import (
                current_tenant_var,
                tenant_job_context,
            )

            tid = str(uuid.uuid4())

            with tenant_job_context(tid):
                assert current_tenant_var.get() == tid

            # After the context exits the var is reset
            assert current_tenant_var.get() is None

            _reload_settings()

    def test_job_context_noop_in_single_tenant(self):
        """tenant_job_context is a no-op in single_tenant (var stays None)."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEOLENS_TENANCY_MODE", None)
            _reload_settings()

            from app.core.db.tenant_session import (
                current_tenant_var,
                tenant_job_context,
            )

            tid = str(uuid.uuid4())

            with tenant_job_context(tid):
                # single_tenant: var must not be set
                assert current_tenant_var.get() is None

            assert current_tenant_var.get() is None

    def test_job_context_resets_on_exception(self):
        """tenant_job_context resets the var even if the body raises."""
        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()

            from app.core.db.tenant_session import (
                current_tenant_var,
                tenant_job_context,
            )

            tid = str(uuid.uuid4())

            try:
                with tenant_job_context(tid):
                    assert current_tenant_var.get() == tid
                    raise ValueError("boom")
            except ValueError:
                pass

            assert current_tenant_var.get() is None

            _reload_settings()


# ---------------------------------------------------------------------------
# H: worker propagation — defer_async_with_tenant + tenant_task (PR #256 P1-b)
# ---------------------------------------------------------------------------


class TestDeferAsyncWithTenant:
    """defer_async_with_tenant threads current_tenant_var into the job payload."""

    @pytest.mark.asyncio
    async def test_no_tenant_id_injected_when_var_unset(self):
        """single_tenant (var None) → byte-identical to task.defer_async(**kwargs)."""
        from app.core.db.tenant_session import defer_async_with_tenant

        task = MagicMock()
        task.defer_async = AsyncMock(return_value="job")
        result = await defer_async_with_tenant(task, job_id="j1", user_id="u1")
        assert result == "job"
        task.defer_async.assert_awaited_once_with(job_id="j1", user_id="u1")

    @pytest.mark.asyncio
    async def test_injects_current_tenant_when_var_set(self):
        from app.core.db.tenant_session import (
            current_tenant_var,
            defer_async_with_tenant,
        )

        task = MagicMock()
        task.defer_async = AsyncMock()
        tid = str(uuid.uuid4())
        token = current_tenant_var.set(tid)
        try:
            await defer_async_with_tenant(task, job_id="j1")
        finally:
            current_tenant_var.reset(token)
        task.defer_async.assert_awaited_once_with(job_id="j1", tenant_id=tid)

    @pytest.mark.asyncio
    async def test_explicit_tenant_id_is_respected(self):
        """An explicit tenant_id kwarg wins over current_tenant_var (setdefault)."""
        from app.core.db.tenant_session import (
            current_tenant_var,
            defer_async_with_tenant,
        )

        task = MagicMock()
        task.defer_async = AsyncMock()
        explicit = str(uuid.uuid4())
        token = current_tenant_var.set(str(uuid.uuid4()))
        try:
            await defer_async_with_tenant(task, job_id="j1", tenant_id=explicit)
        finally:
            current_tenant_var.reset(token)
        task.defer_async.assert_awaited_once_with(job_id="j1", tenant_id=explicit)

    @pytest.mark.asyncio
    async def test_multi_tenant_enqueue_without_context_fails_closed(self):
        from app.core.db.tenant_session import defer_async_with_tenant

        task = MagicMock()
        task.defer_async = AsyncMock()
        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()
            with pytest.raises(RuntimeError, match="without tenant context"):
                await defer_async_with_tenant(task, job_id="j1")
        task.defer_async.assert_not_awaited()
        _reload_settings()

    @pytest.mark.asyncio
    async def test_multi_tenant_rejects_explicit_tenant_mismatch(self):
        from app.core.db.tenant_session import (
            current_tenant_var,
            defer_async_with_tenant,
        )

        task = MagicMock()
        task.defer_async = AsyncMock()
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()
            token = current_tenant_var.set(tenant_a)
            try:
                with pytest.raises(RuntimeError, match="does not match"):
                    await defer_async_with_tenant(task, job_id="j1", tenant_id=tenant_b)
            finally:
                current_tenant_var.reset(token)
        task.defer_async.assert_not_awaited()
        _reload_settings()

    @pytest.mark.asyncio
    async def test_multi_tenant_rejects_malformed_explicit_tenant(self):
        from app.core.db.tenant_session import defer_async_with_tenant

        task = MagicMock()
        task.defer_async = AsyncMock()
        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()
            with pytest.raises(ValueError, match="invalid tenant_id"):
                await defer_async_with_tenant(
                    task,
                    job_id="j1",
                    tenant_id="tenant-a; SET ROLE postgres",
                )
        task.defer_async.assert_not_awaited()
        _reload_settings()


class TestTenantTaskDecorator:
    """tenant_task binds current_tenant_var from the tenant_id job kwarg at entry."""

    @pytest.mark.asyncio
    async def test_binds_and_pops_tenant_id_in_multi_tenant(self):
        from app.core.db.tenant_session import current_tenant_var, tenant_task

        seen: dict = {}

        @tenant_task
        async def _task(job_id, **kwargs):
            seen["tid_during"] = current_tenant_var.get()
            seen["kwargs"] = dict(kwargs)
            return "ok"

        tid = str(uuid.uuid4())
        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()
            result = await _task(job_id="j1", tenant_id=tid)

        assert result == "ok"
        assert seen["tid_during"] == tid  # context bound for the task body
        assert "tenant_id" not in seen["kwargs"]  # popped before the task fn
        assert current_tenant_var.get() is None  # reset after the task
        _reload_settings()

    @pytest.mark.asyncio
    async def test_task_without_kwargs_is_unaffected(self):
        """A task with a fixed signature (e.g. embed_record) still works — tenant_id popped."""
        from app.core.db.tenant_session import tenant_task

        @tenant_task
        async def _task(record_id):
            return record_id

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()
            result = await _task(record_id="r1", tenant_id=str(uuid.uuid4()))
        assert result == "r1"
        _reload_settings()

    @pytest.mark.asyncio
    async def test_missing_tenant_id_fails_before_task_body(self):
        from app.core.db.tenant_session import tenant_task

        called = False

        @tenant_task
        async def _task():
            nonlocal called
            called = True

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()
            with pytest.raises(RuntimeError, match="missing tenant context"):
                await _task()
        assert called is False
        _reload_settings()

    @pytest.mark.asyncio
    async def test_single_tenant_is_noop(self):
        from app.core.db.tenant_session import current_tenant_var, tenant_task

        seen: dict = {}

        @tenant_task
        async def _task(**kwargs):
            seen["tid_during"] = current_tenant_var.get()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEOLENS_TENANCY_MODE", None)
            _reload_settings()
            await _task(tenant_id=str(uuid.uuid4()))
        assert seen["tid_during"] is None  # never bound in single_tenant
        _reload_settings()


# ---------------------------------------------------------------------------
# I: end-to-end acceptance — verified HTTP tenant context, RLS, and MVT bytes
# ---------------------------------------------------------------------------


def _protobuf_fields(payload: bytes):
    """Yield ``(field_number, wire_type, value)`` from a protobuf message.

    The MVT acceptance below only needs the standard scalar and
    length-delimited wire types emitted by PostGIS. Keeping this tiny decoder in
    the test avoids adding a production dependency solely to inspect one layer
    name.
    """

    def _varint(offset: int) -> tuple[int, int]:
        value = 0
        shift = 0
        while offset < len(payload):
            byte = payload[offset]
            offset += 1
            value |= (byte & 0x7F) << shift
            if not byte & 0x80:
                return value, offset
            shift += 7
            if shift >= 70:
                break
        raise AssertionError("Malformed protobuf varint in MVT response")

    offset = 0
    while offset < len(payload):
        tag, offset = _varint(offset)
        field_number, wire_type = tag >> 3, tag & 0x07
        if wire_type == 0:
            value, offset = _varint(offset)
        elif wire_type == 1:
            value = payload[offset : offset + 8]
            offset += 8
        elif wire_type == 2:
            length, offset = _varint(offset)
            value = payload[offset : offset + length]
            offset += length
        elif wire_type == 5:
            value = payload[offset : offset + 4]
            offset += 4
        else:
            raise AssertionError(f"Unsupported protobuf wire type {wire_type}")
        if offset > len(payload):
            raise AssertionError("Truncated protobuf field in MVT response")
        yield field_number, wire_type, value


def _mvt_layer_names(payload: bytes) -> list[str]:
    """Decode layer names from a Mapbox Vector Tile protobuf payload."""
    names: list[str] = []
    for field_number, wire_type, layer in _protobuf_fields(payload):
        if field_number != 3 or wire_type != 2 or not isinstance(layer, bytes):
            continue
        for layer_field, layer_wire, value in _protobuf_fields(layer):
            if layer_field == 1 and layer_wire == 2 and isinstance(value, bytes):
                names.append(value.decode("utf-8"))
                break
    return names


@pytest.mark.asyncio
async def test_verified_tenant_jwt_scopes_live_force_rls_query_end_to_end():
    """HTTP bearer JWT -> middleware -> ContextVar -> begin hook -> FORCE RLS.

    A temporary LOGIN role is deliberately non-superuser/NOBYPASSRLS, so this
    cannot false-pass through PostgreSQL's superuser RLS exemption. Tenant A
    sees only A's row and tenant B sees only B's row through the same handler.
    """
    from httpx import ASGITransport, AsyncClient
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from starlette.applications import Starlette
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from app.core.config import settings
    from app.core.db.rls import assert_multi_tenant_runtime_role
    from app.core.db.tenant_session import (
        current_tenant_var,
        install_tenant_session_hook,
    )

    suffix = uuid.uuid4().hex[:12]
    role = f"oc_accept_login_{suffix}"
    schema = f"oc_accept_{suffix}"
    table = "tenant_rows"
    password = f"OcAccept{uuid.uuid4().hex}"
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    admin_url = settings.test_database_url
    admin_engine = create_async_engine(
        admin_url,
        poolclass=NullPool,
        isolation_level="AUTOCOMMIT",
    )
    runtime_engine = None
    role_created = False

    try:
        async with admin_engine.connect() as conn:
            is_superuser = await conn.scalar(
                text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")
            )
            if not is_superuser:
                pytest.skip("Acceptance setup requires a role allowed to CREATE ROLE")

            await conn.execute(
                text(
                    f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB "
                    f"NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '{password}'"
                )
            )
            role_created = True
            await conn.execute(text(f"CREATE SCHEMA {schema}"))
            await conn.execute(
                text(
                    f"CREATE TABLE {schema}.{table} ("
                    "tenant_id uuid NOT NULL, label text NOT NULL)"
                )
            )
            await conn.execute(
                text(
                    f"INSERT INTO {schema}.{table} (tenant_id, label) VALUES "
                    "(:tenant_a, 'tenant-a'), (:tenant_b, 'tenant-b')"
                ),
                {"tenant_a": tenant_a, "tenant_b": tenant_b},
            )
            await conn.execute(
                text(f"ALTER TABLE {schema}.{table} ENABLE ROW LEVEL SECURITY")
            )
            await conn.execute(
                text(f"ALTER TABLE {schema}.{table} FORCE ROW LEVEL SECURITY")
            )
            await conn.execute(
                text(
                    f"CREATE POLICY tenant_scope ON {schema}.{table} USING ("
                    "tenant_id = NULLIF("
                    "current_setting('app.current_tenant', true), ''"
                    ")::uuid)"
                )
            )
            await conn.execute(text(f"GRANT USAGE ON SCHEMA {schema} TO {role}"))
            await conn.execute(text(f"GRANT SELECT ON {schema}.{table} TO {role}"))

        runtime_url = make_url(admin_url).set(username=role, password=password)
        runtime_engine = create_async_engine(runtime_url, poolclass=NullPool)
        install_tenant_session_hook(runtime_engine)
        runtime_sessions = async_sessionmaker(runtime_engine, expire_on_commit=False)

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()

            import app.api.middleware.tenant_context as tenant_context

            async with runtime_engine.connect() as conn:
                await assert_multi_tenant_runtime_role(conn)

            async def _probe(_request: StarletteRequest) -> JSONResponse:
                async with runtime_sessions() as session:
                    row = (
                        (
                            await session.execute(
                                text(
                                    "SELECT current_user::text AS db_user, "
                                    "current_setting('app.current_tenant', true) AS guc, "
                                    f"ARRAY(SELECT label FROM {schema}.{table} "
                                    "ORDER BY label) AS labels"
                                )
                            )
                        )
                        .mappings()
                        .one()
                    )
                return JSONResponse(
                    {
                        "context": current_tenant_var.get(),
                        "db_user": row["db_user"],
                        "guc": row["guc"],
                        "labels": row["labels"],
                    }
                )

            def _token(tenant_id: uuid.UUID) -> str:
                now = datetime.now(UTC)
                return jwt.encode(
                    {
                        "sub": str(uuid.uuid4()),
                        "username": "acceptance-user",
                        "tid": str(tenant_id),
                        "jti": uuid.uuid4().hex,
                        "token_version": 1,
                        "iat": now,
                        "exp": now + timedelta(minutes=5),
                    },
                    tenant_context.settings.jwt_secret_key.get_secret_value(),
                    algorithm=tenant_context.settings.jwt_algorithm,
                )

            app = Starlette(routes=[Route("/probe", _probe)])
            app.add_middleware(tenant_context.TenantContextMiddleware)
            transport = ASGITransport(app=app)
            async with AsyncClient(
                transport=transport,
                base_url="http://api.geolens.app",
            ) as client:
                response_a = await client.get(
                    "/probe",
                    headers={"Authorization": f"Bearer {_token(tenant_a)}"},
                )
                response_b = await client.get(
                    "/probe",
                    headers={"Authorization": f"Bearer {_token(tenant_b)}"},
                )

        assert response_a.status_code == 200
        assert response_a.json() == {
            "context": str(tenant_a),
            "db_user": role,
            "guc": str(tenant_a),
            "labels": ["tenant-a"],
        }
        assert response_b.status_code == 200
        assert response_b.json() == {
            "context": str(tenant_b),
            "db_user": role,
            "guc": str(tenant_b),
            "labels": ["tenant-b"],
        }
        assert current_tenant_var.get() is None
    finally:
        _reload_settings()
        if runtime_engine is not None:
            await runtime_engine.dispose()
        if role_created:
            async with admin_engine.connect() as conn:
                await conn.execute(text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
                await conn.execute(text(f"DROP OWNED BY {role}"))
                await conn.execute(text(f"DROP ROLE IF EXISTS {role}"))
        await admin_engine.dispose()


@pytest.mark.asyncio
async def test_live_tenant_tile_binary_has_tenant_qualified_mvt_layer_name():
    """Real PostGIS tile query emits the client-visible tenant layer name.

    The query runs under the exact per-tenant reader role selected by the tile
    binder, then this test decodes the returned MVT protobuf and asserts its
    layer name rather than inspecting mocked call arguments.
    """
    import asyncpg

    from app.core.config import settings
    from app.core.db.tenant_schema import tenant_data_schema, tenant_reader_role
    from app.processing.tiles.pool import set_tenant_role_for_tile_request
    from app.processing.tiles.service import get_tile

    tenant_id = str(uuid.uuid4())
    with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
        _reload_settings()
        schema = tenant_data_schema(tenant_id)
        role = tenant_reader_role(tenant_id)
    _reload_settings()
    table = f"oc_mvt_{uuid.uuid4().hex[:10]}"
    dsn = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    role_created = False

    try:
        is_superuser = await conn.fetchval(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        if not is_superuser:
            pytest.skip("Acceptance setup requires a role allowed to CREATE ROLE")

        await conn.execute(
            f"CREATE ROLE {role} NOLOGIN NOSUPERUSER NOINHERIT NOBYPASSRLS"
        )
        role_created = True
        await conn.execute(f"CREATE SCHEMA {schema}")
        await conn.execute(
            f"CREATE TABLE {schema}.{table} ("
            "gid bigserial PRIMARY KEY, name text, "
            "geom geometry(Point, 3857), geom_4326 geometry(Point, 4326))"
        )
        await conn.execute(
            f"INSERT INTO {schema}.{table} (name, geom, geom_4326) VALUES ("
            "'origin', "
            "ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857), "
            "ST_SetSRID(ST_MakePoint(0, 0), 4326))"
        )
        await conn.execute(f"GRANT USAGE ON SCHEMA {schema} TO {role}")
        await conn.execute(f"GRANT SELECT ON {schema}.{table} TO {role}")

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()
            async with conn.transaction():
                await set_tenant_role_for_tile_request(conn, tenant_id)
                assert await conn.fetchval("SELECT current_user") == role
                tile = await get_tile(
                    None,
                    table,
                    0,
                    0,
                    0,
                    [{"name": "name", "type": "text"}],
                    tile_columns=["name"],
                    conn=conn,
                    schema=schema,
                )

        assert tile is not None
        assert _mvt_layer_names(bytes(tile)) == [f"{schema}.{table}"]
    finally:
        _reload_settings()
        if role_created:
            await conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            await conn.execute(f"DROP OWNED BY {role}")
            await conn.execute(f"DROP ROLE IF EXISTS {role}")
        await conn.close()


@pytest.mark.asyncio
async def test_unresolved_multi_tenant_tile_metadata_fails_before_db_query():
    """An unscoped multi-tenant tile request cannot consult catalog metadata."""
    from fastapi import HTTPException

    from app.core.db.tenant_session import current_tenant_var
    from app.processing.tiles.router import _resolve_dataset_meta

    db = AsyncMock()
    context_token = current_tenant_var.set(None)
    try:
        with (
            patch("app.processing.tiles.router.is_multi_tenant", return_value=True),
            pytest.raises(HTTPException) as exc_info,
        ):
            await _resolve_dataset_meta("must_not_resolve", db)
    finally:
        current_tenant_var.reset(context_token)

    assert exc_info.value.status_code == 403
    db.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_raster_metadata_cache_is_tenant_scoped_and_filtered():
    """Tenant B cannot reuse tenant A's cached raster metadata by dataset id."""
    from fastapi import HTTPException

    from app.core.db.tenant_session import current_tenant_var
    from app.processing.tiles import router as tile_router

    dataset_id = uuid.uuid4()
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())
    row = {
        "visibility": "public",
        "record_status": "published",
        "created_by": uuid.uuid4(),
        "record_type": "raster_dataset",
        "asset_uri": "tenant-a.tif",
        "storage_backend": "local",
        "band_count": 1,
        "dtype": "uint16",
        "is_dem": False,
        "band_info": None,
        "nodata": None,
    }
    result_a = MagicMock()
    result_a.mappings.return_value.one_or_none.return_value = row
    db_a = AsyncMock()
    db_a.execute.return_value = result_a
    result_b = MagicMock()
    result_b.mappings.return_value.one_or_none.return_value = None
    db_b = AsyncMock()
    db_b.execute.return_value = result_b
    unscoped_db = AsyncMock()

    with tile_router._raster_meta_cache_lock:
        tile_router._raster_meta_cache.clear()
    try:
        with patch("app.processing.tiles.router.is_multi_tenant", return_value=True):
            unscoped_context = current_tenant_var.set(None)
            try:
                with pytest.raises(HTTPException) as unscoped_exc:
                    await tile_router._resolve_raster_meta(unscoped_db, dataset_id)
            finally:
                current_tenant_var.reset(unscoped_context)

            context_a = current_tenant_var.set(tenant_a)
            try:
                meta_a = await tile_router._resolve_raster_meta(db_a, dataset_id)
            finally:
                current_tenant_var.reset(context_a)

            context_b = current_tenant_var.set(tenant_b)
            try:
                with pytest.raises(HTTPException) as exc_info:
                    await tile_router._resolve_raster_meta(db_b, dataset_id)
            finally:
                current_tenant_var.reset(context_b)

        assert meta_a.asset_uri == "tenant-a.tif"
        assert unscoped_exc.value.status_code == 403
        unscoped_db.execute.assert_not_awaited()
        assert exc_info.value.status_code == 404
        db_b.execute.assert_awaited_once()
        statement, params = db_b.execute.call_args.args
        assert "d.tenant_id = :tenant_id" in str(statement)
        assert params == {
            "dataset_id": dataset_id,
            "tenant_id": uuid.UUID(tenant_b),
        }
        with tile_router._raster_meta_cache_lock:
            assert f"{tenant_a}:{dataset_id}" in tile_router._raster_meta_cache
            assert f"{tenant_b}:{dataset_id}" not in tile_router._raster_meta_cache
            assert str(dataset_id) not in tile_router._raster_meta_cache
    finally:
        with tile_router._raster_meta_cache_lock:
            tile_router._raster_meta_cache.clear()


async def test_verified_tenant_jwt_serves_live_mvt_through_fastapi_router(
    client, test_db_session
):
    """Serve a real tenant MVT through the production FastAPI tile endpoint.

    This crosses every serving boundary omitted by the direct service probe:
    AuthService issues the signed, server-owned ``tid`` claim; the production
    middleware verifies it; the real auth dependency resolves the tenant user;
    the actual tile router resolves tenant-scoped catalog metadata; and the
    tile pool binds a restricted per-tenant role before PostGIS builds the MVT.

    The tile-pool LOGIN is NOINHERIT and has no direct table access. It may only
    ``SET ROLE`` to the tenant reader, so a missing/failed binder yields 503
    instead of false-passing under the test database's superuser.
    """
    import gzip

    import asyncpg
    from sqlalchemy.engine import make_url

    import app.core.db as core_db
    import app.processing.tiles.pool as tile_pool_module
    import app.processing.tiles.router as tile_router
    from app.core.config import settings
    from app.core.db.tenant_schema import tenant_data_schema, tenant_reader_role
    from app.core.db.tenant_session import install_tenant_session_hook
    from app.modules.auth.models import User
    from app.modules.auth.providers import AuthenticatedIdentity
    from app.modules.auth.service import AuthService
    from app.modules.catalog.datasets.domain.models import Dataset, Record

    tenant_id = uuid.uuid4()
    suffix = uuid.uuid4().hex[:10]
    table = f"oc_http_mvt_{suffix}"
    gateway_role = f"oc_tile_gateway_{suffix}"
    gateway_password = f"OcTileGateway{uuid.uuid4().hex}"
    username = f"oc_tile_user_{suffix}"
    dsn = settings.test_database_url.replace("postgresql+asyncpg://", "postgresql://")

    with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
        _reload_settings()
        schema = tenant_data_schema(str(tenant_id))
        reader_role = tenant_reader_role(str(tenant_id))
    _reload_settings()

    admin_conn = await asyncpg.connect(dsn)
    tile_pool = None
    original_tile_pool = tile_pool_module._tile_pool
    reader_created = False
    gateway_created = False
    user_id: uuid.UUID | None = None
    record_id: uuid.UUID | None = None
    dataset_id: uuid.UUID | None = None

    try:
        is_superuser = await admin_conn.fetchval(
            "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
        )
        if not is_superuser:
            pytest.skip("Acceptance setup requires a role allowed to CREATE ROLE")

        await admin_conn.execute(
            f"CREATE ROLE {reader_role} NOLOGIN NOSUPERUSER NOINHERIT NOBYPASSRLS"
        )
        reader_created = True
        await admin_conn.execute(
            f"CREATE ROLE {gateway_role} LOGIN NOSUPERUSER NOCREATEDB "
            f"NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD '{gateway_password}'"
        )
        gateway_created = True
        await admin_conn.execute(
            f"GRANT {reader_role} TO {gateway_role} WITH INHERIT FALSE, SET TRUE"
        )
        await admin_conn.execute(f"CREATE SCHEMA {schema}")
        await admin_conn.execute(
            f"CREATE TABLE {schema}.{table} ("
            "gid bigserial PRIMARY KEY, name text, "
            "geom geometry(Point, 3857), geom_4326 geometry(Point, 4326))"
        )
        await admin_conn.execute(
            f"INSERT INTO {schema}.{table} (name, geom, geom_4326) VALUES ("
            "'router-origin', "
            "ST_Transform(ST_SetSRID(ST_MakePoint(0, 0), 4326), 3857), "
            "ST_SetSRID(ST_MakePoint(0, 0), 4326))"
        )
        await admin_conn.execute(f"GRANT USAGE ON SCHEMA {schema} TO {reader_role}")
        await admin_conn.execute(f"GRANT SELECT ON {schema}.{table} TO {reader_role}")
        # Permit name resolution for the fail-closed positive control below,
        # but deliberately do not grant the gateway SELECT on the table.
        await admin_conn.execute(f"GRANT USAGE ON SCHEMA {schema} TO {gateway_role}")

        gateway_url = (
            make_url(settings.test_database_url)
            .set(
                drivername="postgresql",
                username=gateway_role,
                password=gateway_password,
            )
            .render_as_string(hide_password=False)
        )
        gateway_conn = await asyncpg.connect(gateway_url)
        try:
            assert await gateway_conn.fetchval("SELECT current_user") == gateway_role
            assert not await gateway_conn.fetchval(
                "SELECT has_table_privilege(current_user, $1, 'SELECT')",
                f"{schema}.{table}",
            )
        finally:
            await gateway_conn.close()

        user = User(
            username=username,
            tenant_id=tenant_id,
            status="active",
            is_active=True,
            token_version=1,
        )
        test_db_session.add(user)
        await test_db_session.flush()
        user_id = user.id

        record = Record(
            title="Tenant HTTP MVT acceptance",
            visibility="public",
            record_status="draft",
            record_type="vector_dataset",
            created_by=user_id,
            tenant_id=tenant_id,
        )
        test_db_session.add(record)
        await test_db_session.flush()
        record_id = record.id

        dataset = Dataset(
            record_id=record_id,
            table_name=table,
            srid=4326,
            geometry_type="Point",
            feature_count=1,
            source_format="geojson",
            source_filename="acceptance.geojson",
            tenant_id=tenant_id,
            column_info=[
                {"name": "gid", "type": "bigint"},
                {"name": "name", "type": "text"},
                {"name": "geom", "type": "geometry"},
                {"name": "geom_4326", "type": "geometry"},
            ],
            tile_columns=["name"],
        )
        test_db_session.add(dataset)
        await test_db_session.commit()
        dataset_id = dataset.id

        # The client fixture swaps in its own app engine. Install the same
        # production transaction-begin tenant hook on that real request engine.
        install_tenant_session_hook(core_db.engine)
        tile_pool = await asyncpg.create_pool(
            dsn=gateway_url,
            min_size=1,
            max_size=1,
            command_timeout=10,
        )
        tile_pool_module._tile_pool = tile_pool
        with tile_router._dataset_cache_lock:
            tile_router._dataset_cache.clear()
        with tile_router._raster_meta_cache_lock:
            tile_router._raster_meta_cache.clear()

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()
            tile_url = f"/tiles/data.{table}/0/0/0.pbf"
            unresolved_response = await client.get(
                tile_url,
                headers={"Host": "api.geolens.app"},
            )
            assert unresolved_response.status_code == 403
            assert unresolved_response.json()["detail"] == (
                "Tenant context is required for tile access"
            )
            with tile_router._dataset_cache_lock:
                assert not tile_router._dataset_cache
            unresolved_raster_response = await client.get(
                "/tiles/raster-auth-check/",
                params={"dataset_id": str(dataset_id)},
                headers={"Host": "api.geolens.app"},
            )
            assert unresolved_raster_response.status_code == 403
            with tile_router._raster_meta_cache_lock:
                assert not tile_router._raster_meta_cache

            token = await AuthService(test_db_session).create_access_token(
                AuthenticatedIdentity(user_id=user_id, username=username)
            )
            response = await client.get(
                tile_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Host": "api.geolens.app",
                },
            )

        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith(
            "application/vnd.mapbox-vector-tile"
        )
        assert response.headers["cache-control"].startswith("private")
        assert response.headers["etag"]
        # httpx normally decodes Content-Encoding automatically. Keep the
        # assertion transport-agnostic in case a future ASGI transport exposes
        # the router's gzip bytes directly.
        payload = response.content
        if payload.startswith(b"\x1f\x8b"):
            payload = gzip.decompress(payload)
        assert _mvt_layer_names(payload) == [f"{schema}.{table}"]
    finally:
        _reload_settings()
        with tile_router._dataset_cache_lock:
            tile_router._dataset_cache.clear()
        with tile_router._raster_meta_cache_lock:
            tile_router._raster_meta_cache.clear()
        tile_pool_module._tile_pool = original_tile_pool
        if tile_pool is not None:
            await tile_pool.close()
        if dataset_id is not None:
            await admin_conn.execute(
                "DELETE FROM catalog.datasets WHERE id = $1", dataset_id
            )
        if record_id is not None:
            await admin_conn.execute(
                "DELETE FROM catalog.records WHERE id = $1", record_id
            )
        if user_id is not None:
            await admin_conn.execute("DELETE FROM catalog.users WHERE id = $1", user_id)
        if reader_created:
            await admin_conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        if gateway_created and reader_created:
            await admin_conn.execute(f"REVOKE {reader_role} FROM {gateway_role}")
        if gateway_created:
            await admin_conn.execute(f"DROP OWNED BY {gateway_role}")
            await admin_conn.execute(f"DROP ROLE IF EXISTS {gateway_role}")
        if reader_created:
            await admin_conn.execute(f"DROP OWNED BY {reader_role}")
            await admin_conn.execute(f"DROP ROLE IF EXISTS {reader_role}")
        await admin_conn.close()
