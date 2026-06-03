"""SEC-13: OAuth callback responses set Referrer-Policy: no-referrer.

Pins the v13.13 closure of L-67. The redirect URL fragment carries access +
refresh tokens; the request URL carries the IdP authorization code. Both
must not leak via Referer header to assets loaded on the post-redirect page.

Implementation notes:

* SecurityHeadersMiddleware.dispatch (`backend/app/api/middleware/security.py`)
  was updated to use `setdefault`-style semantics: only set Referrer-Policy on
  the response when the route did not already set one. This keeps the global
  `strict-origin-when-cross-origin` default for non-OAuth routes intact while
  letting OAuth callback routes override it with `no-referrer`.
* The 3 RedirectResponse sites in `app.modules.auth.oauth.router.oauth_callback`
  (success, email-not-verified, generic-error) all carry
  `headers={"Referrer-Policy": "no-referrer"}`.

These tests run without the autouse DB session fixture by using the
`fastapi.testclient.TestClient` directly with patched dependencies — they
verify response headers only.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def oauth_test_client():
    """Lightweight TestClient that does not require DB-fixture setup.

    Skips the FastAPI lifespan context (DB health check + migrations) by
    constructing TestClient WITHOUT a `with` block — Starlette's TestClient
    only triggers lifespan startup/shutdown when used as a context manager.
    The `oauth_callback` handler's `get_db` dependency is overridden with a
    no-op async generator so the route reaches the patched
    `build_oauth_client` site without touching the real engine.
    """
    from app.api.main import app
    from app.core.dependencies import get_db

    async def _noop_get_db():
        yield None  # type: ignore[misc]

    original_overrides = dict(app.dependency_overrides)
    app.dependency_overrides[get_db] = _noop_get_db
    tc = TestClient(app)  # NOTE: no `with` — skip lifespan
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(original_overrides)


def test_oauth_callback_failure_sets_referrer_policy(oauth_test_client: TestClient):
    """The generic-error redirect path emits Referrer-Policy: no-referrer.

    Patch `build_oauth_client` to raise a synthetic exception, forcing the
    generic-error branch (line 220 area in router.py). The response must be
    a 302 redirect with `Referrer-Policy: no-referrer` in the headers.
    """
    with (
        patch(
            "app.modules.auth.oauth.router.build_oauth_client",
            side_effect=Exception("synthetic failure"),
        ),
        patch(
            "app.modules.auth.oauth.router.get_public_app_url",
            new=AsyncMock(return_value="https://app.example.com"),
        ),
    ):
        resp = oauth_test_client.get(
            "/auth/oauth/google/callback?code=abc&state=xyz",
            follow_redirects=False,
        )

    assert resp.status_code == 302, (
        f"expected 302 redirect on synthetic-failure path, got {resp.status_code}: "
        f"{resp.text[:200]}"
    )
    assert resp.headers.get("referrer-policy") == "no-referrer", (
        f"OAuth error-redirect Referrer-Policy was {resp.headers.get('referrer-policy')!r}; "
        f"expected 'no-referrer'."
    )


def test_global_referrer_policy_unchanged_on_health(oauth_test_client: TestClient):
    """The global Referrer-Policy on non-OAuth routes is unchanged.

    Confirms the SEC-13 setdefault semantics in SecurityHeadersMiddleware
    do NOT regress the global default — non-OAuth routes still receive
    `strict-origin-when-cross-origin` from the middleware.
    """
    resp = oauth_test_client.get("/health")
    # /health may be 200 or 503 depending on DB reachability, but
    # the security headers are set unconditionally by the middleware.
    assert resp.headers.get("referrer-policy") == "strict-origin-when-cross-origin", (
        f"non-OAuth route referrer-policy was {resp.headers.get('referrer-policy')!r}; "
        f"expected 'strict-origin-when-cross-origin'."
    )


def test_oauth_callback_response_has_explicit_no_referrer(
    oauth_test_client: TestClient,
):
    """Sanity: SecurityHeadersMiddleware no longer overwrites the route-set value.

    Pre-SEC-13 the middleware unconditionally set `Referrer-Policy:
    strict-origin-when-cross-origin`, which would have overwritten any
    route-level header. After SEC-13 the middleware uses setdefault semantics,
    so the route's `no-referrer` survives. This test pins that behavior.
    """
    with (
        patch(
            "app.modules.auth.oauth.router.build_oauth_client",
            side_effect=Exception("synthetic"),
        ),
        patch(
            "app.modules.auth.oauth.router.get_public_app_url",
            new=AsyncMock(return_value="https://app.example.com"),
        ),
    ):
        resp = oauth_test_client.get(
            "/auth/oauth/google/callback?code=abc&state=xyz",
            follow_redirects=False,
        )
    assert resp.headers.get("referrer-policy") == "no-referrer", (
        f"OAuth callback Referrer-Policy was {resp.headers.get('referrer-policy')!r}; "
        f"the SecurityHeadersMiddleware likely overwrote the route-level header. "
        f"Confirm SecurityHeadersMiddleware.dispatch uses setdefault semantics for "
        f"Referrer-Policy."
    )
