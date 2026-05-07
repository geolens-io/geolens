"""SEC-01: SVG icon GET responses carry CSP `default-src 'none'; sandbox`.

Pins the v13.13 closure of M-63. The header isolates uploaded SVGs from
running scripts in the user's auth context (cookies, localStorage) — even if
the upload validator is bypassed by a future regression, browsers honor the
CSP sandbox on image/svg+xml responses.

The strict CSP is set by the route handler (router.py) and the global
SecurityHeadersMiddleware honors a route-level CSP via setdefault semantics
(matching the SEC-13 pattern for Referrer-Policy). Non-icon routes continue
to get the global default `frame-ancestors 'self'`.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.anyio
async def test_builtin_marker_svg_icon_emits_csp_sandbox(client: AsyncClient):
    """The 'marker' built-in icon is SVG; its GET MUST include the strict CSP."""
    resp = await client.get("/maps/icons/builtin:marker/asset")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    assert resp.headers["content-security-policy"] == "default-src 'none'; sandbox"


@pytest.mark.anyio
async def test_builtin_circle_dot_icon_emits_csp_sandbox(client: AsyncClient):
    """The 'circle-dot' built-in icon is SVG; same CSP header expected."""
    resp = await client.get("/maps/icons/builtin:circle-dot/asset")
    assert resp.status_code == 200
    assert resp.headers["content-security-policy"] == "default-src 'none'; sandbox"


@pytest.mark.anyio
async def test_icon_get_preserves_cache_control(client: AsyncClient):
    """The Cache-Control: public, max-age=3600 header MUST still be present."""
    resp = await client.get("/maps/icons/builtin:marker/asset")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "public, max-age=3600"


@pytest.mark.anyio
async def test_csp_header_is_exactly_strict_form(client: AsyncClient):
    """The icon CSP MUST be the exact two-directive sandbox form, not a longer
    policy. The strict form is the only one that disables cookies for SVG
    sandboxing across Chromium and Firefox."""
    resp = await client.get("/maps/icons/builtin:marker/asset")
    csp = resp.headers["content-security-policy"]
    # Exact byte-equality — no extra directives, no different quoting
    assert csp == "default-src 'none'; sandbox", f"unexpected CSP: {csp!r}"


@pytest.mark.anyio
async def test_non_icon_route_keeps_global_csp(client: AsyncClient):
    """Regression: GET /health uses the global frame-ancestors 'self' CSP and
    is NOT affected by the icon-specific override."""
    resp = await client.get("/health")
    # Health endpoint may return 200 or 503 in test env — care only about CSP
    assert resp.headers["content-security-policy"] == "frame-ancestors 'self'"
