"""The raster tile cache key must not vary on an arg the active stretch mode
ignores, and a cache HIT must never change the status code a request gets
(#1778, codebase audit 2026-08-30; codex round 1 on #1791).

frontend/nginx.conf's raster_cache proxy_cache_key used to hold
$arg_pmin/$arg_pmax/$arg_sigma unconditionally. In
backend/app/processing/tiles/router.py, stretch=percentile is the only mode
that reads pmin/pmax (_compute_stretch_rescale) and stretch=stddev is the only
mode that reads sigma; stretch=minmax (the default) or an absent stretch reads
neither -- the fragment passed to Titiler is unchanged either way. So
``?stretch=minmax&pmin=<random>`` produced a fresh cache key holding bytes
byte-identical to the unfiltered tile, the same defeat #1785 closed for the
vector tile ``cols=`` param.

The first revision of this fix blanked every inactive value unconditionally,
which introduced a different bug: raster_tile_proxy validates pmin/pmax/sigma
whenever they are PRESENT, regardless of the active stretch mode (T-1153-01),
so ``?stretch=minmax&pmin=200`` uncached answers 422 -- but blanking pmin
unconditionally collapsed it onto the SAME key as a cached ``?stretch=minmax``
and returned that entry's 200. A cache hit must never change endpoint
semantics.

The current maps blank a value only when it is BOTH inactive for the request's
mode AND within the range the API itself accepts (0-100 for pmin/pmax,
positive for sigma). A value in that range can never turn the API's verdict
from 200 into 422, so blanking it never changes the status a client gets;
anything malformed or out of range is left RAW, so it misses the cache and
reaches the API for the same 422 an uncached request would get.

These are structural (they read the conf and simulate nginx's own map
evaluation in Python), because there is no nginx binary in this test
environment to render and query directly. The companion API-level pin lives in
test_raster_colormap_proxy.py::TestRasterColormapProxy::
test_invalid_bounds_return_422_even_under_an_inactive_stretch_mode, which
confirms the API side of the property these maps rely on: pmin/pmax/sigma are
rejected whenever present, regardless of stretch mode.
"""

import re

from tests.repo_paths import repo_root

NGINX_CONF = repo_root(__file__) / "frontend" / "nginx.conf"

RASTER_TILES_LOCATION = r"location\s+~\s+\^/raster-tiles/"

_LOCATION_HEADER = re.compile(r"^[ \t]*location\b[^\n{]*\{", re.M)
_MAP_HEADER = re.compile(r"^map\s+(\S+)\s+(\S+)\s*\{", re.M)
_PROXY_CACHE_KEY = re.compile(r'^\s*proxy_cache_key\s+"([^"]+)"\s*;', re.M)

# (unquoted source template, dest var) for each param this file cares about.
_MAPS: dict[str, tuple[str, str]] = {
    "pmin": ("$arg_stretch:$arg_pmin", "$geolens_raster_pmin"),
    "pmax": ("$arg_stretch:$arg_pmax", "$geolens_raster_pmax"),
    "sigma": ("$arg_stretch:$arg_sigma", "$geolens_raster_sigma"),
}


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


def _map_body(text: str, source_expr: str, dest_var: str) -> str:
    """Body of ``map "source_expr" dest_var { ... }`` (source_expr unquoted)."""
    quoted_source = f'"{source_expr}"'
    for match in _MAP_HEADER.finditer(text):
        if match.group(1) == quoted_source and match.group(2) == dest_var:
            return _balanced_body(text, text.index("{", match.start()))
    raise AssertionError(f'no `map "{source_expr}" {dest_var} {{ ... }}` block found')


def _map_entries_ordered(body: str) -> tuple[list[tuple[str, str]], str]:
    """``([(pattern_without_tilde, value_template), ...], default_template)``.

    Declaration order is preserved, since nginx tries regex entries in the
    order they were written and the first match wins. Asserts every non-default
    entry is a regex (``~``-prefixed) — a literal entry slipping in would be
    matched by nginx's hash lookup instead, which this simulation does not
    model, and a silent mismatch there is worse than a loud assertion here.
    """
    entries: list[tuple[str, str]] = []
    default_value: str | None = None
    for line in body.splitlines():
        line = line.strip().rstrip(";")
        if not line:
            continue
        key, value = line.split(None, 1)
        key = key.strip('"')
        value = value.strip().strip('"')
        if key == "default":
            default_value = value
        else:
            assert key.startswith("~"), f"expected a regex map entry, got {key!r}"
            entries.append((key[1:], value))
    assert default_value is not None, "map has no default entry"
    return entries, default_value


def _expand(template: str, arg_values: dict[str, str]) -> str:
    """Substitute ``$arg_NAME`` tokens in a map source template or value."""

    def _sub(match: re.Match) -> str:
        return arg_values.get(match.group(1), "")

    return re.sub(r"\$arg_(\w+)", _sub, template)


def _evaluate_map(
    source_template: str,
    entries: list[tuple[str, str]],
    default_value: str,
    arg_values: dict[str, str],
) -> str:
    """Evaluate one nginx ``map`` the way nginx itself would: try each regex
    entry in declaration order, first match wins; ``default`` otherwise."""
    source = _expand(source_template, arg_values)
    for pattern, template in entries:
        if re.match(pattern, source):
            return _expand(template, arg_values)
    return _expand(default_value, arg_values)


def _conf() -> str:
    return _without_comments(NGINX_CONF.read_text())


def _derive(conf: str, param: str, stretch: str, value: str) -> str:
    """The cache-key value nginx would compute for ``param`` given
    ``?stretch=<stretch>&<param>=<value>``."""
    source_template, dest_var = _MAPS[param]
    entries, default_value = _map_entries_ordered(
        _map_body(conf, source_template, dest_var)
    )
    arg_values = {"stretch": stretch, param: value}
    return _evaluate_map(source_template, entries, default_value, arg_values)


# ---------------------------------------------------------------------------
# The cache key itself
# ---------------------------------------------------------------------------


def test_cache_key_does_not_hold_the_raw_stretch_args():
    """The raw args must not appear in proxy_cache_key at all -- only the
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


# ---------------------------------------------------------------------------
# pmin / pmax: percentile is the active mode; blank only a well-formed,
# in-range (0-100) inactive value.
# ---------------------------------------------------------------------------


def test_percentile_mode_always_passes_pmin_pmax_through_raw():
    """Active mode: pmin/pmax must vary the key regardless of validity,
    unchanged from before this fix -- percentile genuinely reads them, and an
    invalid value under percentile already 422s on its own (unaffected by
    caching, since a 422 is never stored under `proxy_cache_valid 200 1h`)."""
    conf = _conf()
    for param in ("pmin", "pmax"):
        for value in ("5", "200", "-1", "abc", ""):
            assert _derive(conf, param, "percentile", value) == value


def test_valid_random_pmin_pmax_still_collapse_to_one_key():
    """The cache-busting vector #1785's fix closed for `cols=`: many DIFFERENT
    but individually well-formed pmin/pmax values under an inactive stretch
    mode must all still collapse to the SAME (blank) cache-key component."""
    conf = _conf()
    values = ["", "0", "2", "50", "98", "99.999", "100", "100.0"]
    for param in ("pmin", "pmax"):
        for stretch in ("minmax", ""):
            derived = {_derive(conf, param, stretch, v) for v in values}
            assert derived == {""}, (
                f"{param} under stretch={stretch!r} collapsed to {derived!r}, "
                "expected all blank -- a well-formed random value must not "
                "defeat the cache"
            )


def test_out_of_range_pmin_pmax_are_not_blanked():
    """fix(#1778 codex r1): the regression codex found. Blanking pmin
    unconditionally under an inactive stretch mode let a cached
    `?stretch=minmax` answer `?stretch=minmax&pmin=200` with its cached 200,
    though raster_tile_proxy validates pmin whenever it is present regardless
    of stretch mode and would 422 an out-of-range value uncached. A value
    outside what the API accepts must stay RAW: it misses the cache and
    reaches the API for the same 422 an uncached request would get."""
    conf = _conf()
    for param in ("pmin", "pmax"):
        for bad in ("200", "-5", "abc", "1e10", "101", "100.5", "50:60"):
            derived = _derive(conf, param, "minmax", bad)
            assert derived == bad, (
                f"{param}={bad!r} under an inactive stretch mode must stay "
                f"RAW in the cache key, got {derived!r} -- a cache hit here "
                "would answer 200 for a request the API would 422"
            )
            assert derived != "", (
                f"{param}={bad!r} must not collapse onto the blank key"
            )


# ---------------------------------------------------------------------------
# sigma: stddev is the active mode; blank only a well-formed positive value.
# ---------------------------------------------------------------------------


def test_stddev_mode_always_passes_sigma_through_raw():
    conf = _conf()
    for value in ("2", "-1", "0", "abc", ""):
        assert _derive(conf, "sigma", "stddev", value) == value


def test_valid_random_sigma_still_collapses_to_one_key():
    """Counterfactual for the failure mode a blanket blank-everything fix
    would introduce: two stddev requests with different sigma render
    different bytes and must still key apart (covered separately below); this
    pins the complementary half, that well-formed sigma values collapse when
    sigma is inactive."""
    conf = _conf()
    values = ["", "0.5", "1", "2", "10", "0.001"]
    derived = {_derive(conf, "sigma", "minmax", v) for v in values}
    assert derived == {""}, (
        f"sigma under an inactive stretch mode collapsed to {derived!r}, "
        "expected all blank"
    )


def test_out_of_range_sigma_is_not_blanked():
    """sigma must be strictly positive (`sigma > 0`); zero and negative
    values must stay RAW under an inactive stretch mode for the same reason
    an out-of-range pmin must."""
    conf = _conf()
    for bad in ("-1", "0", "0.0", "0.000", "abc"):
        derived = _derive(conf, "sigma", "minmax", bad)
        assert derived == bad, (
            f"sigma={bad!r} under an inactive stretch mode must stay RAW, "
            f"got {derived!r}"
        )


def test_sigma_still_varies_the_key_under_stddev():
    """Counterfactual for the failure mode a blanket blank-everything fix would
    introduce: two stddev requests with different sigma render different
    bytes, so sigma must still reach the cache key when stretch=stddev."""
    conf = _conf()
    key_match = _PROXY_CACHE_KEY.search(_location_block(conf, RASTER_TILES_LOCATION))
    assert key_match and "$geolens_raster_sigma" in key_match.group(1)
    assert _derive(conf, "sigma", "stddev", "2") != _derive(
        conf, "sigma", "stddev", "3"
    ), (
        "stddev must not blank sigma out of the key, or two stddev requests "
        "with different sigma would collide on one cache entry and serve one "
        "request's bytes for the other's distinct render"
    )
