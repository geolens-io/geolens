"""The raster tile cache key must not vary on an arg the active stretch mode
ignores (#1778, codebase audit 2026-08-30).

frontend/nginx.conf's raster_cache proxy_cache_key used to hold
$arg_pmin/$arg_pmax/$arg_sigma unconditionally. In
backend/app/processing/tiles/router.py, stretch=percentile is the only mode
that reads pmin/pmax (_compute_stretch_rescale) and stretch=stddev is the only
mode that reads sigma; stretch=minmax (the default) or an absent stretch reads
neither — the fragment passed to Titiler is unchanged either way. So
``?stretch=minmax&pmin=<random>`` produced a fresh cache key holding bytes
byte-identical to the unfiltered tile, the same defeat #1785 closed for the
vector tile ``cols=`` param: on the default production stack (no Valkey) those
writes land in a bounded LRU and evict legitimate tiles.

The fix mirrors #1785's shape: a ``map`` keyed on ``$arg_stretch`` blanks each
arg family down to what the active mode can actually change, and the cache key
is built from the mapped variables rather than the raw ``$arg_*`` ones.
Blanking BOTH families unconditionally would not just fragment the cache the
other direction, it would misbehave: two stddev requests with different sigma
values render different bytes and must still key apart, so only the family
each mode ignores is blanked.

These are structural (they read the conf), because there is no nginx binary
in this test environment to render and query directly.
"""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"

RASTER_TILES_LOCATION = r"location\s+~\s+\^/raster-tiles/"

_LOCATION_HEADER = re.compile(r"^[ \t]*location\b[^\n{]*\{", re.M)
_MAP_HEADER = re.compile(r"^map\s+(\S+)\s+(\S+)\s*\{", re.M)
_PROXY_CACHE_KEY = re.compile(r'^\s*proxy_cache_key\s+"([^"]+)"\s*;', re.M)


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
    match = re.search(header_pattern, text)
    assert match, f"expected a location block matching {header_pattern!r}"
    return _balanced_body(text, text.index("{", match.start()))


def _map_body(text: str, source_var: str, dest_var: str) -> str:
    """Body of ``map $source_var $dest_var { ... }``, or raise."""
    for match in _MAP_HEADER.finditer(text):
        if match.group(1) == source_var and match.group(2) == dest_var:
            return _balanced_body(text, text.index("{", match.start()))
    raise AssertionError(f"no `map {source_var} {dest_var} {{ ... }}` block found")


def _map_entries(body: str) -> dict[str, str]:
    """``{key: value}`` for each ``key value;`` entry in a map body (quotes stripped)."""
    entries: dict[str, str] = {}
    for line in body.splitlines():
        line = line.strip().rstrip(";")
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        key, value = parts
        entries[key.strip('"')] = value.strip().strip('"')
    return entries


def _conf() -> str:
    return _without_comments(NGINX_CONF.read_text())


def test_cache_key_does_not_hold_the_raw_stretch_args():
    """The raw args must not appear in proxy_cache_key at all — only the
    mapped variables that blank what the active stretch mode ignores."""
    conf = _conf()
    match = _PROXY_CACHE_KEY.search(_location_block(conf, RASTER_TILES_LOCATION))
    assert match, "expected a proxy_cache_key in the /raster-tiles/ location"
    key = match.group(1)
    for raw_arg in ("$arg_pmin", "$arg_pmax", "$arg_sigma"):
        assert raw_arg not in key, (
            f"proxy_cache_key still holds {raw_arg} unconditionally: {key!r}. "
            "An anonymous caller can randomize it under stretch=minmax/absent "
            "(where it changes nothing) to mint a fresh key per request, "
            "defeating the cache the way `cols=<random>` did before #1785."
        )
    for mapped_var in (
        "$geolens_raster_pmin",
        "$geolens_raster_pmax",
        "$geolens_raster_sigma",
    ):
        assert mapped_var in key, f"expected {mapped_var} in proxy_cache_key: {key!r}"


def test_percentile_args_are_blanked_unless_stretch_is_percentile():
    """pmin/pmax only change rendered bytes under stretch=percentile
    (_compute_stretch_rescale); every other mode must key on a blank."""
    conf = _conf()
    for dest_var, arg_var in (
        ("$geolens_raster_pmin", "$arg_pmin"),
        ("$geolens_raster_pmax", "$arg_pmax"),
    ):
        entries = _map_entries(_map_body(conf, "$arg_stretch", dest_var))
        assert entries.get("percentile") == arg_var, (
            f"map $arg_stretch {dest_var}: stretch=percentile must forward "
            f"{arg_var}, got {entries.get('percentile')!r}"
        )
        assert entries.get("default") == "", (
            f"map $arg_stretch {dest_var}: every non-percentile stretch mode "
            f"(minmax, absent, stddev) must blank the value, got "
            f"{entries.get('default')!r}"
        )


def test_sigma_is_blanked_unless_stretch_is_stddev():
    """sigma only changes rendered bytes under stretch=stddev; blanking it
    unconditionally would instead collide two DIFFERENT stddev renders onto
    one cache entry, which is a correctness bug, not just fragmentation."""
    conf = _conf()
    entries = _map_entries(_map_body(conf, "$arg_stretch", "$geolens_raster_sigma"))
    assert entries.get("stddev") == "$arg_sigma", (
        "map $arg_stretch $geolens_raster_sigma: stretch=stddev must forward "
        f"$arg_sigma, got {entries.get('stddev')!r}"
    )
    assert entries.get("default") == "", (
        "map $arg_stretch $geolens_raster_sigma: every non-stddev stretch mode "
        f"(minmax, absent, percentile) must blank the value, got "
        f"{entries.get('default')!r}"
    )


def test_sigma_still_varies_the_key_under_stddev():
    """Counterfactual for the failure mode a blanket blank-everything fix would
    introduce: two stddev requests with different sigma render different
    bytes, so sigma must still reach the cache key when stretch=stddev."""
    conf = _conf()
    key_match = _PROXY_CACHE_KEY.search(_location_block(conf, RASTER_TILES_LOCATION))
    assert key_match and "$geolens_raster_sigma" in key_match.group(1)
    entries = _map_entries(_map_body(conf, "$arg_stretch", "$geolens_raster_sigma"))
    assert entries.get("stddev") not in (None, ""), (
        "stddev must not blank sigma out of the key, or two stddev requests "
        "with different sigma would collide on one cache entry and serve one "
        "request's bytes for the other's distinct render"
    )
