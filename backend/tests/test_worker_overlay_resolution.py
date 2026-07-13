"""WORK-01 / WORK-02 / WORK-03: Worker bootstrap + overlay-resolution tests.

RED phase: these tests exercise the not-yet-implemented
``bootstrap()`` helper and ``assert_enterprise_ports_resolved()`` from
``app.platform.extensions.bootstrap``.

References: WORK-01 (shared bootstrap), WORK-02 (affirmative port assertion),
WORK-03 (API-vs-worker parity via dummy overlay)
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest


def _reset_registry():
    """Reset extension registry state between tests."""
    import app.platform.extensions as ext_mod

    ext_mod._extensions.clear()
    ext_mod._routers.clear()
    ext_mod._loaded = False
    ext_mod._slot_owners.clear()


def _reset_edition():
    import app.core.edition as ed_mod

    ed_mod._info = None


def _set_edition(edition: str) -> None:
    """Force the resolved edition singleton (bypasses init_edition/license)."""
    import app.core.edition as ed_mod
    from app.core.edition import EditionInfo

    ed_mod._info = EditionInfo(edition=edition, features=())


def _reset_storage():
    """Reset storage provider state between tests."""
    import app.platform.storage.provider as prov

    prov._storage = None


def _reset_cache():
    """Reset cache provider state between tests."""
    try:
        import app.platform.cache as cache_mod

        cache_mod._cache = None
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset registry + edition singleton, isolate from discovered entry points.

    Mocks init_storage() and init_cache() to avoid filesystem/network operations
    in unit tests — those are tested at integration level.
    """
    _reset_registry()
    _reset_edition()
    with (
        patch("app.platform.extensions.entry_points", return_value=[]),
        patch("app.platform.extensions.bootstrap.init_storage"),
        patch("app.platform.extensions.bootstrap.init_cache"),
        # apply_tenancy_rls_from_engine uses the global engine (created on the
        # main event loop); when tests call asyncio.run(bootstrap(...)) they
        # create a fresh loop, causing "Future attached to a different loop".
        # Patch at the source module — it's imported inline inside bootstrap().
        # The RLS path is covered by test_tenant_rls_migration.py and
        # test_iso_single_tenant_byte_identical.py (Phase 1208-05).
        patch("app.core.db.rls.apply_tenancy_rls_from_engine"),
    ):
        yield
    _reset_registry()
    _reset_edition()


def _make_mock_ep(name: str, loader_fn):
    """Build a mock entry-point object from a loader callable."""
    from unittest.mock import MagicMock
    from app.platform.extensions.version import EXTENSION_API_VERSION

    # Attach the version attribute so load_extensions() passes the version check
    loader_fn.EXTENSION_API_VERSION = EXTENSION_API_VERSION

    ep = MagicMock()
    ep.name = name
    ep.load.return_value = loader_fn
    return ep


# ---------------------------------------------------------------------------
# bootstrap() basic behaviour
# ---------------------------------------------------------------------------


class TestBootstrapCommunity:
    """bootstrap(app=None) with an empty registry → community, Default* ports."""

    def test_bootstrap_returns_edition_info(self):
        """bootstrap() returns an EditionInfo."""
        from app.platform.extensions.bootstrap import bootstrap

        edition_info = asyncio.run(bootstrap(app=None))
        assert edition_info is not None
        assert hasattr(edition_info, "edition")

    def test_bootstrap_community_on_empty_registry(self):
        """Empty registry → community edition."""
        from app.platform.extensions.bootstrap import bootstrap

        edition_info = asyncio.run(bootstrap(app=None))
        assert edition_info.edition == "community"

    def test_bootstrap_empty_registry_ports_are_default(self):
        """Empty registry → Default* port impls."""
        from app.platform.extensions import get_catalog_port
        from app.platform.extensions.bootstrap import bootstrap

        asyncio.run(bootstrap(app=None))

        catalog_port = get_catalog_port()
        assert type(catalog_port).__name__ == "DefaultCatalogPort"

    def test_bootstrap_empty_registry_processing_port_is_default(self):
        """Empty registry → DefaultProcessingPort."""
        from app.platform.extensions import get_processing_port
        from app.platform.extensions.bootstrap import bootstrap

        asyncio.run(bootstrap(app=None))

        processing_port = get_processing_port()
        assert type(processing_port).__name__ == "DefaultProcessingPort"


class TestBootstrapWithDummyOverlay:
    """bootstrap(app=None) with dummy overlay → non-Default catalog_port."""

    def test_bootstrap_with_dummy_overlay_non_empty_extensions(self):
        """With dummy overlay entry point, list_extensions() is non-empty after bootstrap."""
        from tests.fixtures.dummy_overlay.overlay import register_extensions as _reg

        mock_ep = _make_mock_ep("dummy_overlay", _reg)

        from app.platform.extensions import list_extensions
        from app.platform.extensions.bootstrap import bootstrap

        with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
            asyncio.run(bootstrap(app=None))

        # list_extensions() should include catalog_port (registered by dummy overlay)
        extensions = list_extensions()
        assert len(extensions) > 0

    def test_bootstrap_with_dummy_overlay_catalog_port_not_default(self):
        """Worker bootstrap with dummy overlay → non-DefaultCatalogPort resolved."""
        from tests.fixtures.dummy_overlay.overlay import register_extensions as _reg

        mock_ep = _make_mock_ep("dummy_overlay", _reg)

        from app.platform.extensions import get_catalog_port
        from app.platform.extensions.bootstrap import bootstrap

        with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
            asyncio.run(bootstrap(app=None))

        catalog_port = get_catalog_port()
        assert type(catalog_port).__name__ != "DefaultCatalogPort", (
            "Worker bootstrap with dummy overlay should resolve DummyCatalogPort, "
            "not DefaultCatalogPort — the worker is not loading extensions."
        )


# ---------------------------------------------------------------------------
# assert_enterprise_ports_resolved() behaviour
# ---------------------------------------------------------------------------


class TestAssertEnterprisePortsResolved:
    """WORK-02: assert_enterprise_ports_resolved() tiered loud-failure checks."""

    def test_no_raise_on_community(self):
        """Resolved community + single-tenant → no raise even with Default ports."""
        from app.platform.extensions.bootstrap import assert_enterprise_ports_resolved

        # _info is None (community) via the autouse fixture.
        with patch(
            "app.platform.extensions.bootstrap.is_multi_tenant", return_value=False
        ):
            assert_enterprise_ports_resolved()

    def test_no_raise_on_enterprise_without_cloud_ports(self):
        """WORK-02 regression: enterprise with the enterprise-overlay ports
        resolved but the cloud ports still Default → NO raise.

        A bare enterprise deploy legitimately runs the community processing /
        catalog / entitlement ports (only the cloud overlay replaces them), so
        the worker must not crash-loop demanding them.
        """
        from app.platform.extensions.bootstrap import assert_enterprise_ports_resolved

        _set_edition("enterprise")

        class _Perm: ...

        class _Ident: ...

        class _Flow: ...

        with (
            patch(
                "app.platform.extensions.get_permission_extension",
                return_value=_Perm(),
            ),
            patch(
                "app.platform.extensions.get_identity_extension",
                return_value=_Ident(),
            ),
            patch(
                "app.platform.extensions.get_workflow_extension",
                return_value=_Flow(),
            ),
            patch(
                "app.platform.extensions.bootstrap.is_multi_tenant",
                return_value=False,
            ),
        ):
            # Cloud ports stay Default* — must NOT raise under bare enterprise.
            assert_enterprise_ports_resolved()

    def test_raises_on_enterprise_with_default_ports(self):
        """Enterprise + all-Default ports → RuntimeError naming the enterprise
        ports (permission/identity/workflow), NOT the cloud-only ports."""
        from app.platform.extensions.bootstrap import assert_enterprise_ports_resolved

        _set_edition("enterprise")
        with patch(
            "app.platform.extensions.bootstrap.is_multi_tenant", return_value=False
        ):
            with pytest.raises(RuntimeError) as exc_info:
                assert_enterprise_ports_resolved()

        msg = str(exc_info.value)
        assert "permission" in msg or "identity" in msg or "workflow" in msg
        # Cloud-only ports must not be demanded under bare enterprise.
        assert "processing_port" not in msg and "catalog_port" not in msg
        assert "entitlement" not in msg
        # Remediation points at the enterprise overlay, NOT the cloud overlay.
        assert (
            "INSTALL_ENTERPRISE_OVERLAY" in msg
            or 'INSTALL_OVERLAYS="/enterprise"' in msg
        )
        assert "/cloud" not in msg

    def test_raises_on_multi_tenant_missing_cloud_ports(self):
        """multi_tenant + Default cloud ports → RuntimeError naming them."""
        from app.platform.extensions.bootstrap import assert_enterprise_ports_resolved

        _set_edition("enterprise")
        with patch(
            "app.platform.extensions.bootstrap.is_multi_tenant", return_value=True
        ):
            with pytest.raises(RuntimeError) as exc_info:
                assert_enterprise_ports_resolved()

        msg = str(exc_info.value)
        assert "processing_port" in msg
        assert "catalog_port" in msg
        # Cloud-port failure must send the operator to the CLOUD overlay build,
        # not INSTALL_ENTERPRISE_OVERLAY=1 (which bakes /enterprise only).
        assert 'INSTALL_OVERLAYS="/enterprise /cloud"' in msg

    def test_raises_on_multi_tenant_missing_entitlement_port(self):
        """multi_tenant with processing/catalog resolved but entitlement still
        DefaultEntitlementPort → RuntimeError.

        DefaultEntitlementPort is fail-OPEN (grant-all), so a green boot with it
        in place would silently pass every tenant quota/plan check. The cloud
        assertion must fail closed on it.
        """
        from app.platform.extensions.bootstrap import assert_enterprise_ports_resolved

        _set_edition("enterprise")

        class _Proc: ...

        class _Cat: ...

        class _Perm: ...

        class _Ident: ...

        class _Flow: ...

        with (
            patch("app.platform.extensions.get_processing_port", return_value=_Proc()),
            patch("app.platform.extensions.get_catalog_port", return_value=_Cat()),
            patch(
                "app.platform.extensions.get_permission_extension",
                return_value=_Perm(),
            ),
            patch(
                "app.platform.extensions.get_identity_extension", return_value=_Ident()
            ),
            patch(
                "app.platform.extensions.get_workflow_extension", return_value=_Flow()
            ),
            patch(
                "app.platform.extensions.bootstrap.is_multi_tenant", return_value=True
            ),
        ):
            # Only entitlement stays DefaultEntitlementPort.
            with pytest.raises(RuntimeError) as exc_info:
                assert_enterprise_ports_resolved()

        msg = str(exc_info.value)
        assert "entitlement" in msg
        assert 'INSTALL_OVERLAYS="/enterprise /cloud"' in msg

    def test_licensed_enterprise_without_env_var_is_checked(self):
        """License-key activation is asserted from the RESOLVED edition, not the
        GEOLENS_EDITION env var — the env-var dodge is closed (WORK-02)."""
        from app.platform.extensions.bootstrap import assert_enterprise_ports_resolved

        _set_edition("enterprise")
        env = {k: v for k, v in os.environ.items() if k != "GEOLENS_EDITION"}
        with patch.dict("os.environ", env, clear=True):
            with patch(
                "app.platform.extensions.bootstrap.is_multi_tenant",
                return_value=False,
            ):
                with pytest.raises(RuntimeError):
                    assert_enterprise_ports_resolved()


# ---------------------------------------------------------------------------
# Structural: bootstrap() is idempotent on load_extensions call
# ---------------------------------------------------------------------------


class TestBootstrapIdempotency:
    """Calling bootstrap() twice should not corrupt the registry."""

    def test_bootstrap_twice_stays_community(self):
        """Two bootstrap() calls on empty registry → community each time."""
        from app.platform.extensions.bootstrap import bootstrap

        info1 = asyncio.run(bootstrap(app=None))
        _reset_edition()

        info2 = asyncio.run(bootstrap(app=None))

        assert info1.edition == "community"
        assert info2.edition == "community"
