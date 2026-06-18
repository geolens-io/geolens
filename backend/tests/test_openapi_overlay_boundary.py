"""OCG-01: OpenAPI-without-lifespan overlay sentinel.

This module pins the open-core SDK boundary: overlay (cloud/billing/tenant) routers
stay OUT of the published ``@geolens/sdk`` ONLY because ``dump_openapi.py:24-26``
calls ``app.openapi()`` WITHOUT entering the FastAPI lifespan. Overlay routers are
included INSIDE the lifespan via ``bootstrap(app=app)`` → ``app.include_router(...)``.

This implicit, untested contract is the ENTIRE open-core schema boundary.  A future
refactor that moves ``include_router`` to import time (e.g. for eagerness or
discoverability) would silently leak overlay routes + schemas into the published
``openapi.json`` and SDK before any reviewer noticed.

Tests
-----
- ``test_sentinel_absent_without_lifespan``: mirrors ``dump_openapi._load_spec()`` —
  calls ``app.openapi()`` WITHOUT entering the lifespan and asserts the dummy overlay's
  sentinel path (``/__dummy_overlay__/ping``) AND ``DummyOverlayPing`` schema are
  ABSENT from the spec.  This is the green state the public SDK relies on.

- ``test_sentinel_present_after_lifespan_include``: installs the dummy overlay,
  performs the same router-include the lifespan does (``get_extension_routers()`` →
  ``app.include_router(...)``), regenerates the spec, and asserts the sentinel path
  AND schema are now PRESENT.  This proves the mechanism works and the test is not
  vacuously green.

- ``test_regression_intent``: documents (as a runtime assertion) that moving
  ``include_router`` to import time would flip the ABSENT test red — the test is
  the canary.

References: OCG-01, T-1206-07
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_extension_registry():
    """Isolate the extension registry from the environment and reset after each test.

    Patches ``entry_points`` to return empty so no installed enterprise overlay
    (editable-install in the test venv) pollutes the registry.  Mirrors the
    ``_clean_registry`` fixture in ``test_extensions.py``.
    """
    import app.platform.extensions as ext_mod

    ext_mod._extensions.clear()
    ext_mod._loaded = False
    ext_mod._routers.clear()
    ext_mod._slot_owners.clear()

    with patch("app.platform.extensions.entry_points", return_value=[]):
        yield

    # --- teardown ---
    ext_mod._extensions.clear()
    ext_mod._loaded = False
    ext_mod._routers.clear()
    ext_mod._slot_owners.clear()


@pytest.fixture(autouse=True)
def _reset_openapi_schema_cache():
    """Clear FastAPI's cached OpenAPI schema before and after each test.

    ``app.openapi()`` returns ``app.openapi_schema`` if it has been set (FastAPI
    caches after the first call).  Without clearing it, the ABSENT test might
    inadvertently test a cached schema built before the test ran.
    """
    from app.api.main import app

    app.openapi_schema = None
    yield
    # Remove any routes added by the test (uninstall helpers handle registry;
    # this handles the FastAPI router state).
    app.openapi_schema = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_SENTINEL_PATH = "/__dummy_overlay__/ping"
_SENTINEL_SCHEMA = "DummyOverlayPing"
_SENTINEL_OPERATION_ID = "dummy_overlay_ping"


def _get_spec_without_lifespan() -> dict:
    """Mirror ``dump_openapi._load_spec()``: call ``app.openapi()`` with no lifespan.

    This is the exact same call that produces the public ``@geolens/sdk``.  The
    lifespan is never entered, so any router registered inside the lifespan is absent.
    """
    from app.api.main import app

    # Clear the cache so FastAPI regenerates from the current route set.
    app.openapi_schema = None
    return app.openapi()


def _path_present(spec: dict, path: str) -> bool:
    return path in spec.get("paths", {})


def _schema_present(spec: dict, schema_name: str) -> bool:
    return schema_name in spec.get("components", {}).get("schemas", {})


# ---------------------------------------------------------------------------
# OCG-01 sentinel tests
# ---------------------------------------------------------------------------


class TestOpenAPIOverlayBoundary:
    """OCG-01: Sentinel route+schema is ABSENT without lifespan, PRESENT after include."""

    def test_sentinel_absent_without_lifespan(self):
        """ABSENT: the dummy overlay's route and schema do NOT appear in app.openapi().

        This mirrors ``dump_openapi._load_spec()``: we call ``app.openapi()`` WITHOUT
        entering the FastAPI lifespan.  Overlay routers are only included INSIDE the
        lifespan (via ``bootstrap(app=app)``), so the sentinel path and schema must be
        absent from the spec that becomes the public SDK.

        If this test fails, it means an overlay router was included at import time —
        the open-core SDK boundary has been breached.

        References: OCG-01, T-1206-07
        """
        from app.platform.extensions import load_extensions

        # Load extensions so the dummy overlay would register (via entry points) IF any
        # were present — but _clean_extension_registry patches entry_points to empty,
        # so the registry stays clean.  This mirrors the dump_openapi scenario where the
        # overlay package might be installed but is ONLY loaded in the lifespan.
        load_extensions()

        spec = _get_spec_without_lifespan()

        assert not _path_present(spec, _SENTINEL_PATH), (
            f"BREACH: sentinel path '{_SENTINEL_PATH}' appeared in the no-lifespan spec. "
            "An overlay router was included at import time — the open-core boundary is broken. "
            "References: OCG-01, T-1206-07"
        )
        assert not _schema_present(spec, _SENTINEL_SCHEMA), (
            f"BREACH: sentinel schema '{_SENTINEL_SCHEMA}' appeared in the no-lifespan spec. "
            "The DummyOverlayPing model leaked into the public openapi.json. "
            "References: OCG-01, T-1206-07"
        )

    def test_sentinel_present_after_lifespan_include(self):
        """PRESENT: the dummy overlay's route and schema appear after include_router.

        This proves the mechanism is correct and the ABSENT test is not vacuously green:

        1. Install the dummy overlay via the Plan-01 ``install()`` helper (populates
           ``_extensions`` with ``catalog_port`` + adds ``router`` to ``_routers``).
        2. Perform the same router-include the lifespan does:
           ``get_extension_routers()`` → ``app.include_router(...)``.
        3. Clear ``app.openapi_schema`` so FastAPI regenerates from the new route set.
        4. Assert the sentinel path and schema ARE present.

        References: OCG-01, T-1206-07
        """
        import app.platform.extensions as ext_mod
        from app.api.main import app
        from tests.fixtures.dummy_overlay import install, uninstall

        saved = install(ext_mod._extensions)
        # The install() helper calls register_extensions(), which appends to
        # ext_mod._extensions["_routers"] — but load_extensions() moves _routers out
        # of _extensions into ext_mod._routers.  Manually mirror that here:
        overlay_routers = ext_mod._extensions.pop("_routers", [])
        ext_mod._routers.extend(overlay_routers)

        try:
            # Mirror the lifespan's bootstrap(app=app) router-include step:
            #   for ext_router in get_extension_routers():
            #       app.include_router(ext_router)
            for ext_router in ext_mod.get_extension_routers():
                app.include_router(ext_router)

            # Clear the cache so FastAPI regenerates the spec with the new route.
            app.openapi_schema = None
            spec = app.openapi()

            assert _path_present(spec, _SENTINEL_PATH), (
                f"Sentinel path '{_SENTINEL_PATH}' was NOT found in the spec after "
                "include_router — the dummy overlay router was not registered correctly. "
                "References: OCG-01"
            )
            assert _schema_present(spec, _SENTINEL_SCHEMA), (
                f"Sentinel schema '{_SENTINEL_SCHEMA}' was NOT found in the spec after "
                "include_router — the Pydantic model did not appear in components/schemas. "
                "References: OCG-01"
            )

            # Also assert the operation_id is present in the path's operations.
            path_item = spec["paths"][_SENTINEL_PATH]
            operation_ids = [
                op.get("operationId", "")
                for op in path_item.values()
                if isinstance(op, dict)
            ]
            assert _SENTINEL_OPERATION_ID in operation_ids, (
                f"operationId '{_SENTINEL_OPERATION_ID}' not found in the sentinel path item. "
                f"Found: {operation_ids}"
            )

        finally:
            # Teardown: undo the include_router by rebuilding the route list without
            # the dummy overlay routes.  FastAPI does not support removing routes, so
            # we reset openapi_schema — the router object itself stays but _reset_openapi_schema_cache
            # autouse fixture will clear it.  The registry is restored via uninstall().
            app.openapi_schema = None
            ext_mod._routers.clear()
            uninstall(ext_mod._extensions, saved)

    def test_regression_intent(self):
        """Documents that moving include_router to import time would break the boundary.

        This is a static-analysis comment encoded as a runtime assertion.  The assertion
        itself is trivially true (it checks a string constant), but the comment is the
        load-bearing artifact: it tells the next refactorer WHY the ABSENT test exists
        and what would break if they move the include_router call.

        If ``test_sentinel_absent_without_lifespan`` ever starts failing with a message
        about a sentinel path being present in the no-lifespan spec, the cause is almost
        certainly that someone moved an ``app.include_router(overlay_router)`` call from
        inside the lifespan to module level — inadvertently leaking overlay schemas into
        the public SDK.

        References: OCG-01, T-1206-07
        """
        # The open-core SDK boundary is maintained by this invariant:
        #   overlay routers are included ONLY inside the FastAPI lifespan.
        # Moving include_router to import time would:
        #   1. Flip test_sentinel_absent_without_lifespan RED (path appears in spec).
        #   2. Cause dump_openapi.py → openapi.json to contain overlay routes.
        #   3. Cause make sdks-check CI to publish overlay schemas in @geolens/sdk.
        boundary_maintained_by = "lifespan-only include_router"
        assert boundary_maintained_by == "lifespan-only include_router", (
            "This assertion should never fail.  If test_sentinel_absent_without_lifespan "
            "fails, the open-core boundary was broken — see module docstring. OCG-01."
        )


# ---------------------------------------------------------------------------
# OCG-01 extension: cloud control-plane + signup paths must be absent / present
# ---------------------------------------------------------------------------


_CLOUD_CONTROL_PLANE_PATH = "/cloud/control-plane/tenants"
_CLOUD_SIGNUP_PATH = "/cloud/signup/register/"


class TestCloudOpenAPIBoundary:
    """OCG-01 extended: cloud control-plane + signup paths are absent without lifespan.

    The cloud overlay registers its routers via the same lazy lifespan mechanism
    as enterprise overlays (geolens_cloud/__init__.py::_get_routers() → registry
    ["_routers"] list-slot → load_extensions() drains into ext_mod._routers →
    lifespan bootstrap calls app.include_router for each).

    Without lifespan, app.openapi() must NOT contain:
      - /cloud/control-plane/tenants   (CLOUD-02 tenant CRUD routes)
      - /cloud/signup/register/        (CLOUD-03 atomic signup)

    After the lifespan-equivalent include (simulated), both paths MUST be present
    (proves the mechanism is not vacuous — T-1211-18).

    References: OCG-01, T-1211-18, CLOUD-02, CLOUD-03
    """

    def test_cloud_routes_absent_without_lifespan(self):
        """ABSENT: cloud control-plane and signup paths must NOT appear without lifespan.

        Mirrors dump_openapi._load_spec(): we call app.openapi() WITHOUT entering
        the lifespan. Cloud routers are only included INSIDE the lifespan via
        load_extensions() → bootstrap(app=app). They must be absent here.

        If this test fails, a cloud router was included at import time — the
        open-core SDK boundary has been breached (OCG-01, T-1211-18).
        """
        from app.platform.extensions import load_extensions

        # _clean_extension_registry patches entry_points to empty so no installed
        # cloud/enterprise overlay pollutes the registry. This mirrors dump_openapi.
        load_extensions()

        spec = _get_spec_without_lifespan()

        assert not _path_present(spec, _CLOUD_CONTROL_PLANE_PATH), (
            f"BREACH: cloud control-plane path '{_CLOUD_CONTROL_PLANE_PATH}' "
            f"appeared in the no-lifespan spec. A cloud router was included at "
            f"import time — the open-core boundary is broken. "
            f"References: OCG-01, T-1211-18"
        )
        assert not _path_present(spec, _CLOUD_SIGNUP_PATH), (
            f"BREACH: cloud signup path '{_CLOUD_SIGNUP_PATH}' "
            f"appeared in the no-lifespan spec. A cloud router was included at "
            f"import time — the open-core boundary is broken. "
            f"References: OCG-01, T-1211-18"
        )

        # Also assert: no path under /cloud/... at all
        cloud_paths = [p for p in spec.get("paths", {}) if p.startswith("/cloud")]
        assert not cloud_paths, (
            f"Cloud paths appeared in no-lifespan spec: {cloud_paths}. "
            f"Cloud routers must stay out of the public @geolens/sdk (OCG-01)."
        )

    def test_cloud_routes_present_after_lifespan_include(self):
        """PRESENT: cloud control-plane and signup paths appear after include_router.

        Proves the mechanism is correct and test_cloud_routes_absent_without_lifespan
        is not vacuously green:

        1. Install the cloud overlay routers by importing and calling the cloud
           register_extensions function (simulates the lifespan loading the cloud entry point).
        2. Extract the routers from the registry and include them via app.include_router.
        3. Regenerate the spec and assert cloud paths ARE present.

        References: OCG-01, T-1211-18
        """
        from app.api.main import app

        # Clear cache so app.openapi() regenerates from current routes.
        app.openapi_schema = None

        # Install cloud routers by simulating what load_extensions + lifespan do.
        # We bypass entry_points (which is patched to empty by _clean_extension_registry)
        # and directly call the cloud register_extensions function.
        try:
            from geolens_cloud import register_extensions as cloud_register
        except ImportError:
            pytest.skip(
                "geolens_cloud is not installed in the core venv — "
                "run the gate with cloud editable-installed to verify OCG-01 PRESENT test"
            )

        # Call register_extensions on a temporary registry to extract _routers
        tmp_registry: dict = {}
        # Pre-seed with mock slots so wrappers have something to wrap
        tmp_registry["permission"] = MagicMock(name="mock_perm")
        tmp_registry["identity"] = MagicMock(name="mock_identity")
        tmp_registry["processing_port"] = MagicMock(name="mock_processing")
        tmp_registry["catalog_port"] = MagicMock(name="mock_catalog")

        cloud_register(tmp_registry)

        # Extract the routers cloud registered
        cloud_routers = tmp_registry.get("_routers", [])

        if not cloud_routers:
            pytest.skip(
                "Cloud register_extensions returned no routers — nothing to test"
            )

        try:
            for ext_router in cloud_routers:
                app.include_router(ext_router)

            # Regenerate spec with the new routes.
            app.openapi_schema = None
            spec = app.openapi()

            assert _path_present(spec, _CLOUD_CONTROL_PLANE_PATH), (
                f"Cloud control-plane path '{_CLOUD_CONTROL_PLANE_PATH}' NOT found "
                f"in spec after include_router — the cloud router was not registered "
                f"correctly. References: OCG-01"
            )
            assert _path_present(spec, _CLOUD_SIGNUP_PATH), (
                f"Cloud signup path '{_CLOUD_SIGNUP_PATH}' NOT found in spec after "
                f"include_router — the signup router was not registered correctly. "
                f"References: OCG-01"
            )

        finally:
            # Teardown: clear the cached schema so the route addition does not
            # persist to subsequent tests (routes stay on the app object but
            # _reset_openapi_schema_cache autouse fixture clears the cache).
            app.openapi_schema = None
