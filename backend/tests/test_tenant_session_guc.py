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
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_settings():
    import app.core.config as cfg_mod

    cfg_mod.settings = cfg_mod.Settings()  # type: ignore[attr-defined]
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
    """_resolve_tenant_uuid: UUID passthrough + slug→catalog.tenants lookup (Gap A)."""

    @pytest.mark.asyncio
    async def test_none_signal_returns_none(self):
        from app.api.middleware.tenant_context import _resolve_tenant_uuid

        assert await _resolve_tenant_uuid(None) is None

    @pytest.mark.asyncio
    async def test_uuid_signal_passes_through_without_db(self):
        """A JWT 'tid' that is already a UUID is returned unchanged — no DB hit."""
        import app.core.db as core_db
        from app.api.middleware.tenant_context import _resolve_tenant_uuid

        tid = str(uuid.uuid4())
        with patch.object(
            core_db, "async_session", side_effect=AssertionError("must not hit DB")
        ):
            assert await _resolve_tenant_uuid(tid) == tid

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
