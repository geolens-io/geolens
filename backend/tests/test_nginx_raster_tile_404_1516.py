"""The public raster-tile route must not turn a 404 into an empty tile (#1516).

``/raster-tiles/{id}/tiles/{z}/{x}/{y}.{fmt}`` and
``/api/tiles/raster-proxy/{id}/{z}/{x}/{y}.{fmt}`` serve the same tile from the
same handler, and the public one is what dataset metadata, saved-map styles and
search results hand to clients. While nginx carried
``proxy_intercept_errors on; error_page 404 = @empty_tile;`` they disagreed on
the one case that matters: a dataset id that does not exist answered 204 on the
public route and 404 on the api one, so a typo'd id rendered as a blank map with
nothing anywhere to report.

The mapping was added when a tile outside the raster's extent 404'd upstream.
``raster_tile_proxy`` converts Titiler's out-of-bounds 404 into a 204 itself
now, so it no longer catches that case, and the only 404s left to catch are
genuine. Measured against the api: in-footprint 200, out-of-extent 204, missing
dataset 404, private-and-anonymous 401.

This file is a text check on the config. The behaviour was verified by running
nginx over it against the dev api.
"""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"

RASTER_TILES_LOCATION = r"location\s+~\s+\^/raster-tiles/"


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


def test_raster_tiles_does_not_map_404_to_an_empty_tile():
    conf = _without_comments(NGINX_CONF.read_text())
    block = _location_block(conf, RASTER_TILES_LOCATION)

    assert not re.search(r"\berror_page\s+404\b", block), (
        "the /raster-tiles/ location must let a genuine upstream 404 through; "
        "mapping it to an empty tile makes a missing dataset indistinguishable "
        "from a tile outside the extent, which the api already answers 204"
    )


def test_raster_tiles_does_not_intercept_upstream_errors():
    """`proxy_intercept_errors` is inert with no error_page, so it should go.

    Left behind it reads as an active policy and invites the next reader to
    re-add an error_page for a case the api already handles.
    """
    conf = _without_comments(NGINX_CONF.read_text())
    block = _location_block(conf, RASTER_TILES_LOCATION)

    assert not re.search(r"\bproxy_intercept_errors\s+on\b", block), (
        "the /raster-tiles/ location should pass upstream statuses through"
    )


def test_no_empty_tile_location_remains():
    """The named location was reachable only through that error_page.

    A location nothing routes to is not a fallback, it is a comment that looks
    like one. The CORS header it repeated for #1464 now comes from the
    /raster-tiles/ block's own `always` declaration, which reaches the 204 the
    api returns directly.
    """
    conf = _without_comments(NGINX_CONF.read_text())

    assert not re.search(r"@empty_tile", conf), (
        "@empty_tile is unreachable once the error_page mapping is gone; "
        "delete it rather than leaving a guard wired to nothing"
    )
