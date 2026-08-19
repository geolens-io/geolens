"""The nginx raster-tile cache must not fragment on the upstream ``Vary`` (#1605).

The api's CORS middleware sends ``Vary: Origin`` on every response it touches
(#1602/#1603), and ``/raster-tiles/...`` is proxied to it. nginx honours an
upstream ``Vary`` when it stores a cache entry (the ``Vary`` parameter of
``proxy_ignore_headers`` exists since 1.7.7 precisely because of that), so
``raster_cache`` keeps one copy of the same tile bytes per distinct ``Origin``
request header — a fresh set of tiles for every site that embeds a map.

Nothing about the representation varies by origin: the block answers every
caller with the static ``Access-Control-Allow-Origin: *`` (#1464). So the
correct shape is to ignore the header for caching AND hide it from the client,
and both halves are load-bearing. Measured against nginx 1.31.3 serving a
harness with this exact shape (cache key without the origin, upstream sending
``Vary: Origin`` and a unique body):

* ``proxy_ignore_headers Set-Cookie;`` only — origin A MISS, origin B MISS,
  origin A again HIT. The third request is the control: caching works, and B's
  MISS is fragmentation.
* ``proxy_hide_header Vary;`` only — origin A MISS, origin B MISS, origin A
  again HIT, and no ``Vary`` on the wire. Hiding changes what the client is
  told, not what nginx keys on.
* both — origin A MISS, origins B and C HIT with A's body, no ``Vary`` header.

The assertions are structural (they read the conf) and brace-aware, and they
enumerate every location with a real ``proxy_cache`` rather than naming the
raster route, so a second cached route inherits the requirement instead of
quietly reintroducing the bug.

One directive per block, listing every field. nginx's merge rules for
``proxy_ignore_headers`` were measured too, because they are not symmetric:
two directives at the SAME level accumulate (``Vary`` stayed ignored with a
later ``Set-Cookie`` directive after it), but a directive in a location
REPLACES the value inherited from ``http``/``server`` (a location declaring
only ``Set-Cookie`` under an http-level ``Vary`` went back to MISS/MISS, while
a sibling location with no directive at all kept the HIT). The directive in a
block is therefore the whole set for that block, and splitting it across lines
hides that.
"""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"

RASTER_TILES_LOCATION = r"location\s+~\s+\^/raster-tiles/"

# `proxy_cache off;` disables caching, so it is not a cached location.
_ENABLED_PROXY_CACHE = re.compile(r"^\s*proxy_cache\s+(?!off\s*;)(\S+)\s*;", re.M)
_IGNORE_HEADERS = re.compile(r"^\s*proxy_ignore_headers\s+([^;]+);", re.M)
_HIDE_VARY = re.compile(r"^\s*proxy_hide_header\s+Vary\s*;", re.M)
_LOCATION_HEADER = re.compile(r"^[ \t]*location\b[^\n{]*\{", re.M)


def _without_comments(text: str) -> str:
    """Drop nginx comment lines so prose can never satisfy an assertion."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _balanced_body(text: str, brace_index: int) -> str:
    """Return the body between ``text[brace_index]`` and its matching brace."""
    depth = 0
    for index in range(brace_index, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_index + 1 : index]
    raise AssertionError(f"unbalanced braces at offset {brace_index}")


def _location_block(text: str, header_pattern: str) -> str:
    """Return the body of the first location block whose header matches."""
    match = re.search(header_pattern, text)
    assert match, f"expected a location block matching {header_pattern!r}"
    return _balanced_body(text, text.index("{", match.start()))


def _own_directives(body: str) -> str:
    """``body`` with any nested ``location { ... }`` blocks removed.

    Directives in a nested location belong to that location, not to this one:
    ``location /api/`` contains the export sub-location, and counting through
    it would attribute the child's directives to the parent.
    """
    out = body
    while True:
        match = _LOCATION_HEADER.search(out)
        if match is None:
            return out
        start = out.index("{", match.start())
        end = start + len(_balanced_body(out, start)) + 2
        out = out[: match.start()] + out[end:]


def _cached_locations(text: str) -> list[tuple[str, str]]:
    """Every ``location`` whose own directives enable a proxy cache."""
    found: list[tuple[str, str]] = []
    for match in _LOCATION_HEADER.finditer(text):
        header = match.group(0).rstrip("{").strip()
        body = _own_directives(_balanced_body(text, text.index("{", match.start())))
        if _ENABLED_PROXY_CACHE.search(body):
            found.append((header, body))
    return found


def _ignored_fields(body: str) -> list[list[str]]:
    """The field lists of each ``proxy_ignore_headers`` directive in ``body``."""
    return [match.group(1).split() for match in _IGNORE_HEADERS.finditer(body)]


def test_every_cached_location_ignores_and_hides_vary():
    """The property belongs to caching, not to the raster route by name."""
    conf = _without_comments(NGINX_CONF.read_text())
    cached = _cached_locations(conf)

    assert cached, "expected at least one location with a proxy_cache"
    for header, body in cached:
        directives = _ignored_fields(body)
        assert len(directives) == 1, (
            f"{header}: expected exactly one proxy_ignore_headers directive, "
            f"found {len(directives)}. A location's directive replaces, and is "
            "never merged with, the value inherited from http/server scope, so "
            "the one line is the complete set for this block."
        )
        assert "Vary" in directives[0], (
            f"{header}: proxy_ignore_headers must list Vary. The api sends "
            "`Vary: Origin` on every response, and nginx keys a cache entry on "
            "the upstream Vary, so this cache would keep one copy of each tile "
            "per embedding origin."
        )
        assert _HIDE_VARY.search(body), (
            f"{header}: must also `proxy_hide_header Vary;`. Ignoring it for "
            "caching without hiding it leaves clients told about a variance "
            "this route does not serve — one representation reaches every "
            "origin."
        )


def test_raster_tiles_still_ignores_set_cookie():
    """Adding Vary must not drop the field that was already there.

    An upstream ``Set-Cookie`` makes nginx skip caching the response outright,
    so losing this field would silently turn the tile cache off rather than
    fail anything.
    """
    conf = _without_comments(NGINX_CONF.read_text())
    block = _location_block(conf, RASTER_TILES_LOCATION)
    directives = _ignored_fields(block)

    assert directives, "the /raster-tiles/ location must ignore upstream headers"
    assert set(directives[0]) >= {"Set-Cookie", "Vary"}, (
        "the /raster-tiles/ proxy_ignore_headers must list both Set-Cookie and "
        f"Vary, got {directives[0]}"
    )


def test_hiding_vary_without_ignoring_it_fails():
    """Counterfactual for the half that is easy to mistake for the whole fix.

    ``proxy_hide_header`` only changes the response the client sees; nginx
    still stores one entry per ``Origin``. Measured: hide-only answered origin
    B with a MISS and a second upstream fetch.
    """
    conf = _without_comments(NGINX_CONF.read_text())
    hide_only = conf.replace(
        "proxy_ignore_headers Set-Cookie Vary;", "proxy_ignore_headers Set-Cookie;"
    )

    assert hide_only != conf, "the conf no longer ignores Vary in one directive"
    assert _HIDE_VARY.search(_location_block(hide_only, RASTER_TILES_LOCATION))
    for _, body in _cached_locations(hide_only):
        assert "Vary" not in _ignored_fields(body)[0]


def test_ignoring_vary_without_hiding_it_fails():
    """Counterfactual for the other half: the client must not be told of a
    variance nginx does not serve."""
    conf = _without_comments(NGINX_CONF.read_text())
    ignore_only = re.sub(r"^\s*proxy_hide_header\s+Vary\s*;\n", "", conf, flags=re.M)

    assert ignore_only != conf, "the conf no longer hides the upstream Vary"
    for _, body in _cached_locations(ignore_only):
        assert "Vary" in _ignored_fields(body)[0]
        assert not _HIDE_VARY.search(body)


def test_splitting_the_directive_in_two_fails():
    """Counterfactual for the single-directive rule."""
    conf = _without_comments(NGINX_CONF.read_text())
    split = conf.replace(
        "proxy_ignore_headers Set-Cookie Vary;",
        "proxy_ignore_headers Set-Cookie;\n        proxy_ignore_headers Vary;",
    )

    assert split != conf
    block = _location_block(split, RASTER_TILES_LOCATION)
    assert len(_ignored_fields(block)) == 2


def test_nested_locations_are_not_counted_as_the_parents_directives():
    """Counterfactual for the block parser: a directive inside a nested
    location must not be attributed to the location that contains it."""
    conf = _without_comments(NGINX_CONF.read_text())
    api_block = _location_block(conf, r"location\s+/api/\s*\{")

    assert "location ~ ^/api/datasets/" in api_block, (
        "expected the /api/ block to still contain a nested location"
    )
    assert "gzip off;" not in _own_directives(api_block), (
        "the nested location's directives leaked into the parent's own set"
    )
