"""Regression tests: a real Content-Security-Policy backstops the
JWT-in-localStorage exfil risk if a future XSS lands.

On main the only CSP was `frame-ancestors 'self'` (no script-src/default-src), so
an injected or inline script could run unrestricted and exfiltrate the access +
refresh tokens from the geolens-auth localStorage key. These assert the SPA HTML
now ships a script-src/default-src CSP and that the FOUC script is externalized
(so no inline <script> exists for script-src 'self' to block). Fail on main.

fix(#1302): the refresh token has since moved out of localStorage into an
httpOnly cookie, so the exfil surface described above is now the access token
alone. The CSP assertions here are unchanged and still load-bearing.

The CSP was verified live against the production build: the app, login, and the
MapLibre map builder (external basemap tiles, web workers, inline styles) all
render with zero CSP violations.
"""

import os
import re
import shutil
import subprocess

import pytest

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


def test_csp_restricts_form_action():
    csps = _CSP_RE.findall(NGINX_CONF.read_text())
    assert csps
    for csp in csps:
        assert "form-action 'self'" in csp, f"CSP missing form-action 'self': {csp}"


def test_env_config_and_raster_tiles_restate_security_headers():
    conf = NGINX_CONF.read_text()
    for opener in (
        "location = /env-config.js {",
        "location ~ ^/raster-tiles/",
    ):
        start = conf.index(opener)
        block = conf[start : conf.index("\n    }\n", start)]
        for header in ("X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy"):
            assert f"add_header {header} " in block, f"{opener} drops {header}"


def test_raster_tiles_hides_upstream_frame_options():
    conf = NGINX_CONF.read_text()
    start = conf.index("location ~ ^/raster-tiles/")
    block = conf[start : conf.index("\n    }\n", start)]
    assert "proxy_hide_header X-Frame-Options;" in block


_ENTRYPOINT = ROOT / "frontend" / "docker-entrypoint.sh"
_BEACON = "https://static.cloudflareinsights.com/beacon.min.js"


def _render_script_src(extra):
    """Run the entrypoint's CSP section, then envsubst the real template."""
    text = _ENTRYPOINT.read_text()
    section = (
        "CSP_SCRIPT_SRC_EXTRA="
        + text.split("\nCSP_SCRIPT_SRC_EXTRA=", 1)[1].split("\nexport API_UPSTREAM", 1)[
            0
        ]
    )
    env = {k: v for k, v in os.environ.items() if k != "CSP_SCRIPT_SRC_EXTRA"}
    if extra is not None:
        env["CSP_SCRIPT_SRC_EXTRA"] = extra
    result = subprocess.run(
        ["sh", "-c", "set -e\n" + section + "\nprintf '%s' \"$CSP_SCRIPT_SRC_EXTRA\""],
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return result, None
    # A file on stdin always reaches EOF; a pipe stalled envsubst under xdist.
    with NGINX_CONF.open() as template:
        rendered = subprocess.run(
            ["envsubst", "$CSP_SCRIPT_SRC_EXTRA"],
            stdin=template,
            env={**env, "CSP_SCRIPT_SRC_EXTRA": result.stdout},
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
    return result, rendered


needs_envsubst = pytest.mark.skipif(
    shutil.which("envsubst") is None, reason="envsubst not installed"
)


@needs_envsubst
def test_script_src_has_no_third_party_host_by_default():
    result, rendered = _render_script_src(None)
    assert result.returncode == 0
    assert "cloudflareinsights" not in rendered
    csps = _CSP_RE.findall(rendered)
    assert len(csps) == 2
    for csp in csps:
        assert "script-src 'self' 'wasm-unsafe-eval'; style-src" in csp


@needs_envsubst
def test_script_src_extra_lands_in_both_policies():
    result, rendered = _render_script_src(_BEACON)
    assert result.returncode == 0
    csps = _CSP_RE.findall(rendered)
    assert len(csps) == 2
    for csp in csps:
        assert f"script-src 'self' 'wasm-unsafe-eval' {_BEACON}; style-src" in csp


@pytest.mark.parametrize(
    "value",
    [
        'https://a.example"; x',
        "https://a.example; img-src *",
        "a,b",
        "$HOME",
        "a\\b",
        "a\nb",
    ],
)
def test_script_src_extra_rejects_characters_outside_a_source_list(value):
    result, _ = _render_script_src(value)
    assert result.returncode != 0
    assert "CSP_SCRIPT_SRC_EXTRA" in result.stderr
