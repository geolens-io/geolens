"""Tests for the tenancy MODE axis, inert tenant-context middleware, and GUARD-01 edition-half.

TSEAM-03: GEOLENS_TENANCY_MODE setting + is_multi_tenant() helper.
TSEAM-04: TenantContextMiddleware is a strict no-op in single_tenant.
GUARD-01 edition-half: multi_tenant without a tenancy overlay fails loud at boot.
"""

from __future__ import annotations

import os
from importlib import reload
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reload_settings():
    """Force pydantic-settings to re-read os.environ for Settings."""
    import app.core.config as cfg_mod

    cfg_mod.settings = cfg_mod.Settings()  # type: ignore[attr-defined]
    return cfg_mod.settings


def _reload_tenancy():
    """Reload tenancy module so is_multi_tenant() re-evaluates settings."""
    import app.core.tenancy as tenancy_mod

    reload(tenancy_mod)
    return tenancy_mod


@pytest.fixture(autouse=True)
def _restore_settings_and_tenancy_globals():
    """Snapshot and restore process-global config/tenancy state for every test here.

    ``_reload_settings()`` rebinds ``app.core.config.settings`` to a fresh
    ``Settings()`` and ``_reload_tenancy()`` reloads ``app.core.tenancy`` — both
    are PROCESS-GLOBAL mutations, not per-test. Under pytest-xdist these tests are
    co-located on one worker (conftest ``tenancy_global_state`` group), so without
    a restore the fresh ``Settings()`` (which loses the conftest-injected
    per-worker ``postgres_db_test`` suffix → reverts to bare ``geolens_test``)
    leaks onto sibling tests on the same worker, making them connect to a
    non-existent DB (InvalidCatalogNameError) or read wrong config. Restoring the
    original singleton object and reloading tenancy back to baseline after each
    test keeps this file's global mutations from escaping.
    """
    import app.core.config as cfg_mod

    original_settings = cfg_mod.settings
    try:
        yield
    finally:
        cfg_mod.settings = original_settings
        # Reload tenancy against the restored settings so is_multi_tenant()
        # re-binds to the original singleton (the reloaded module captured a
        # stale reference during the test).
        _reload_tenancy()


# ---------------------------------------------------------------------------
# Test A: default mode is single_tenant, is_multi_tenant() returns False
# ---------------------------------------------------------------------------


class TestModeAxisDefault:
    def test_default_mode_is_single_tenant(self):
        """With no env override the default mode must be single_tenant."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEOLENS_TENANCY_MODE", None)
            settings = _reload_settings()
            assert settings.geolens_tenancy_mode == "single_tenant"

    def test_is_multi_tenant_false_by_default(self):
        """is_multi_tenant() returns False under the default mode."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEOLENS_TENANCY_MODE", None)
            _reload_settings()
            tenancy = _reload_tenancy()
            assert tenancy.is_multi_tenant() is False

    def test_constants_exist(self):
        """TENANCY_MODE_SINGLE and TENANCY_MODE_MULTI constants exist."""
        import app.core.tenancy as tenancy_mod

        assert tenancy_mod.TENANCY_MODE_SINGLE == "single_tenant"
        assert tenancy_mod.TENANCY_MODE_MULTI == "multi_tenant"


# ---------------------------------------------------------------------------
# Test B: monkeypatching to multi_tenant flips is_multi_tenant() True
# ---------------------------------------------------------------------------


class TestModeAxisMultiTenant:
    def test_is_multi_tenant_true_when_env_set(self):
        """is_multi_tenant() returns True when GEOLENS_TENANCY_MODE=multi_tenant."""
        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            _reload_settings()
            tenancy = _reload_tenancy()
            assert tenancy.is_multi_tenant() is True

    def test_mode_flip_back_to_single(self):
        """After switching back to single_tenant is_multi_tenant() returns False."""
        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "single_tenant"}):
            _reload_settings()
            tenancy = _reload_tenancy()
            assert tenancy.is_multi_tenant() is False

    def test_invalid_mode_raises_at_boot(self):
        """An invalid GEOLENS_TENANCY_MODE value raises ValidationError."""
        from pydantic import ValidationError

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "cloud"}):
            with pytest.raises(ValidationError):
                _reload_settings()


# ---------------------------------------------------------------------------
# Test C: TenantContextMiddleware is a no-op in single_tenant
# ---------------------------------------------------------------------------


class TestTenantContextMiddlewareInert:
    def test_middleware_does_not_set_tenant_id_in_single_tenant(self):
        """In single_tenant mode the middleware must not set request.state.tenant_id."""
        from starlette.applications import Starlette
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse
        from starlette.routing import Route
        from starlette.testclient import TestClient

        # Ensure single_tenant mode
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GEOLENS_TENANCY_MODE", None)
            _reload_settings()
            _reload_tenancy()

        from app.api.middleware.tenant_context import TenantContextMiddleware

        # Use bare Starlette (not FastAPI) to avoid anyio_mode="auto" interference
        # with async route functions that take Request — pytest-anyio treats them
        # as fixtures when anyio_mode=auto is active in pyproject.toml.
        def _probe_route(request: StarletteRequest) -> JSONResponse:
            tid = getattr(request.state, "tenant_id", "NOT_SET")
            return JSONResponse({"tenant_id": str(tid)})

        probe_app = Starlette(routes=[Route("/probe", _probe_route)])
        probe_app.add_middleware(TenantContextMiddleware)

        client = TestClient(probe_app, raise_server_exceptions=True)
        resp = client.get("/probe")
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}: {resp.text}"
        )
        data = resp.json()
        # In single_tenant the middleware must not set a non-None tenant_id.
        assert data["tenant_id"] in ("None", "NOT_SET"), (
            f"Expected no tenant_id in single_tenant but got: {data['tenant_id']!r}"
        )


# ---------------------------------------------------------------------------
# Test D: GUARD-01 edition-half — multi_tenant without overlay raises
# ---------------------------------------------------------------------------


class TestGuard01EditionHalf:
    def test_multi_tenant_without_overlay_raises(self):
        """check_tenancy_mode_supported raises RuntimeError when mode=multi_tenant but no overlay loaded."""
        from app.core.edition import check_tenancy_mode_supported

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            with pytest.raises(RuntimeError, match="GEOLENS_TENANCY_MODE=multi_tenant"):
                check_tenancy_mode_supported(loaded_extensions=[])

    def test_multi_tenant_with_overlay_does_not_raise(self):
        """check_tenancy_mode_supported is silent when mode=multi_tenant and an overlay is loaded."""
        from app.core.edition import check_tenancy_mode_supported

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "multi_tenant"}):
            # Should NOT raise — overlay present
            check_tenancy_mode_supported(loaded_extensions=["geolens_cloud"])

    def test_single_tenant_with_no_overlay_does_not_raise(self):
        """check_tenancy_mode_supported is silent in single_tenant regardless of extensions."""
        from app.core.edition import check_tenancy_mode_supported

        with patch.dict(os.environ, {"GEOLENS_TENANCY_MODE": "single_tenant"}):
            check_tenancy_mode_supported(loaded_extensions=[])


# ---------------------------------------------------------------------------
# Test E (lint self-test): no literal 'cloud' in core/edition.py or core/license.py
# ---------------------------------------------------------------------------


class TestNoCloudEditionToken:
    def test_edition_py_contains_no_cloud_literal(self):
        """core/edition.py must not contain a literal 'cloud' string."""
        import re
        from pathlib import Path

        edition_path = (
            Path(__file__).resolve().parents[1] / "app" / "core" / "edition.py"
        )
        text = edition_path.read_text()
        matches = re.findall(r"""['"]cloud['"]""", text)
        assert not matches, (
            f"Found forbidden 'cloud' literal in {edition_path}: {matches}"
        )

    def test_license_py_contains_no_cloud_literal(self):
        """core/license.py must not contain a literal 'cloud' string."""
        import re
        from pathlib import Path

        license_path = (
            Path(__file__).resolve().parents[1] / "app" / "core" / "license.py"
        )
        text = license_path.read_text()
        matches = re.findall(r"""['"]cloud['"]""", text)
        assert not matches, (
            f"Found forbidden 'cloud' literal in {license_path}: {matches}"
        )
