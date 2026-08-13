"""Regression coverage for CORS headers on the nginx raster-tile route (#1464).

Raster tiles are served from the app origin at ``/raster-tiles/...`` and never
pass through the api's CORS handling, so the header has to come from nginx.
Two properties matter and neither is visible from a single grep:

* the header must reach the ``@empty_tile`` fallback as well, because
  ``error_page 404 = @empty_tile`` internal-redirects and nginx then emits only
  the FINAL location's ``add_header`` set; and
* the value must stay the static ``*``, because the route sits behind the
  ``raster_cache`` proxy cache (and a CDN tile cache in the demo), where a
  reflected ``$http_origin`` would be replayed to the wrong origin.
"""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"

RASTER_TILES_LOCATION = r"location\s+~\s+\^/raster-tiles/"
EMPTY_TILE_LOCATION = r"location\s+@empty_tile\b"

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


def test_raster_tiles_location_emits_cors_header():
    conf = _without_comments(NGINX_CONF.read_text())
    block = _location_block(conf, RASTER_TILES_LOCATION)

    assert _ACAO_DIRECTIVE.search(block), (
        "the /raster-tiles/ location must emit "
        'add_header Access-Control-Allow-Origin "*" always'
    )


def test_empty_tile_fallback_repeats_the_cors_header():
    """Out-of-extent tiles 404 upstream and are served from @empty_tile.

    nginx emits the add_header set of the location that finally handles the
    request, so the header on the /raster-tiles/ block does not survive the
    internal redirect. Without this, sparse rasters fail CORS on every edge tile.
    """
    conf = _without_comments(NGINX_CONF.read_text())
    block = _location_block(conf, EMPTY_TILE_LOCATION)

    assert _ACAO_DIRECTIVE.search(block), (
        "@empty_tile must repeat the CORS header; add_header sets are not "
        "inherited across the error_page internal redirect"
    )


def test_raster_cors_header_is_static_never_reflected():
    """A reflected origin is cache-poisonous behind raster_cache and the CDN."""
    conf = _without_comments(NGINX_CONF.read_text())
    values = _ANY_ACAO_VALUE.findall(conf)

    assert values, "expected at least one Access-Control-Allow-Origin header"
    for value in values:
        assert value == '"*"', (
            f'Access-Control-Allow-Origin must be the static "*", got {value!r}; '
            "a per-origin value would be cached and replayed to other origins"
        )


def test_raster_tiles_hides_upstream_cors_header():
    """add_header appends, so a duplicate wildcard would break CORS outright."""
    conf = _without_comments(NGINX_CONF.read_text())
    block = _location_block(conf, RASTER_TILES_LOCATION)

    assert re.search(r"proxy_hide_header\s+Access-Control-Allow-Origin\s*;", block), (
        "the /raster-tiles/ location must hide any upstream "
        "Access-Control-Allow-Origin so exactly one value is emitted"
    )
