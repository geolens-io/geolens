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
