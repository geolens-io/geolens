"""Regression tests for SEC-020: a real Content-Security-Policy backstops the
JWT-in-localStorage exfil risk if a future XSS lands.

On main the only CSP was `frame-ancestors 'self'` (no script-src/default-src), so
an injected or inline script could run unrestricted and exfiltrate the access +
refresh tokens from the geolens-auth localStorage key. These assert the SPA HTML
now ships a script-src/default-src CSP and that the FOUC script is externalized
(so no inline <script> exists for script-src 'self' to block). Fail on main.

The CSP was verified live against the production build: the app, login, and the
MapLibre map builder (external basemap tiles, web workers, inline styles) all
render with zero CSP violations.
"""

import re

from tests.repo_paths import repo_root

ROOT = repo_root(__file__)
NGINX_CONF = ROOT / "frontend" / "nginx.conf"
INDEX_HTML = ROOT / "frontend" / "index.html"
THEME_INIT = ROOT / "frontend" / "public" / "theme-init.js"

_CSP_RE = re.compile(r'Content-Security-Policy\s+"([^"]+)"')


def test_csp_has_script_and_default_src():
    csps = _CSP_RE.findall(NGINX_CONF.read_text())
    assert csps, (
        "nginx.conf must set a Content-Security-Policy on HTML responses (SEC-020)"
    )
    for csp in csps:
        assert "default-src 'self'" in csp, f"CSP missing default-src 'self': {csp}"
        assert "script-src 'self'" in csp, f"CSP missing script-src 'self': {csp}"
        assert "object-src 'none'" in csp, f"CSP missing object-src 'none': {csp}"
        assert "base-uri 'self'" in csp, f"CSP missing base-uri 'self': {csp}"


def test_main_app_csp_has_frame_ancestors():
    # The main `location /` CSP must include frame-ancestors 'self'; the /m/ embed
    # variant intentionally omits it so per-token cross-origin framing still works.
    csps = _CSP_RE.findall(NGINX_CONF.read_text())
    assert any("frame-ancestors 'self'" in c for c in csps), (
        "the main-app CSP must include frame-ancestors 'self' (SEC-020)"
    )


def test_fouc_script_externalized():
    html = INDEX_HTML.read_text()
    # The FOUC logic must be referenced as an external file (script-src 'self'),
    # and there must be no inline <script> body for the CSP to block.
    assert "/theme-init.js" in html, "index.html must load /theme-init.js (SEC-020)"
    assert not re.search(r"<script>\s*\S", html), (
        "index.html must not contain an inline <script> block (SEC-020 / script-src 'self')"
    )
    assert THEME_INIT.exists(), "frontend/public/theme-init.js must exist"
