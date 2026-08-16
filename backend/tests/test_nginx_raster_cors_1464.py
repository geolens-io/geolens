"""Regression coverage for CORS headers on the nginx raster-tile route (#1464).

Raster tiles are served from the app origin at ``/raster-tiles/...`` and never
pass through the api's CORS handling, so the header has to come from nginx.
Two properties matter and neither is visible from a single grep:

* the header must be declared ``always``, because the outcomes that need it
  most are not 200s. Out-of-extent tiles are a 204 from the api, a missing
  dataset is a 404 (#1516), and the ``limit_req`` ceiling is a 503; a plain
  ``add_header`` would skip every one of them and a sparse raster would fail
  CORS on exactly its edge tiles.
* the value must stay the static ``*``, because the route sits behind the
  ``raster_cache`` proxy cache (and a CDN tile cache in the demo), where a
  reflected ``$http_origin`` would be replayed to the wrong origin.

Until #1516 the 204 came from an internal redirect to a ``@empty_tile``
location, which had to repeat the header because nginx emits only the FINAL
location's ``add_header`` set. That redirect is gone: the api answers 204
itself, so the header now reaches every outcome from this one block.
"""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"

RASTER_TILES_LOCATION = r"location\s+~\s+\^/raster-tiles/"

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


def test_raster_cors_header_is_declared_always():
    """A plain add_header would drop the header on 204, 404 and 503.

    Those are the statuses this route actually returns for an out-of-extent
    tile, a missing dataset (#1516) and the rate-limit ceiling. Measured
    against nginx serving this config: all three carry the wildcard.
    """
    conf = _without_comments(NGINX_CONF.read_text())
    block = _location_block(conf, RASTER_TILES_LOCATION)

    plain = re.search(
        r'add_header\s+Access-Control-Allow-Origin\s+"\*"\s*;',
        block,
    )
    assert plain is None, (
        "Access-Control-Allow-Origin must be declared `always`; without it "
        "nginx emits the header on 2xx/3xx only and every empty, missing or "
        "rate-limited tile fails CORS in the browser"
    )
    assert _ACAO_DIRECTIVE.search(block)


def test_raster_cors_header_is_static_never_reflected():
    """A reflected origin is cache-poisonous behind raster_cache and the CDN.

    Scoped to the raster location on purpose. The cache-safety invariant
    belongs to this cached route, and an uncached location elsewhere may have
    good reason to answer a specific origin.
    """
    conf = _without_comments(NGINX_CONF.read_text())
    values = _ANY_ACAO_VALUE.findall(_location_block(conf, RASTER_TILES_LOCATION))

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
