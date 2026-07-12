"""WORK-03: API-vs-worker parity regression test via dummy overlay.

This file tests that for the same env + overlay combination, the "API path"
(bootstrap with a FastAPI stub) and the "worker path" (bootstrap with app=None)
resolve to:
- identical ``get_edition().edition``
- identical ``type(get_processing_port())``
- identical ``type(get_catalog_port())``

Also: structural assertion that worker.main() references "bootstrap" (mirrors
TestEnterpriseCheckWiredIntoLifespan in test_enterprise_overlay_startup_check.py).

References: WORK-03 (parity), WORK-01 (structural wiring), T-1206-06 (drift detection)
"""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import patch

import pytest


def _reset_registry():
    import app.platform.extensions as ext_mod

    ext_mod._extensions.clear()
    ext_mod._routers.clear()
    ext_mod._loaded = False
    ext_mod._slot_owners.clear()


def _reset_edition():
    import app.core.edition as ed_mod

    ed_mod._info = None


@pytest.fixture(autouse=True)
def _clean_state():
    """Reset registry + edition singleton, isolate from discovered entry points."""
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
    """Build a mock entry-point from a loader callable."""
    from unittest.mock import MagicMock

    from app.platform.extensions.version import EXTENSION_API_VERSION

    loader_fn.EXTENSION_API_VERSION = EXTENSION_API_VERSION
    ep = MagicMock()
    ep.name = name
    ep.load.return_value = loader_fn
    return ep


# ---------------------------------------------------------------------------
# Structural: worker.main() and api.main.lifespan both reference "bootstrap"
# ---------------------------------------------------------------------------


class TestBootstrapWiredIntoEntrypoints:
    """Structural regression: both entrypoints delegate to bootstrap() (T-1206-06)."""

    def test_worker_main_references_bootstrap(self):
        """worker.main source must reference 'bootstrap' (WORK-01 drift guard)."""
        from app.platform.jobs import worker as worker_module

        worker_src = inspect.getsource(worker_module.main)
        assert "bootstrap" in worker_src, (
            "WORK-01: worker.main() must call bootstrap() so it loads extensions "
            "and runs the enterprise overlay before run_worker_async. "
            "Without this, the worker runs community code even on licensed enterprise deployments."
        )

    def test_lifespan_references_bootstrap(self):
        """api/main.py lifespan source must reference 'bootstrap' (WORK-01 drift guard)."""
        from app.api import main as main_module

        lifespan_src = inspect.getsource(main_module.lifespan)
        assert "bootstrap" in lifespan_src, (
            "WORK-01: api lifespan must call bootstrap() — the shared extension-load "
            "sequence must not be re-inlined directly in the lifespan."
        )

    def test_lifespan_references_port_assertion(self):
        """api lifespan must run assert_enterprise_ports_resolved() after bootstrap.

        WORK-02: the affirmative port assertion has to run in BOTH entrypoints,
        else a license-key activation with a missing overlay crashes the worker
        while the API keeps serving Default community ports (API-up/worker-down
        split-brain).
        """
        from app.api import main as main_module

        lifespan_src = inspect.getsource(main_module.lifespan)
        assert "assert_enterprise_ports_resolved" in lifespan_src, (
            "WORK-02: api lifespan must call assert_enterprise_ports_resolved() "
            "so the API fails closed on a missing overlay, matching worker.main()."
        )

    def test_worker_main_references_port_assertion(self):
        """worker.main must run assert_enterprise_ports_resolved() (its half of the pair)."""
        from app.platform.jobs import worker as worker_module

        worker_src = inspect.getsource(worker_module.main)
        assert "assert_enterprise_ports_resolved" in worker_src, (
            "WORK-02: worker.main() must call assert_enterprise_ports_resolved()."
        )

    def test_lifespan_does_not_directly_call_load_extensions(self):
        """lifespan must NOT re-inline load_extensions() directly (single source of truth).

        bootstrap() owns the load_extensions call. If lifespan still calls
        load_extensions() directly it has drifted back to two divergent bootstraps.
        """
        from app.api import main as main_module

        lifespan_src = inspect.getsource(main_module.lifespan)
        assert "load_extensions()" not in lifespan_src, (
            "WORK-01: lifespan must not call load_extensions() directly — "
            "bootstrap() is the single source of truth for extension loading."
        )

    def test_worker_init_storage_removed(self):
        """worker.main() must NOT call init_storage() directly (bootstrap owns it).

        Acceptance criterion: grep -c 'init_storage()' worker.py == 0
        """
        from app.platform.jobs import worker as worker_module

        worker_src = inspect.getsource(worker_module.main)
        assert "init_storage()" not in worker_src, (
            "WORK-01: worker.main() must not call init_storage() directly — "
            "bootstrap() is the single source of truth for storage initialization."
        )

    def test_worker_init_cache_removed(self):
        """worker.main() must NOT call init_cache() directly (bootstrap owns it)."""
        from app.platform.jobs import worker as worker_module

        worker_src = inspect.getsource(worker_module.main)
        assert "init_cache()" not in worker_src, (
            "WORK-01: worker.main() must not call init_cache() directly — "
            "bootstrap() owns cache initialization."
        )


# ---------------------------------------------------------------------------
# WORK-03: API vs worker parity — empty-overlay (community) case
# ---------------------------------------------------------------------------


class TestApiWorkerParityCommunity:
    """Both paths yield community + Default* ports on empty overlay."""

    def test_edition_matches_community(self):
        """API-path and worker-path produce the same community edition."""
        from fastapi import FastAPI

        from app.core.edition import get_edition
        from app.platform.extensions import get_catalog_port
        from app.platform.extensions.bootstrap import bootstrap

        # Worker path
        asyncio.run(bootstrap(app=None))
        worker_edition = get_edition().edition
        worker_catalog_cls = type(get_catalog_port()).__name__
        _reset_registry()
        _reset_edition()

        # API path (stub app — billing dispatch is exercised but billing is no-op)
        stub_app = FastAPI()
        asyncio.run(bootstrap(app=stub_app))
        api_edition = get_edition().edition
        api_catalog_cls = type(get_catalog_port()).__name__
        _reset_registry()
        _reset_edition()

        assert worker_edition == api_edition == "community"
        assert worker_catalog_cls == api_catalog_cls == "DefaultCatalogPort"

    def test_processing_port_matches_community(self):
        """Both paths resolve DefaultProcessingPort on empty overlay."""
        from fastapi import FastAPI

        from app.platform.extensions import get_processing_port
        from app.platform.extensions.bootstrap import bootstrap

        asyncio.run(bootstrap(app=None))
        worker_proc_cls = type(get_processing_port()).__name__
        _reset_registry()
        _reset_edition()

        stub_app = FastAPI()
        asyncio.run(bootstrap(app=stub_app))
        api_proc_cls = type(get_processing_port()).__name__

        assert worker_proc_cls == api_proc_cls == "DefaultProcessingPort"


# ---------------------------------------------------------------------------
# WORK-03: API vs worker parity — dummy overlay case
# ---------------------------------------------------------------------------


class TestApiWorkerParityWithDummyOverlay:
    """With the dummy overlay installed, both paths resolve identical edition + port classes."""

    def test_edition_matches_with_dummy_overlay(self):
        """Both API and worker paths resolve the same edition with dummy overlay."""
        from fastapi import FastAPI

        from tests.fixtures.dummy_overlay.overlay import register_extensions as _reg

        mock_ep = _make_mock_ep("dummy_overlay", _reg)

        from app.core.edition import get_edition
        from app.platform.extensions.bootstrap import bootstrap

        # Worker path
        with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
            asyncio.run(bootstrap(app=None))
        worker_edition = get_edition().edition
        _reset_registry()
        _reset_edition()

        # API path
        stub_app = FastAPI()
        with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
            asyncio.run(bootstrap(app=stub_app))
        api_edition = get_edition().edition

        assert worker_edition == api_edition, (
            f"Edition mismatch: worker='{worker_edition}', api='{api_edition}'. "
            "Both entrypoints must produce the same edition for the same env/overlay."
        )

    def test_catalog_port_class_matches_with_dummy_overlay(self):
        """Both paths resolve DummyCatalogPort (not DefaultCatalogPort) with dummy overlay."""
        from fastapi import FastAPI

        from tests.fixtures.dummy_overlay.overlay import register_extensions as _reg

        mock_ep = _make_mock_ep("dummy_overlay", _reg)

        from app.platform.extensions import get_catalog_port
        from app.platform.extensions.bootstrap import bootstrap

        # Worker path
        with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
            asyncio.run(bootstrap(app=None))
        worker_catalog_cls = type(get_catalog_port()).__name__
        _reset_registry()
        _reset_edition()

        # API path
        stub_app = FastAPI()
        with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
            asyncio.run(bootstrap(app=stub_app))
        api_catalog_cls = type(get_catalog_port()).__name__

        assert worker_catalog_cls == api_catalog_cls, (
            f"CatalogPort class mismatch: worker='{worker_catalog_cls}', "
            f"api='{api_catalog_cls}'. Both must resolve the same class."
        )
        # Both must be non-Default
        assert worker_catalog_cls != "DefaultCatalogPort"
        assert api_catalog_cls != "DefaultCatalogPort"

    def test_processing_port_class_matches_with_dummy_overlay(self):
        """ProcessingPort class is identical between API-path and worker-path.

        The dummy overlay only claims catalog_port; both paths should still
        resolve DefaultProcessingPort — the important thing is they agree.
        """
        from fastapi import FastAPI

        from tests.fixtures.dummy_overlay.overlay import register_extensions as _reg

        mock_ep = _make_mock_ep("dummy_overlay", _reg)

        from app.platform.extensions import get_processing_port
        from app.platform.extensions.bootstrap import bootstrap

        # Worker path
        with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
            asyncio.run(bootstrap(app=None))
        worker_proc_cls = type(get_processing_port()).__name__
        _reset_registry()
        _reset_edition()

        # API path
        stub_app = FastAPI()
        with patch("app.platform.extensions.entry_points", return_value=[mock_ep]):
            asyncio.run(bootstrap(app=stub_app))
        api_proc_cls = type(get_processing_port()).__name__

        assert worker_proc_cls == api_proc_cls, (
            f"ProcessingPort class mismatch: worker='{worker_proc_cls}', "
            f"api='{api_proc_cls}'. Both must resolve the same class."
        )
