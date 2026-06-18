"""Reusable in-repo dummy overlay for GeoLens core test suite.

Purpose
-------
This module acts as a minimal, version-declaring overlay that can be:

1. **Imported directly** by test helpers (not installed via entry points).
2. **Monkeypatched** into the live extension registry via ``install()`` / ``uninstall()``
   (mirrors ``conftest.saml_overlay_registered`` save-restore pattern).
3. **Extended** by Phase 1208's in-repo isolation gate (adds a ``tenant_id``
   isolation surface on top of this fixture without modifying it — kept minimal
   and extensible for exactly that reason).

Consumers
---------
- Plan 1206-02 (WORK-03): worker/API parity test — the worker must resolve
  ``DummyCatalogPort`` (not ``DefaultCatalogPort``) after extension load.
- Plan 1206-03 (OCG-01): OpenAPI sentinel — ``DummyOverlayPing`` schema must
  be ABSENT from ``app.openapi()`` without lifespan and PRESENT after include.
- Plan 1206-04 (OCG-04 CI): Docker probe — asserts overlay resolves on both
  api + worker image targets.
- Phase 1208 (GATE-01): in-repo isolation gate — extends this fixture with
  a ``tenant_id`` surface for RLS assertion.

References: OCG-01 (consumer), WORK-03 (consumer), GATE-01/Phase-1208 (future consumer)
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Version coupling (OCG-04)
# ---------------------------------------------------------------------------

# This module-level attribute is read by load_extensions() via
# getattr(loader, "EXTENSION_API_VERSION", None) before invoking the loader.
# It MUST equal the core constant — update together when the contract changes.
from app.platform.extensions.version import EXTENSION_API_VERSION  # noqa: F401

# ---------------------------------------------------------------------------
# Sentinel schema (OCG-01 consumer)
# ---------------------------------------------------------------------------


class DummyOverlayPing(BaseModel):
    """Sentinel Pydantic schema for the dummy overlay route.

    This schema MUST be:
    - ABSENT from ``app.openapi()`` without lifespan extension loading.
    - PRESENT in the OpenAPI output after ``load_extensions()`` + router include.

    Plan 1206-03 asserts both conditions to verify the SDK boundary gate.
    """

    pong: str = "ok"


# ---------------------------------------------------------------------------
# Sentinel router (OCG-01 consumer)
# ---------------------------------------------------------------------------

router = APIRouter(tags=["dummy_overlay"])
"""FastAPI router exposing a single sentinel GET route.

The route path ``/__dummy_overlay__/ping`` and operation_id ``dummy_overlay_ping``
are stable strings that Plan 1206-03's sentinel assertion matches against.
Do NOT rename these without updating that plan's assertion.
"""


@router.get(
    "/__dummy_overlay__/ping",
    response_model=DummyOverlayPing,
    operation_id="dummy_overlay_ping",
    tags=["dummy_overlay"],
    summary="Dummy overlay sentinel ping (test fixture only)",
)
async def dummy_overlay_ping() -> DummyOverlayPing:
    """Sentinel endpoint injected by the dummy overlay during tests.

    MUST NOT appear in the production OpenAPI spec (no real entry-point install).
    """
    return DummyOverlayPing(pong="ok")


# ---------------------------------------------------------------------------
# Single-slot claim: catalog_port (SLOT-01)
# ---------------------------------------------------------------------------


class DummyCatalogPort:
    """Minimal marker class occupying the 'catalog_port' single-slot registry key.

    ``__class__.__name__ == 'DummyCatalogPort'`` is intentionally non-Default so
    tests can assert ``type(get_catalog_port()).__name__ != 'DefaultCatalogPort'``
    after ``install()`` is called. Phase 1208 may subclass this to add a
    ``tenant_id`` assertion surface.
    """

    _sentinel: str = "dummy_overlay_catalog_port"


# ---------------------------------------------------------------------------
# Registry install / uninstall helpers
# ---------------------------------------------------------------------------


def register_extensions(registry: dict) -> None:
    """Populate the extension registry with the dummy overlay's contributions.

    Designed to be called once per load:
    - Claims ``registry["catalog_port"]`` with ``DummyCatalogPort()`` (single-slot).
    - Appends the sentinel router to ``registry["_routers"]`` (additive-slot).

    This function is importable as the entry-point loader callback; it also
    serves as the ``install()`` helper's inner operation.

    References: OCG-01, WORK-03
    """
    registry["catalog_port"] = DummyCatalogPort()
    registry.setdefault("_routers", []).append(router)


def install(registry: dict) -> dict:
    """Install the dummy overlay into ``registry``, returning a saved snapshot.

    Usage in tests::

        saved = install(ext_mod._extensions)
        ext_mod._routers.append(router)  # or install handles it
        try:
            ...your test...
        finally:
            uninstall(registry, saved)

    Mirrors ``conftest.saml_overlay_registered`` save-restore discipline.
    Returns the pre-install snapshot for ``uninstall()``.
    """
    snapshot = dict(registry)
    register_extensions(registry)
    return snapshot


def uninstall(registry: dict, snapshot: dict) -> None:
    """Restore the extension registry to the pre-install snapshot.

    Mirrors ``conftest.saml_overlay_registered`` teardown::

        finally:
            _extensions.clear()
            _extensions.update(saved_ext)

    Parameters
    ----------
    registry:
        The live ``_extensions`` dict to restore.
    snapshot:
        The dict returned by ``install()``.
    """
    registry.clear()
    registry.update(snapshot)
