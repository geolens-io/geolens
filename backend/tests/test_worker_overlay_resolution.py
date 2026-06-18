"""WORK-01 / WORK-02 / WORK-03: Worker bootstrap + overlay-resolution tests.

RED phase: these tests exercise the not-yet-implemented
``bootstrap()`` helper and ``assert_enterprise_ports_resolved()`` from
``app.platform.extensions.bootstrap``.

References: WORK-01 (shared bootstrap), WORK-02 (affirmative port assertion),
WORK-03 (API-vs-worker parity via dummy overlay)
"""

from __future__ import annotations

import asyncio
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
    """WORK-02: assert_enterprise_ports_resolved() loud-failure checks."""

    def test_no_raise_on_community(self):
        """Community edition (no GEOLENS_EDITION) → no raise."""
        import os

        from app.platform.extensions.bootstrap import assert_enterprise_ports_resolved

        env = {k: v for k, v in os.environ.items() if k != "GEOLENS_EDITION"}
        with patch.dict("os.environ", env, clear=True):
            # Must not raise
            assert_enterprise_ports_resolved()

    def test_no_raise_on_explicit_community(self):
        """GEOLENS_EDITION=community → no raise even with all-Default ports."""
        from app.platform.extensions.bootstrap import assert_enterprise_ports_resolved

        with patch.dict("os.environ", {"GEOLENS_EDITION": "community"}):
            assert_enterprise_ports_resolved()

    def test_raises_on_enterprise_with_all_default_ports(self):
        """GEOLENS_EDITION=enterprise + all-Default ports → RuntimeError naming each."""
        from app.platform.extensions.bootstrap import assert_enterprise_ports_resolved

        with patch.dict("os.environ", {"GEOLENS_EDITION": "enterprise"}):
            with pytest.raises(RuntimeError) as exc_info:
                assert_enterprise_ports_resolved()

        msg = str(exc_info.value)
        # Must name the offending port(s)
        assert (
            "Default" in msg
            or "default" in msg
            or "processing_port" in msg
            or "catalog_port" in msg
        )

    def test_raises_names_all_default_ports(self):
        """Error message must enumerate every still-Default port."""
        from app.platform.extensions.bootstrap import assert_enterprise_ports_resolved

        with patch.dict("os.environ", {"GEOLENS_EDITION": "enterprise"}):
            with pytest.raises(RuntimeError) as exc_info:
                assert_enterprise_ports_resolved()

        msg = str(exc_info.value)
        # At minimum the two primary ports must appear
        assert "processing_port" in msg or "DefaultProcessingPort" in msg
        assert "catalog_port" in msg or "DefaultCatalogPort" in msg

    def test_raises_on_partial_overlay_still_has_default_ports(self):
        """Partial overlay (only catalog_port) → STILL raises (other ports Default).

        A partial overlay cannot pass the affirmative assertion — EVERY expected
        single-slot port must be resolved to a non-Default implementation.
        """
        from tests.fixtures.dummy_overlay.overlay import register_extensions as _reg

        mock_ep = _make_mock_ep("dummy_overlay", _reg)

        # Load the dummy overlay (registers catalog_port only; others remain Default)
        with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
            from app.platform.extensions import load_extensions

            load_extensions()

        # catalog_port is now DummyCatalogPort; processing_port, permission,
        # identity, workflow remain Default
        from app.platform.extensions.bootstrap import assert_enterprise_ports_resolved

        with patch.dict("os.environ", {"GEOLENS_EDITION": "enterprise"}):
            with pytest.raises(RuntimeError) as exc_info:
                assert_enterprise_ports_resolved()

        msg = str(exc_info.value)
        # Must flag the remaining Default ports (not just catalog_port which is resolved)
        assert "Default" in msg or "processing_port" in msg or "workflow" in msg

    def test_case_insensitive_enterprise_check(self):
        """GEOLENS_EDITION=Enterprise (mixed case) → same loud failure."""
        from app.platform.extensions.bootstrap import assert_enterprise_ports_resolved

        with patch.dict("os.environ", {"GEOLENS_EDITION": "Enterprise"}):
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
