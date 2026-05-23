"""Phase 1092 ROUTE-01 regression tests: trailing-slash redirect no-leak invariant.

The FastAPI app default is ``redirect_slashes=True``, which causes any request
to a route registered without a trailing slash (or vice versa) to be answered
with a 307 Temporary Redirect whose ``Location`` header carries the relative
URL of the canonical form. When the app is hosted behind the docker-compose
``api`` service, that relative ``Location`` resolves against the request's
Host header, leaking the in-container hostname ``api:8000`` to any external
caller (curl, SDKs, third-party integrations) that hit the Vite dev proxy.

The fix is the **(c) hybrid** from Phase 1092 CONTEXT.md:
- Disable ``redirect_slashes`` at the FastAPI app level
  (``backend/app/api/main.py``)
- Register both slash and no-slash variants on the two surfaces that were
  leaking — ``/auth/login`` and ``/collections`` — via stacked decorators,
  mirroring the Phase 280 ``catalog/maps/router.py`` pattern.
- Add a Vite dev-proxy ``Location``-header rewrite as defense in depth
  (``frontend/vite.config.ts``).

This test pins the no-leak behavior across the four canonical surfaces plus the
documented ``/collections/datasets`` exception which must remain unchanged.
"""

from __future__ import annotations

from httpx import AsyncClient


class TestRedirectSlashesNoLeak:
    """ROUTE-01 (Phase 1092): both slash and no-slash variants of the two
    previously-leaking surfaces must resolve directly — no 307, no
    ``api:8000`` hostname in any ``Location`` header. The documented
    ``/collections/datasets`` no-slash exception is preserved.

    All tests use ``follow_redirects=False`` so a regression — re-enabling
    ``redirect_slashes`` or removing one of the stacked decorators —
    surfaces as a 307 with the relative ``Location`` header still set,
    not as a silently-followed 200.
    """

    async def test_collections_slash_returns_200_directly(
        self,
        client: AsyncClient,
    ) -> None:
        """``GET /collections/`` resolves directly to 200 — no 307 redirect.

        Reverting the dual-shape decorator on ``list_collections`` OR
        removing ``redirect_slashes=False`` on the app makes this test fail
        with status_code=307 and a ``Location`` header.
        """
        resp = await client.get("/collections/", follow_redirects=False)

        assert resp.status_code != 307, (
            "307 regression: trailing-slash decorator missing on "
            "list_collections OR redirect_slashes still enabled; "
            f"Location={resp.headers.get('location')!r}"
        )
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}; "
            f"location={resp.headers.get('location')!r} body={resp.text[:200]}"
        )
        location = resp.headers.get("location", "")
        assert "api:8000" not in location and "://api/" not in location, (
            f"in-container hostname leak: {location!r}"
        )

    async def test_collections_no_slash_returns_200_directly(
        self,
        client: AsyncClient,
    ) -> None:
        """Canonical no-slash surface preserved: ``GET /collections`` still
        returns 200 directly (the OpenAPI-published form).
        """
        resp = await client.get("/collections", follow_redirects=False)

        assert resp.status_code == 200, (
            f"Expected 200 on canonical no-slash form, got "
            f"{resp.status_code}; location={resp.headers.get('location')!r}"
        )

    async def test_auth_login_slash_returns_correctly_without_leak(
        self,
        client: AsyncClient,
    ) -> None:
        """``POST /auth/login/`` resolves directly — no 307 redirect with
        ``api:8000`` leak. With the wrong credentials the response is
        401/422; with valid credentials it would be 200. Either way the
        contract is "not 307".

        SP-11 (v1009.1) originally pinned the no-trailing-slash-only
        registration because FastAPI's default 307 stripped the POST body
        for OAuth2 form callers. ROUTE-01 closes that gap structurally by
        disabling ``redirect_slashes`` at the app level — both shapes now
        deliver the body straight to the handler.
        """
        resp = await client.post(
            "/auth/login/",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )

        assert resp.status_code != 307, (
            "307 regression: trailing-slash decorator missing on login OR "
            "redirect_slashes still enabled; "
            f"Location={resp.headers.get('location')!r}"
        )
        # 200 = success, 401 = bad creds, 422 = malformed body.
        # All acceptable contracts; 307 is the failure shape.
        assert resp.status_code in (200, 401, 422), (
            f"Expected 200/401/422, got {resp.status_code}; body={resp.text[:200]}"
        )
        location = resp.headers.get("location", "")
        assert "api:8000" not in location and "://api/" not in location, (
            f"in-container hostname leak: {location!r}"
        )

    async def test_auth_login_no_slash_returns_correctly(
        self,
        client: AsyncClient,
    ) -> None:
        """Canonical no-slash surface preserved: ``POST /auth/login`` still
        resolves directly. The OpenAPI-published form.
        """
        resp = await client.post(
            "/auth/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )

        assert resp.status_code in (200, 401, 422), (
            f"Expected 200/401/422 on canonical no-slash form, got "
            f"{resp.status_code}; body={resp.text[:200]}"
        )

    async def test_collections_datasets_no_slash_preserved(
        self,
        client: AsyncClient,
    ) -> None:
        """Documented OGC exception preserved: ``GET /collections/datasets``
        (no trailing slash) still returns 200 directly. The OGC API Features
        catalog endpoint is registered without a trailing slash by design;
        ROUTE-01 must not regress that contract.
        """
        resp = await client.get(
            "/collections/datasets", follow_redirects=False
        )

        assert resp.status_code == 200, (
            f"OGC exception regression: GET /collections/datasets must "
            f"return 200, got {resp.status_code}; "
            f"location={resp.headers.get('location')!r}"
        )


class TestAllTrailingSlashRoutesAcceptBothShapes:
    """ROUTE-01 broad enumeration (Phase 1092 / CR-01 sweep): every route
    registered with a trailing slash in the FastAPI app must ALSO accept
    the no-trailing-slash form. This pins the dual-shape sweep applied
    across 9 router files in this phase's review-fix iteration.

    With ``redirect_slashes=False`` at the app level
    (``backend/app/api/main.py``), routes that only register the
    trailing-slash form silently 404 when the no-slash form is
    requested. Pre-sweep this affected ~28 routes. The sweep adds a
    hidden no-slash alias (``include_in_schema=False``) on every
    trailing-slash-only registered route in ``backend/app/modules/``.

    This test enumerates ``app.routes`` and asserts that for every
    method-path pair where the path ends in ``/`` (except the root path
    ``/``), the same-method registration EXISTS for the no-slash form.

    Routes registered with parameters (e.g.,
    ``/maps/{map_id}/visibility-check/``) are included in the
    enumeration. Routes registered as no-slash only (e.g.
    ``/collections/datasets``) are skipped — they were never
    trailing-slash-eligible and remain no-slash-canonical by design.

    Acceptance: zero misses. Any miss fails with a list of the
    trailing-slash-only registered routes that lack a no-slash sibling.
    """

    async def test_every_trailing_slash_route_has_no_slash_sibling(
        self,
    ) -> None:
        """Enumerate app.routes and assert dual-shape coverage.

        The sweep covers ALL trailing-slash registered routes under
        ``/api/``. Adding a new trailing-slash-only route without a
        sibling will fail this test, surfacing the missing alias.
        """
        from app.api.main import app
        from fastapi.routing import APIRoute

        # Collect (method, path) for every APIRoute.
        registered: set[tuple[str, str]] = set()
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in route.methods:
                if method in ("HEAD", "OPTIONS"):
                    # FastAPI auto-adds HEAD for GET routes; skip noise.
                    continue
                registered.add((method, route.path))

        # For every trailing-slash route (excluding the root ``/``), the
        # no-slash sibling must also be registered for the same method.
        missing: list[tuple[str, str]] = []
        for method, path in sorted(registered):
            if not path.endswith("/") or path == "/":
                continue
            no_slash = path.rstrip("/")
            if (method, no_slash) not in registered:
                missing.append((method, path))

        assert not missing, (
            f"ROUTE-01 dual-shape coverage gap: {len(missing)} "
            f"trailing-slash-only registered route(s) lack a no-slash "
            f"sibling. With redirect_slashes=False these now return 404 "
            f"for callers omitting the slash. Add a stacked decorator "
            f"with ``include_in_schema=False`` for the no-slash form. "
            f"Missing routes:\n"
            + "\n".join(f"  {m} {p}" for m, p in missing[:30])
            + (
                f"\n  ... and {len(missing) - 30} more"
                if len(missing) > 30
                else ""
            )
        )

    async def test_dual_shape_sweep_smoke_routes_no_leak(
        self,
        client: AsyncClient,
    ) -> None:
        """Spot-check that the sweep delivers the no-leak invariant on a
        representative sample of routes from the sweep. Each route is
        probed with BOTH the trailing-slash and no-trailing-slash form
        and we assert (a) the responses are the same status code (no
        404 regression) and (b) neither response leaks ``api:8000`` in
        a Location header.

        Sample is intentionally diverse — auth, settings, admin (writes),
        search (reads), collections (catalog). Routes that require auth
        return 401, routes registered as public return 200 — either way
        the contract is "no 404, no leak, same status both shapes".
        """
        # Format: (method, path) — body omitted, only routing dispatch matters.
        sample = [
            ("GET", "/auth/me"),  # 401 (no token)
            ("GET", "/auth/config"),  # 200 (public)
            ("GET", "/auth/api-keys"),  # 401 (no token)
            ("GET", "/settings/branding"),  # 200 (public)
            ("GET", "/settings/edition"),  # 200 (public)
            ("GET", "/settings/all"),  # 401 (no token)
            ("GET", "/admin/users"),  # 401 (no token)
            ("GET", "/admin/jobs"),  # 401 (no token)
            ("GET", "/search/saved"),  # 401 (no token)
            ("GET", "/search/facets"),  # 200 (public reads)
            ("GET", "/catalog/collections"),  # 401 (no token)
            ("GET", "/datasets"),  # 200 (public reads on this endpoint)
        ]

        mismatches: list[str] = []
        leaks: list[str] = []

        for method, path in sample:
            no_slash = path
            with_slash = path + "/"

            r1 = await client.request(
                method, no_slash, follow_redirects=False
            )
            r2 = await client.request(
                method, with_slash, follow_redirects=False
            )

            # The two responses must have the SAME status code — no
            # 404 regression on the no-slash form, no 307 redirect on
            # the with-slash form.
            if r1.status_code != r2.status_code:
                mismatches.append(
                    f"{method} {path}: no-slash={r1.status_code} "
                    f"with-slash={r2.status_code}"
                )

            # No-leak invariant on both responses.
            for r, label in ((r1, no_slash), (r2, with_slash)):
                loc = r.headers.get("location", "")
                if "api:8000" in loc or "://api/" in loc:
                    leaks.append(f"{method} {label}: {loc!r}")

        assert not mismatches, (
            "ROUTE-01 dual-shape coverage mismatch: at least one route "
            "returns a different status code for the slash vs no-slash "
            "form. With redirect_slashes=False and a missing alias, the "
            "no-slash form returns 404 while the slash form returns the "
            "real status code.\n" + "\n".join(mismatches)
        )
        assert not leaks, (
            "ROUTE-01 no-leak invariant breached: at least one response "
            "carries ``api:8000`` or ``://api/`` in its Location header. "
            "redirect_slashes=False at the app level was supposed to "
            "structurally prevent this.\n" + "\n".join(leaks)
        )
