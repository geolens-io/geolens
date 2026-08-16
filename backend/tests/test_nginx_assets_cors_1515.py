"""Regression coverage for CORS on the hashed-asset route (#1515).

The embed snippet frames ``/m/{token}`` with ``sandbox="allow-scripts"`` and no
``allow-same-origin``, which gives the frame an opaque origin. The shell loads
the app as ``<script type="module" crossorigin>``, so every hashed asset fetch
is CORS-mode and, from an opaque origin, cross-origin. Without an
``Access-Control-Allow-Origin`` header the browser refuses it and the app never
boots.

Two properties, neither visible from a single grep:

* the header has to be on the ``/assets/`` location, not merely somewhere in
  the file; and
* the value has to stay the static ``*`` — these responses are served
  ``immutable`` and sit behind a CDN, so a reflected ``$http_origin`` would be
  cached and replayed to a different origin.
"""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"

ASSETS_LOCATION = r"location\s+/assets/"

_ACAO_DIRECTIVE = re.compile(
    r'add_header\s+Access-Control-Allow-Origin\s+"\*"\s+always\s*;'
)
_ANY_ACAO_VALUE = re.compile(r"add_header\s+Access-Control-Allow-Origin\s+(\S+)")


def _without_comments(text: str) -> str:
    """Drop nginx comment lines so prose can never satisfy an assertion."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _location_block(text: str, header_pattern: str) -> str:
    """Return the body of the first location block whose header matches."""
    match = re.search(header_pattern, text)
    assert match, f"expected a location block matching {header_pattern!r}"
    start = text.index("{", match.start())
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : index]
    raise AssertionError(f"unbalanced braces after {header_pattern!r}")


def test_assets_location_emits_cors_header():
    conf = _without_comments(NGINX_CONF.read_text())
    block = _location_block(conf, ASSETS_LOCATION)

    assert _ACAO_DIRECTIVE.search(block), (
        "the /assets/ location must emit "
        'add_header Access-Control-Allow-Origin "*" always, or an embedded '
        "viewer cannot load its own module graph"
    )


def test_assets_cors_header_is_static_never_reflected():
    """A reflected origin is cache-poisonous on an `immutable` response."""
    conf = _without_comments(NGINX_CONF.read_text())
    values = _ANY_ACAO_VALUE.findall(_location_block(conf, ASSETS_LOCATION))

    assert values, "expected at least one Access-Control-Allow-Origin header"
    for value in values:
        assert value == '"*"', (
            f'Access-Control-Allow-Origin must be the static "*", got {value!r}; '
            "these responses are cached for a year and would be replayed"
        )


def test_assets_location_keeps_the_security_headers():
    """add_header disables inheritance, so this block has to re-declare them.

    The block already carried an add_header (Cache-Control) before #1515, which
    silently dropped the server-scope security headers. Re-declared here now
    that the same responses are readable cross-origin.
    """
    conf = _without_comments(NGINX_CONF.read_text())
    block = _location_block(conf, ASSETS_LOCATION)

    for header, value in (
        ("X-Frame-Options", "SAMEORIGIN"),
        ("X-Content-Type-Options", "nosniff"),
        ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ):
        assert re.search(
            rf'add_header\s+{re.escape(header)}\s+"{re.escape(value)}"\s+always\s*;',
            block,
        ), f"/assets/ must re-declare {header}; add_header disables inheritance"
