"""Both spellings of the raster tile route are rate limited, from one bucket (#1778).

nginx defines a single ``limit_req_zone`` (``raster_anon``) and it used to be
applied in a single place: the ``/raster-tiles/...`` location, which rewrites to
``/tiles/raster-proxy/$dataset_id/$z/$x/$y.$fmt`` and proxies that to the api.
The api mounts the tiles router at ``/tiles``, and ``location /api/`` rewrites
``^/api/(.*)`` to ``/$1``, so asking for ``/api/tiles/raster-proxy/...`` reaches
the identical handler with no ``limit_req`` at the edge, no ``@limiter.limit``
at the app (the handler is ``@limiter.exempt``) and no ``proxy_cache``: every
request a live Titiler COG read. The rate limit was opt-in by URL spelling, and
only the product's own clients ever used the spelling that opts in.

Measured against nginx 1.29 (alpine) with this file rendered, the upstream
pointed at a closed port so a proxied request answers 502 and a refused one
answers 503, and the zone temporarily narrowed to 1r/m with no burst:

* without the nested location: ``/api/tiles/raster-proxy/...`` answered 502,
  502, 502, and a following ``/raster-tiles/...`` answered 502 as well. Not
  limited, and not even drawing on the other spelling's bucket.
* with it: ``/api/tiles/raster-proxy/...`` answered 502 then 503, ``/api/health``
  answered 502 twice (the outer block stays unlimited), and ``/raster-tiles/...``
  answered 503 on its first request, which is the shared-bucket half: the tokens
  had already been spent under the other spelling.

The assertions below are structural. They resolve a sample URL through nginx's
own location-selection rules and ask what the SELECTED block does, rather than
naming the block, so a third route reaching the same handler inherits the
requirement instead of quietly reintroducing the bypass.
"""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"

# The path an attacker types. Whatever serves it must be throttled.
API_SPELLING = "/api/tiles/raster-proxy/00000000-0000-0000-0000-000000000000/1/2/3.png"
# The path the product mints, already covered before this change.
EDGE_SPELLING = "/raster-tiles/00000000-0000-0000-0000-000000000000/tiles/1/2/3.png"
# The control: an ordinary api route, which must stay off the tile budget.
UNRELATED_API_PATH = "/api/health"

_LOCATION_HEADER = re.compile(r"^[ \t]*location\b([^\n{]*)\{", re.M)
_LIMIT_REQ = re.compile(r"^\s*limit_req\s+zone=(\w+)", re.M)
_ZONE_DECL = re.compile(r"^\s*limit_req_zone\s+\S+\s+zone=(\w+):", re.M)


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


class _Location:
    """One ``location`` block: its header, its own directives, its children."""

    def __init__(self, header: str, body: str) -> None:
        parts = header.split()
        self.header = header
        self.modifier = parts[0] if parts and parts[0] in ("=", "~", "~*", "^~") else ""
        self.pattern = parts[1] if self.modifier else (parts[0] if parts else "")
        self.children = _parse_locations(body)
        self.own = body
        for child in self.children:
            start = self.own.index("{", self.own.index(f"location{child.header}"))
            end = start + len(_balanced_body(self.own, start)) + 1
            head = self.own.index(f"location{child.header}")
            self.own = self.own[:head] + self.own[end:]

    def matches(self, path: str) -> bool:
        if self.modifier == "=":
            return path == self.pattern
        if self.modifier in ("~", "~*"):
            # PCRE spells a named group `(?<name>...)`; Python spells it
            # `(?P<name>...)`. The raster-tiles location uses four of them.
            pattern = self.pattern.replace("(?<", "(?P<")
            flags = re.I if self.modifier == "~*" else 0
            return re.search(pattern, path, flags) is not None
        if self.pattern.startswith("@"):
            return False  # named location, reachable only by internal redirect
        return path.startswith(self.pattern)


def _parse_locations(text: str) -> list[_Location]:
    """Top-level ``location`` blocks of ``text``, each with its own children."""
    found: list[_Location] = []
    index = 0
    while True:
        match = _LOCATION_HEADER.search(text, index)
        if match is None:
            return found
        brace = text.index("{", match.start())
        body = _balanced_body(text, brace)
        found.append(_Location(match.group(1), body))
        index = brace + len(body) + 2


def _select(locations: list[_Location], path: str) -> _Location | None:
    """The block nginx would serve ``path`` from, by nginx's own rules.

    Exact match wins outright; otherwise the longest prefix is remembered and
    the regexes are tried in order, with ``^~`` on the winning prefix skipping
    them. The selected block's own children are then resolved the same way, and
    a block with no matching child serves the request itself.
    """
    candidates = [loc for loc in locations if loc.matches(path)]
    for loc in candidates:
        if loc.modifier == "=":
            return loc
    prefixes = [loc for loc in candidates if loc.modifier in ("", "^~")]
    best_prefix = max(prefixes, key=lambda loc: len(loc.pattern), default=None)
    chosen = best_prefix
    if best_prefix is None or best_prefix.modifier != "^~":
        for loc in candidates:
            if loc.modifier in ("~", "~*"):
                chosen = loc
                break
    if chosen is None:
        return None
    return _select(chosen.children, path) or chosen


def _tree() -> list[_Location]:
    return _parse_locations(_without_comments(NGINX_CONF.read_text()))


def test_the_api_spelling_of_the_raster_proxy_is_rate_limited():
    """Whatever nginx selects for the /api/ spelling must carry limit_req."""
    served_by = _select(_tree(), API_SPELLING)
    assert served_by is not None, f"no location matches {API_SPELLING}"
    assert _LIMIT_REQ.search(served_by.own), (
        f"{API_SPELLING} is served by `location{served_by.header}`, which "
        "declares no limit_req. That URL reaches the same api handler as the "
        "throttled /raster-tiles/ spelling, so leaving it unthrottled makes the "
        "rate limit opt-in by URL spelling."
    )


def test_both_spellings_draw_on_the_same_zone():
    """One zone, so switching spelling mid-flood buys no fresh allowance."""
    tree = _tree()
    zones = {}
    for path in (API_SPELLING, EDGE_SPELLING):
        selected = _select(tree, path)
        assert selected is not None, path
        zones[path] = set(_LIMIT_REQ.findall(selected.own))
    assert zones[API_SPELLING] and zones[EDGE_SPELLING], zones
    assert zones[API_SPELLING] == zones[EDGE_SPELLING], (
        "the two spellings of one handler must share a limit_req zone, or a "
        f"caller doubles their budget by alternating between them: {zones}"
    )
    declared = set(_ZONE_DECL.findall(_without_comments(NGINX_CONF.read_text())))
    assert zones[API_SPELLING] <= declared, (
        f"limit_req names a zone with no limit_req_zone declaration: {zones}"
    )


def test_ordinary_api_routes_are_not_pulled_onto_the_tile_budget():
    """The control, and the reason the block is nested rather than widened.

    ``raster_anon`` is sized for tiles. Applying it to ``location /api/`` as a
    whole would put login, search and the admin UI on a budget shaped by how
    many tiles a tilted 3D view cold-starts with.
    """
    selected = _select(_tree(), UNRELATED_API_PATH)
    assert selected is not None
    assert not _LIMIT_REQ.search(selected.own), (
        f"{UNRELATED_API_PATH} is served by `location{selected.header}`, which "
        "now carries a limit_req. The tile zone must not govern general api "
        "traffic."
    )


def test_the_nested_location_restates_what_nginx_does_not_inherit():
    """``proxy_pass``, ``rewrite`` and ``set`` do not reach a nested location.

    A nested block that omits them stops proxying to the api entirely, which
    would turn this fix into a broken route rather than a throttled one. The
    inheritable directives (``proxy_cache off``, the timeouts, the forwarded
    headers) are deliberately NOT restated, so this test also records which
    half is which. Measured: a 502 from this block and a 502 from
    ``/api/health`` carry byte-identical header sets.
    """
    served_by = _select(_tree(), API_SPELLING)
    assert served_by is not None
    for directive in ("set $upstream_api", "rewrite ^/api/(.*)", "proxy_pass"):
        assert directive in served_by.own, (
            f"{directive!r} is missing. nginx does not inherit it into a nested "
            "location, so without it this block answers something other than "
            "the api's raster tile."
        )
    for inherited in ("proxy_cache", "add_header", "proxy_hide_header"):
        assert inherited not in served_by.own, (
            f"{inherited!r} is restated here. It is inherited from location "
            "/api/, and declaring add_header or proxy_hide_header at this level "
            "disables inheritance of the whole set rather than adding to it."
        )
