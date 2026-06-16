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
from unittest.mock import patch

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

    def test_middleware_sets_var_in_multi_tenant(self):
        """In multi_tenant a resolved tenant_id is bridged to current_tenant_var."""
        from starlette.applications import Starlette
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
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

            # Subdomain header that will resolve to a slug (3-part host)
            resp = client.get(
                "/probe",
                headers={"host": "acme.geolens.app"},
            )
            assert resp.status_code == 200
            # The var should be set to "acme" (the subdomain) during the request
            assert captured and captured[0] == "acme", (
                f"Expected var='acme' during request but got {captured[0]!r}"
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

            from app.api.middleware.tenant_context import TenantContextMiddleware
            from app.core.db.tenant_session import current_tenant_var

            def _probe(request: StarletteRequest) -> JSONResponse:
                return JSONResponse({"ok": True})

            app = Starlette(routes=[Route("/probe", _probe)])
            app.add_middleware(TenantContextMiddleware)
            client = TestClient(app, raise_server_exceptions=True)

            # First request sets the var; after it completes the var should be None
            client.get("/probe", headers={"host": "acme.geolens.app"})
            assert current_tenant_var.get() is None, (
                "current_tenant_var leaked across requests"
            )

        _reload_settings()


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
